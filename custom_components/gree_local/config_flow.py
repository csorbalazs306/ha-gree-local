"""Config and options flow for Gree Local."""

from __future__ import annotations

import ipaddress
from typing import Any

from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_DOMAIN_NAME,
    CONF_EXTERNAL_IP,
    CONF_MQTT_HOLD,
    CONF_MQTT_MODE,
    CONF_MQTT_PORT,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    DEFAULT_DOMAIN_NAME,
    DEFAULT_MQTT_HOLD,
    DEFAULT_MQTT_MODE,
    DEFAULT_MQTT_PORT,
    DEFAULT_TCP_PORT,
    DEFAULT_TLS_PORT,
    DOMAIN,
    MQTT_MODES,
)

PORT = vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_EXTERNAL_IP, default=defaults[CONF_EXTERNAL_IP]): str,
            vol.Required(CONF_DOMAIN_NAME, default=defaults[CONF_DOMAIN_NAME]): str,
            vol.Required(CONF_TCP_PORT, default=defaults[CONF_TCP_PORT]): PORT,
            vol.Required(CONF_TLS_PORT, default=defaults[CONF_TLS_PORT]): PORT,
            vol.Required(CONF_MQTT_MODE, default=defaults[CONF_MQTT_MODE]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=MQTT_MODES, translation_key=CONF_MQTT_MODE)
            ),
            vol.Required(CONF_MQTT_PORT, default=defaults[CONF_MQTT_PORT]): PORT,
            vol.Required(CONF_MQTT_HOLD, default=defaults[CONF_MQTT_HOLD]): vol.All(
                vol.Coerce(float), vol.Range(min=0, max=300)
            ),
        }
    )


def _validate(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    try:
        ipaddress.IPv4Address(data[CONF_EXTERNAL_IP])
    except ValueError:
        errors[CONF_EXTERNAL_IP] = "invalid_ip"
    if len({data[CONF_TCP_PORT], data[CONF_TLS_PORT], data[CONF_MQTT_PORT]}) < 3:
        errors["base"] = "duplicate_ports"
    return errors


async def _defaults(hass: HomeAssistant) -> dict[str, Any]:
    try:
        ip = await async_get_source_ip(hass)
    except Exception:  # noqa: BLE001 - fall back to an editable placeholder
        ip = ""
    return {
        CONF_EXTERNAL_IP: ip or "",
        CONF_DOMAIN_NAME: DEFAULT_DOMAIN_NAME,
        CONF_TCP_PORT: DEFAULT_TCP_PORT,
        CONF_TLS_PORT: DEFAULT_TLS_PORT,
        CONF_MQTT_MODE: DEFAULT_MQTT_MODE,
        CONF_MQTT_PORT: DEFAULT_MQTT_PORT,
        CONF_MQTT_HOLD: DEFAULT_MQTT_HOLD,
    }


class GreeLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(title="Gree Local", data=user_input)
        defaults = user_input or await _defaults(self.hass)
        return self.async_show_form(step_id="user", data_schema=_schema(defaults), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GreeLocalOptionsFlow()


class GreeLocalOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
        defaults = user_input or {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(defaults), errors=errors)
