"""Download diagnostics: the pack info and the last /getbmsdata page."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import RmdConfigEntry

# Identify the owner's pack or network if a download is shared in an issue.
TO_REDACT = {
    "BMS Serial Number",
    "Pack Serial Number",
    "Pack Part Number",
    "ssid",
    "bssid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RmdConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "last_update_success": coordinator.last_update_success,
            "bms_info": coordinator.info.raw,
            "rmd_version": coordinator.info.rmd_version,
            "bms_data": coordinator.data,
            "wifi": asdict(coordinator.wifi) if coordinator.wifi else None,
        },
        TO_REDACT,
    )
