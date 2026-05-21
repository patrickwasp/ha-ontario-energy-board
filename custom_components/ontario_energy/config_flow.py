"""Config flow for the Ontario Energy Board integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_CLASS,
    CONF_DISTRIBUTOR,
    CONF_PLAN,
    CONF_RATE_CLASS,
    CONF_SERVICE_AREA,
    CONF_UTILITY,
    DOMAIN,
    PLAN_AUTO,
    PLAN_OPTIONS,
    UTILITY_ELECTRICITY,
    UTILITY_GAS,
    UTILITY_OPTIONS,
)
from .gas_parser import (
    GasRateRow,
    fetch_gas_feed,
    list_gas_distributors,
    list_gas_rate_classes,
    list_gas_service_areas,
    parse_gas_feed,
)
from .parser import (
    OEBError,
    RateRow,
    fetch_all_electricity_rows,
    list_classes,
    list_distributors,
)


def _plan_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=list(PLAN_OPTIONS),
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="plan",
        )
    )


def _utility_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=list(UTILITY_OPTIONS),
            mode=SelectSelectorMode.LIST,
            translation_key="utility",
        )
    )


class OEBConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two- or three-step flow depending on selected utility."""

    VERSION = 1

    def __init__(self) -> None:
        self._utility: str | None = None
        self._elec_rows: list[RateRow] | None = None
        self._gas_rows: list[GasRateRow] | None = None
        self._distributor: str | None = None
        self._service_area: str | None = None

    async def _load_electricity(self) -> list[RateRow] | None:
        if self._elec_rows is not None:
            return self._elec_rows
        session = async_get_clientsession(self.hass)
        try:
            self._elec_rows = await fetch_all_electricity_rows(session)
        except OEBError:
            return None
        return self._elec_rows

    async def _load_gas(self) -> list[GasRateRow] | None:
        if self._gas_rows is not None:
            return self._gas_rows
        session = async_get_clientsession(self.hass)
        try:
            xml_bytes = await fetch_gas_feed(session)
            self._gas_rows = parse_gas_feed(xml_bytes)
        except OEBError:
            return None
        return self._gas_rows

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: pick utility type (electricity or gas)."""
        if user_input is not None:
            self._utility = user_input[CONF_UTILITY]
            if self._utility == UTILITY_GAS:
                return await self.async_step_gas_distributor()
            return await self.async_step_distributor()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_UTILITY, default=UTILITY_ELECTRICITY): (
                        _utility_selector()
                    ),
                }
            ),
        )

    # --- Electricity branch ---------------------------------------------

    async def async_step_distributor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Electricity step 2: pick distributor."""
        errors: dict[str, str] = {}
        rows = await self._load_electricity()
        if rows is None:
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="distributor", data_schema=vol.Schema({}), errors=errors
            )

        distributors = list_distributors(rows)
        if not distributors:
            return self.async_abort(reason="invalid_feed")

        if user_input is not None:
            self._distributor = user_input[CONF_DISTRIBUTOR]
            return await self.async_step_class()

        return self.async_show_form(
            step_id="distributor",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DISTRIBUTOR): SelectSelector(
                        SelectSelectorConfig(
                            options=distributors,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_class(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Electricity step 3: pick customer class and plan filter."""
        assert self._distributor is not None
        rows = await self._load_electricity()
        if rows is None:
            return self.async_abort(reason="cannot_connect")

        classes = list_classes(rows, self._distributor)
        if not classes:
            return self.async_abort(reason="invalid_feed")

        if user_input is not None:
            customer_class = user_input[CONF_CLASS]
            plan = user_input[CONF_PLAN]
            unique_id = f"electricity::{self._distributor}::{customer_class}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{self._distributor} - {customer_class}",
                data={
                    CONF_UTILITY: UTILITY_ELECTRICITY,
                    CONF_DISTRIBUTOR: self._distributor,
                    CONF_CLASS: customer_class,
                },
                options={CONF_PLAN: plan},
            )

        # Default to RESIDENTIAL when available (the most common case);
        # otherwise fall back to whatever's first in the list.
        default_class = "RESIDENTIAL" if "RESIDENTIAL" in classes else classes[0]
        return self.async_show_form(
            step_id="class",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLASS, default=default_class): SelectSelector(
                        SelectSelectorConfig(
                            options=classes,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_PLAN, default=PLAN_AUTO): _plan_selector(),
                }
            ),
        )

    # --- Gas branch -----------------------------------------------------

    async def async_step_gas_distributor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Gas step 2: pick distributor."""
        errors: dict[str, str] = {}
        rows = await self._load_gas()
        if rows is None:
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="gas_distributor", data_schema=vol.Schema({}), errors=errors
            )

        distributors = list_gas_distributors(rows)
        if not distributors:
            return self.async_abort(reason="invalid_feed")

        if user_input is not None:
            self._distributor = user_input[CONF_DISTRIBUTOR]
            return await self.async_step_gas_service_area()

        return self.async_show_form(
            step_id="gas_distributor",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DISTRIBUTOR): SelectSelector(
                        SelectSelectorConfig(
                            options=distributors,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_gas_service_area(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Gas step 3: pick service area for the chosen distributor."""
        assert self._distributor is not None
        rows = await self._load_gas()
        if rows is None:
            return self.async_abort(reason="cannot_connect")

        service_areas = list_gas_service_areas(rows, self._distributor)
        if not service_areas:
            return self.async_abort(reason="invalid_feed")

        if user_input is not None:
            self._service_area = user_input[CONF_SERVICE_AREA]
            return await self.async_step_gas_rate_class()

        return self.async_show_form(
            step_id="gas_service_area",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERVICE_AREA): SelectSelector(
                        SelectSelectorConfig(
                            options=service_areas,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_gas_rate_class(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Gas step 4: pick rate class for the chosen distributor + service area."""
        assert self._distributor is not None
        assert self._service_area is not None
        rows = await self._load_gas()
        if rows is None:
            return self.async_abort(reason="cannot_connect")

        rate_classes = list_gas_rate_classes(rows, self._distributor, self._service_area)
        if not rate_classes:
            return self.async_abort(reason="invalid_feed")

        if user_input is not None:
            rate_class = user_input[CONF_RATE_CLASS]
            unique_id = (
                f"gas::{self._distributor}::{self._service_area}::{rate_class}"
            )
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=(
                    f"{self._distributor} - {self._service_area} (RC {rate_class})"
                ),
                data={
                    CONF_UTILITY: UTILITY_GAS,
                    CONF_DISTRIBUTOR: self._distributor,
                    CONF_SERVICE_AREA: self._service_area,
                    CONF_RATE_CLASS: rate_class,
                },
                options={},
            )

        return self.async_show_form(
            step_id="gas_rate_class",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RATE_CLASS): SelectSelector(
                        SelectSelectorConfig(
                            options=rate_classes,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    # --- Options flow ---------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options flow for changing the plan filter (electricity entries only)."""
        return OEBOptionsFlow()


class OEBOptionsFlow(OptionsFlow):
    """Options flow: only the electricity plan filter can be changed."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update the plan option; HA will reload via the update listener."""
        # Gas entries have no configurable options — nothing to expose.
        if self.config_entry.data.get(CONF_UTILITY) == UTILITY_GAS:
            return self.async_create_entry(title="", data=dict(self.config_entry.options))

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_plan = self.config_entry.options.get(
            CONF_PLAN, self.config_entry.data.get(CONF_PLAN, PLAN_AUTO)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAN, default=current_plan): _plan_selector(),
                }
            ),
        )
