# Ontario Energy Board for Home Assistant

A custom integration that exposes Ontario **electricity** and **natural gas** rates as Home Assistant sensors, driven by the Ontario Energy Board's official public feeds:

- Residential electricity: [BillData.xml](https://www.oeb.ca/_html/calculator/data/BillData.xml) — TOU, ULO, Tiered + delivery components
- Small commercial electricity: [BillData_GS.xml](https://www.oeb.ca/_html/calculator/data/BillData_GS.xml) — General Service < 50 kW and related small-commercial rate classes (same schema as residential, merged transparently in the config flow)
- Natural gas: [GasBillData.xml](https://www.oeb.ca/_html/calculator/data/GasBillData.xml) — declining-block delivery, commodity, transportation, storage, carbon charges

Architected to mirror Home Assistant core conventions (config-flow-only, `DataUpdateCoordinator`, `runtime_data`, `defusedxml` parsing, full test suite) so an eventual upstream PR is realistic.

> **Domain note**: the HA domain is `ontario_energy` (entity ids: `sensor.ontario_energy_*`). A separate HACS integration uses `ontario_energy_board`; only one can be installed at a time.

## Features

**Electricity**

- 66 Ontario electricity distributors and 15 customer classes selectable via UI — residential variants (`RESIDENTIAL`, `RESIDENTIAL R1`, `SEASONAL CUSTOMERS`, etc.) plus small-commercial classes (`GENERAL SERVICE LESS THAN 50 KW`, `GENERAL SERVICE ENERGY BILLED`, `URBAN GENERAL SERVICE ENERGY BILLED`)
- TOU, ULO, and Tiered commodity rates as sensors
- "Current TOU price", "Current TOU period", "Current ULO price", "Current ULO period" sensors that flip at each hour boundary using the verified IESO TOU/ULO schedule and holiday list (including weekend-shifted observances)
- Distributor delivery components: service charge, distribution, network, connection, WMSR, RRRP, SSS admin, loss factor, HST, Ontario Electricity Rebate
- Plan filter (Auto / TOU / ULO / Tiered) configurable via options flow

**Natural gas**

- 3 Ontario gas distributors (Enbridge Gas, EPCOR Natural Gas, Union Gas) across 6 service areas
- Declining-block delivery rates — 1 to 5 tiers per distributor, with low/high m³ bounds
- Commodity, transportation, storage charges with their respective price adjustments
- Federal and facility carbon charges
- Monthly customer charge (fixed $/month)
- Typical monthly consumption sensor (m³) — state reflects the current month; all 12 months exposed as attributes

**Both**

- HA diagnostics export
- Translations: English, French (Canadian), Spanish, Italian, Portuguese, Polish, Arabic, Urdu, Simplified Chinese

## Installation

### HACS

1. In HACS → Integrations → Custom repositories, add this repo as type "Integration".
2. Install "Ontario Energy Board".
3. Restart Home Assistant.
4. Settings → Devices & services → Add integration → "Ontario Energy Board".

### Manual

Copy `custom_components/ontario_energy/` into your Home Assistant `config/custom_components/` directory, then restart.

## Configuration

Add the integration once per (utility × distributor × customer combo) you want to track. You can run electricity and gas side-by-side as separate config entries.

### Electricity

1. Pick **Electricity** as the utility.
2. Pick your distributor (e.g. "Hydro One Networks Inc.", "Toronto Hydro-Electric System Limited").
3. Pick your customer class (typically `RESIDENTIAL`).
4. Pick a plan filter:
   - **Auto** — expose all sensors (TOU, ULO, Tiered).
   - **Time-of-Use** — only TOU sensors.
   - **Ultra-Low Overnight** — only ULO sensors.
   - **Tiered** — only Tier 1/Tier 2 sensors.

Plan can be changed later via Settings → Devices & services → ⋯ → Configure.

### Natural gas

1. Pick **Natural gas** as the utility.
2. Pick your distributor (Enbridge Gas, EPCOR Natural Gas, or Union Gas).
3. Pick your service area (e.g. "All" for Enbridge; "North East", "North West", "South" for Union; "Aylmer", "South Bruce" for EPCOR).
4. Pick your rate class (the residential default is typically `1`, `01`, or `M1` depending on distributor).

## Schedules (verified from OEB)

**Time-of-Use (RPP)**

- Summer (May 1 – Oct 31), weekdays: on-peak 11:00–17:00, mid-peak 07:00–11:00 + 17:00–19:00, off-peak 19:00–07:00
- Winter (Nov 1 – Apr 30), weekdays: on-peak 07:00–11:00 + 17:00–19:00, mid-peak 11:00–17:00, off-peak 19:00–07:00
- Weekends and observed holidays: off-peak all day

**Ultra-Low Overnight (year-round)**

- Overnight 23:00–07:00 every day
- Weekday on-peak 16:00–21:00
- Weekday mid-peak 07:00–16:00 + 21:00–23:00
- Weekends and observed holidays: weekend off-peak 07:00–23:00

**Observed holidays** (10): New Year's Day, Family Day, Good Friday, Victoria Day, Canada Day, Civic Holiday, Labour Day, Thanksgiving, Christmas, Boxing Day. If a holiday falls on a weekend, the next weekday that is not also a holiday gets the holiday treatment.

Source: [OEB electricity rates](https://www.oeb.ca/consumer-information-and-protection/electricity-rates), [OEB holiday schedule](https://www.oeb.ca/consumer-information-and-protection/electricity-rates/holiday-schedule-time-use-and-ultra-low).

## Limitations

- Rates are exposed as their raw bill components. The HST and OER rebate are separate sensors; combining them into a single "all-in" effective rate is left to the user (HA template sensors work well).
- The integration cannot know your consumption, so for **electricity** it cannot tell you which tier (1 or 2) you are currently billed at, and for **gas** it cannot tell you which declining-block tier you are in mid-cycle. All tier rates are exposed for you to apply.
- The OEB feeds have no published schema. If OEB silently changes field names, the integration will surface a clear `UpdateFailed` error and refuse to display stale data; refresh the test fixture (`scripts/refresh_fixture.py`) and open an issue.

## Development

```bash
pip install -e ".[dev]"
ruff check .
mypy custom_components
pytest --cov=custom_components/ontario_energy --cov-report=term-missing
```

## Attribution

Rate data is provided by the Ontario Energy Board (https://www.oeb.ca/). This integration is not affiliated with or endorsed by the OEB.
