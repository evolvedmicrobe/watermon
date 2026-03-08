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
zone_regex = "(\w*\s*\w*\s*\w+)\s+(?:completed|began|stopped)"
offline_regex_pattern = "watered for (\d+) minutes while offline"
offline_regex = re.compile(offline_regex_pattern)
matcher = re.compile(zone_regex)
matcher.match(text)


class EventData:
    def __init__(self, data) -> None:
        if "type" not in data and not offline_regex.match(data.get("summary", "")):
            print(data)
            raise Exception(data)
        self.data = data
        self.type = data.get("type", "ZONE_STATUS")
        self.eventDate = data["eventDate"]
        self.summary = data["summary"]
        self.subType = data.get("subType")
        # Hack for
        self._parse_possible_offline_event()
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

        match = matcher.match(self.summary)
        if match:
            self.zone = match.group(1)
        else:
            self.zone = "UNKNOWN"

    def _parse_possible_offline_event(self):
        if self.data.get("subType") is None:
            # If we watered offline, promote to a full time,
            # time zones might be off here.
            if offline_regex.match(self.summary):
                self.subType = "ZONE_STOPPED"
                self.topic = "WATERING"

    def __str__(self) -> str:
        return f"{self.summary} - {self.date_string} - {self.data}"

    def __repr__(self) -> str:
        return self.__str__()


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

    # Iterate through datetime intervals
    for i in range(0, len(zone_data), 2):
        start = zone_data[i]
        end = zone_data[i + 1]
        assert (
            start.subType == "ZONE_STARTED"
        ), f"{start} - {end} {start.subType} starter"
        msg = "\n".join([str(x) for x in zone_data[i - 2 : i + 2]])
        print(f"Failures! {msg}")
        assert (
            end.subType == "ZONE_STOPPED" or end.subType == "ZONE_COMPLETED"
        ), f"{start} - {end} {end.subType} stopper"

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
    print(data)
    if (len(data) < 2) | (data[0]["status"] != 200):
        raise IOError("Failed to query device information")
    for device in data[1]["devices"]:
        if device["name"] == "Davis 16":
            did = device["id"]
            return did
    raise Exception("Failed to find ID")


def download_data():
    rachio, did = None, None
    _, _, rachio = common.get_creds()
    davis_api_key = rachio["api_key"]
    # The device was activated/installed on this day
    start_time = "2023-07-09"
    weeks = common.enumerate_weekly_times(start_date_str=start_time)
    for interval in weeks:
        start = interval["start_time"]
        end = interval["end_time"]
        file_name = get_rachio_filename(start)
        if os.path.exists(file_name):
            print(f"File: {file_name} already exists, not performing query")
        else:
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
                of.close()
            print(f"Downloaded {file_name}")


def combine_data():
    files = glob.glob(RACHIO_DATA_DIRECTORY + "/**.json")
    files.sort()
    data = []
    for file_name in files:
        cur_file = json.loads(open(file_name, "r").read())
        # aprint(cur_file)
        data += cur_file

    cdata = [
        EventData(x)
        for x in data
        if x.get("type") == "ZONE_STATUS"
        or "while offline" in x.get("summary")
        and (
            not x.get("subType") is None
            and x.get("subType").startswith("ZONE_CYCLING")
            or x.get("subType") is None
        )
    ]
    cdata.sort(key=lambda x: x.eventDate)
    # for x in cdata:
    #     print(x.date_string)
    # Now let's get the start and end times for each zone
    dd = defaultdict(list)
    for data in cdata:
        dd[data.zone].append(data)
    for k, v in dd.items():
        print(f"K = {k} VAL = {dd[k][:10]}")
    dfs = []
    for zone, events in dd.items():
        dfs.append(parse_datetime_intervals(zone, events))
    return pd.concat(dfs), dd


def load_rachio_data():
    download_data()
    data, cd = combine_data()
    # print(cd["UNKNOWN"])
    # print(cd.keys())
    data.to_csv("rachio.csv", index=False)
    return data


load_rachio_data()
