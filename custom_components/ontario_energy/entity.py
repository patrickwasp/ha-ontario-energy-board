"""Base entity for the Ontario Energy Board integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, UTILITY_GAS

if TYPE_CHECKING:
    from .coordinator import OEBConfigEntry, OEBUpdateCoordinator


_GAS_MODEL = "Natural Gas Pricing Feed"
_ELECTRICITY_MODEL = "Electricity Pricing Feed"


class OEBEntity(CoordinatorEntity["OEBUpdateCoordinator"]):
    """Base entity binding to the OEB coordinator and a stable device."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: OEBUpdateCoordinator,
        entry: OEBConfigEntry,
    ) -> None:
        """Initialize the entity and build device info from coordinator data."""
        super().__init__(coordinator)
        data = coordinator.data
        unique_id = entry.unique_id or entry.entry_id
        if data.utility == UTILITY_GAS:
            assert data.gas_row is not None
            row = data.gas_row
            device_name = f"{row.distributor} - {row.service_area} (RC {row.rate_class})"
            model = _GAS_MODEL
        else:
            assert data.electricity_row is not None
            erow = data.electricity_row
            device_name = f"{erow.distributor} - {erow.customer_class}"
            model = _ELECTRICITY_MODEL

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=model,
            configuration_url="https://www.oeb.ca/",
        )
