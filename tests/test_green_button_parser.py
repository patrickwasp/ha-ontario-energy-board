"""Tests for ``custom_components.ontario_energy.green_button.parser``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.ontario_energy.green_button_parser import (
    COMMODITY_ELECTRICITY,
    COMMODITY_NATURAL_GAS,
    FLOW_FORWARD,
    UOM_M3,
    UOM_WH,
    parse_espi,
)
from custom_components.ontario_energy.parser import OEBParseError, OEBSchemaError


def test_parse_electricity(espi_electricity_xml: bytes) -> None:
    points = parse_espi(espi_electricity_xml)
    assert len(points) == 1
    up = points[0]

    rt = up.reading_type
    assert rt.commodity == COMMODITY_ELECTRICITY
    assert rt.flow_direction == FLOW_FORWARD
    assert rt.uom == UOM_WH
    assert rt.power_of_ten_multiplier == 0
    assert rt.interval_length_seconds == 3600
    assert rt.normalized_unit == "kWh"

    # Raw values in Wh become kWh by dividing by 1000.
    expected = [Decimal("0.5"), Decimal("0.75"), Decimal("1.25"), Decimal("0.9")]
    assert [r.value for r in up.readings] == expected

    # First reading start: epoch 1769904000 = 2026-02-01T00:00:00Z.
    assert up.readings[0].start == datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
    assert up.readings[0].duration == timedelta(seconds=3600)
    # Readings are sorted by start time even if XML order is arbitrary.
    starts = [r.start for r in up.readings]
    assert starts == sorted(starts)


def test_parse_gas(espi_gas_xml: bytes) -> None:
    points = parse_espi(espi_gas_xml)
    assert len(points) == 1
    up = points[0]
    assert up.reading_type.commodity == COMMODITY_NATURAL_GAS
    assert up.reading_type.uom == UOM_M3
    assert up.normalized_unit == "m³"
    assert [r.value for r in up.readings] == [Decimal(3), Decimal(5), Decimal(4)]


def test_parse_malformed(espi_malformed_xml: bytes) -> None:
    with pytest.raises(OEBParseError):
        parse_espi(espi_malformed_xml)


def test_parse_wrong_root() -> None:
    body = b"<?xml version='1.0'?><not_a_feed/>"
    with pytest.raises(OEBSchemaError):
        parse_espi(body)


def test_parse_empty_feed() -> None:
    body = (
        b'<?xml version="1.0"?>'
        b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    )
    with pytest.raises(OEBSchemaError) as info:
        parse_espi(body)
    assert "no <entry>" in str(info.value)


def test_parse_no_reading_type() -> None:
    body = (
        b'<?xml version="1.0"?>'
        b'<feed xmlns="http://www.w3.org/2005/Atom">'
        b"<entry><id>x</id><title>y</title></entry>"
        b"</feed>"
    )
    with pytest.raises(OEBSchemaError) as info:
        parse_espi(body)
    assert "ReadingType" in str(info.value)


def test_parse_applies_power_of_ten_multiplier() -> None:
    """A ReadingType with powerOfTenMultiplier=3 scales values by 1000."""
    body = (
        b'<?xml version="1.0"?>'
        b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:espi="http://naesb.org/espi">'
        b"<entry>"
        b'<link rel="self" href="https://x/ReadingType/1"/>'
        b"<content>"
        b"<espi:ReadingType>"
        b"<espi:commodity>1</espi:commodity>"
        b"<espi:flowDirection>1</espi:flowDirection>"
        b"<espi:uom>72</espi:uom>"
        b"<espi:powerOfTenMultiplier>3</espi:powerOfTenMultiplier>"
        b"<espi:intervalLength>3600</espi:intervalLength>"
        b"</espi:ReadingType>"
        b"</content>"
        b"</entry>"
        b"<entry>"
        b'<link rel="related" href="https://x/ReadingType/1"/>'
        b"<content>"
        b"<espi:IntervalBlock>"
        b"<espi:interval><espi:duration>3600</espi:duration>"
        b"<espi:start>1769904000</espi:start></espi:interval>"
        b"<espi:IntervalReading>"
        b"<espi:timePeriod><espi:duration>3600</espi:duration>"
        b"<espi:start>1769904000</espi:start></espi:timePeriod>"
        b"<espi:value>2</espi:value>"  # 2 * 10^3 / 1000 = 2 kWh
        b"</espi:IntervalReading>"
        b"</espi:IntervalBlock>"
        b"</content>"
        b"</entry>"
        b"</feed>"
    )
    points = parse_espi(body)
    assert points[0].readings[0].value == Decimal(2)


def test_parse_skips_reverse_flow() -> None:
    """Reverse-flow (generation/export) streams are dropped in v1."""
    body = (
        b'<?xml version="1.0"?>'
        b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:espi="http://naesb.org/espi">'
        b"<entry>"
        b'<link rel="self" href="https://x/ReadingType/1"/>'
        b"<content>"
        b"<espi:ReadingType>"
        b"<espi:commodity>1</espi:commodity>"
        b"<espi:flowDirection>19</espi:flowDirection>"  # reverse
        b"<espi:uom>72</espi:uom>"
        b"<espi:powerOfTenMultiplier>0</espi:powerOfTenMultiplier>"
        b"<espi:intervalLength>3600</espi:intervalLength>"
        b"</espi:ReadingType>"
        b"</content>"
        b"</entry>"
        b"<entry>"
        b'<link rel="related" href="https://x/ReadingType/1"/>'
        b"<content>"
        b"<espi:IntervalBlock>"
        b"<espi:interval><espi:duration>3600</espi:duration>"
        b"<espi:start>1769904000</espi:start></espi:interval>"
        b"<espi:IntervalReading>"
        b"<espi:timePeriod><espi:duration>3600</espi:duration>"
        b"<espi:start>1769904000</espi:start></espi:timePeriod>"
        b"<espi:value>500</espi:value>"
        b"</espi:IntervalReading>"
        b"</espi:IntervalBlock>"
        b"</content>"
        b"</entry>"
        b"</feed>"
    )
    points = parse_espi(body)
    # ReadingType exists but no readings (reverse-flow dropped).
    assert points == []
