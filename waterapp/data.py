"""
Data loading, downloading, and merging for watermon.

Timezone strategy:
  - AquaHawk CSVs: Timestamp column is naive local Pacific time → localized to LOCAL_TZ
  - Rachio JSONs: eventDate is epoch milliseconds UTC → converted to LOCAL_TZ
  - All merged DataFrames carry tz-aware Pacific timestamps for safe comparison.
"""

import glob
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import common
from config import AQUAHAWK_START_DATE, LOCAL_TIMEZONE, RACHIO_START_DATE

LOCAL_TZ = ZoneInfo(LOCAL_TIMEZONE)

AQUAHAWK_URL = "https://aquahawk.us"
_ZONE_RE = re.compile(r"(\w*\s*\w*\s*\w+)\s+(?:completed|began|stopped)")
_OFFLINE_RE = re.compile(r"watered for \d+ minutes while offline")


# ── Downloading ───────────────────────────────────────────────────────────────

def download_aquahawk() -> int:
    """Download missing AquaHawk weekly CSVs. Returns count of new files."""
    login, account, _ = common.get_creds()
    datadir = common.get_data_directory("aquahawk")
    os.makedirs(datadir, exist_ok=True)
    intervals = common.enumerate_weekly_times(AQUAHAWK_START_DATE)

    downloaded = 0
    logged_in = False
    session = requests.Session()
    try:
        for interval in intervals:
            start = interval["start_time"]
            fname = common.format_timeseries_filename(start, "AquaHawk", datadir, "csv")
            if os.path.exists(fname):
                continue
            if not logged_in:
                r = session.post(f"{AQUAHAWK_URL}/login", data=login)
                r.raise_for_status()
                logged_in = True
            body = {
                "firstTime": start,
                "lastTime": interval["end_time"],
                "interval": "1 hour",
                "districtName": account["districtName"],
                "accountNumber": account["accountNumber"],
            }
            r = session.post(
                f"{AQUAHAWK_URL}/timeseries/export",
                data=body,
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            meta = r.json()
            csv_r = session.get(
                f"{AQUAHAWK_URL}/download",
                data={
                    "district": meta["district"],
                    "username": meta["username"],
                    "type": meta["type"],
                    "filename": meta["filename"],
                },
            )
            with open(fname, "w") as fh:
                fh.write(csv_r.content.decode())
            downloaded += 1
            time.sleep(1)
    finally:
        session.close()
    return downloaded


def download_rachio() -> int:
    """Download missing Rachio weekly JSONs. Returns count of new files."""
    from rachiopy import Rachio

    _, _, rachio_creds = common.get_creds()
    datadir = common.get_data_directory("rachio")
    os.makedirs(datadir, exist_ok=True)
    intervals = common.enumerate_weekly_times(RACHIO_START_DATE)

    rachio_client = None
    device_id = None
    downloaded = 0

    for interval in intervals:
        start = interval["start_time"]
        fname = common.format_timeseries_filename(start, "Rachio", datadir, "json")
        if os.path.exists(fname):
            continue
        if rachio_client is None:
            rachio_client = Rachio(rachio_creds["api_key"])
            pi = rachio_client.person.info()
            pid = pi[1]["id"]
            person_data = rachio_client.person.get(pid)
            for device in person_data[1]["devices"]:
                if device["name"] == "Davis 16":
                    device_id = device["id"]
                    break
            if device_id is None:
                raise RuntimeError("Could not find Rachio device 'Davis 16'")
        st = common.convert_iso_to_epoch_millis(start)
        et = common.convert_iso_to_epoch_millis(interval["end_time"])
        events = rachio_client.device.event(device_id, st, et)
        if events[0]["status"] != 200:
            raise IOError(f"Rachio API error for interval starting {start}")
        with open(fname, "w") as fh:
            json.dump(events[1], fh, indent=2)
        downloaded += 1
    return downloaded


# ── Loading ───────────────────────────────────────────────────────────────────

def load_aquahawk_df(start_date=None, end_date=None) -> pd.DataFrame:
    """Load all cached AquaHawk CSVs into a single DataFrame.

    Returns columns: Timestamp (tz-aware Pacific), Gallons
    """
    datadir = common.get_data_directory("aquahawk")
    files = sorted(glob.glob(os.path.join(datadir, "*.csv")))
    if not files:
        return pd.DataFrame(columns=["Timestamp", "Gallons"])

    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df.columns = [c.strip() for c in df.columns]

    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"])

    # Localize naive Pacific timestamps
    df["Timestamp"] = df["Timestamp"].dt.tz_localize(
        LOCAL_TZ, nonexistent="shift_forward", ambiguous="NaT"
    )
    df = df.dropna(subset=["Timestamp"])
    df["Gallons"] = pd.to_numeric(df["Water Use (Gallons)"], errors="coerce").fillna(0.0)

    df = (
        df[["Timestamp", "Gallons"]]
        .drop_duplicates("Timestamp")
        .sort_values("Timestamp")
        .reset_index(drop=True)
    )

    if start_date:
        start_dt = pd.Timestamp(start_date, tz=LOCAL_TZ)
        df = df[df["Timestamp"] >= start_dt]
    if end_date:
        end_dt = pd.Timestamp(end_date, tz=LOCAL_TZ) + pd.Timedelta(days=1)
        df = df[df["Timestamp"] < end_dt]

    return df.reset_index(drop=True)


def _epoch_ms_to_pacific(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)


def _parse_zone(summary: str) -> str:
    m = _ZONE_RE.match(summary)
    return m.group(1).strip() if m else "Unknown"


def load_rachio_df(start_date=None, end_date=None) -> pd.DataFrame:
    """Load all cached Rachio JSONs and return watering event intervals.

    Returns columns: Start, End (tz-aware Pacific), Zone, Minutes
    """
    datadir = common.get_data_directory("rachio")
    files = sorted(glob.glob(os.path.join(datadir, "*.json")))
    if not files:
        return pd.DataFrame(columns=["Start", "End", "Zone", "Minutes"])

    raw: list[dict] = []
    for f in files:
        raw.extend(json.loads(open(f).read()))

    # Filter to zone-level watering events
    watering = []
    for e in raw:
        t = e.get("type")
        sub = e.get("subType", "")
        summary = e.get("summary", "")
        if t == "ZONE_STATUS":
            # Skip cycling sub-events (ZONE_CYCLING_*); keep STARTED/STOPPED/COMPLETED
            if sub and sub.startswith("ZONE_CYCLING"):
                continue
            watering.append(e)
        elif _OFFLINE_RE.search(summary) and sub is None:
            # Offline watering event — promote to a ZONE_STOPPED equivalent
            e = dict(e)
            e["subType"] = "ZONE_STOPPED"
            watering.append(e)

    watering.sort(key=lambda x: x["eventDate"])

    # Group by zone and pair STARTED → STOPPED/COMPLETED
    by_zone: dict[str, list] = defaultdict(list)
    for e in watering:
        by_zone[_parse_zone(e.get("summary", ""))].append(e)

    rows = []
    for zone, events in by_zone.items():
        i = 0
        while i < len(events) - 1:
            s = events[i]
            e = events[i + 1]
            if s.get("subType") == "ZONE_STARTED" and e.get("subType") in (
                "ZONE_STOPPED",
                "ZONE_COMPLETED",
            ):
                t_start = _epoch_ms_to_pacific(s["eventDate"])
                t_end = _epoch_ms_to_pacific(e["eventDate"])
                minutes = (t_end - t_start).total_seconds() / 60.0
                if minutes > 0:
                    rows.append({"Start": t_start, "End": t_end, "Zone": zone, "Minutes": minutes})
                i += 2
            else:
                i += 1

    if not rows:
        return pd.DataFrame(columns=["Start", "End", "Zone", "Minutes"])

    df = pd.DataFrame(rows).sort_values("Start").reset_index(drop=True)

    if start_date:
        start_dt = pd.Timestamp(start_date, tz=LOCAL_TZ)
        df = df[df["Start"] >= start_dt]
    if end_date:
        end_dt = pd.Timestamp(end_date, tz=LOCAL_TZ) + pd.Timedelta(days=1)
        df = df[df["Start"] < end_dt]

    return df.reset_index(drop=True)


# ── Merging ───────────────────────────────────────────────────────────────────

def attribute_gallons(
    aq: pd.DataFrame, rachio: pd.DataFrame, tail_minutes: int = 20
) -> pd.DataFrame:
    """Attribute AquaHawk meter gallons to Rachio watering events by time overlap.

    Both DataFrames must have tz-aware Pacific timestamps (ensured by the loaders above).
    Extends each Rachio event end by tail_minutes to account for meter-read lag.

    Returns the Rachio DataFrame with an added GallonsAttributed column.
    """
    if aq.empty or rachio.empty:
        out = rachio.copy()
        out["GallonsAttributed"] = 0.0
        return out

    # Infer AquaHawk measurement cadence
    diffs = aq["Timestamp"].diff().dropna()
    cadence = diffs.median() if len(diffs) else pd.Timedelta(hours=1)
    if not (pd.Timedelta(minutes=5) <= cadence <= pd.Timedelta(hours=4)):
        cadence = pd.Timedelta(hours=1)

    aq = aq.copy()
    aq["AqEnd"] = aq["Timestamp"] + cadence

    rachio = rachio.copy()
    if tail_minutes > 0:
        rachio["End"] = rachio["End"] + pd.Timedelta(minutes=tail_minutes)

    usage = aq.sort_values("Timestamp").reset_index(drop=True)
    events = rachio.sort_values("Start").reset_index(drop=True)

    gallons_by_event: dict[int, float] = defaultdict(float)
    i = j = 0
    while i < len(usage) and j < len(events):
        u_start = usage.loc[i, "Timestamp"]
        u_end = usage.loc[i, "AqEnd"]
        g = usage.loc[i, "Gallons"]
        e_start = events.loc[j, "Start"]
        e_end = events.loc[j, "End"]

        if u_end <= e_start:
            i += 1
            continue
        if e_end <= u_start:
            j += 1
            continue

        overlap_s = (min(u_end, e_end) - max(u_start, e_start)).total_seconds()
        u_len_s = (u_end - u_start).total_seconds()
        if u_len_s > 0 and overlap_s > 0:
            gallons_by_event[j] += g * (overlap_s / u_len_s)

        if u_end <= e_end:
            i += 1
        else:
            j += 1

    events["GallonsAttributed"] = [gallons_by_event.get(idx, 0.0) for idx in events.index]
    return events
