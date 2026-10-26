"""LG RESU Prime local diagnostics from the RMD's web pages (read-only)."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .coordinator import RmdConfigEntry, RmdCoordinator
from .rmd import RmdClient

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: RmdConfigEntry) -> bool:
    """Set up one pack."""
    client = RmdClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    coordinator = RmdCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RmdConfigEntry) -> bool:
    """Unload one pack."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: RmdConfigEntry) -> None:
    """Reload so a new poll interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
