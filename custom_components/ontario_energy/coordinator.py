"""DataUpdateCoordinator for the Ontario Energy Board integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CLASS,
    CONF_DISTRIBUTOR,
    CONF_PLAN,
    CONF_RATE_CLASS,
    CONF_SERVICE_AREA,
    CONF_UTILITY,
    DOMAIN,
    PLAN_AUTO,
    SCAN_INTERVAL,
    UTILITY_ELECTRICITY,
    UTILITY_GAS,
)
from .gas_parser import (
    GasRateRow,
    fetch_gas_feed,
    find_gas_row,
    parse_gas_feed,
)
from .parser import (
    OEBError,
    RateRow,
    fetch_all_electricity_rows,
    find_row,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

type OEBConfigEntry = ConfigEntry[OEBUpdateCoordinator]


@dataclass(frozen=True, slots=True)
class OEBData:
    """Snapshot stored by the coordinator for one config entry.

    Exactly one of ``electricity_row`` / ``gas_row`` is non-None, selected by
    ``utility``. The other utility's field is unused.
    """

    utility: str
    fetched_at: datetime
    electricity_row: RateRow | None = None
    plan: str | None = None
    gas_row: GasRateRow | None = None


class OEBUpdateCoordinator(DataUpdateCoordinator[OEBData]):
    """Fetch and parse either the electricity or the gas OEB feed."""

    def __init__(self, hass: HomeAssistant, entry: OEBConfigEntry) -> None:
        """Initialize from the entry's utility-type + identifying fields."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self._utility: str = entry.data.get(CONF_UTILITY, UTILITY_ELECTRICITY)
        if self._utility == UTILITY_GAS:
            self._distributor: str = entry.data[CONF_DISTRIBUTOR]
            self._service_area: str = entry.data[CONF_SERVICE_AREA]
            self._rate_class: str = entry.data[CONF_RATE_CLASS]
        else:
            self._distributor = entry.data[CONF_DISTRIBUTOR]
            self._customer_class: str = entry.data[CONF_CLASS]
            self._plan: str = entry.options.get(
                CONF_PLAN, entry.data.get(CONF_PLAN, PLAN_AUTO)
            )

    @property
    def utility(self) -> str:
        """Either ``UTILITY_ELECTRICITY`` or ``UTILITY_GAS``."""
        return self._utility

    @property
    def plan(self) -> str:
        """Electricity plan filter. Returns 'auto' for gas entries."""
        return getattr(self, "_plan", PLAN_AUTO)

    async def _async_update_data(self) -> OEBData:
        """Fetch and parse the feed; map parser errors to UpdateFailed."""
        session = async_get_clientsession(self.hass)
        now = datetime.now(tz=UTC)
        if self._utility == UTILITY_GAS:
            try:
                gas_bytes = await fetch_gas_feed(session)
                gas_rows = parse_gas_feed(gas_bytes)
                gas_row = find_gas_row(
                    gas_rows, self._distributor, self._service_area, self._rate_class
                )
            except OEBError as err:
                raise UpdateFailed(str(err)) from err
            return OEBData(utility=UTILITY_GAS, gas_row=gas_row, fetched_at=now)

        try:
            elec_rows = await fetch_all_electricity_rows(session)
            elec_row = find_row(elec_rows, self._distributor, self._customer_class)
        except OEBError as err:
            raise UpdateFailed(str(err)) from err
        return OEBData(
            utility=UTILITY_ELECTRICITY,
            electricity_row=elec_row,
            plan=self._plan,
            fetched_at=now,
        )
