"""Base entity: one device per pack."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import RmdCoordinator


class RmdEntity(CoordinatorEntity[RmdCoordinator]):
    """An entity fed by the pack's coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RmdCoordinator, key: str) -> None:
        super().__init__(coordinator)
        info = coordinator.info
        self._attr_unique_id = f"{info.serial}_{key}"
        versions = [
            f"BMS {info.bms_version}" if info.bms_version else None,
            f"RMD {info.rmd_version}" if info.rmd_version else None,
            f"DC-DC {info.dcdc_fw_version}" if info.dcdc_fw_version else None,
        ]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.serial)},
            name=coordinator.config_entry.title,
            manufacturer=MANUFACTURER,
            model=info.battery_name,
            model_id=info.part_number,
            serial_number=info.serial,
            sw_version=", ".join(v for v in versions if v) or None,
            hw_version=info.bms_hw_version,
            configuration_url=f"http://{coordinator.client.host}/",
        )
