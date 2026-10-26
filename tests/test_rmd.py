"""Parser tests against pages saved from two live RMDs on 2026-10-24."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

# Load rmd.py on its own; the package __init__ needs Home Assistant.
_spec = importlib.util.spec_from_file_location(
    "rmd", ROOT / "custom_components" / "lg_resu_rmd" / "rmd.py"
)
rmd = importlib.util.module_from_spec(_spec)
sys.modules["rmd"] = rmd
_spec.loader.exec_module(rmd)

PACKS = ("pack91", "pack92")


def _page(pack: str, page: str) -> str:
    return (FIXTURES / f"{pack}-{page}.html").read_bytes().decode("utf-8", "replace")


@pytest.fixture(params=PACKS)
def data(request) -> dict[str, str]:
    return rmd.parse_bms_data(_page(request.param, "getbmsdata"))


def test_row_count_and_arrays(data):
    assert len(data) == 147
    assert rmd.cell_numbers(data) == list(range(1, 71))
    assert rmd.probe_numbers(data) == list(range(1, 9))
    # The DC-DC temperature and the probes are separate fields.
    assert "Temperature" in data and "Temperature[1]" in data


def test_units_are_stripped(data):
    assert rmd.to_float(data["SumSerialCellVoltage"]) == pytest.approx(
        float(data["SumSerialCellVoltage"].rstrip("V"))
    )
    assert data["MinTemperature"].endswith("℃")  # &#8451 decoded
    assert rmd.to_float(data["CycleCount"]) == 1.0
    assert rmd.to_float(data["LifeTimeDischargeEnergy"]) > 0


def test_pack91_values():
    data = rmd.parse_bms_data(_page("pack91", "getbmsdata"))
    assert rmd.to_float(data["SumSerialCellVoltage"]) == 256.2778
    assert rmd.to_float(data["Current"]) == -5.0
    assert rmd.to_float(data["SOC"]) == 49.54
    assert rmd.to_float(data["MinTemperature"]) == 18.3
    assert rmd.to_float(data["Temperature"]) == 30.4
    assert rmd.to_int(data["MinCellNumber"]) == 8
    assert rmd.to_int(data["HWInput"]) == 0x60001000
    assert rmd.cell_spread_mv(data) == 11.0
    assert rmd.pack_power(data) == pytest.approx(-1281.4, abs=0.05)


def test_bpi_current_matches_current(data):
    # BPI_Current is printed as unsigned x 0.1; corrected it equals Current.
    assert rmd.signed_tenths(data["BPI_Current"]) == pytest.approx(
        rmd.to_float(data["Current"]), abs=0.05
    )
    assert rmd.signed_tenths(data["IPI_Current"]) < 0  # discharging


@pytest.mark.parametrize(
    ("printed", "real"),
    [("6549.9A", -3.7), ("3276.7A", 3276.7), ("12.3A", 12.3), ("0.0A", 0.0)],
)
def test_signed_tenths(printed, real):
    assert rmd.signed_tenths(printed) == real


def test_no_problem_on_clean_pages(data):
    words = rmd.diag_words(data)
    assert len(words) == 11 and all(v is not None for v in words.values())
    assert rmd.has_problem(data) is False


def test_problem_when_any_word_set(data):
    data = dict(data, DiagResultHwWarning="0x00000010")
    assert rmd.has_problem(data) is True


def test_info():
    a = rmd.parse_info(_page("pack91", "getbmsinfo"), _page("pack91", "getversion"))
    b = rmd.parse_info(_page("pack92", "getbmsinfo"), _page("pack92", "getversion"))
    assert (a.serial, b.serial) == ("2201010001", "2201010002")
    assert a.battery_name == "RESU16H Prime"
    assert a.part_number == "EH257064P8S8DMA2201010001"
    assert a.bms_version == "0x02060304"
    assert a.rmd_version == "4.2.1"


def test_wrong_page_rejected():
    with pytest.raises(rmd.RmdResponseError):
        rmd.parse_bms_data("Moved to /login.html")
    with pytest.raises(rmd.RmdResponseError):
        rmd.parse_info(_page("pack91", "getrmdinfo"), None)


def test_saved_warranty_rows_parse():
    rows = rmd.parse_rows(_page("pack91", "getSavedWarranty"))
    assert rows["LifeTimeDischargeEnergy"] == "11298"


def test_client_refuses_other_paths():
    import asyncio

    client = rmd.RmdClient(session=None, host="192.0.2.1")
    with pytest.raises(ValueError):
        asyncio.run(client._get("/rst"))


def test_truncated_page_rejected():
    info = rmd.parse_info(_page("pack91", "getbmsinfo"), None)
    required = rmd.expected_fields(info)
    assert len(required) == 70 + 8 + 6
    page = _page("pack91", "getbmsdata")
    assert len(rmd.parse_bms_data(page, required)) == 147
    cut = page[: page.index("<tr><td>Cell[40]Voltage")]
    with pytest.raises(rmd.RmdResponseError, match="incomplete"):
        rmd.parse_bms_data(cut, required)
    # A reply that starts mid-page lacks the summary fields.
    tail = page[page.index("<tr><td>Cell[1]Voltage") :]
    with pytest.raises(rmd.RmdResponseError):
        rmd.parse_bms_data(tail, required)


def test_parse_wifi():
    wifi = rmd.parse_wifi((FIXTURES / "pack92-showapinfo.json").read_text())
    assert (wifi.rssi, wifi.channel, wifi.bssid) == (-75, 6, "02:00:00:00:00:02")
    assert wifi.ssid == "example-wifi"
    assert wifi.connected


def test_parse_wifi_not_connected():
    # Not observed on these packs (both on Wi-Fi): an empty SSID is what the
    # RMD's own UI treats as "WiFi is not connected!", e.g. on Ethernet.
    wifi = rmd.parse_wifi('{"state":0,"ssid":"","bssid":"","channel":0,"rssi":0}')
    assert not wifi.connected
    assert wifi.rssi is None


@pytest.mark.parametrize(
    "text", ["Moved to /login.html", '{"state":1}', "[]", '{"state":0,"rssi":"x"}']
)
def test_parse_wifi_rejects_or_degrades(text):
    if text == '{"state":0,"rssi":"x"}':
        assert rmd.parse_wifi(text).rssi is None  # no SSID, so not connected
    else:
        with pytest.raises(rmd.RmdResponseError):
            rmd.parse_wifi(text)


def test_showapinfo_is_the_only_new_path():
    assert rmd.READ_ONLY_PATHS == {
        "/getbmsdata",
        "/getbmsinfo",
        "/getversion",
        "/showapinfo",
    }
