"""HA-integration tests for the Green Button importer + service.

The recorder isn't mocked here — instead we patch the single ``async_add_external_statistics``
call site and assert it received the right metadata + cumulative-sum data.
That covers everything the integration owns; the actual recorder write is
HA's responsibility and has its own tests upstream.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
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
from custom_components.ontario_energy.green_button_importer import async_import_file

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.test_util.aiohttp import (
        AiohttpClientMocker,
    )


DIST_E = "Alectra Utilities Corporation-Brampton Rate Zone"
DIST_G = "Enbridge Gas"
ADD_STATS_PATH = (
    "custom_components.ontario_energy.green_button_importer."
    "async_add_external_statistics"
)


async def _setup_electricity_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
) -> MockConfigEntry:
    aioclient_mock.get(ELECTRICITY_FEED_URL, content=bill_data_xml)
    aioclient_mock.get(ELECTRICITY_GS_FEED_URL, content=bill_data_gs_xml)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"electricity::{DIST_E}::RESIDENTIAL",
        data={
            CONF_UTILITY: UTILITY_ELECTRICITY,
            CONF_DISTRIBUTOR: DIST_E,
            CONF_CLASS: "RESIDENTIAL",
        },
        options={CONF_PLAN: "auto"},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


async def _setup_gas_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
) -> MockConfigEntry:
    aioclient_mock.get(GAS_FEED_URL, content=gas_bill_data_xml)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"gas::{DIST_G}::All::1",
        data={
            CONF_UTILITY: UTILITY_GAS,
            CONF_DISTRIBUTOR: DIST_G,
            CONF_SERVICE_AREA: "All",
            CONF_RATE_CLASS: "1",
        },
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


def _copy_fixture(tmp_path: Path, fixture_name: str) -> Path:
    src = Path(__file__).parent / "fixtures" / fixture_name
    dst = tmp_path / fixture_name
    dst.write_bytes(src.read_bytes())
    return dst


async def test_import_electricity_writes_expected_stats(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
    tmp_path: Path,
) -> None:
    entry = await _setup_electricity_entry(
        hass, aioclient_mock, bill_data_xml, bill_data_gs_xml
    )
    espi = _copy_fixture(tmp_path, "espi_electricity_minimal.xml")

    with patch(ADD_STATS_PATH) as mock_add:
        result = await async_import_file(hass, entry, espi)

    assert mock_add.called
    metadata, stats = mock_add.call_args.args[1], list(mock_add.call_args.args[2])

    assert metadata["source"] == DOMAIN
    assert metadata["statistic_id"].endswith("_elec_consumption")
    assert metadata["has_sum"] is True
    assert metadata["unit_of_measurement"] == "kWh"

    # 4 hourly readings → 4 statistics, cumulative sums = [0.5, 1.25, 2.5, 3.4].
    assert [round(s["sum"], 4) for s in stats] == [0.5, 1.25, 2.5, 3.4]
    assert [round(s["state"], 4) for s in stats] == [0.5, 0.75, 1.25, 0.9]

    assert result.intervals_imported == 4
    assert result.unit == "kWh"
    assert result.total == Decimal("3.4")


async def test_import_gas_writes_expected_stats(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    gas_bill_data_xml: bytes,
    tmp_path: Path,
) -> None:
    entry = await _setup_gas_entry(hass, aioclient_mock, gas_bill_data_xml)
    espi = _copy_fixture(tmp_path, "espi_gas_minimal.xml")

    with patch(ADD_STATS_PATH) as mock_add:
        result = await async_import_file(hass, entry, espi)

    assert mock_add.called
    metadata, stats = mock_add.call_args.args[1], list(mock_add.call_args.args[2])

    assert metadata["statistic_id"].endswith("_gas_consumption")
    assert metadata["unit_of_measurement"] == "m³"
    assert [round(s["sum"], 4) for s in stats] == [3.0, 8.0, 12.0]

    assert result.unit == "m³"
    assert result.intervals_imported == 3


async def test_import_wrong_commodity_raises(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
    tmp_path: Path,
) -> None:
    """Gas ESPI imported against an electricity entry must fail loudly."""
    entry = await _setup_electricity_entry(
        hass, aioclient_mock, bill_data_xml, bill_data_gs_xml
    )
    espi = _copy_fixture(tmp_path, "espi_gas_minimal.xml")
    with patch(ADD_STATS_PATH), pytest.raises(ValueError, match="commodity"):
        await async_import_file(hass, entry, espi)


async def test_import_missing_file(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
    tmp_path: Path,
) -> None:
    entry = await _setup_electricity_entry(
        hass, aioclient_mock, bill_data_xml, bill_data_gs_xml
    )
    with pytest.raises(FileNotFoundError):
        await async_import_file(hass, entry, tmp_path / "does_not_exist.xml")


async def test_service_registered_and_callable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
    tmp_path: Path,
) -> None:
    entry = await _setup_electricity_entry(
        hass, aioclient_mock, bill_data_xml, bill_data_gs_xml
    )
    assert hass.services.has_service(DOMAIN, "import_green_button_file")

    espi = _copy_fixture(tmp_path, "espi_electricity_minimal.xml")
    with patch(ADD_STATS_PATH):
        response = await hass.services.async_call(
            DOMAIN,
            "import_green_button_file",
            {"file_path": str(espi), "config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )
    assert response is not None
    assert response["intervals_imported"] == 4
    assert response["unit"] == "kWh"


async def test_service_invalid_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    bill_data_xml: bytes,
    bill_data_gs_xml: bytes,
    tmp_path: Path,
) -> None:
    await _setup_electricity_entry(
        hass, aioclient_mock, bill_data_xml, bill_data_gs_xml
    )
    espi = _copy_fixture(tmp_path, "espi_electricity_minimal.xml")
    with patch(ADD_STATS_PATH), pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "import_green_button_file",
            {"file_path": str(espi), "config_entry_id": "not-a-real-entry-id"},
            blocking=True,
            return_response=True,
        )
