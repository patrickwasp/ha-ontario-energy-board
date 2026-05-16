"""Parser for the Ontario Energy Board GasBillData.xml feed.

Pure functions: bytes in, dataclasses out. Reuses the exception hierarchy
defined in ``parser.py``.

Gas rates differ structurally from electricity:
- 3-part composite key: (distributor, service area, rate class)
- Declining-block pricing with up to 5 tiers (rate falls as consumption rises)
- No time-of-day component; gas pricing is purely volumetric
- Typical monthly consumption (Jan-Dec) baked into each row
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final

import aiohttp
from defusedxml import ElementTree as DefusedET

from .const import FEED_TIMEOUT_SECONDS, GAS_FEED_URL
from .parser import (
    OEBFetchError,
    OEBParseError,
    OEBRowNotFoundError,
    OEBSchemaError,
    _decimal,
)

_LOGGER = logging.getLogger(__name__)

_MONTH_TAGS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

GAS_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "Dist",
        "SA",
        "RC",
        "ED",
        "MC",
        "DT1Low",
        "DT1High",
        "DT2Low",
        "DT2High",
        "DT3Low",
        "DT3High",
        "DT4Low",
        "DT4High",
        "DT5Low",
        "DT5High",
        "DCT1",
        "DCT2",
        "DCT3",
        "DCT4",
        "DCT5",
        "DCPA",
        "SC",
        "SCPA",
        "CM",
        "CMPA",
        "TC",
        "TCPA",
        "FedCC",
        "FacCC",
        "GST",
        *_MONTH_TAGS,
    }
)


@dataclass(frozen=True, slots=True)
class GasTier:
    """One declining-block tier on a gas rate schedule."""

    low: Decimal       # cubic meters
    high: Decimal      # cubic meters; 99999 typically means "no upper bound"
    rate: Decimal      # $/m³


@dataclass(frozen=True, slots=True)
class GasRateRow:
    """One parsed row of the OEB GasBillData feed."""

    distributor: str
    service_area: str
    rate_class: str
    effective_date: date
    monthly_customer_charge: Decimal   # MC, $/month
    tiers: tuple[GasTier, ...]         # only "active" tiers (high > low and rate > 0)
    delivery_pa: Decimal               # DCPA, $/m³ rider
    storage_charge: Decimal            # SC, $/m³
    storage_pa: Decimal                # SCPA, $/m³ rider
    commodity: Decimal                 # CM, $/m³
    commodity_pa: Decimal              # CMPA, $/m³ rider
    transportation: Decimal            # TC, $/m³
    transportation_pa: Decimal         # TCPA, $/m³ rider
    federal_carbon_charge: Decimal     # FedCC, $/m³
    facility_carbon_charge: Decimal    # FacCC, $/m³
    hst: Decimal                       # GST, fraction (0.13)
    typical_consumption: tuple[Decimal, ...]  # 12 values Jan-Dec, m3


async def fetch_gas_feed(session: aiohttp.ClientSession) -> bytes:
    """Fetch the raw GasBillData XML bytes.

    Raises:
        OEBFetchError: HTTP error, timeout, or other transport failure.
    """
    try:
        async with session.get(
            GAS_FEED_URL,
            timeout=aiohttp.ClientTimeout(total=FEED_TIMEOUT_SECONDS),
        ) as response:
            if response.status != 200:
                raise OEBFetchError(
                    f"OEB gas feed returned HTTP {response.status}"
                )
            return await response.read()
    except TimeoutError as err:
        raise OEBFetchError("OEB gas feed request timed out") from err
    except aiohttp.ClientError as err:
        raise OEBFetchError(f"OEB gas feed request failed: {err}") from err


def _build_tiers(_text: Callable[[str], str | None]) -> tuple[GasTier, ...]:
    """Return only tiers where the block is non-empty and the rate is positive."""
    tiers: list[GasTier] = []
    for n in range(1, 6):
        low = _decimal(_text(f"DT{n}Low"))
        high = _decimal(_text(f"DT{n}High"))
        rate = _decimal(_text(f"DCT{n}"))
        # An inactive tier carries zero high+rate (per Enbridge/EPCOR rows that
        # use fewer than 5 tiers). Keep the tier if either the block has width
        # OR the rate is non-zero — defensive against partial-zero rows.
        if high > low or rate > 0:
            tiers.append(GasTier(low=low, high=high, rate=rate))
    return tuple(tiers)


def parse_gas_feed(xml_bytes: bytes) -> list[GasRateRow]:
    """Parse the OEB GasBillData XML into a list of GasRateRow.

    Raises:
        OEBParseError: XML is malformed.
        OEBSchemaError: XML structure does not match the expected schema.
    """
    try:
        root = DefusedET.fromstring(xml_bytes)
    except DefusedET.ParseError as err:
        raise OEBParseError(f"OEB gas feed is not valid XML: {err}") from err

    if root.tag != "dataroot":
        raise OEBSchemaError(
            f"Expected root <dataroot>, got <{root.tag}>"
        )

    rows: list[GasRateRow] = []
    for idx, row_el in enumerate(root.findall("GasBillData")):
        present = {child.tag for child in row_el}
        missing = GAS_REQUIRED_FIELDS - present
        if missing:
            raise OEBSchemaError(
                f"Gas row {idx}: missing required fields {sorted(missing)}"
            )

        def _text(tag: str, _row: object = row_el) -> str | None:
            el = _row.find(tag)  # type: ignore[attr-defined]
            return None if el is None else el.text

        try:
            ed_text = _text("ED")
            if ed_text is None or not ed_text.strip():
                raise OEBSchemaError(f"Gas row {idx}: ED is empty")
            effective = datetime.fromisoformat(ed_text.strip()).date()
            row = GasRateRow(
                distributor=(_text("Dist") or "").strip(),
                service_area=(_text("SA") or "").strip(),
                rate_class=(_text("RC") or "").strip(),
                effective_date=effective,
                monthly_customer_charge=_decimal(_text("MC")),
                tiers=_build_tiers(_text),
                delivery_pa=_decimal(_text("DCPA")),
                storage_charge=_decimal(_text("SC")),
                storage_pa=_decimal(_text("SCPA")),
                commodity=_decimal(_text("CM")),
                commodity_pa=_decimal(_text("CMPA")),
                transportation=_decimal(_text("TC")),
                transportation_pa=_decimal(_text("TCPA")),
                federal_carbon_charge=_decimal(_text("FedCC")),
                facility_carbon_charge=_decimal(_text("FacCC")),
                hst=_decimal(_text("GST")),
                typical_consumption=tuple(
                    _decimal(_text(tag)) for tag in _MONTH_TAGS
                ),
            )
        except ValueError as err:
            raise OEBSchemaError(f"Gas row {idx}: {err}") from err
        rows.append(row)

    if not rows:
        raise OEBSchemaError("OEB gas feed contains no <GasBillData> entries")
    return rows


def find_gas_row(
    rows: list[GasRateRow],
    distributor: str,
    service_area: str,
    rate_class: str,
) -> GasRateRow:
    """Return the row matching (distributor, service_area, rate_class).

    Raises:
        OEBRowNotFoundError: no matching row.
    """
    for row in rows:
        if (
            row.distributor == distributor
            and row.service_area == service_area
            and row.rate_class == rate_class
        ):
            return row
    raise OEBRowNotFoundError(
        f"No gas row for distributor={distributor!r}, "
        f"service_area={service_area!r}, rate_class={rate_class!r}"
    )


def list_gas_distributors(rows: list[GasRateRow]) -> list[str]:
    """Sorted, deduplicated list of gas distributor names."""
    return sorted({row.distributor for row in rows})


def list_gas_service_areas(
    rows: list[GasRateRow], distributor: str
) -> list[str]:
    """Sorted, deduplicated list of service areas under one distributor."""
    return sorted(
        {row.service_area for row in rows if row.distributor == distributor}
    )


def list_gas_rate_classes(
    rows: list[GasRateRow], distributor: str, service_area: str
) -> list[str]:
    """Sorted, deduplicated list of rate classes for (distributor, service area)."""
    return sorted(
        {
            row.rate_class
            for row in rows
            if row.distributor == distributor and row.service_area == service_area
        }
    )


# Silence unused-import warning while keeping a stable import surface.
__all__ = [
    "GAS_REQUIRED_FIELDS",
    "GasRateRow",
    "GasTier",
    "OEBFetchError",
    "OEBParseError",
    "OEBRowNotFoundError",
    "OEBSchemaError",
    "fetch_gas_feed",
    "find_gas_row",
    "list_gas_distributors",
    "list_gas_rate_classes",
    "list_gas_service_areas",
    "parse_gas_feed",
]

# Suppress unused warning for asyncio used in TimeoutError context.
_ = asyncio
