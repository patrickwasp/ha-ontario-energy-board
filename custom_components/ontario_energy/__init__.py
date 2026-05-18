"""The Ontario Energy Board integration."""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import OEBConfigEntry, OEBUpdateCoordinator
from .green_button_importer import GreenButtonImportResult, async_import_file
from .parser import OEBError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

SERVICE_IMPORT_GREEN_BUTTON_FILE = "import_green_button_file"
_IMPORT_SCHEMA = vol.Schema(
    {
        vol.Required("file_path"): cv.string,
        vol.Required("config_entry_id"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register integration-wide services (none of which need a config entry)."""

    async def _handle_import(call: ServiceCall) -> ServiceResponse:
        # call.data is already validated by the schema= passed to async_register.
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if entry is None or entry.domain != DOMAIN:
            raise ConfigEntryError(
                f"Config entry {call.data['config_entry_id']!r} is not an Ontario Energy Board entry"
            )
        try:
            result: GreenButtonImportResult = await async_import_file(
                hass, entry, Path(call.data["file_path"])
            )
        except FileNotFoundError as err:
            raise HomeAssistantError(str(err)) from err
        except (OEBError, ValueError) as err:
            raise HomeAssistantError(f"Green Button import failed: {err}") from err
        payload: dict[str, Any] = asdict(result)
        payload["total"] = str(result.total)  # Decimal -> str for JSON
        return payload

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_GREEN_BUTTON_FILE,
        _handle_import,
        schema=_IMPORT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OEBConfigEntry) -> bool:
    """Set up Ontario Energy Board from a config entry."""
    coordinator = OEBUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OEBConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: OEBConfigEntry
) -> None:
    """Reload entry when options change so the entity set re-registers."""
    await hass.config_entries.async_reload(entry.entry_id)
