"""Tests for ``custom_components.ontario_energy.gas_parser``."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from custom_components.ontario_energy.gas_parser import (
    GAS_REQUIRED_FIELDS,
    OEBParseError,
    OEBRowNotFoundError,
    OEBSchemaError,
    find_gas_row,
    list_gas_distributors,
    list_gas_rate_classes,
    list_gas_service_areas,
    parse_gas_feed,
)


def test_parse_gas_minimal(gas_minimal_xml: bytes) -> None:
    rows = parse_gas_feed(gas_minimal_xml)
    assert len(rows) == 1
    row = rows[0]
    assert row.distributor == "Enbridge Gas"
    assert row.service_area == "All"
    assert row.rate_class == "1"
    assert row.effective_date == date(2026, 4, 1)
    assert isinstance(row.monthly_customer_charge, Decimal)
    assert row.monthly_customer_charge > Decimal(0)
    assert isinstance(row.commodity, Decimal)
    assert isinstance(row.hst, Decimal)
    assert row.hst == Decimal("0.13")
    # Enbridge has 4 active tiers (DT5 is zero).
    assert len(row.tiers) == 4
    # Tiers should be in declining-rate order for residential gas.
    assert row.tiers[0].rate > row.tiers[1].rate
    # Typical consumption is 12 months, Jan highest, Jul/Aug lowest.
    assert len(row.typical_consumption) == 12
    assert row.typical_consumption[0] > row.typical_consumption[6]


def test_parse_gas_full_feed(gas_bill_data_xml: bytes) -> None:
    rows = parse_gas_feed(gas_bill_data_xml)
    assert len(rows) == 6
    distributors = list_gas_distributors(rows)
    assert set(distributors) == {
        "Enbridge Gas",
        "EPCOR Natural Gas Limited Partnership",
        "Union Gas",
    }
    sa = list_gas_service_areas(rows, "Union Gas")
    assert set(sa) == {"North East", "North West", "South"}
    rc = list_gas_rate_classes(rows, "Union Gas", "South")
    assert rc == ["M1"]


def test_find_gas_row_match(gas_bill_data_xml: bytes) -> None:
    rows = parse_gas_feed(gas_bill_data_xml)
    row = find_gas_row(rows, "Union Gas", "North East", "01")
    assert row.distributor == "Union Gas"
    assert row.service_area == "North East"
    assert row.rate_class == "01"
    # Union NE has all 5 tiers active.
    assert len(row.tiers) == 5


def test_find_gas_row_miss(gas_bill_data_xml: bytes) -> None:
    rows = parse_gas_feed(gas_bill_data_xml)
    with pytest.raises(OEBRowNotFoundError):
        find_gas_row(rows, "Nope Gas", "Somewhere", "1")


def test_parse_gas_malformed(gas_malformed_xml: bytes) -> None:
    with pytest.raises(OEBParseError):
        parse_gas_feed(gas_malformed_xml)


def test_parse_gas_wrong_root() -> None:
    body = b"<?xml version='1.0'?><NotDataRoot/>"
    with pytest.raises(OEBSchemaError):
        parse_gas_feed(body)


def test_parse_gas_empty_feed() -> None:
    body = b"<?xml version='1.0'?><dataroot></dataroot>"
    with pytest.raises(OEBSchemaError):
        parse_gas_feed(body)


def test_parse_gas_missing_field() -> None:
    body = (
        b"<?xml version='1.0'?><dataroot>"
        b"<GasBillData><Dist>X</Dist></GasBillData>"
        b"</dataroot>"
    )
    with pytest.raises(OEBSchemaError) as info:
        parse_gas_feed(body)
    assert "missing required fields" in str(info.value)


def test_gas_required_fields_snapshot() -> None:
    """Lock the schema contract so OEB renames surface in CI."""
    expected = {
        "Dist", "SA", "RC", "ED", "MC",
        "DT1Low", "DT1High", "DT2Low", "DT2High",
        "DT3Low", "DT3High", "DT4Low", "DT4High",
        "DT5Low", "DT5High",
        "DCT1", "DCT2", "DCT3", "DCT4", "DCT5", "DCPA",
        "SC", "SCPA", "CM", "CMPA", "TC", "TCPA",
        "FedCC", "FacCC", "GST",
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    }
    assert frozenset(expected) == GAS_REQUIRED_FIELDS


def test_epcor_aylmer_only_two_tiers(gas_bill_data_xml: bytes) -> None:
    rows = parse_gas_feed(gas_bill_data_xml)
    row = find_gas_row(rows, "EPCOR Natural Gas Limited Partnership", "Aylmer", "1")
    assert len(row.tiers) == 2  # DT3..DT5 are all zero
