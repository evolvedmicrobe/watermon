# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**watermon** is a water monitoring tool that:
1. Downloads hourly water usage data from **AquaHawk** (water utility meter) and watering event data from **Rachio** (smart sprinkler controller), caching them locally as weekly files.
2. Provides a **Streamlit web app** (`chatgpt_app/app.py`) that accepts AquaHawk and Rachio CSVs and attributes meter gallons to individual irrigation zones by proportional time overlap.

## Running the Apps

```bash
# Run the Streamlit app (primary UI)
streamlit run chatgpt_app/app.py

# Run the Flask stub app
flask --app app run

# Download AquaHawk data (runs download + concat on import)
python aquahawk.py

# Download Rachio data (runs download + parse on import)
python rachio.py

# Test weekly time generation
python testdates.py
```

No build step or test suite exists yet.

## Credentials

`credentials.json` (gitignored) must exist at the repo root with this shape:

```json
{
  "login": { "username": "...", "password": "..." },
  "aquahawk": { "districtName": "...", "accountNumber": "..." },
  "rachio": { "api_key": "..." }
}
```

`common.get_creds()` reads this file and returns `(login, aquahawk_info, rachio_info)`.

## Architecture

### Data Download Layer (`aquahawk.py`, `rachio.py`)

Both scripts follow the same pattern:
- Call `common.enumerate_weekly_times()` to get all Monday–Sunday intervals from a start date to ~3 days before now.
- For each interval, check if the local cache file already exists (skip if so), otherwise fetch from the API and write to disk.
- AquaHawk data lands in `data/aquahawk_weeklies/*.csv` (hourly meter readings).
- Rachio data lands in `data/rachio_weeklies/*.json` (device events including `ZONE_STARTED`, `ZONE_STOPPED`, `ZONE_COMPLETED`).
- **Caution**: both scripts call their top-level `load_*` function at module level, so `import aquahawk` or `import rachio` triggers a full download+parse run.

### Common Utilities (`common.py`)

- `enumerate_weekly_times(start_date_str)` — generates weekly UTC intervals with an 8-hour offset (Pacific → UTC).
- `format_timeseries_filename(firstTime, device, datadir, ext)` — canonical filename for cached data files.
- `get_data_directory(device)` — returns `data/{device}_weeklies/` relative to the repo root.

### Streamlit App (`chatgpt_app/app.py`)

Stand-alone; does **not** import `aquahawk.py` or `rachio.py`. Users upload CSVs directly via the UI.

Key functions:
- `load_aquahawk(csv_file, tzinfo)` — parses AquaHawk CSV, returns `[Timestamp, End, Gallons]`. Handles both `Water Use (Gallons)` and cumulative `Water Reading` (cubic feet → gallons via ×7.48052).
- `load_rachio(csv_file)` — parses Rachio CSV (from `load_rachio_data()` output or manual export), returns `[Start, End, Minutes, Zone]`.
- `proportional_overlap(all_usage, events)` — sweep-line algorithm that attributes meter gallons to each Rachio watering event by fraction of time overlap. Core analytics logic.
- `add_tail(events, minutes_tail)` — extends event end times to account for meter-read lag.

### Rachio Event Parsing (`rachio.py`)

- `EventData` class wraps raw API event JSON, parsing zone name from the event summary string via regex, and handling offline watering events (which have no `subType`).
- `parse_datetime_intervals(zone, zone_data)` — takes alternating `ZONE_STARTED`/`ZONE_STOPPED` pairs and expands them into per-hour rows with fractional minutes.
- `combine_data()` — loads all cached JSON files, filters to watering events, groups by zone, and calls `parse_datetime_intervals` per zone.
