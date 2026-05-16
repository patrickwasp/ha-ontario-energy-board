"""Sensor platform for the Ontario Energy Board integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CURRENCY_DOLLAR,
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfVolume,
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_PLAN,
    CONF_UTILITY,
    PLAN_AUTO,
    PLAN_TIERED,
    PLAN_TOU,
    PLAN_ULO,
    TZ_NAME,
    UTILITY_ELECTRICITY,
    UTILITY_GAS,
)
from .coordinator import OEBData
from .entity import OEBEntity
from .schedule import (
    TouPeriod,
    UloPeriod,
    tou_period,
    tou_rate_for,
    ulo_period,
    ulo_rate_for,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import OEBConfigEntry, OEBUpdateCoordinator
    from .gas_parser import GasRateRow
    from .parser import RateRow


_ELEC_PRICE_UNIT = f"{CURRENCY_DOLLAR}/{UnitOfEnergy.KILO_WATT_HOUR}"
_GAS_PRICE_UNIT = f"{CURRENCY_DOLLAR}/{UnitOfVolume.CUBIC_METERS}"
_PLANS_ALL = frozenset({PLAN_AUTO, PLAN_TOU, PLAN_ULO, PLAN_TIERED})
_PLANS_TOU = frozenset({PLAN_AUTO, PLAN_TOU})
_PLANS_ULO = frozenset({PLAN_AUTO, PLAN_ULO})
_PLANS_TIERED = frozenset({PLAN_AUTO, PLAN_TIERED})


def _to_float(value: Decimal | int) -> float:
    """HA's StateType prefers float; convert Decimal cleanly."""
    return float(value)


@dataclass(frozen=True, kw_only=True)
class OEBSensorEntityDescription(SensorEntityDescription):
    """Sensor description with a value_fn and (electricity-only) plan filter."""

    value_fn: Callable[[OEBData, datetime], Any]
    plans: frozenset[str] = frozenset()  # electricity-only; empty for gas
    dynamic: bool = False


# ---------------------------------------------------------------------------
# ELECTRICITY SENSORS
# ---------------------------------------------------------------------------


def _elec_row(d: OEBData) -> RateRow:
    """Return the electricity row, asserting it's set for the active branch."""
    assert d.electricity_row is not None
    return d.electricity_row


ELECTRICITY_SENSORS: tuple[OEBSensorEntityDescription, ...] = (
    OEBSensorEntityDescription(
        key="current_tou_price",
        translation_key="current_tou_price",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        value_fn=lambda d, now: _to_float(tou_rate_for(_elec_row(d), now)),
        plans=_PLANS_TOU,
        dynamic=True,
    ),
    OEBSensorEntityDescription(
        key="current_tou_period",
        translation_key="current_tou_period",
        device_class=SensorDeviceClass.ENUM,
        options=[p.value for p in TouPeriod],
        value_fn=lambda d, now: tou_period(now).value,
        plans=_PLANS_TOU,
        dynamic=True,
    ),
    OEBSensorEntityDescription(
        key="current_ulo_price",
        translation_key="current_ulo_price",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        value_fn=lambda d, now: _to_float(ulo_rate_for(_elec_row(d), now)),
        plans=_PLANS_ULO,
        dynamic=True,
    ),
    OEBSensorEntityDescription(
        key="current_ulo_period",
        translation_key="current_ulo_period",
        device_class=SensorDeviceClass.ENUM,
        options=[p.value for p in UloPeriod],
        value_fn=lambda d, now: ulo_period(now).value,
        plans=_PLANS_ULO,
        dynamic=True,
    ),
    OEBSensorEntityDescription(
        key="tou_on_peak_rate",
        translation_key="tou_on_peak_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).tou_on),
        plans=_PLANS_TOU,
    ),
    OEBSensorEntityDescription(
        key="tou_mid_peak_rate",
        translation_key="tou_mid_peak_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).tou_mid),
        plans=_PLANS_TOU,
    ),
    OEBSensorEntityDescription(
        key="tou_off_peak_rate",
        translation_key="tou_off_peak_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).tou_off),
        plans=_PLANS_TOU,
    ),
    OEBSensorEntityDescription(
        key="ulo_on_peak_rate",
        translation_key="ulo_on_peak_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).ulo_on),
        plans=_PLANS_ULO,
    ),
    OEBSensorEntityDescription(
        key="ulo_mid_peak_rate",
        translation_key="ulo_mid_peak_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).ulo_mid),
        plans=_PLANS_ULO,
    ),
    OEBSensorEntityDescription(
        key="ulo_weekend_off_peak_rate",
        translation_key="ulo_weekend_off_peak_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).ulo_weekend_off),
        plans=_PLANS_ULO,
    ),
    OEBSensorEntityDescription(
        key="ulo_overnight_rate",
        translation_key="ulo_overnight_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).ulo_overnight),
        plans=_PLANS_ULO,
    ),
    OEBSensorEntityDescription(
        key="tier1_rate",
        translation_key="tier1_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).tier1_rate),
        plans=_PLANS_TIERED,
    ),
    OEBSensorEntityDescription(
        key="tier2_rate",
        translation_key="tier2_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).tier2_rate),
        plans=_PLANS_TIERED,
    ),
    OEBSensorEntityDescription(
        key="tier1_threshold",
        translation_key="tier1_threshold",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).tier1_threshold_kwh),
        plans=_PLANS_TIERED,
    ),
    OEBSensorEntityDescription(
        key="service_charge",
        translation_key="service_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_DOLLAR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).service_charge),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="distribution_volumetric",
        translation_key="distribution_volumetric",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).distribution_volumetric),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="network_charge",
        translation_key="network_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).network),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="connection_charge",
        translation_key="connection_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).connection),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="wmsr_charge",
        translation_key="wmsr_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).wmsr),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="rrrp_charge",
        translation_key="rrrp_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_ELEC_PRICE_UNIT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).rrrp),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="sss_admin_fee",
        translation_key="sss_admin_fee",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_DOLLAR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).sss_admin),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="loss_factor",
        translation_key="loss_factor",
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).loss_factor),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="hst_rate",
        translation_key="hst_rate",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).hst * 100),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="rebate_rate",
        translation_key="rebate_rate",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_elec_row(d).rebate * 100),
        plans=_PLANS_ALL,
    ),
    OEBSensorEntityDescription(
        key="rate_year",
        translation_key="rate_year",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _elec_row(d).rate_year,
        plans=_PLANS_ALL,
    ),
)


# ---------------------------------------------------------------------------
# GAS SENSORS
# ---------------------------------------------------------------------------


def _gas_row(d: OEBData) -> GasRateRow:
    """Return the gas row, asserting it's set for the active branch."""
    assert d.gas_row is not None
    return d.gas_row


def _typical_consumption_attrs(row: GasRateRow) -> dict[str, float]:
    months = (
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    )
    return {m: float(v) for m, v in zip(months, row.typical_consumption, strict=True)}


GAS_FIXED_SENSORS: tuple[OEBSensorEntityDescription, ...] = (
    OEBSensorEntityDescription(
        key="gas_monthly_customer_charge",
        translation_key="gas_monthly_customer_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_DOLLAR,
        suggested_display_precision=2,
        value_fn=lambda d, _now: _to_float(_gas_row(d).monthly_customer_charge),
    ),
    OEBSensorEntityDescription(
        key="gas_commodity_charge",
        translation_key="gas_commodity_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        value_fn=lambda d, _now: _to_float(_gas_row(d).commodity),
    ),
    OEBSensorEntityDescription(
        key="gas_commodity_pa",
        translation_key="gas_commodity_pa",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_gas_row(d).commodity_pa),
    ),
    OEBSensorEntityDescription(
        key="gas_transportation_charge",
        translation_key="gas_transportation_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        value_fn=lambda d, _now: _to_float(_gas_row(d).transportation),
    ),
    OEBSensorEntityDescription(
        key="gas_transportation_pa",
        translation_key="gas_transportation_pa",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_gas_row(d).transportation_pa),
    ),
    OEBSensorEntityDescription(
        key="gas_storage_charge",
        translation_key="gas_storage_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_gas_row(d).storage_charge),
    ),
    OEBSensorEntityDescription(
        key="gas_storage_pa",
        translation_key="gas_storage_pa",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_gas_row(d).storage_pa),
    ),
    OEBSensorEntityDescription(
        key="gas_delivery_pa",
        translation_key="gas_delivery_pa",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_gas_row(d).delivery_pa),
    ),
    OEBSensorEntityDescription(
        key="gas_federal_carbon_charge",
        translation_key="gas_federal_carbon_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        value_fn=lambda d, _now: _to_float(_gas_row(d).federal_carbon_charge),
    ),
    OEBSensorEntityDescription(
        key="gas_facility_carbon_charge",
        translation_key="gas_facility_carbon_charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        value_fn=lambda d, _now: _to_float(_gas_row(d).facility_carbon_charge),
    ),
    OEBSensorEntityDescription(
        key="gas_hst_rate",
        translation_key="gas_hst_rate",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _to_float(_gas_row(d).hst * 100),
    ),
    OEBSensorEntityDescription(
        key="gas_effective_year",
        translation_key="gas_effective_year",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _now: _gas_row(d).effective_date.year,
    ),
    OEBSensorEntityDescription(
        key="gas_typical_consumption",
        translation_key="gas_typical_consumption",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=0,
        value_fn=lambda d, now: _to_float(
            _gas_row(d).typical_consumption[now.month - 1]
        ),
        dynamic=True,
    ),
)


def _gas_tier_descriptions(n: int) -> Iterable[OEBSensorEntityDescription]:
    """Return the 3 sensor descriptions for tier *n* (rate, low, high)."""

    def _rate(d: OEBData, _now: datetime, *, idx: int = n - 1) -> float:
        return _to_float(_gas_row(d).tiers[idx].rate)

    def _low(d: OEBData, _now: datetime, *, idx: int = n - 1) -> float:
        return _to_float(_gas_row(d).tiers[idx].low)

    def _high(d: OEBData, _now: datetime, *, idx: int = n - 1) -> float:
        return _to_float(_gas_row(d).tiers[idx].high)

    yield OEBSensorEntityDescription(
        key=f"gas_delivery_tier_{n}_rate",
        translation_key=f"gas_delivery_tier_{n}_rate",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=_GAS_PRICE_UNIT,
        suggested_display_precision=6,
        value_fn=_rate,
    )
    yield OEBSensorEntityDescription(
        key=f"gas_delivery_tier_{n}_low",
        translation_key=f"gas_delivery_tier_{n}_low",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_low,
    )
    yield OEBSensorEntityDescription(
        key=f"gas_delivery_tier_{n}_high",
        translation_key=f"gas_delivery_tier_{n}_high",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_high,
    )


# ---------------------------------------------------------------------------
# PLATFORM SETUP
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OEBConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for one config entry, branched by utility type."""
    coordinator = entry.runtime_data
    utility = entry.data.get(CONF_UTILITY, UTILITY_ELECTRICITY)

    if utility == UTILITY_GAS:
        assert coordinator.data.gas_row is not None
        gas_row = coordinator.data.gas_row
        descriptions: list[OEBSensorEntityDescription] = list(GAS_FIXED_SENSORS)
        for n in range(1, len(gas_row.tiers) + 1):
            descriptions.extend(_gas_tier_descriptions(n))
        async_add_entities(
            OEBSensor(coordinator, entry, d) for d in descriptions
        )
        return

    plan = entry.options.get(CONF_PLAN, entry.data.get(CONF_PLAN, PLAN_AUTO))
    async_add_entities(
        OEBSensor(coordinator, entry, d)
        for d in ELECTRICITY_SENSORS
        if plan in d.plans
    )


class OEBSensor(OEBEntity, SensorEntity):
    """A single sensor backed by an OEBSensorEntityDescription."""

    entity_description: OEBSensorEntityDescription

    def __init__(
        self,
        coordinator: OEBUpdateCoordinator,
        entry: OEBConfigEntry,
        description: OEBSensorEntityDescription,
    ) -> None:
        """Initialize the sensor with its description and a stable unique_id."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        unique_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{unique_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Compute the value from current coordinator data + Ontario-local time."""
        from homeassistant.util import dt as dt_util

        now = dt_util.utcnow().astimezone(ZoneInfo(TZ_NAME))
        return self.entity_description.value_fn(self.coordinator.data, now)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attach all 12 months of typical consumption to the live sensor."""
        if (
            self.entity_description.key == "gas_typical_consumption"
            and self.coordinator.data.gas_row is not None
        ):
            return _typical_consumption_attrs(self.coordinator.data.gas_row)
        return None

    async def async_added_to_hass(self) -> None:
        """Subscribe to hourly updates for dynamic (period-dependent) sensors."""
        await super().async_added_to_hass()
        if self.entity_description.dynamic:
            self.async_on_remove(
                async_track_time_change(
                    self.hass, self._handle_hour, minute=0, second=0
                )
            )

    @callback
    def _handle_hour(self, _now: datetime) -> None:
        """Re-evaluate the value at the top of each hour."""
        self.async_write_ha_state()
