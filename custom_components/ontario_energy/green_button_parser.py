"""Parser for ESPI (Green Button) Atom XML files.

ESPI is the Energy Services Provider Interface — the standardized XML schema
used by every Green Button "Download My Data" file. The format is an Atom
feed whose ``<entry>`` resources reference each other by URL:

    UsagePoint  ─►  MeterReading  ─►  IntervalBlock(s)  ─►  IntervalReading(s)
                              ─►  ReadingType (units, multipliers, commodity)

This parser is intentionally lenient: it walks every entry, finds Reading-
Types and IntervalBlocks regardless of order, and resolves the ReadingType
for each block via the ``<link rel="related">`` chain when present (and falls
back to the only-RT-in-the-file heuristic when not).

Returns plain dataclasses with values normalized to **kWh** (electricity) or
**m³** (gas) — the units HA's recorder expects for the Energy Dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from defusedxml import ElementTree as DefusedET

from .parser import OEBParseError, OEBSchemaError

# Atom and ESPI namespaces. ESPI files always use these exact URIs.
_NS: Final = {
    "atom": "http://www.w3.org/2005/Atom",
    "espi": "http://naesb.org/espi",
}

# ESPI ReadingType.commodity (subset relevant to Ontario):
#   1 = electricitySecondaryMetered (kWh)
#   7 = naturalGas (m³)
COMMODITY_ELECTRICITY: Final = 1
COMMODITY_NATURAL_GAS: Final = 7

# ReadingType.flowDirection: 1 = forward (consumption from the grid).
# Everything else (reverse / net / unknown) is ignored for v1.
FLOW_FORWARD: Final = 1

# ReadingType.uom (unit of measure) codes per IEC 61968:
#   72 = Wh, 119 = m³. Everything else surfaces as an error so a future
#   schema surprise is loud rather than silent.
UOM_WH: Final = 72
UOM_M3: Final = 119


@dataclass(frozen=True, slots=True)
class ReadingType:
    """Metadata describing one stream of readings (units, scale, commodity)."""

    href: str
    commodity: int
    flow_direction: int
    uom: int                   # raw IEC 61968 code
    power_of_ten_multiplier: int   # apply 10**multiplier to raw values
    interval_length_seconds: int

    @property
    def is_electricity(self) -> bool:
        return self.commodity == COMMODITY_ELECTRICITY

    @property
    def is_gas(self) -> bool:
        return self.commodity == COMMODITY_NATURAL_GAS

    @property
    def normalized_unit(self) -> str:
        """Return ``kWh`` or ``m³`` after unit + multiplier conversion."""
        if self.commodity == COMMODITY_ELECTRICITY:
            return "kWh"
        if self.commodity == COMMODITY_NATURAL_GAS:
            return "m³"
        raise OEBSchemaError(f"Unsupported commodity code {self.commodity}")


@dataclass(frozen=True, slots=True)
class IntervalReading:
    """One reading in normalized units (kWh or m³) at a UTC start time."""

    start: datetime
    duration: timedelta
    value: Decimal  # in normalized_unit


@dataclass(frozen=True, slots=True)
class UsagePoint:
    """A meter's worth of readings sharing one ReadingType."""

    reading_type: ReadingType
    readings: tuple[IntervalReading, ...] = field(default_factory=tuple)

    @property
    def normalized_unit(self) -> str:
        return self.reading_type.normalized_unit


def _self_href(entry: object) -> str | None:
    """Return the ``rel="self"`` href on an entry, or None."""
    for link in entry.findall("atom:link", _NS):  # type: ignore[attr-defined]
        if link.get("rel") == "self":
            href: str | None = link.get("href")
            if href is not None:
                return href
    return None


def _related_hrefs(entry: object) -> list[str]:
    """Return all ``rel="related"`` hrefs on an entry."""
    out: list[str] = []
    for link in entry.findall("atom:link", _NS):  # type: ignore[attr-defined]
        if link.get("rel") == "related":
            href = link.get("href")
            if href is not None:
                out.append(href)
    return out


def _int_text(parent: object, tag: str, *, default: int | None = None) -> int:
    el = parent.find(f"espi:{tag}", _NS)  # type: ignore[attr-defined]
    if el is None or el.text is None or not el.text.strip():
        if default is None:
            raise OEBSchemaError(f"Missing required ESPI field <{tag}>")
        return default
    try:
        return int(el.text.strip())
    except ValueError as err:
        raise OEBSchemaError(f"Non-integer ESPI field <{tag}>: {el.text!r}") from err


def _parse_reading_type(entry: object, self_href: str) -> ReadingType:
    content = entry.find("atom:content/espi:ReadingType", _NS)  # type: ignore[attr-defined]
    if content is None:
        raise OEBSchemaError("ReadingType entry has no <ReadingType> content")
    return ReadingType(
        href=self_href,
        commodity=_int_text(content, "commodity", default=0),
        flow_direction=_int_text(content, "flowDirection", default=FLOW_FORWARD),
        uom=_int_text(content, "uom", default=0),
        power_of_ten_multiplier=_int_text(
            content, "powerOfTenMultiplier", default=0
        ),
        interval_length_seconds=_int_text(content, "intervalLength", default=0),
    )


def _parse_interval_block(
    entry: object, reading_type: ReadingType
) -> list[IntervalReading]:
    block = entry.find("atom:content/espi:IntervalBlock", _NS)  # type: ignore[attr-defined]
    if block is None:
        raise OEBSchemaError("IntervalBlock entry has no <IntervalBlock> content")

    # Apply the multiplier once, plus the unit conversion.
    multiplier = Decimal(10) ** reading_type.power_of_ten_multiplier
    unit_divisor = _unit_divisor(reading_type)

    out: list[IntervalReading] = []
    for reading_el in block.findall("espi:IntervalReading", _NS):
        period = reading_el.find("espi:timePeriod", _NS)
        if period is None:
            raise OEBSchemaError("IntervalReading missing <timePeriod>")
        start_secs = _int_text(period, "start")
        duration_secs = _int_text(
            period, "duration", default=reading_type.interval_length_seconds
        )
        value_el = reading_el.find("espi:value", _NS)
        if value_el is None or value_el.text is None:
            raise OEBSchemaError("IntervalReading missing <value>")
        try:
            raw = Decimal(value_el.text.strip())
        except (ValueError, ArithmeticError) as err:
            raise OEBSchemaError(
                f"Non-numeric IntervalReading value {value_el.text!r}"
            ) from err
        normalized = (raw * multiplier) / unit_divisor
        out.append(
            IntervalReading(
                start=datetime.fromtimestamp(start_secs, tz=UTC),
                duration=timedelta(seconds=duration_secs),
                value=normalized,
            )
        )
    return out


def _unit_divisor(reading_type: ReadingType) -> Decimal:
    """Convert raw ESPI units to our normalized unit (kWh or m³)."""
    if reading_type.commodity == COMMODITY_ELECTRICITY:
        if reading_type.uom != UOM_WH:
            raise OEBSchemaError(
                f"Electricity ReadingType uom={reading_type.uom}; expected {UOM_WH} (Wh)"
            )
        return Decimal(1000)  # Wh -> kWh
    if reading_type.commodity == COMMODITY_NATURAL_GAS:
        if reading_type.uom != UOM_M3:
            raise OEBSchemaError(
                f"Gas ReadingType uom={reading_type.uom}; expected {UOM_M3} (m³)"
            )
        return Decimal(1)  # already m³
    raise OEBSchemaError(f"Unsupported commodity code {reading_type.commodity}")


def parse_espi(xml_bytes: bytes) -> list[UsagePoint]:
    """Parse an ESPI Atom XML payload into one UsagePoint per ReadingType.

    Raises:
        OEBParseError: payload is not valid XML.
        OEBSchemaError: payload parses but isn't a recognizable ESPI feed.
    """
    try:
        root = DefusedET.fromstring(xml_bytes)
    except DefusedET.ParseError as err:
        raise OEBParseError(f"ESPI file is not valid XML: {err}") from err

    # The root must be an Atom <feed>.
    if not root.tag.endswith("}feed") and root.tag != "feed":
        raise OEBSchemaError(
            f"Expected Atom <feed>, got <{root.tag}>"
        )

    entries = root.findall("atom:entry", _NS)
    if not entries:
        raise OEBSchemaError("ESPI feed contains no <entry> elements")

    # Pass 1: collect ReadingTypes by their self-URI.
    reading_types: dict[str, ReadingType] = {}
    for entry in entries:
        if entry.find("atom:content/espi:ReadingType", _NS) is None:
            continue
        self_href = _self_href(entry)
        if self_href is None:
            continue
        reading_types[self_href] = _parse_reading_type(entry, self_href)

    if not reading_types:
        raise OEBSchemaError("ESPI feed contains no ReadingType entries")

    # Pass 2: collect IntervalBlocks, resolve ReadingType, group by RT.
    by_rt: dict[str, list[IntervalReading]] = {rt: [] for rt in reading_types}
    for entry in entries:
        if entry.find("atom:content/espi:IntervalBlock", _NS) is None:
            continue
        rt_href = _resolve_reading_type_href(entry, reading_types)
        rt = reading_types[rt_href]
        if rt.flow_direction != FLOW_FORWARD:
            # Skip reverse / net-export streams in v1.
            continue
        by_rt[rt_href].extend(_parse_interval_block(entry, rt))

    return [
        UsagePoint(reading_type=reading_types[href], readings=tuple(sorted(rs, key=lambda r: r.start)))
        for href, rs in by_rt.items()
        if rs  # drop ReadingTypes with no associated readings
    ]


def _resolve_reading_type_href(
    block_entry: object, reading_types: dict[str, ReadingType]
) -> str:
    """Find the ReadingType href associated with an IntervalBlock entry.

    Strategy:
      1. Match any ``rel="related"`` link that ends in "/ReadingType/<id>"
         against a known ReadingType href.
      2. If none match and only one ReadingType exists, return it.
      3. Otherwise raise — we can't safely guess.
    """
    related = _related_hrefs(block_entry)
    for href in related:
        for rt_href in reading_types:
            if rt_href == href or rt_href.endswith(href) or href.endswith(rt_href):
                return rt_href
        # Match by tail path (handles base-URL differences between datacustodians).
        tail = href.rsplit("ReadingType/", 1)
        if len(tail) == 2:
            for rt_href in reading_types:
                if rt_href.endswith(f"ReadingType/{tail[1]}"):
                    return rt_href

    if len(reading_types) == 1:
        return next(iter(reading_types))

    raise OEBSchemaError(
        "IntervalBlock has no matching ReadingType via rel='related' links"
    )
