# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**watermon** is a water monitoring tool that:
1. Downloads hourly water usage data from **AquaHawk** (water utility meter) and watering event data from **Rachio** (smart sprinkler controller), caching them locally as weekly files.
2. Provides a **Flask web app** (`waterapp/`) that displays interactive Plotly charts and is deployed to GoDaddy cPanel via Passenger WSGI.
3. Also contains an older **Streamlit prototype** (`chatgpt_app/app.py`) — superseded by the Flask app.

## Running the App

```bash
# Install dependencies
pip install -r requirements.txt

# Run the Flask web app locally
flask --app passenger_wsgi:application run

# Run the legacy Streamlit prototype
streamlit run chatgpt_app/app.py

# Standalone data download scripts (WARNING: both execute on import)
python aquahawk.py
python rachio.py
```

No build step or test suite exists yet.

## GoDaddy cPanel Deployment

1. In cPanel → **Setup Python App**, create a Python 3.x app pointed at the repo root.
2. Set the **Application startup file** to `passenger_wsgi.py` and **Application entry point** to `application`.
3. Install dependencies via the cPanel Python app's pip (or SSH: `pip install -r requirements.txt`).
4. Copy `credentials.json` to the repo root on the server.
5. Edit `config.py` on the server: set a strong `APP_PASSWORD` and a random `SECRET_KEY` (or set the `WATERMON_SECRET_KEY` env var in cPanel).
6. Restart the app in cPanel after any code changes.

To schedule automatic data refreshes, add a cPanel **Cron Job**:
```
0 8 * * 1  cd /path/to/watermon && python -c "from waterapp.data import download_aquahawk, download_rachio; download_aquahawk(); download_rachio()"
```

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

### Flask Web App (`waterapp/`)

- `__init__.py` — Flask app factory (`create_app()`), used by `passenger_wsgi.py`.
- `auth.py` — `login_required` decorator and `check_password()` against `config.APP_PASSWORD`.
- `data.py` — All data I/O. Does **not** import from `aquahawk.py` or `rachio.py` (those execute at module level). Contains:
  - `download_aquahawk()` / `download_rachio()` — fetch missing weekly files from APIs.
  - `load_aquahawk_df(start, end)` — reads cached CSVs, localizes naive Pacific timestamps.
  - `load_rachio_df(start, end)` — reads cached JSONs, converts epoch-ms UTC → Pacific, pairs ZONE_STARTED/STOPPED into interval rows.
  - `attribute_gallons(aq, rachio, tail_minutes)` — sweep-line algorithm attributing meter gallons to watering events by proportional time overlap.
- `charts.py` — Plotly chart builders, each returning `plotly.io.to_json()` for browser rendering:
  1. `chart_daily_usage` — daily AquaHawk gallons bar chart
  2. `chart_rachio_timeline` — watering event scatter timeline by zone
  3. `chart_zone_totals` — attributed gallons + total minutes per zone
  4. `chart_gpm` — gallons per minute per event per zone (efficiency over time)
  5. `chart_alignment` — **timezone verification**: AquaHawk hourly bars overlaid with Rachio event bands; spikes should visually coincide if TZ handling is correct
- `routes.py` — Dashboard (date range + tail filter), login/logout, `/refresh` (POST, runs download in background thread), `/refresh/status` (polling endpoint).

### Timezone Handling

- **AquaHawk**: CSV timestamps are naive `"YYYY-MM-DD HH:MM"` in local Pacific time → localized to `America/Los_Angeles`.
- **Rachio**: `eventDate` is Unix epoch milliseconds UTC → converted to `America/Los_Angeles`.
- All merged data carries tz-aware Pacific timestamps. Plotly receives these directly.
- `config.LOCAL_TIMEZONE` controls the target timezone (default `America/Los_Angeles`).

### Legacy Scripts

- `aquahawk.py` / `rachio.py` — original standalone download+parse scripts. **Both execute their top-level load function on import** — do not import them from other modules.
- `chatgpt_app/app.py` — superseded Streamlit prototype. Kept for reference.
