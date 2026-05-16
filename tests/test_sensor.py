"""Sensor platform tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ontario_energy.const import (
    CONF_CLASS,
    CONF_DISTRIBUTOR,
    CONF_PLAN,
    DOMAIN,
    ELECTRICITY_FEED_URL,
    ELECTRICITY_GS_FEED_URL,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


DISTRIBUTOR = "Alectra Utilities Corporation-Brampton Rate Zone"
UNIQUE_ID = f"electricity::{DISTRIBUTOR}::RESIDENTIAL"


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    body: bytes,
    gs_body: bytes,
    plan: str,
) -> MockConfigEntry:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=body)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=gs_body)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID,
        data={
            "utility": "electricity",
            CONF_DISTRIBUTOR: DISTRIBUTOR,
            CONF_CLASS: "RESIDENTIAL",
        },
        options={CONF_PLAN: plan},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity_id_for(
    hass: HomeAssistant, entry: MockConfigEntry, key: str
) -> str | None:
    """Look up the actual entity_id for ``description.key`` via the registry."""
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.unique_id}_{key}"
    )


async def test_auto_plan_exposes_full_set(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    entry = await _setup(hass, aioclient_mock, bill_data_xml, bill_data_gs_xml, "auto")
    for key in (
        "current_tou_price",
        "current_tou_period",
        "current_ulo_price",
        "current_ulo_period",
        "tou_on_peak_rate",
        "ulo_overnight_rate",
        "tier1_rate",
        "service_charge",
        "hst_rate",
        "rebate_rate",
        "rate_year",
    ):
        assert _entity_id_for(hass, entry, key) is not None, key


@pytest.mark.parametrize(
    ("plan", "must_have", "must_lack"),
    [
        ("tou", "current_tou_price", "current_ulo_price"),
        ("ulo", "current_ulo_price", "current_tou_price"),
        ("tiered", "tier1_rate", "current_tou_price"),
    ],
)
async def test_plan_filters_hide_off_plan_sensors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
    plan: str,
    must_have: str,
    must_lack: str,
) -> None:
    entry = await _setup(hass, aioclient_mock, bill_data_xml, bill_data_gs_xml, plan)
    assert _entity_id_for(hass, entry, must_have) is not None
    assert _entity_id_for(hass, entry, must_lack) is None
    # Delivery sensors stay regardless of plan.
    assert _entity_id_for(hass, entry, "service_charge") is not None


async def test_current_tou_price_matches_period(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    entry = await _setup(hass, aioclient_mock, bill_data_xml, bill_data_gs_xml, "auto")
    period_eid = _entity_id_for(hass, entry, "current_tou_period")
    price_eid = _entity_id_for(hass, entry, "current_tou_price")
    assert period_eid is not None
    assert price_eid is not None

    period_state = hass.states.get(period_eid)
    price_state = hass.states.get(price_eid)
    assert period_state is not None
    assert price_state is not None
    assert period_state.state in {"on", "mid", "off"}

    matching_key = {
        "on": "tou_on_peak_rate",
        "mid": "tou_mid_peak_rate",
        "off": "tou_off_peak_rate",
    }[period_state.state]
    matching_eid = _entity_id_for(hass, entry, matching_key)
    assert matching_eid is not None
    matching_state = hass.states.get(matching_eid)
    assert matching_state is not None
    assert float(price_state.state) == pytest.approx(float(matching_state.state))
