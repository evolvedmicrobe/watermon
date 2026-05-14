import glob
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
import pytz

import pandas as pd
from rachiopy import Rachio

import common

RACHIO_DATA_DIRECTORY = common.get_data_directory("rachio")
ZONE_STARTED = "ZONE_STARTED"
ZONE_COMPLETED = "ZONE_COMPLETED"
WATERING_TOPIC = "WATERING"

text = "Backyard Middle West began watering at 12:44 PM (PDT). - 2023-07-09 12:44:16 PDT-0700"
zone_regex = "(\w*\s*\w*\s*\w+)\s+(?:completed|began|stopped|watered)"
offline_regex_pattern = "watered for (\d+) minutes while offline"
offline_regex = re.compile(offline_regex_pattern)
matcher = re.compile(zone_regex)
matcher.match(text)


class EventData:
    def __init__(self, data) -> None:
        if "type" not in data and not offline_regex.search(data.get("summary", "")):
            print(data)
            raise Exception(data)
        self.data = data
        self.type = data.get("type", "ZONE_STATUS")
        self.eventDate = data["eventDate"]
        self.summary = data["summary"]
        self.subType = data.get("subType")
        self.topic = data.get("topic", "WATERING")
        # Convert to human readable datetime
        # Your timestamp in milliseconds
        # Convert milliseconds to seconds
        timestamp_s = self.eventDate / 1000
        # Convert to a datetime object in UTC
        dt_utc = datetime.utcfromtimestamp(timestamp_s).replace(tzinfo=pytz.utc)

        # Convert to Pacific Time
        dt_pacific = dt_utc.astimezone(pytz.timezone("America/Los_Angeles"))
        self.pacific_date_time = dt_pacific

        # Format the datetime object to a string
        self.date_string = dt_pacific.strftime("%Y-%m-%d %H:%M:%S %Z%z")

        # Rachio has started truncating some strings, stupid because the three periods take up more room
        self.summary = self.summary.replace(
            "Backyard Middle We...", "Backyard Middle West"
        )
        self.summary = self.summary.replace(
            "Backyard South Wes...", "Backyard South West"
        )
        match = matcher.match(self.summary)
        if match:
            self.zone = match.group(1)
        else:
            quick_run = "Quick Run"
            if self.summary.startswith(quick_run):
                self.zone = quick_run
            else:
                print(f"Unparseable zone: {self.summary}")
                print(self.eventDate)
                self.zone = "UNKNOWN"

    def __str__(self) -> str:
        return f"{self.summary} - {self.date_string} - {self.data}"

    def __repr__(self) -> str:
        return self.__str__()


def _expand_offline_event(ev):
    """Expand a "watered for X minutes while offline" event into a synthetic
    (ZONE_STARTED, ZONE_STOPPED) pair so it can be paired up by
    parse_datetime_intervals. The reported eventDate is when the controller
    surfaced the event after reconnecting, so we treat it as the end and
    estimate start as end - X minutes — wall-clock timing is approximate.
    """
    if ev.get("subType") is not None:
        return [ev]
    match = offline_regex.search(ev.get("summary") or "")
    if not match:
        return [ev]
    minutes = int(match.group(1))
    end_ms = ev["eventDate"]
    start_ms = end_ms - minutes * 60 * 1000
    start_ev = dict(ev, type="ZONE_STATUS", subType="ZONE_STARTED", eventDate=start_ms)
    stop_ev = dict(ev, type="ZONE_STATUS", subType="ZONE_STOPPED")
    return [start_ev, stop_ev]


def parse_datetime_intervals(zone: str, zone_data: list[EventData]):
    """Parses a list of datetime intervals and calculates total minutes spent in each hour."""
    # Initialize a dictionary to hold total minutes for each hour
    year = []
    months = []
    weekday = []
    day = []
    hour = []
    minutes_watering = []
    date = []

    # Iterate through datetime intervals, skipping any unpaired events
    i = 0
    while i < len(zone_data) - 1:
        start = zone_data[i]
        end = zone_data[i + 1]
        if start.subType != "ZONE_STARTED" or end.subType not in (
            "ZONE_STOPPED",
            "ZONE_COMPLETED",
        ):
            i += 1
            continue

        # Loop through each hour in the interval
        current = start.pacific_date_time
        while current < end.pacific_date_time:
            next_hour = (current + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
            interval_end = min(next_hour, end.pacific_date_time)
            minutes_spent = (interval_end - current).total_seconds() / 60
            year.append(current.year)
            months.append(current.month)
            day.append(current.day)
            weekday.append(current.weekday())
            hour.append(current.hour)
            minutes_watering.append(minutes_spent)
            date.append(current)
            current = interval_end
        i += 2
    return pd.DataFrame(
        {
            "Year": year,
            "Month": months,
            "Day": day,
            "WeekDay": weekday,
            "Hour": hour,
            "WateringMinutes": minutes_watering,
            "Zone": [zone] * len(hour),
            "Timestamp": date,
        }
    )


def get_rachio_filename(start):
    return common.format_timeseries_filename(
        start, "Rachio", RACHIO_DATA_DIRECTORY, "json"
    )


def get_davis_device_id(rachio: Rachio):
    pi = rachio.person.info()
    if len(pi) < 2 or pi[0]["status"] != 200:
        raise IOError("Failed todo initial query with API token")
    pid = pi[1]["id"]
    data = rachio.person.get(pid)
    # print(data)
    if (len(data) < 2) | (data[0]["status"] != 200):
        raise IOError("Failed to query device information")
    for device in data[1]["devices"]:
        if device["name"] == "Davis 16":
            did = device["id"]
            return did
    raise Exception("Failed to find ID")


def download_data(start_date_str: str = "2023-07-09") -> int:
    """Download missing weekly Rachio event JSONs.

    Returns the number of newly downloaded weekly files.
    """
    os.makedirs(RACHIO_DATA_DIRECTORY, exist_ok=True)
    rachio, did = None, None
    _, _, rachio_creds = common.get_creds()
    davis_api_key = rachio_creds["api_key"]
    weeks = common.enumerate_weekly_times(start_date_str=start_date_str)
    downloaded_count = 0
    for interval in weeks:
        start = interval["start_time"]
        end = interval["end_time"]
        file_name = get_rachio_filename(start)
        if os.path.exists(file_name):
            print(f"File: {file_name} already exists, not performing query")
            continue
        if rachio is None or did is None:
            rachio = Rachio(davis_api_key)
            did = get_davis_device_id(rachio)
        st = common.convert_iso_to_epoch_millis(start)
        et = common.convert_iso_to_epoch_millis(end)
        events = rachio.device.event(did, st, et)
        if (len(events) < 2) | (events[0]["status"] != 200):
            raise IOError(f"Failed to gather data for starttime {st}")
        with open(file_name, "w") as of:
            of.write(json.dumps(events[1], indent=4))
        print(f"Downloaded {file_name}")
        downloaded_count += 1
    return downloaded_count


def parse_rachio_events() -> dict[str, list[EventData]]:
    """Load every cached Rachio JSON and group parsed events by zone.

    Expands "watered while offline" events into synthetic STARTED/STOPPED pairs,
    filters out ZONE_CYCLING_* sub-events, and sorts chronologically within
    each zone. The returned dict is what `combine_data` and downstream callers
    use to build interval / hourly DataFrames.
    """
    files = sorted(glob.glob(RACHIO_DATA_DIRECTORY + "/**.json"))
    raw = []
    for file_name in files:
        with open(file_name, "r") as fh:
            raw += json.loads(fh.read())

    expanded = []
    for x in raw:
        expanded.extend(_expand_offline_event(x))

    cdata = [
        EventData(x)
        for x in expanded
        if x.get("type") == "ZONE_STATUS"
        and not (x.get("subType") or "").startswith("ZONE_CYCLING")
    ]
    cdata.sort(key=lambda x: x.eventDate)

    dd = defaultdict(list)
    for ev in cdata:
        dd[ev.zone].append(ev)
    return dd


def combine_data():
    dd = parse_rachio_events()
    dfs = [parse_datetime_intervals(zone, events) for zone, events in dd.items()]
    return pd.concat(dfs), dd


def load_rachio_data():
    download_data()
    data, _ = combine_data()
    return data


if __name__ == "__main__":
    data = load_rachio_data()
    data.to_csv("rachio.csv", index=False)
