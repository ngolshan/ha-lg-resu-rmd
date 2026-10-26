"""Setup, entity values, failure handling, diagnostics and unload."""

from __future__ import annotations

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.lg_resu_rmd.const import DEFAULT_SCAN_INTERVAL, DOMAIN
from custom_components.lg_resu_rmd.rmd import (
    READ_ONLY_PATHS,
    RmdConnectionError,
    RmdResponseError,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from .conftest import HOST, NAME, SERIAL, page

E = "lg_resu16h_1"
NO_RETRY_DELAY = patch("custom_components.lg_resu_rmd.coordinator.RETRY_DELAY", 0)


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    # Interval refreshes run as background tasks.
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_device(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), setup_entry.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, SERIAL)}
    assert device.name == NAME
    assert device.manufacturer == "LG Energy Solution"
    assert device.model == "RESU16H Prime"
    assert device.model_id == "EH257064P8S8DMA2201010001"
    assert device.serial_number == SERIAL
    assert device.sw_version == "BMS 0x02060304, RMD 4.2.1, DC-DC 0x01040000"
    assert device.configuration_url == f"http://{HOST}/"


async def test_sensor_values(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    # Values from tests/fixtures/pack91-getbmsdata.html.
    expected = {
        f"sensor.{E}_soc": "49.54",
        f"sensor.{E}_real_soc": "49.54",
        f"sensor.{E}_soh": "100.0",
        f"sensor.{E}_voltage": "256.2778",
        f"sensor.{E}_current": "-5.0",
        f"sensor.{E}_power": "-1281.4",
        f"sensor.{E}_min_cell_voltage": "3.6565",
        f"sensor.{E}_max_cell_voltage": "3.6675",
        f"sensor.{E}_avg_cell_voltage": "3.6611",
        f"sensor.{E}_cell_spread": "11.0",
        f"sensor.{E}_lowest_cell": "8",
        f"sensor.{E}_highest_cell": "67",
        f"sensor.{E}_min_temperature": "18.3",
        f"sensor.{E}_max_temperature": "19.9",
        f"sensor.{E}_avg_temperature": "19.2",
        f"sensor.{E}_charge_current_limit": "27.314",
        f"sensor.{E}_discharge_current_limit": "28.172",
        f"sensor.{E}_charge_power_limit": "7000.0",
        f"sensor.{E}_discharge_power_limit": "7220.0",
        f"sensor.{E}_cycle_count": "1.0",
        f"sensor.{E}_lifetime_discharge_energy": "11.298",
        f"sensor.{E}_bpi_voltage": "256.7",
        f"sensor.{E}_bpi_current": "-5.0",
        f"sensor.{E}_ipi_voltage": "406.3",
        f"sensor.{E}_ipi_current": "-3.2",
        f"sensor.{E}_dc_dc_temperature": "30.4",
        f"sensor.{E}_shutdown_reason": "0x0000",
    }
    actual = {entity_id: _state(hass, entity_id) for entity_id in expected}
    assert actual == expected

    energy = hass.states.get(f"sensor.{E}_lifetime_discharge_energy")
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert energy.attributes["state_class"] == "total_increasing"


async def test_display_precision(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    precision = {
        "voltage": 4,
        "current": 1,
        "soc": 2,
        "cell_spread": 1,
        "min_cell_voltage": 4,
    }
    for key, digits in precision.items():
        entry = registry.async_get(f"sensor.{E}_{key}")
        assert entry.options["sensor"]["suggested_display_precision"] == digits, key


async def test_cells_and_probes_disabled_by_default(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, setup_entry.entry_id)
    cells = [e for e in entries if e.unique_id.startswith(f"{SERIAL}_cell_")]
    cells.remove(registry.async_get(f"sensor.{E}_cell_spread"))
    probes = [e for e in entries if e.unique_id.startswith(f"{SERIAL}_temperature_")]
    assert len(cells) == 70 and len(probes) == 8
    for entry in cells + probes:
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entry.entity_id) is None
    assert registry.async_get(f"sensor.{E}_cell_70_voltage") is not None
    assert registry.async_get(f"sensor.{E}_temperature_8") is not None
    # 27 summary sensors, 70 cells, 8 probes, 1 problem sensor.
    assert len(entries) == 27 + 70 + 8 + 1


async def test_problem_sensor_off(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    state = hass.states.get(f"binary_sensor.{E}_problem")
    assert state.state == STATE_OFF
    assert state.attributes["device_class"] == "problem"
    assert state.attributes["DiagResultGeneralAlarm"] == "0x00000000"
    assert state.attributes["DCDC Diag 3"] == "0x0000"
    assert len([k for k in state.attributes if k.startswith(("Diag", "DCDC"))]) == 11


async def test_problem_sensor_on(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    bad = page("pack91", "getbmsdata").replace(
        b"<td>DiagResultHwWarning</td><td>0x00000000</td>",
        b"<td>DiagResultHwWarning</td><td>0x00000010</td>",
    )
    for name in ("getbmsinfo", "getversion"):
        aioclient_mock.get(f"http://{HOST}/{name}", content=page("pack91", name))
    aioclient_mock.get(f"http://{HOST}/getbmsdata", content=bad)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(f"binary_sensor.{E}_problem")
    assert state.state == STATE_ON
    assert state.attributes["DiagResultHwWarning"] == "0x00000010"


async def test_one_request_per_poll_and_read_only(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_rmd: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    calls_after_setup = mock_rmd.call_count
    await _poll(hass, freezer)
    assert mock_rmd.call_count == calls_after_setup + 1
    for method, url, _data, _headers in mock_rmd.mock_calls:
        assert method == "GET"
        assert url.path in READ_ONLY_PATHS


async def test_failed_poll_retries_then_goes_unavailable(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = setup_entry.runtime_data
    good = coordinator.data
    with (
        NO_RETRY_DELAY,
        patch.object(
            coordinator.client,
            "async_get_bms_data",
            side_effect=RmdResponseError("incomplete"),
        ) as get,
    ):
        await _poll(hass, freezer)
    assert get.call_count == 2
    assert _state(hass, f"sensor.{E}_soc") == STATE_UNAVAILABLE
    assert _state(hass, f"binary_sensor.{E}_problem") == STATE_UNAVAILABLE

    # A failure followed by a good retry keeps the entities available.
    with (
        NO_RETRY_DELAY,
        patch.object(
            coordinator.client,
            "async_get_bms_data",
            side_effect=[RmdConnectionError("timed out"), good],
        ) as get,
    ):
        await _poll(hass, freezer)
    assert get.call_count == 2
    assert _state(hass, f"sensor.{E}_soc") == "49.54"


async def test_truncated_page_goes_unavailable(
    hass: HomeAssistant,
    setup_entry: MockConfigEntry,
    mock_rmd: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    full = page("pack91", "getbmsdata")
    mock_rmd.clear_requests()
    mock_rmd.get(
        f"http://{HOST}/getbmsdata", content=full[: full.index(b"<tr><td>Cell[40]")]
    )
    with NO_RETRY_DELAY:
        await _poll(hass, freezer)
    assert _state(hass, f"sensor.{E}_voltage") == STATE_UNAVAILABLE


async def test_unreachable_at_startup_retries_setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    aioclient_mock.get(f"http://{HOST}/getbmsinfo", exc=TimeoutError())
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry: MockConfigEntry,
) -> None:
    assert await async_setup_component(hass, "diagnostics", {})
    diag = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)
    assert diag["entry"]["data"] == {"host": HOST}
    assert diag["bms_info"]["BMS Serial Number"] == SERIAL
    assert diag["bms_data"]["HWInput"] == "0x60001000"
    assert len(diag["bms_data"]) == 147


async def test_unload(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.NOT_LOADED
