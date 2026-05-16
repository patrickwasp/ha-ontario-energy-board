"""Constants for the Ontario Energy Board integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ontario_energy"
MANUFACTURER: Final = "Ontario Energy Board"
ATTRIBUTION: Final = "Data provided by the Ontario Energy Board"

ELECTRICITY_FEED_URL: Final = "https://www.oeb.ca/_html/calculator/data/BillData.xml"
ELECTRICITY_GS_FEED_URL: Final = "https://www.oeb.ca/_html/calculator/data/BillData_GS.xml"
GAS_FEED_URL: Final = "https://www.oeb.ca/_html/calculator/data/GasBillData.xml"
FEED_TIMEOUT_SECONDS: Final = 30
SCAN_INTERVAL: Final = timedelta(hours=12)

# Shared config keys
CONF_UTILITY: Final = "utility"
CONF_DISTRIBUTOR: Final = "distributor"
CONF_CLASS: Final = "customer_class"
CONF_PLAN: Final = "plan"
# Gas-specific
CONF_SERVICE_AREA: Final = "service_area"
CONF_RATE_CLASS: Final = "rate_class"

# Utility types
UTILITY_ELECTRICITY: Final = "electricity"
UTILITY_GAS: Final = "gas"
UTILITY_OPTIONS: Final = (UTILITY_ELECTRICITY, UTILITY_GAS)

# Electricity plan filters
PLAN_AUTO: Final = "auto"
PLAN_TOU: Final = "tou"
PLAN_ULO: Final = "ulo"
PLAN_TIERED: Final = "tiered"
PLAN_OPTIONS: Final = (PLAN_AUTO, PLAN_TOU, PLAN_ULO, PLAN_TIERED)

TZ_NAME: Final = "America/Toronto"
