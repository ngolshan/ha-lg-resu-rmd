"""Download diagnostics: the pack info and the last /getbmsdata page."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import RmdConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RmdConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "last_update_success": coordinator.last_update_success,
        "bms_info": coordinator.info.raw,
        "rmd_version": coordinator.info.rmd_version,
        "bms_data": coordinator.data,
    }
