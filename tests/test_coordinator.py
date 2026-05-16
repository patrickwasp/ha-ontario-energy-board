"""Coordinator-level tests: HTTP errors map to UpdateFailed, happy path works."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ontario_energy.const import (
    CONF_CLASS,
    CONF_DISTRIBUTOR,
    DOMAIN,
    ELECTRICITY_FEED_URL,
    ELECTRICITY_GS_FEED_URL,
)
from custom_components.ontario_energy.coordinator import OEBUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


def _entry(plan: str = "auto", customer_class: str = "RESIDENTIAL") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=(
            "electricity::Alectra Utilities Corporation-Brampton Rate Zone::"
            + customer_class
        ),
        data={
            "utility": "electricity",
            CONF_DISTRIBUTOR: "Alectra Utilities Corporation-Brampton Rate Zone",
            CONF_CLASS: customer_class,
        },
        options={"plan": plan},
    )


async def test_coordinator_happy_path(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=bill_data_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    entry = _entry()
    entry.add_to_hass(hass)
    coord = OEBUpdateCoordinator(hass, entry)
    await coord.async_refresh()
    assert coord.last_update_success
    assert coord.data is not None
    assert coord.data.electricity_row is not None
    assert coord.data.electricity_row.customer_class == "RESIDENTIAL"


async def test_coordinator_http_500(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_gs_xml: bytes,
) -> None:
    aioclient_mock.get(ELECTRICITY_FEED_URL, status=500)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    entry = _entry()
    entry.add_to_hass(hass)
    coord = OEBUpdateCoordinator(hass, entry)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_coordinator_malformed_xml(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    malformed_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=malformed_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    entry = _entry()
    entry.add_to_hass(hass)
    coord = OEBUpdateCoordinator(hass, entry)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_coordinator_missing_row(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_minimal_xml: bytes,
    bill_data_gs_minimal_xml: bytes,
) -> None:
    # Minimal fixtures have only RESIDENTIAL + GS<50 — asking for SEASONAL must fail.
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=bill_data_minimal_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_minimal_xml)
    entry = _entry(customer_class="SEASONAL CUSTOMERS")
    entry.add_to_hass(hass)
    coord = OEBUpdateCoordinator(hass, entry)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
