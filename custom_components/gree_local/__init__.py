"""Gree Local: a local stand-in for the Gree cloud."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .server import GreeLocalServer, build_ssl_context

_LOGGER = logging.getLogger(__name__)

type GreeLocalConfigEntry = ConfigEntry[GreeLocalServer]


async def async_setup_entry(hass: HomeAssistant, entry: GreeLocalConfigEntry) -> bool:
    config = {**entry.data, **entry.options}
    ssl_context = await hass.async_add_executor_job(build_ssl_context, hass.config.path(DOMAIN))
    server = GreeLocalServer(config, ssl_context)
    try:
        await server.start()
    except OSError as err:
        raise ConfigEntryNotReady(f"Cannot open listening port: {err}") from err
    entry.runtime_data = server
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GreeLocalConfigEntry) -> bool:
    await entry.runtime_data.stop()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: GreeLocalConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
