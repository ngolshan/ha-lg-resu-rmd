"""Sensors from the RMD's /getbmsdata page."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import RmdConfigEntry, RmdCoordinator
from .entity import RmdEntity
from .rmd import (
    cell_numbers,
    cell_spread_mv,
    pack_power,
    probe_numbers,
    signed_tenths,
    to_float,
    to_int,
)

V = UnitOfElectricPotential.VOLT
A = UnitOfElectricCurrent.AMPERE
W = UnitOfPower.WATT
DEG_C = UnitOfTemperature.CELSIUS
DIAG = EntityCategory.DIAGNOSTIC
MEAS = SensorStateClass.MEASUREMENT


@dataclass(frozen=True, kw_only=True)
class RmdSensorDescription(SensorEntityDescription):
    """A sensor and how to read it from the page."""

    value_fn: Callable[[dict[str, str]], StateType]


def _num(field: str) -> Callable[[dict[str, str]], StateType]:
    return lambda data: to_float(data.get(field))


def _int(field: str) -> Callable[[dict[str, str]], StateType]:
    return lambda data: to_int(data.get(field))


def _signed(field: str) -> Callable[[dict[str, str]], StateType]:
    return lambda data: signed_tenths(data.get(field))


def _text(field: str) -> Callable[[dict[str, str]], StateType]:
    return lambda data: data.get(field)


def _volts(key: str, field: str, precision: int = 4, **kw) -> RmdSensorDescription:
    return RmdSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=V,
        state_class=MEAS,
        suggested_display_precision=precision,
        value_fn=_num(field),
        **kw,
    )


def _amps(key: str, value_fn, **kw) -> RmdSensorDescription:
    return RmdSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=A,
        state_class=MEAS,
        suggested_display_precision=1,
        value_fn=value_fn,
        **kw,
    )


def _temp(key: str, field: str, **kw) -> RmdSensorDescription:
    return RmdSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=DEG_C,
        state_class=MEAS,
        suggested_display_precision=1,
        value_fn=_num(field),
        **kw,
    )


def _watts(key: str, value_fn, **kw) -> RmdSensorDescription:
    return RmdSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=W,
        state_class=MEAS,
        suggested_display_precision=0,
        value_fn=value_fn,
        **kw,
    )


def _pct(key: str, field: str, **kw) -> RmdSensorDescription:
    return RmdSensorDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PERCENTAGE,
        state_class=MEAS,
        suggested_display_precision=2,
        value_fn=_num(field),
        **kw,
    )


SENSORS: tuple[RmdSensorDescription, ...] = (
    _pct("soc", "SOC", device_class=SensorDeviceClass.BATTERY),
    _pct("real_soc", "RealSOC"),
    _pct("soh", "SOH"),
    _volts("voltage", "SumSerialCellVoltage"),
    _amps("current", _num("Current")),
    _watts("power", pack_power),
    _volts("min_cell_voltage", "MinCellVoltage"),
    _volts("max_cell_voltage", "MaxCellVoltage"),
    _volts("avg_cell_voltage", "AvgCellVoltage"),
    RmdSensorDescription(
        key="cell_spread",
        translation_key="cell_spread",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        state_class=MEAS,
        suggested_display_precision=1,
        value_fn=cell_spread_mv,
    ),
    RmdSensorDescription(
        key="min_cell_number",
        translation_key="min_cell_number",
        entity_category=DIAG,
        value_fn=_int("MinCellNumber"),
    ),
    RmdSensorDescription(
        key="max_cell_number",
        translation_key="max_cell_number",
        entity_category=DIAG,
        value_fn=_int("MaxCellNumber"),
    ),
    _temp("min_temperature", "MinTemperature"),
    _temp("max_temperature", "MaxTemperature"),
    _temp("avg_temperature", "AvgTemperature"),
    _amps("charge_current_limit", _num("ChargeCurrentLimit"), entity_category=DIAG),
    _amps(
        "discharge_current_limit", _num("DischargeCurrentLimit"), entity_category=DIAG
    ),
    _watts("charge_power_limit", _num("ChargePowerLimit"), entity_category=DIAG),
    _watts("discharge_power_limit", _num("DischargePowerLimit"), entity_category=DIAG),
    RmdSensorDescription(
        key="cycle_count",
        translation_key="cycle_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=_num("CycleCount"),
    ),
    RmdSensorDescription(
        key="lifetime_discharge_energy",
        translation_key="lifetime_discharge_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        value_fn=_num("LifeTimeDischargeEnergy"),
    ),
    _volts("bpi_voltage", "BPI_Voltage", precision=1, entity_category=DIAG),
    _amps("bpi_current", _signed("BPI_Current"), entity_category=DIAG),
    _volts("ipi_voltage", "IPI_Voltage", precision=1, entity_category=DIAG),
    _amps("ipi_current", _signed("IPI_Current"), entity_category=DIAG),
    _temp("dcdc_temperature", "Temperature", entity_category=DIAG),
    RmdSensorDescription(
        key="shutdown_reason",
        translation_key="shutdown_reason",
        entity_category=DIAG,
        value_fn=_text("ShutdownReason"),
    ),
)


def _cell_sensor(n: int) -> RmdSensorDescription:
    return RmdSensorDescription(
        key=f"cell_{n}_voltage",
        translation_key="cell_voltage",
        translation_placeholders={"cell": str(n)},
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=V,
        state_class=MEAS,
        suggested_display_precision=4,
        entity_category=DIAG,
        entity_registry_enabled_default=False,
        value_fn=_num(f"Cell[{n}]Voltage"),
    )


def _probe_sensor(n: int) -> RmdSensorDescription:
    return RmdSensorDescription(
        key=f"temperature_{n}",
        translation_key="probe_temperature",
        translation_placeholders={"probe": str(n)},
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=DEG_C,
        state_class=MEAS,
        suggested_display_precision=1,
        entity_category=DIAG,
        entity_registry_enabled_default=False,
        value_fn=_num(f"Temperature[{n}]"),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RmdConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    descriptions = [
        *SENSORS,
        *(_cell_sensor(n) for n in cell_numbers(coordinator.data)),
        *(_probe_sensor(n) for n in probe_numbers(coordinator.data)),
    ]
    async_add_entities(
        [*(RmdSensor(coordinator, d) for d in descriptions), RmdWifiSensor(coordinator)]
    )


class RmdSensor(RmdEntity, SensorEntity):
    """One value from /getbmsdata."""

    entity_description: RmdSensorDescription

    def __init__(
        self, coordinator: RmdCoordinator, description: RmdSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.translation_placeholders:
            self._attr_translation_placeholders = dict(
                description.translation_placeholders
            )

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)


class RmdWifiSensor(RmdEntity, SensorEntity):
    """RSSI of the RMD's Wi-Fi link from /showapinfo; SSID, BSSID, channel as attributes."""

    _attr_translation_key = "wifi_signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = MEAS
    _attr_entity_category = DIAG
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: RmdCoordinator) -> None:
        super().__init__(coordinator, "wifi_signal")

    @property
    def available(self) -> bool:
        # Unavailable when the read failed or the RMD isn't on Wi-Fi (Ethernet).
        wifi = self.coordinator.wifi
        return super().available and wifi is not None and wifi.connected

    @property
    def native_value(self) -> int | None:
        wifi = self.coordinator.wifi
        return wifi.rssi if wifi else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        wifi = self.coordinator.wifi
        if wifi is None or not wifi.connected:
            return {}
        return {"ssid": wifi.ssid, "bssid": wifi.bssid, "channel": wifi.channel}
