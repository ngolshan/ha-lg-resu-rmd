"""Read-only client and parser for the LG RESU Prime RMD's local web pages.

This module has no Home Assistant imports so the parser can be unit-tested on
its own. It only ever issues GETs of four pages the RMD's own web UI reads for
display (/getbmsdata, /getbmsinfo, /getversion, /showapinfo); the RMD's write
and action endpoints (/factory, /rst, /setbmsmode, /dcdccmd, /cantx, /scanap,
...) are never called.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import html
import json
import re

import aiohttp

# The only paths this client will request.
PATH_BMS_DATA = "/getbmsdata"
PATH_BMS_INFO = "/getbmsinfo"
PATH_VERSION = "/getversion"
# The station link: SSID, BSSID, channel and RSSI of the AP the RMD joined.
PATH_WIFI = "/showapinfo"
READ_ONLY_PATHS = frozenset({PATH_BMS_DATA, PATH_BMS_INFO, PATH_VERSION, PATH_WIFI})

# Pack 2 has taken up to 9 s to answer over Wi-Fi when it does answer.
DEFAULT_TIMEOUT = 15

# Rows look like <tr><td>Name</td><td>Value</td></tr>; /getSavedWarranty
# writes <td > with a space, so allow attributes and whitespace.
_ROW_RE = re.compile(
    r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>", re.S | re.I
)
_NUM_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")
_CELL_RE = re.compile(r"^Cell\[(\d+)\]Voltage$")
_PROBE_RE = re.compile(r"^Temperature\[(\d+)\]$")

# Fields /getbmsdata must contain for a response to count as valid.
REQUIRED_FIELDS = ("SumSerialCellVoltage", "Current", "SOC", "SOH")

# Alarm, warning and fault words; any non-zero word means a problem.
DIAG_WORDS = (
    "DiagResultGeneralAlarm",
    "DiagResultGeneralWarning",
    "DiagResultFault1",
    "DiagResultFault2",
    "DiagResultHwAlarm",
    "DiagResultHwWarning",
    "DiagResultHwFault1",
    "DiagResultHwFault2",
    "DCDC Diag 1",
    "DCDC Diag 2",
    "DCDC Diag 3",
)


class RmdError(Exception):
    """Base error for RMD access."""


class RmdConnectionError(RmdError):
    """The RMD could not be reached or timed out."""


class RmdResponseError(RmdError):
    """The RMD answered, but not with the expected page."""


@dataclass(frozen=True)
class RmdInfo:
    """Static pack identity from /getbmsinfo and /getversion."""

    serial: str
    battery_name: str | None
    part_number: str | None
    bms_version: str | None
    bms_hw_version: str | None
    dcdc_fw_version: str | None
    rmd_version: str | None
    raw: dict[str, str]


@dataclass(frozen=True)
class RmdWifi:
    """The RMD's Wi-Fi station link from /showapinfo.

    An empty SSID means the RMD isn't on Wi-Fi (its own web UI shows "WiFi is
    not connected!" then), e.g. when it uses Ethernet; any RSSI is ignored.
    """

    connected: bool
    rssi: int | None
    ssid: str | None
    bssid: str | None
    channel: int | None


def parse_wifi(text: str) -> RmdWifi:
    """Parse /showapinfo, e.g. {"state":0,"ssid":..,"bssid":..,"channel":6,"rssi":-75}."""
    try:
        raw = json.loads(text)
    except ValueError as err:
        raise RmdResponseError(f"/showapinfo is not JSON: {err}") from err
    if not isinstance(raw, dict) or raw.get("state") != 0:
        raise RmdResponseError(f"/showapinfo returned {text[:80]!r}")

    def _int(key: str) -> int | None:
        value = raw.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    connected = bool(raw.get("ssid"))
    return RmdWifi(
        connected=connected,
        rssi=_int("rssi") if connected else None,
        ssid=raw.get("ssid") or None,
        bssid=raw.get("bssid") or None,
        channel=_int("channel"),
    )


def parse_rows(text: str) -> dict[str, str]:
    """Return {name: value} for every two-cell row, HTML entities decoded."""
    return {
        html.unescape(name).strip(): html.unescape(value).strip()
        for name, value in _ROW_RE.findall(text)
    }


def to_float(value: str | None) -> float | None:
    """Leading number of a value such as '283.8066V', '18.7℃' or '1 Cycle'."""
    if value is None:
        return None
    if (match := _NUM_RE.match(value)) is None:
        return None
    return float(match.group(1))


def to_int(value: str | None) -> int | None:
    """Integer of a hex word ('0x0000') or a plain count ('8')."""
    if value is None:
        return None
    value = value.strip()
    try:
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    except ValueError:
        return None


def signed_tenths(value: str | None) -> float | None:
    """Fix a signed 16-bit field the page prints as unsigned x 0.1.

    BPI_Current/IPI_Current show e.g. 6549.9 A for -3.7 A, so anything above
    3276.7 has 6553.6 subtracted.
    """
    number = to_float(value)
    if number is None:
        return None
    if number > 3276.7:
        number -= 6553.6
    return round(number, 1)


def cell_spread_mv(data: dict[str, str]) -> float | None:
    """(MaxCellVoltage - MinCellVoltage) in mV."""
    vmax = to_float(data.get("MaxCellVoltage"))
    vmin = to_float(data.get("MinCellVoltage"))
    if vmax is None or vmin is None:
        return None
    return round((vmax - vmin) * 1000, 1)


def pack_power(data: dict[str, str]) -> float | None:
    """SumSerialCellVoltage x Current in W (negative when discharging)."""
    volts = to_float(data.get("SumSerialCellVoltage"))
    amps = to_float(data.get("Current"))
    if volts is None or amps is None:
        return None
    return round(volts * amps, 1)


def cell_numbers(data: dict[str, str]) -> list[int]:
    """Cell indices present in the page (1..70 on a RESU16H Prime)."""
    return sorted(int(m.group(1)) for k in data if (m := _CELL_RE.match(k)))


def probe_numbers(data: dict[str, str]) -> list[int]:
    """Temperature[n] probe indices present in the page."""
    return sorted(int(m.group(1)) for k in data if (m := _PROBE_RE.match(k)))


def diag_words(data: dict[str, str]) -> dict[str, str | None]:
    """Each alarm, warning and fault word as printed on the page."""
    return {word: data.get(word) for word in DIAG_WORDS}


def has_problem(data: dict[str, str]) -> bool | None:
    """True if any alarm, warning or fault word is non-zero."""
    values = [to_int(v) for v in diag_words(data).values() if v is not None]
    if not values:
        return None
    return any(values)


def expected_fields(info: RmdInfo) -> frozenset[str]:
    """Array fields /getbmsdata must hold, from the counts in /getbmsinfo.

    Aux Voltage[n] are the last rows on the page, so a reply cut short (seen
    live: 65 of 147 rows) loses them.
    """
    cells = to_int(info.raw.get("Number Of Cell")) or 0
    probes = to_int(info.raw.get("Number Of Temp.")) or 0
    aux = to_int(info.raw.get("Number Of Aux.")) or 0
    return frozenset(
        [f"Cell[{n}]Voltage" for n in range(1, cells + 1)]
        + [f"Temperature[{n}]" for n in range(1, probes + 1)]
        + [f"Aux Voltage[{n}]" for n in range(aux)]
    )


def parse_bms_data(text: str, required: frozenset[str] = frozenset()) -> dict[str, str]:
    """Parse /getbmsdata and reject anything but a complete page."""
    data = parse_rows(text)
    missing = [f for f in (*REQUIRED_FIELDS, *sorted(required)) if f not in data]
    if missing:
        raise RmdResponseError(
            f"/getbmsdata incomplete ({len(data)} rows): missing {', '.join(missing[:5])}"
            + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
        )
    return data


def parse_info(info_text: str, version_text: str | None) -> RmdInfo:
    """Parse /getbmsinfo (plus the bare /getversion string)."""
    raw = parse_rows(info_text)
    serial = raw.get("BMS Serial Number")
    if not serial:
        raise RmdResponseError("/getbmsinfo has no BMS Serial Number")
    return RmdInfo(
        serial=serial,
        battery_name=raw.get("Battery Name") or None,
        part_number=raw.get("Pack Part Number") or None,
        bms_version=raw.get("BMS Application Version") or None,
        bms_hw_version=raw.get("BMS HW Version") or None,
        dcdc_fw_version=raw.get("DCDC FW") or None,
        rmd_version=(version_text or "").strip() or None,
        raw=raw,
    )


class RmdClient:
    """Sequential, read-only HTTP client for one RMD.

    The RMD appears to serve one client at a time, so every request to it goes
    through one lock and asks the server to close the connection afterwards.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self.host = host
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()
        self._required: frozenset[str] = frozenset()

    async def _get(self, path: str) -> str:
        if path not in READ_ONLY_PATHS:
            raise ValueError(f"{path} is not a read-only RMD page")
        url = f"http://{self.host}{path}"
        async with self._lock:
            try:
                async with self._session.get(
                    url, timeout=self._timeout, headers={"Connection": "close"}
                ) as resp:
                    if resp.status != 200:
                        raise RmdResponseError(f"{url} returned HTTP {resp.status}")
                    body = await resp.read()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise RmdConnectionError(f"{url}: {err!r}") from err
        # A few /getbmsinfo fields hold raw non-UTF-8 bytes.
        return body.decode("utf-8", errors="replace")

    async def async_get_bms_data(self) -> dict[str, str]:
        """One GET of /getbmsdata, parsed."""
        return parse_bms_data(await self._get(PATH_BMS_DATA), self._required)

    async def async_get_wifi(self) -> RmdWifi:
        """One GET of /showapinfo, parsed."""
        return parse_wifi(await self._get(PATH_WIFI))

    async def async_get_info(self) -> RmdInfo:
        """GET /getbmsinfo then /getversion, one after the other.

        Also sets the array fields later /getbmsdata replies must contain.
        """
        info_text = await self._get(PATH_BMS_INFO)
        try:
            version_text = await self._get(PATH_VERSION)
        except RmdError:
            version_text = None
        info = parse_info(info_text, version_text)
        self._required = expected_fields(info)
        return info
