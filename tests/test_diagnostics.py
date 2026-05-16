"""Diagnostics tests."""

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
)
from custom_components.ontario_energy.diagnostics import (
    async_get_config_entry_diagnostics,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


async def test_diagnostics_payload_shape(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_minimal_xml: bytes,
    bill_data_gs_minimal_xml: bytes,
) -> None:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=bill_data_minimal_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_minimal_xml)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="electricity::Alectra Utilities Corporation-Brampton Rate Zone::RESIDENTIAL",
        data={
            "utility": "electricity",
            CONF_DISTRIBUTOR: "Alectra Utilities Corporation-Brampton Rate Zone",
            CONF_CLASS: "RESIDENTIAL",
        },
        options={CONF_PLAN: "auto"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    payload = await async_get_config_entry_diagnostics(hass, entry)

    assert payload["utility"] == "electricity"
    assert payload["plan"] == "auto"
    assert payload["last_update_success"] is True
    assert "fetched_at" in payload
    assert payload["entry"]["unique_id"].endswith("::RESIDENTIAL")

    row = payload["electricity_row"]
    # Money fields must be JSON-safe strings (Decimals were converted).
    for key in (
        "tou_off",
        "tou_mid",
        "tou_on",
        "ulo_overnight",
        "tier1_rate",
        "service_charge",
        "hst",
        "rebate",
    ):
        assert isinstance(row[key], str), key
    assert row["rate_year"] == 2026
    assert row["customer_class"] == "RESIDENTIAL"
