# watermon

A personal water monitoring dashboard that pulls data from an **AquaHawk** utility meter and a **Rachio** smart sprinkler controller, attributes meter usage to individual irrigation zones, and displays everything as interactive charts in a password-protected web app.

## What it does

- Downloads hourly water meter readings from AquaHawk and watering event logs from Rachio, caching them locally as weekly files.
- Attributes meter gallons to each Rachio irrigation zone using a proportional time-overlap algorithm, accounting for meter-read lag.
- Renders six interactive Plotly charts on a dark-themed dashboard:
  1. **Daily water usage** — AquaHawk meter gallons per day
  2. **Monthly usage by zone** — stacked bar chart showing per-zone consumption and how it changes over time
  3. **Rachio event timeline** — all watering events plotted by zone, bubble-sized by duration
  4. **Zone totals** — total attributed gallons and watering minutes per zone
  5. **Gallons per minute** — flow rate efficiency per zone over time
  6. **Timezone alignment check** — AquaHawk hourly usage overlaid with Rachio event bands to verify the two data sources are correctly time-aligned

## Requirements

- Python 3.9+
- AquaHawk account credentials
- Rachio API key
- A `credentials.json` file at the repo root (see below — this file is gitignored)

```bash
pip install -r requirements.txt
```

## Configuration

Copy the template below to `credentials.json` and fill in your details:

```json
{
  "login":    { "username": "your@email.com", "password": "aquahawk-password" },
  "aquahawk": { "districtName": "YourDistrict", "accountNumber": "123456-789" },
  "rachio":   { "api_key": "your-rachio-api-key" }
}
```

Edit `config.py` to set the app password and a secret key before running:

```python
APP_PASSWORD = "your-dashboard-password"
SECRET_KEY   = "a-long-random-string"
```

You can also set `WATERMON_SECRET_KEY` as an environment variable instead of editing the file.

## Running locally

```bash
flask --app passenger_wsgi:application run
```

Then open `http://localhost:5000`, enter the password from `config.py`, and use the **Refresh Data** button to trigger the initial download from AquaHawk and Rachio.

## Deploying to GoDaddy cPanel

1. Upload the repo to your cPanel hosting account.
2. In cPanel → **Setup Python App**, create a Python 3.x app pointed at the repo root.
3. Set **Application startup file** to `passenger_wsgi.py` and **Application entry point** to `application`.
4. Install dependencies via cPanel's pip or SSH: `pip install -r requirements.txt`.
5. Place `credentials.json` in the repo root on the server.
6. Edit `config.py` on the server with a strong password and secret key.
7. Restart the app from cPanel after any code changes.

To keep data fresh automatically, add a cPanel Cron Job (e.g. weekly on Monday at 8 AM):

```
0 8 * * 1  cd /path/to/watermon && python -c "from waterapp.data import download_aquahawk, download_rachio; download_aquahawk(); download_rachio()"
```

## Project structure

```
watermon/
├── waterapp/
│   ├── __init__.py     # Flask app factory
│   ├── auth.py         # Session-based login
│   ├── data.py         # Download, load, and merge AquaHawk + Rachio data
│   ├── charts.py       # Plotly chart builders
│   └── routes.py       # Dashboard, login/logout, refresh endpoints
├── templates/
│   ├── login.html
│   └── dashboard.html
├── static/
│   └── style.css
├── data/
│   ├── aquahawk_weeklies/   # Cached CSV files (gitignored)
│   └── rachio_weeklies/     # Cached JSON files (gitignored)
├── passenger_wsgi.py   # cPanel WSGI entry point
├── config.py           # App password, secret key, timezone
├── common.py           # Shared date/file utilities
├── aquahawk.py         # Legacy standalone download script
└── rachio.py           # Legacy standalone download script
```

## Data sources

| Source | Format | Granularity | Timezone |
|--------|--------|-------------|----------|
| AquaHawk | CSV (weekly export) | Hourly meter readings | Naive local (Pacific) |
| Rachio | JSON (API events) | Per-event (zone start/stop) | UTC epoch ms |

Both are normalized to `America/Los_Angeles` before merging. The **timezone alignment chart** makes it easy to verify this visually.
