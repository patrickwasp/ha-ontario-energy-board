"""Diagnostics support for the Ontario Energy Board integration."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import OEBConfigEntry


def _jsonable(obj: Any) -> Any:
    """Recursively convert non-JSON-native values (Decimal, date, datetime)."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OEBConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    payload: dict[str, Any] = {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
                "unique_id": entry.unique_id,
            },
            set(),
        ),
        "utility": data.utility,
        "plan": data.plan,
        "last_update_success": coordinator.last_update_success,
        "fetched_at": data.fetched_at.isoformat(),
    }
    if data.electricity_row is not None:
        payload["electricity_row"] = _jsonable(asdict(data.electricity_row))
    if data.gas_row is not None:
        payload["gas_row"] = _jsonable(asdict(data.gas_row))
    return payload
