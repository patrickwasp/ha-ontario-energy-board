"""Tests for ``custom_components.ontario_energy.parser``."""

from __future__ import annotations

from decimal import Decimal

import pytest

from custom_components.ontario_energy.parser import (
    REQUIRED_FIELDS,
    OEBParseError,
    OEBRowNotFoundError,
    OEBSchemaError,
    find_row,
    list_classes,
    list_distributors,
    parse_feed,
)


def test_parse_feed_decodes_one_row(bill_data_minimal_xml: bytes) -> None:
    rows = parse_feed(bill_data_minimal_xml)
    assert len(rows) == 1
    row = rows[0]
    assert row.distributor.startswith("Alectra")
    assert row.customer_class == "RESIDENTIAL"
    assert row.rate_year == 2026
    # Sanity-check that money fields are Decimal, not float.
    for value in (
        row.tou_off,
        row.tou_mid,
        row.tou_on,
        row.ulo_overnight,
        row.tier1_rate,
        row.tier2_rate,
        row.service_charge,
        row.hst,
        row.rebate,
    ):
        assert isinstance(value, Decimal)
    # Ranges that won't be wrong even after a rate change (just sanity).
    assert Decimal(0) < row.tou_off < row.tou_mid < row.tou_on
    assert row.ulo_overnight < row.ulo_on


def test_parse_feed_multiple_rows(bill_data_xml: bytes) -> None:
    rows = parse_feed(bill_data_xml)
    assert len(rows) == 10
    distributors = list_distributors(rows)
    assert "Alectra Utilities Corporation-Brampton Rate Zone" in distributors
    assert "Algoma Power Inc." in distributors
    classes = list_classes(rows, "Algoma Power Inc.")
    assert "RESIDENTIAL R1" in classes
    assert "SEASONAL CUSTOMERS" in classes


def test_find_row_match(bill_data_xml: bytes) -> None:
    rows = parse_feed(bill_data_xml)
    row = find_row(rows, "Algoma Power Inc.", "SEASONAL CUSTOMERS")
    assert row.distributor == "Algoma Power Inc."
    assert row.customer_class == "SEASONAL CUSTOMERS"


def test_find_row_miss(bill_data_xml: bytes) -> None:
    rows = parse_feed(bill_data_xml)
    with pytest.raises(OEBRowNotFoundError):
        find_row(rows, "Nope Power Inc.", "RESIDENTIAL")


def test_parse_feed_malformed(malformed_xml: bytes) -> None:
    with pytest.raises(OEBParseError):
        parse_feed(malformed_xml)


def test_parse_feed_missing_field() -> None:
    body = (
        b"<?xml version='1.0'?><BillDataTable>"
        b"<BillDataRow><Dist>X</Dist></BillDataRow>"
        b"</BillDataTable>"
    )
    with pytest.raises(OEBSchemaError) as info:
        parse_feed(body)
    msg = str(info.value)
    # The error message lists the missing fields so we can keep up with schema drift.
    assert "missing required fields" in msg


def test_parse_feed_wrong_root() -> None:
    body = b"<?xml version='1.0'?><NotBillData/>"
    with pytest.raises(OEBSchemaError):
        parse_feed(body)


def test_parse_feed_empty_table() -> None:
    body = b"<?xml version='1.0'?><BillDataTable></BillDataTable>"
    with pytest.raises(OEBSchemaError) as info:
        parse_feed(body)
    assert "no <BillDataRow>" in str(info.value)


def test_parse_feed_empty_decimal_becomes_zero() -> None:
    """An empty numeric element (`<DC/>`) should become ``Decimal(0)``, not raise."""
    body = b"<?xml version='1.0'?><BillDataTable>" + (
        b"<BillDataRow>"
        b"<Dist>Test</Dist><Class>RESIDENTIAL</Class><YEAR>2026</YEAR>"
        b"<ET1>600</ET1><RPP1>0.1</RPP1><RPP2>0.14</RPP2>"
        b"<RPPOffP>0.1</RPPOffP><RPPMidP>0.15</RPPMidP><RPPOnP>0.2</RPPOnP>"
        b"<ULO_overnight>0.04</ULO_overnight>"
        b"<ULO_weekendoffp>0.1</ULO_weekendoffp>"
        b"<ULO_midp>0.15</ULO_midp><ULO_onp>0.4</ULO_onp>"
        b"<SC>30</SC><DC/><Net>0.01</Net><Conn>0.01</Conn>"
        b"<WMSR>0.005</WMSR><RRRP>0.001</RRRP><SSS>0.25</SSS>"
        b"<LF>1.03</LF><GST>0.13</GST><Rebate>0.235</Rebate>"
        b"</BillDataRow>"
    ) + b"</BillDataTable>"
    rows = parse_feed(body)
    assert rows[0].distribution_volumetric == Decimal(0)


def test_parse_feed_invalid_decimal() -> None:
    body = b"<?xml version='1.0'?><BillDataTable>" + (
        b"<BillDataRow>"
        b"<Dist>X</Dist><Class>RESIDENTIAL</Class><YEAR>2026</YEAR>"
        b"<ET1>not-a-number</ET1><RPP1>0.1</RPP1><RPP2>0.14</RPP2>"
        b"<RPPOffP>0.1</RPPOffP><RPPMidP>0.15</RPPMidP><RPPOnP>0.2</RPPOnP>"
        b"<ULO_overnight>0.04</ULO_overnight>"
        b"<ULO_weekendoffp>0.1</ULO_weekendoffp>"
        b"<ULO_midp>0.15</ULO_midp><ULO_onp>0.4</ULO_onp>"
        b"<SC>30</SC><DC>0</DC><Net>0.01</Net><Conn>0.01</Conn>"
        b"<WMSR>0.005</WMSR><RRRP>0.001</RRRP><SSS>0.25</SSS>"
        b"<LF>1.03</LF><GST>0.13</GST><Rebate>0.235</Rebate>"
        b"</BillDataRow>"
    ) + b"</BillDataTable>"
    with pytest.raises(OEBSchemaError):
        parse_feed(body)


def test_parse_feed_empty_year() -> None:
    body = b"<?xml version='1.0'?><BillDataTable>" + (
        b"<BillDataRow>"
        b"<Dist>X</Dist><Class>RESIDENTIAL</Class><YEAR></YEAR>"
        b"<ET1>600</ET1><RPP1>0.1</RPP1><RPP2>0.14</RPP2>"
        b"<RPPOffP>0.1</RPPOffP><RPPMidP>0.15</RPPMidP><RPPOnP>0.2</RPPOnP>"
        b"<ULO_overnight>0.04</ULO_overnight>"
        b"<ULO_weekendoffp>0.1</ULO_weekendoffp>"
        b"<ULO_midp>0.15</ULO_midp><ULO_onp>0.4</ULO_onp>"
        b"<SC>30</SC><DC>0</DC><Net>0.01</Net><Conn>0.01</Conn>"
        b"<WMSR>0.005</WMSR><RRRP>0.001</RRRP><SSS>0.25</SSS>"
        b"<LF>1.03</LF><GST>0.13</GST><Rebate>0.235</Rebate>"
        b"</BillDataRow>"
    ) + b"</BillDataTable>"
    with pytest.raises(OEBSchemaError) as info:
        parse_feed(body)
    assert "YEAR" in str(info.value)


def test_parse_feed_non_integer_year() -> None:
    body = b"<?xml version='1.0'?><BillDataTable>" + (
        b"<BillDataRow>"
        b"<Dist>X</Dist><Class>RESIDENTIAL</Class><YEAR>twenty-six</YEAR>"
        b"<ET1>600</ET1><RPP1>0.1</RPP1><RPP2>0.14</RPP2>"
        b"<RPPOffP>0.1</RPPOffP><RPPMidP>0.15</RPPMidP><RPPOnP>0.2</RPPOnP>"
        b"<ULO_overnight>0.04</ULO_overnight>"
        b"<ULO_weekendoffp>0.1</ULO_weekendoffp>"
        b"<ULO_midp>0.15</ULO_midp><ULO_onp>0.4</ULO_onp>"
        b"<SC>30</SC><DC>0</DC><Net>0.01</Net><Conn>0.01</Conn>"
        b"<WMSR>0.005</WMSR><RRRP>0.001</RRRP><SSS>0.25</SSS>"
        b"<LF>1.03</LF><GST>0.13</GST><Rebate>0.235</Rebate>"
        b"</BillDataRow>"
    ) + b"</BillDataTable>"
    with pytest.raises(OEBSchemaError):
        parse_feed(body)


def test_parse_gs50_feed(bill_data_gs_xml: bytes) -> None:
    """The General Service <50 kW feed shares the residential schema."""
    rows = parse_feed(bill_data_gs_xml)
    assert len(rows) == 10
    # Every row in this fixture is the same customer class.
    classes = {row.customer_class for row in rows}
    assert classes == {"GENERAL SERVICE LESS THAN 50 KW"}
    # GS<50 has a higher Tier 1 threshold (750 kWh) than residential (600).
    assert rows[0].tier1_threshold_kwh == Decimal(750)


def test_required_fields_snapshot() -> None:
    """Lock the schema contract: if OEB renames a field, this fails first."""
    assert frozenset(
        {
            "Dist", "Class", "YEAR", "ET1",
            "RPP1", "RPP2",
            "RPPOffP", "RPPMidP", "RPPOnP",
            "ULO_overnight", "ULO_weekendoffp", "ULO_midp", "ULO_onp",
            "SC", "DC", "Net", "Conn", "WMSR", "RRRP", "SSS", "LF",
            "GST", "Rebate",
        }
    ) == REQUIRED_FIELDS
