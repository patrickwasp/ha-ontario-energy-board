"""Integration setup / unload / reload tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ontario_energy.const import (
    CONF_CLASS,
    CONF_DISTRIBUTOR,
    CONF_PLAN,
    DOMAIN,
    ELECTRICITY_FEED_URL,
    ELECTRICITY_GS_FEED_URL,
    PLAN_AUTO,
)
from custom_components.ontario_energy.coordinator import OEBUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


async def _setup_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    body: bytes,
    gs_body: bytes,
    plan: str = PLAN_AUTO,
) -> MockConfigEntry:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=body)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=gs_body)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="electricity::Alectra Utilities Corporation-Brampton Rate Zone::RESIDENTIAL",
        data={
            "utility": "electricity",
            CONF_DISTRIBUTOR: "Alectra Utilities Corporation-Brampton Rate Zone",
            CONF_CLASS: "RESIDENTIAL",
        },
        options={CONF_PLAN: plan},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_unload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    entry = await _setup_entry(hass, aioclient_mock, bill_data_xml, bill_data_gs_xml)
    assert isinstance(entry.runtime_data, OEBUpdateCoordinator)
    assert entry.runtime_data.data.electricity_row is not None
    assert entry.runtime_data.data.electricity_row.distributor.startswith("Alectra")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_options_flow_triggers_reload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    entry = await _setup_entry(hass, aioclient_mock, bill_data_xml, bill_data_gs_xml)
    first_coordinator = entry.runtime_data
    assert first_coordinator.plan == "auto"

    # Change plan via options → update listener triggers a reload.
    hass.config_entries.async_update_entry(entry, options={CONF_PLAN: "tou"})
    await hass.async_block_till_done()

    # After reload, a fresh coordinator with the new plan is in place.
    second_coordinator = entry.runtime_data
    assert second_coordinator is not first_coordinator
    assert second_coordinator.plan == "tou"
