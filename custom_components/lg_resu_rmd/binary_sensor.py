"""Problem sensor: on if any alarm, warning or fault word is non-zero."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import RmdConfigEntry, RmdCoordinator
from .entity import RmdEntity
from .rmd import diag_words, has_problem


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RmdConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([RmdProblemSensor(entry.runtime_data)])


class RmdProblemSensor(RmdEntity, BinarySensorEntity):
    """Any DiagResult* or DCDC Diag word non-zero; each word is an attribute."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "problem"

    def __init__(self, coordinator: RmdCoordinator) -> None:
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool | None:
        return has_problem(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return diag_words(self.coordinator.data)
