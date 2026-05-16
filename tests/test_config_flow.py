"""Config flow tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ontario_energy.const import (
    CONF_CLASS,
    CONF_DISTRIBUTOR,
    CONF_PLAN,
    CONF_RATE_CLASS,
    CONF_SERVICE_AREA,
    CONF_UTILITY,
    DOMAIN,
    ELECTRICITY_FEED_URL,
    ELECTRICITY_GS_FEED_URL,
    GAS_FEED_URL,
    UTILITY_ELECTRICITY,
    UTILITY_GAS,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


DISTRIBUTOR = "Alectra Utilities Corporation-Brampton Rate Zone"


async def _start_user_flow(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )


# --- Electricity branch ----------------------------------------------------


async def test_electricity_happy_path(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=bill_data_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    step1 = await _start_user_flow(hass)
    assert step1["step_id"] == "user"

    step2 = await hass.config_entries.flow.async_configure(
        step1["flow_id"], {CONF_UTILITY: UTILITY_ELECTRICITY}
    )
    assert step2["step_id"] == "distributor"

    step3 = await hass.config_entries.flow.async_configure(
        step2["flow_id"], {CONF_DISTRIBUTOR: DISTRIBUTOR}
    )
    assert step3["step_id"] == "class"

    result = await hass.config_entries.flow.async_configure(
        step3["flow_id"],
        {CONF_CLASS: "RESIDENTIAL", CONF_PLAN: "auto"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_UTILITY: UTILITY_ELECTRICITY,
        CONF_DISTRIBUTOR: DISTRIBUTOR,
        CONF_CLASS: "RESIDENTIAL",
    }
    assert result["options"] == {CONF_PLAN: "auto"}
    assert result["result"].unique_id == f"electricity::{DISTRIBUTOR}::RESIDENTIAL"
    await hass.async_block_till_done()


async def test_electricity_duplicate_aborts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=bill_data_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"electricity::{DISTRIBUTOR}::RESIDENTIAL",
        data={
            CONF_UTILITY: UTILITY_ELECTRICITY,
            CONF_DISTRIBUTOR: DISTRIBUTOR,
            CONF_CLASS: "RESIDENTIAL",
        },
        options={CONF_PLAN: "auto"},
    )
    existing.add_to_hass(hass)

    step1 = await _start_user_flow(hass)
    step2 = await hass.config_entries.flow.async_configure(
        step1["flow_id"], {CONF_UTILITY: UTILITY_ELECTRICITY}
    )
    step3 = await hass.config_entries.flow.async_configure(
        step2["flow_id"], {CONF_DISTRIBUTOR: DISTRIBUTOR}
    )
    result = await hass.config_entries.flow.async_configure(
        step3["flow_id"],
        {CONF_CLASS: "RESIDENTIAL", CONF_PLAN: "auto"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_electricity_gs50_happy_path(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    """A GS<50 kW class from BillData_GS.xml is selectable end-to-end."""
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=bill_data_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    step1 = await _start_user_flow(hass)
    step2 = await hass.config_entries.flow.async_configure(
        step1["flow_id"], {CONF_UTILITY: UTILITY_ELECTRICITY}
    )
    step3 = await hass.config_entries.flow.async_configure(
        step2["flow_id"], {CONF_DISTRIBUTOR: DISTRIBUTOR}
    )
    # The merged feed exposes both RESIDENTIAL (from BillData) and
    # GENERAL SERVICE LESS THAN 50 KW (from BillData_GS).
    classes = step3["data_schema"].schema[CONF_CLASS].config["options"]
    assert "RESIDENTIAL" in classes
    assert "GENERAL SERVICE LESS THAN 50 KW" in classes

    result = await hass.config_entries.flow.async_configure(
        step3["flow_id"],
        {CONF_CLASS: "GENERAL SERVICE LESS THAN 50 KW", CONF_PLAN: "tou"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CLASS] == "GENERAL SERVICE LESS THAN 50 KW"
    assert (
        result["result"].unique_id
        == f"electricity::{DISTRIBUTOR}::GENERAL SERVICE LESS THAN 50 KW"
    )
    await hass.async_block_till_done()


async def test_electricity_cannot_connect(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_gs_xml: bytes,
) -> None:
    aioclient_mock.get(ELECTRICITY_FEED_URL, status=500)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    step1 = await _start_user_flow(hass)
    step2 = await hass.config_entries.flow.async_configure(
        step1["flow_id"], {CONF_UTILITY: UTILITY_ELECTRICITY}
    )
    assert step2["type"] is FlowResultType.FORM
    assert step2["errors"] == {"base": "cannot_connect"}


async def test_options_flow_round_trip(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> None:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=bill_data_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"electricity::{DISTRIBUTOR}::RESIDENTIAL",
        data={
            CONF_UTILITY: UTILITY_ELECTRICITY,
            CONF_DISTRIBUTOR: DISTRIBUTOR,
            CONF_CLASS: "RESIDENTIAL",
        },
        options={CONF_PLAN: "auto"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    init = await hass.config_entries.options.async_init(entry.entry_id)
    assert init["type"] is FlowResultType.FORM
    assert init["step_id"] == "init"

    saved = await hass.config_entries.options.async_configure(
        init["flow_id"], {CONF_PLAN: "tou"}
    )
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PLAN] == "tou"
    # Let the update listener fire its reload before pytest-HA checks for
    # lingering timers (the per-entity hour-tick subscription).
    await hass.async_block_till_done()


# --- Gas branch ------------------------------------------------------------

GAS_DIST = "Enbridge Gas"
GAS_SA = "All"
GAS_RC = "1"


async def test_gas_happy_path(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
) -> None:
    aioclient_mock.get(GAS_FEED_URL, content=gas_bill_data_xml)
    step1 = await _start_user_flow(hass)
    step2 = await hass.config_entries.flow.async_configure(
        step1["flow_id"], {CONF_UTILITY: UTILITY_GAS}
    )
    assert step2["step_id"] == "gas_distributor"

    step3 = await hass.config_entries.flow.async_configure(
        step2["flow_id"], {CONF_DISTRIBUTOR: GAS_DIST}
    )
    assert step3["step_id"] == "gas_service_area"

    step4 = await hass.config_entries.flow.async_configure(
        step3["flow_id"], {CONF_SERVICE_AREA: GAS_SA}
    )
    assert step4["step_id"] == "gas_rate_class"

    result = await hass.config_entries.flow.async_configure(
        step4["flow_id"], {CONF_RATE_CLASS: GAS_RC}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_UTILITY: UTILITY_GAS,
        CONF_DISTRIBUTOR: GAS_DIST,
        CONF_SERVICE_AREA: GAS_SA,
        CONF_RATE_CLASS: GAS_RC,
    }
    assert result["result"].unique_id == f"gas::{GAS_DIST}::{GAS_SA}::{GAS_RC}"
    await hass.async_block_till_done()


async def test_gas_duplicate_aborts(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
) -> None:
    aioclient_mock.get(GAS_FEED_URL, content=gas_bill_data_xml)
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"gas::{GAS_DIST}::{GAS_SA}::{GAS_RC}",
        data={
            CONF_UTILITY: UTILITY_GAS,
            CONF_DISTRIBUTOR: GAS_DIST,
            CONF_SERVICE_AREA: GAS_SA,
            CONF_RATE_CLASS: GAS_RC,
        },
    )
    existing.add_to_hass(hass)

    step1 = await _start_user_flow(hass)
    step2 = await hass.config_entries.flow.async_configure(
        step1["flow_id"], {CONF_UTILITY: UTILITY_GAS}
    )
    step3 = await hass.config_entries.flow.async_configure(
        step2["flow_id"], {CONF_DISTRIBUTOR: GAS_DIST}
    )
    step4 = await hass.config_entries.flow.async_configure(
        step3["flow_id"], {CONF_SERVICE_AREA: GAS_SA}
    )
    result = await hass.config_entries.flow.async_configure(
        step4["flow_id"], {CONF_RATE_CLASS: GAS_RC}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_gas_options_flow_is_noop(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
) -> None:
    """Gas entries have no configurable options; options flow short-circuits."""
    aioclient_mock.get(GAS_FEED_URL, content=gas_bill_data_xml)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"gas::{GAS_DIST}::{GAS_SA}::{GAS_RC}",
        data={
            CONF_UTILITY: UTILITY_GAS,
            CONF_DISTRIBUTOR: GAS_DIST,
            CONF_SERVICE_AREA: GAS_SA,
            CONF_RATE_CLASS: GAS_RC,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    init = await hass.config_entries.options.async_init(entry.entry_id)
    assert init["type"] is FlowResultType.CREATE_ENTRY
