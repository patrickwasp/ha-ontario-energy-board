"""Parser for the Ontario Energy Board BillData.xml feed.

Pure functions: bytes in, dataclasses out. No `hass` dependency, no I/O leak
beyond `fetch_feed` (which takes the session as a parameter).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

import aiohttp
from defusedxml import ElementTree as DefusedET

from .const import (
    ELECTRICITY_FEED_URL,
    ELECTRICITY_GS_FEED_URL,
    FEED_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class OEBError(Exception):
    """Base exception for Ontario Energy Board parser errors."""


class OEBFetchError(OEBError):
    """The OEB feed could not be fetched (HTTP error or timeout)."""


class OEBParseError(OEBError):
    """The OEB feed could not be parsed as XML."""


class OEBSchemaError(OEBError):
    """The OEB feed parsed but did not match the expected schema."""


class OEBRowNotFoundError(OEBError):
    """No row matched the requested distributor and customer class."""


REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "Dist",
        "Class",
        "YEAR",
        "ET1",
        "RPP1",
        "RPP2",
        "RPPOffP",
        "RPPMidP",
        "RPPOnP",
        "ULO_overnight",
        "ULO_weekendoffp",
        "ULO_midp",
        "ULO_onp",
        "SC",
        "DC",
        "Net",
        "Conn",
        "WMSR",
        "RRRP",
        "SSS",
        "LF",
        "GST",
        "Rebate",
    }
)


@dataclass(frozen=True, slots=True)
class RateRow:
    """One parsed row of the OEB BillData feed."""

    distributor: str
    customer_class: str
    rate_year: int
    # Tiered
    tier1_threshold_kwh: Decimal
    tier1_rate: Decimal
    tier2_rate: Decimal
    # TOU (RPP)
    tou_off: Decimal
    tou_mid: Decimal
    tou_on: Decimal
    # ULO
    ulo_overnight: Decimal
    ulo_weekend_off: Decimal
    ulo_mid: Decimal
    ulo_on: Decimal
    # Distributor charges
    service_charge: Decimal
    distribution_volumetric: Decimal
    network: Decimal
    connection: Decimal
    wmsr: Decimal
    rrrp: Decimal
    sss_admin: Decimal
    loss_factor: Decimal
    hst: Decimal
    rebate: Decimal


async def _fetch_url(
    session: aiohttp.ClientSession, url: str, label: str
) -> bytes:
    """Internal: GET ``url`` with a timeout, wrap errors in OEBFetchError."""
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=FEED_TIMEOUT_SECONDS)
        ) as response:
            if response.status != 200:
                raise OEBFetchError(
                    f"OEB {label} feed returned HTTP {response.status}"
                )
            return await response.read()
    except TimeoutError as err:
        raise OEBFetchError(f"OEB {label} feed request timed out") from err
    except aiohttp.ClientError as err:
        raise OEBFetchError(f"OEB {label} feed request failed: {err}") from err


async def fetch_feed(session: aiohttp.ClientSession) -> bytes:
    """Fetch the residential ``BillData.xml`` feed bytes.

    Raises:
        OEBFetchError: HTTP error, timeout, or other transport failure.
    """
    return await _fetch_url(session, ELECTRICITY_FEED_URL, "electricity")


async def fetch_gs50_feed(session: aiohttp.ClientSession) -> bytes:
    """Fetch the General Service < 50 kW ``BillData_GS.xml`` feed bytes."""
    return await _fetch_url(session, ELECTRICITY_GS_FEED_URL, "electricity GS")


async def fetch_all_electricity_rows(
    session: aiohttp.ClientSession,
) -> list[RateRow]:
    """Fetch BillData.xml + BillData_GS.xml in parallel and return combined rows.

    Both feeds share the same schema; the only differences are the customer
    classes they cover (residential variants vs. GS<50 kW variants).
    """
    import asyncio

    residential_bytes, gs_bytes = await asyncio.gather(
        fetch_feed(session), fetch_gs50_feed(session)
    )
    return parse_feed(residential_bytes) + parse_feed(gs_bytes)


def _decimal(text: str | None) -> Decimal:
    """Convert XML text to Decimal; empty/None → 0."""
    if text is None or not text.strip():
        return Decimal(0)
    try:
        return Decimal(text.strip())
    except InvalidOperation as err:
        raise OEBSchemaError(f"Invalid decimal value {text!r}") from err


def parse_feed(xml_bytes: bytes) -> list[RateRow]:
    """Parse the OEB BillData XML into a list of RateRow.

    Raises:
        OEBParseError: XML is malformed.
        OEBSchemaError: XML structure does not match the expected schema.
    """
    try:
        root = DefusedET.fromstring(xml_bytes)
    except DefusedET.ParseError as err:
        raise OEBParseError(f"OEB feed is not valid XML: {err}") from err

    if root.tag != "BillDataTable":
        raise OEBSchemaError(
            f"Expected root <BillDataTable>, got <{root.tag}>"
        )

    rows: list[RateRow] = []
    for idx, row_el in enumerate(root.findall("BillDataRow")):
        present = {child.tag for child in row_el}
        missing = REQUIRED_FIELDS - present
        if missing:
            raise OEBSchemaError(
                f"Row {idx}: missing required fields {sorted(missing)}"
            )

        def _text(tag: str, _row: object = row_el) -> str | None:
            el = _row.find(tag)  # type: ignore[attr-defined]
            return None if el is None else el.text

        try:
            year_text = _text("YEAR")
            if year_text is None or not year_text.strip():
                raise OEBSchemaError(f"Row {idx}: YEAR is empty")
            row = RateRow(
                distributor=(_text("Dist") or "").strip(),
                customer_class=(_text("Class") or "").strip(),
                rate_year=int(year_text.strip()),
                tier1_threshold_kwh=_decimal(_text("ET1")),
                tier1_rate=_decimal(_text("RPP1")),
                tier2_rate=_decimal(_text("RPP2")),
                tou_off=_decimal(_text("RPPOffP")),
                tou_mid=_decimal(_text("RPPMidP")),
                tou_on=_decimal(_text("RPPOnP")),
                ulo_overnight=_decimal(_text("ULO_overnight")),
                ulo_weekend_off=_decimal(_text("ULO_weekendoffp")),
                ulo_mid=_decimal(_text("ULO_midp")),
                ulo_on=_decimal(_text("ULO_onp")),
                service_charge=_decimal(_text("SC")),
                distribution_volumetric=_decimal(_text("DC")),
                network=_decimal(_text("Net")),
                connection=_decimal(_text("Conn")),
                wmsr=_decimal(_text("WMSR")),
                rrrp=_decimal(_text("RRRP")),
                sss_admin=_decimal(_text("SSS")),
                loss_factor=_decimal(_text("LF")),
                hst=_decimal(_text("GST")),
                rebate=_decimal(_text("Rebate")),
            )
        except ValueError as err:
            raise OEBSchemaError(f"Row {idx}: {err}") from err
        rows.append(row)

    if not rows:
        raise OEBSchemaError("OEB feed contains no <BillDataRow> entries")
    return rows


def find_row(
    rows: list[RateRow], distributor: str, customer_class: str
) -> RateRow:
    """Return the row matching (distributor, customer_class).

    Raises:
        OEBRowNotFoundError: no matching row.
    """
    for row in rows:
        if row.distributor == distributor and row.customer_class == customer_class:
            return row
    raise OEBRowNotFoundError(
        f"No row for distributor={distributor!r}, class={customer_class!r}"
    )


def list_distributors(rows: list[RateRow]) -> list[str]:
    """Sorted, deduplicated list of distributor names."""
    return sorted({row.distributor for row in rows})


def list_classes(rows: list[RateRow], distributor: str) -> list[str]:
    """Sorted, deduplicated list of customer classes for one distributor."""
    return sorted(
        {row.customer_class for row in rows if row.distributor == distributor}
    )
