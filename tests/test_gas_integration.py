"""Integration tests for the gas branch (coordinator, sensor, init)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ontario_energy.const import (
    CONF_DISTRIBUTOR,
    CONF_RATE_CLASS,
    CONF_SERVICE_AREA,
    CONF_UTILITY,
    DOMAIN,
    GAS_FEED_URL,
    UTILITY_GAS,
)
from custom_components.ontario_energy.coordinator import OEBUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


GAS_DIST = "Enbridge Gas"
GAS_SA = "All"
GAS_RC = "1"
GAS_UNIQUE_ID = f"gas::{GAS_DIST}::{GAS_SA}::{GAS_RC}"


def _gas_entry(
    distributor: str = GAS_DIST,
    service_area: str = GAS_SA,
    rate_class: str = GAS_RC,
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"gas::{distributor}::{service_area}::{rate_class}",
        data={
            CONF_UTILITY: UTILITY_GAS,
            CONF_DISTRIBUTOR: distributor,
            CONF_SERVICE_AREA: service_area,
            CONF_RATE_CLASS: rate_class,
        },
    )


async def test_gas_coordinator_happy_path(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
) -> None:
    aioclient_mock.get(GAS_FEED_URL, content=gas_bill_data_xml)
    entry = _gas_entry()
    entry.add_to_hass(hass)
    coord = OEBUpdateCoordinator(hass, entry)
    await coord.async_refresh()
    assert coord.last_update_success
    assert coord.data is not None
    assert coord.data.utility == UTILITY_GAS
    assert coord.data.gas_row is not None
    assert coord.data.gas_row.distributor == GAS_DIST


async def test_gas_coordinator_missing_row(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_minimal_xml: bytes,
) -> None:
    # Minimal fixture has only Enbridge — asking for Union must fail.
    aioclient_mock.get(GAS_FEED_URL, content=gas_minimal_xml)
    entry = _gas_entry(distributor="Union Gas", service_area="South", rate_class="M1")
    entry.add_to_hass(hass)
    coord = OEBUpdateCoordinator(hass, entry)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_gas_sensors_registered(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
) -> None:
    aioclient_mock.get(GAS_FEED_URL, content=gas_bill_data_xml)
    entry = _gas_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)

    def has(key: str) -> bool:
        return (
            ent_reg.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.unique_id}_{key}"
            )
            is not None
        )

    # Always-present gas sensors
    for key in (
        "gas_monthly_customer_charge",
        "gas_commodity_charge",
        "gas_commodity_pa",
        "gas_transportation_charge",
        "gas_transportation_pa",
        "gas_storage_charge",
        "gas_delivery_pa",
        "gas_federal_carbon_charge",
        "gas_facility_carbon_charge",
        "gas_hst_rate",
        "gas_effective_year",
        "gas_typical_consumption",
    ):
        assert has(key), key

    # Enbridge has 4 active tiers; tier 5 must NOT be registered.
    for n in (1, 2, 3, 4):
        assert has(f"gas_delivery_tier_{n}_rate"), n
        assert has(f"gas_delivery_tier_{n}_low"), n
        assert has(f"gas_delivery_tier_{n}_high"), n
    assert not has("gas_delivery_tier_5_rate")

    # No electricity sensors should appear on a gas entry.
    assert not has("current_tou_price")
    assert not has("tier1_rate")


async def test_gas_typical_consumption_has_monthly_attributes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
) -> None:
    aioclient_mock.get(GAS_FEED_URL, content=gas_bill_data_xml)
    entry = _gas_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    eid = ent_reg.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.unique_id}_gas_typical_consumption"
    )
    assert eid is not None
    state = hass.states.get(eid)
    assert state is not None
    attrs = state.attributes
    for month in (
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ):
        assert month in attrs, month


async def test_gas_setup_unload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
) -> None:
    aioclient_mock.get(GAS_FEED_URL, content=gas_bill_data_xml)
    entry = _gas_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert isinstance(entry.runtime_data, OEBUpdateCoordinator)
    assert entry.runtime_data.utility == UTILITY_GAS

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
