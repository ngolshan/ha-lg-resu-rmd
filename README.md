# LG RESU Prime RMD for Home Assistant

A read-only Home Assistant integration for LG RESU Prime batteries. It reads battery health and diagnostics from each pack's RMD (remote monitoring device) web page on the LAN, with no cloud. It polls slowly by design (every 5 min by default). It is not a fast power-telemetry source.

The design follows the feature list J_W_T posted on the DIY Solar Forum ([LG RESU Prime local diagnostics into Home Assistant – read-only, no cloud](https://diysolarforum.com/threads/lg-resu-prime-local-diagnostics-into-home-assistant-%E2%80%93-read-only-no-cloud.129737/), post #1, Sep 2026). Their code isn't published, so this is a separate implementation.

Tested against two RESU16H Prime packs (BMS app 0x02060304, RMD 4.2.1, DC-DC FW 0x01040000).

## What it does

- **One config entry and one device per pack,** added by IP address in the UI. The device's unique ID is the BMS serial number, so a changed IP is a *Reconfigure*, not a new device.
- **Each poll is one `GET /getbmsdata` per pack,** fed to every entity through a DataUpdateCoordinator. The device info comes from `/getbmsinfo` and `/getversion`, read once at setup.
- **Poll interval** is set in *Configure* (the options flow): 30–3600 s, default 300 s.
- **Strictly read-only.** The client refuses any path except `/getbmsdata`, `/getbmsinfo` and `/getversion`. It never calls the RMD's write or action endpoints (`/factory`, `/rst`, `/setbmsmode`, `/dcdccmd`, `/cantx`, `/clearSVDF`, ...).

### Sensors

| Entity | Page field | Notes |
|---|---|---|
| SOC, Real SOC, SOH | `SOC`, `RealSOC`, `SOH` | %, 0.01 % resolution |
| Voltage | `SumSerialCellVoltage` | V, 4 decimals |
| Current | `Current` | A; negative = discharging; really 0.1 A steps |
| Power | `SumSerialCellVoltage` × `Current` | W, derived |
| Min / max / avg cell voltage | `MinCellVoltage` … | V, 0.1 mV resolution |
| Cell spread | (`MaxCellVoltage` − `MinCellVoltage`) × 1000 | mV, derived |
| Lowest / highest cell | `MinCellNumber`, `MaxCellNumber` | diagnostic |
| Min / max / avg temperature | `MinTemperature` … | °C |
| Charge / discharge current limit | `ChargeCurrentLimit` … | A, diagnostic |
| Charge / discharge power limit | `ChargePowerLimit` … | W, diagnostic |
| Cycle count | `CycleCount` | total increasing |
| Lifetime discharge energy | `LifeTimeDischargeEnergy` | Wh, shown in kWh; see below |
| BPI / IPI voltage and current | `BPI_*`, `IPI_*` | DC-DC battery side and inverter side; diagnostic |
| DC-DC temperature | `Temperature` | not the same field as `Temperature[n]`; diagnostic |
| Shutdown reason | `ShutdownReason` | hex word as printed; diagnostic |
| Cell 1–70 voltage | `Cell[n]Voltage` | **disabled by default** |
| Temperature 1–8 | `Temperature[n]` | **disabled by default** |

**Problem** (binary sensor, diagnostic): on if any of the 11 alarm, warning or fault words is non-zero. The words are `DiagResultGeneralAlarm`, `DiagResultGeneralWarning`, `DiagResultFault1/2`, `DiagResultHwAlarm`, `DiagResultHwWarning`, `DiagResultHwFault1/2` and `DCDC Diag 1–3`. Each word is an attribute, as the page prints it.

**Download diagnostics** on the device page returns the full last `/getbmsdata` page and the `/getbmsinfo` page, including the fields that have no entity (mode and control words, balancing targets, SVDF buffer, aux voltages).

## Quirks of the RMD this handles

These were observed on two packs in Oct 2026, not taken from LG documentation:

- **The page is a fragment of `<tr><td>Name</td><td>Value</td></tr>` rows,** 147 on a RESU16H Prime, with the units in the value (`256.2778V`, `-5.000A`, `18.3&#8451`, `1 Cycle`, `0x00000000`).
- **HTTP version matters.** An HTTP/1.1 request gets a normal chunked `200 OK`, but an HTTP/1.0 request gets the body with no status line. aiohttp sends HTTP/1.1.
- **`BPI_Current` and `IPI_Current` are signed 16-bit values printed as unsigned × 0.1,** so 6549.9 A is really −3.7 A. The integration subtracts 6553.6 from anything above 3276.7. The corrected `BPI_Current` matches `Current`.
- **The RMD appears to serve one client at a time.** With a second poller running, replies came back garbled (starting mid-page with no status line) or cut short (65 of 147 rows). Every request to one RMD therefore goes through a lock and asks for `Connection: close`. A reply that is missing any summary field, or any cell, probe or aux row that `/getbmsinfo` says exists, is rejected rather than shown as partial data. Run only one poller per RMD.
- **Wi-Fi drop-outs.** One pack took 2–9 s per reply and lost 10 % of pings. Requests time out after 15 s. A failed poll is retried once after 5 s; if that also fails, the pack's entities go unavailable until the next good poll.
- **The RMD clock** is UTC−8 with no DST, so the page's `Time` field is ignored and HA's poll time is used.
- **`LifeTimeDischargeEnergy` doesn't update live.** It stayed fixed over about 1.7 kWh of discharge, and seems to change only when the RMD saves its warranty record (`/getSavedWarranty`, `SavedTime`). The RMD has no charge-energy counter.

## Install

**Manual:** copy `custom_components/lg_resu_rmd` into `/config/custom_components/`, so that `/config/custom_components/lg_resu_rmd/manifest.json` exists. On Home Assistant OS, the [Samba share](https://github.com/home-assistant/addons/blob/master/samba/DOCS.md) app is the easiest way to do that from Windows:

1. Install it from *Settings → Apps → Install app → Samba share*. Set a `username` and `password` on its *Configuration* tab, then start it.
2. Map the `config` share, for example in PowerShell (this prompts for the password):
   ```powershell
   net use H: \\HOMEASSISTANT\config * /user:USERNAME /persistent:yes
   ```
3. Copy the folder, leaving out `__pycache__`:
   ```powershell
   robocopy custom_components\lg_resu_rmd H:\custom_components\lg_resu_rmd /E /XD __pycache__
   ```

The File editor app is no help here, because it uploads one file at a time.

Then restart Home Assistant and go to *Settings → Devices & services → Add integration → LG RESU Prime RMD*. Add each pack by its RMD IP and give it a name. The entity IDs follow the name; for example, "LG RESU16H 1" gives `sensor.lg_resu16h_1_soc`.

To update, copy the folder again the same way and restart.

**HACS:** the repo has a `hacs.json`, but HACS can only add public repositories as custom repositories.

## Development

```
py -m pip install aiohttp pytest ruff
py -m pytest
py -m ruff check custom_components tests
```

The parser tests run against pages saved from both packs (`tests/fixtures/`). `rmd.py` has no Home Assistant imports, so it can be tested alone.

## License

MIT
