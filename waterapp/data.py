"""
Data loading, downloading, and merging for watermon.

Thin adapter over `aquahawk.py` and `rachio.py`: those modules own the
download loops, the AquaHawk CSV concat, and the Rachio event-parsing
(EventData / offline-event expansion). This module adds the Flask-app
concerns on top: timezone normalization, date-range filtering, and the
sweep-line meter→event attribution.

Timezone strategy:
  - AquaHawk CSVs: Timestamp column is naive local Pacific time → localized to LOCAL_TZ
  - Rachio JSONs: eventDate is epoch milliseconds UTC → converted to LOCAL_TZ
  - All merged DataFrames carry tz-aware Pacific timestamps for safe comparison.
"""

from collections import defaultdict
from zoneinfo import ZoneInfo

import pandas as pd

import aquahawk
import rachio
from config import AQUAHAWK_START_DATE, LOCAL_TIMEZONE, RACHIO_START_DATE

LOCAL_TZ = ZoneInfo(LOCAL_TIMEZONE)

# A stop timestamp shared by this many distinct zones is treated as a Rachio
# "bulk-stop" connectivity artifact rather than a real run-end (see
# load_rachio_df).
_BULK_STOP_ZONE_THRESHOLD = 3


# ── Downloading ───────────────────────────────────────────────────────────────

def download_aquahawk() -> int:
    """Download missing AquaHawk weekly CSVs. Returns count of new files."""
    return aquahawk.download_aquahawk_data(AQUAHAWK_START_DATE)


def download_rachio() -> int:
    """Download missing Rachio weekly JSONs. Returns count of new files."""
    return rachio.download_data(RACHIO_START_DATE)


# ── Loading ───────────────────────────────────────────────────────────────────

def load_aquahawk_df(start_date=None, end_date=None) -> pd.DataFrame:
    """Load all cached AquaHawk CSVs into a single DataFrame.

    Returns columns: Timestamp (tz-aware Pacific), Gallons
    """
    df = aquahawk.read_aquahawk_csvs()
    if df.empty:
        return pd.DataFrame(columns=["Timestamp", "Gallons"])

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


def load_rachio_df(start_date=None, end_date=None) -> pd.DataFrame:
    """Load all cached Rachio JSONs and return watering event intervals.

    Returns columns: Start, End (tz-aware Pacific), Zone, Minutes
    """
    by_zone = rachio.parse_rachio_events()
    if not by_zone:
        return pd.DataFrame(columns=["Start", "End", "Zone", "Minutes"])

    rows = []
    for zone, events in by_zone.items():
        # parse_rachio_events groups events by zone and sorts them
        # chronologically within each zone, so this loop only ever sees one
        # zone's events at a time — a ZONE_STARTED can only pair with a stop
        # event from the SAME zone, never another zone's. We walk the sequence
        # as a simple state machine, tracking the currently-open start:
        #   STARTED  → opens (or, if one is already open, replaces) the run.
        #              A second start with no intervening stop means the prior
        #              run's stop event was lost; we drop that orphan start
        #              rather than pairing it across the gap into a bogus run.
        #   STOPPED/ → closes the open run and emits the interval. A stop with
        #   COMPLETED  no open start is an orphan and is ignored.
        pending_start = None
        for ev in events:
            if ev.subType == "ZONE_STARTED":
                pending_start = ev
            elif ev.subType in ("ZONE_STOPPED", "ZONE_COMPLETED"):
                if pending_start is None:
                    continue
                t_start = pending_start.pacific_date_time
                t_end = ev.pacific_date_time
                minutes = (t_end - t_start).total_seconds() / 60.0
                if minutes > 0:
                    rows.append(
                        {"Start": t_start, "End": t_end, "Zone": zone, "Minutes": minutes}
                    )
                pending_start = None

    if not rows:
        return pd.DataFrame(columns=["Start", "End", "Zone", "Minutes"])

    df = pd.DataFrame(rows)
    # EventData uses pytz; normalize to LOCAL_TZ so comparisons against
    # pd.Timestamp(..., tz=LOCAL_TZ) below are unambiguous.
    df["Start"] = pd.to_datetime(df["Start"], utc=True).dt.tz_convert(LOCAL_TZ)
    df["End"] = pd.to_datetime(df["End"], utc=True).dt.tz_convert(LOCAL_TZ)
    df = df.sort_values("Start").reset_index(drop=True)

    # Guard against Rachio "bulk-stop" artifacts. When the controller loses
    # connectivity it can emit a synthetic ZONE_STOPPED for many zones at the
    # exact same instant on reconnect (e.g. 2025-07-05, where 7 zones all
    # "stopped" at 12:29:36). Those aren't real run-ends, so pairing a
    # ZONE_STARTED with one yields an impossibly long interval (hours) that
    # wrecks duration-based metrics like predicted GPM. A legitimate schedule
    # runs zones sequentially with distinct stop times, so a stop timestamp
    # shared by 3+ zones is treated as an artifact and its intervals dropped.
    if not df.empty:
        zones_per_stop = df.groupby("End")["Zone"].transform("nunique")
        df = df[zones_per_stop < _BULK_STOP_ZONE_THRESHOLD].reset_index(drop=True)

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

    # AquaHawk timestamps the END of each interval: a 2 AM reading reports the
    # water consumed from 1–2 AM. So the bucket spans [Timestamp - cadence,
    # Timestamp], not [Timestamp, Timestamp + cadence].
    aq = aq.copy()
    aq["AqStart"] = aq["Timestamp"] - cadence
    aq["AqEnd"] = aq["Timestamp"]

    rachio = rachio.copy()
    if tail_minutes > 0:
        rachio["End"] = rachio["End"] + pd.Timedelta(minutes=tail_minutes)

    usage = aq.sort_values("Timestamp").reset_index(drop=True)
    events = rachio.sort_values("Start").reset_index(drop=True)

    gallons_by_event: dict[int, float] = defaultdict(float)
    i = j = 0
    while i < len(usage) and j < len(events):
        u_start = usage.loc[i, "AqStart"]
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
