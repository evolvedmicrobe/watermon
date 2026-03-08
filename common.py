from datetime import datetime, timedelta, timezone
import json
import os


def get_creds():
    direc = os.path.dirname(__file__)
    creds = os.path.join(direc, "credentials.json")
    with open(creds, "r") as fh:
        data = fh.read()
        creds = json.loads(data)

    return creds["login"], creds["aquahawk"], creds["rachio"]


def format_timeseries_filename(firstTime: str, device: str, datadir: str, ext="csv"):
    firstTime = firstTime.replace(":00:00Z", "")
    fname = f"{device}_TimeSeriesReport_{firstTime}.{ext}"
    return os.path.join(datadir, fname)


def get_data_directory(device):
    direc = os.path.dirname(__file__)
    return os.path.join(direc, "data", f"{device}_weeklies")


def enumerate_weekly_times(start_date_str="2022-01-01") -> list[dict[str, str]]:
    """Enumerate weeks from start time up till 3 days before now

    Args:
        start_date_str (str, optional): _description_. Defaults to "2022-01-01".

    Returns:
        _type_: _description_
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.now()
    weekly_times = []
    current_date = start_date
    utc_offset = 8
    stop_polling_date = end_date - timedelta(days=3)  # 3 is conservative

    while current_date <= end_date:
        start_of_week = current_date - timedelta(
            days=current_date.weekday()
        )  # weekday is monday 0, sunday 6
        end_of_week = start_of_week + timedelta(days=6)
        if end_of_week > stop_polling_date:
            break

        # Manually add a Z and adjust for UTC time to match the web interface
        weekly_times.append(
            {
                "start_time": (start_of_week + timedelta(hours=utc_offset)).isoformat()
                + "Z",
                "end_time": (
                    end_of_week.replace(
                        hour=23, minute=59, second=59, microsecond=999999
                    )
                    + timedelta(hours=8)
                ).isoformat()
                + "Z",
            }
        )
        current_date = start_of_week + timedelta(weeks=1)
    return weekly_times


def convert_iso_to_epoch_millis(iso_str):
    # Remove the 'Z' timezone indicator since fromisoformat does not support it
    iso_str = iso_str.replace("Z", "+00:00")

    # Parse the ISO 8601 string into a datetime object, considering it as UTC
    date = datetime.fromisoformat(iso_str)

    # Convert the datetime object to Unix timestamp in seconds,
    # ensuring it's aware of its timezone (UTC in this case)
    timestamp_seconds = date.replace(tzinfo=timezone.utc).timestamp()

    # Convert seconds to milliseconds
    timestamp_millis = int(timestamp_seconds * 1000)

    return timestamp_millis


def convert_to_epoch_millis(date_str):
    # Parse the date string into a datetime object
    date = datetime.strptime(date_str, "%m/%d/%Y")

    # Convert the datetime object to Unix timestamp in seconds
    timestamp_seconds = datetime.timestamp(date)

    # Convert seconds to milliseconds
    timestamp_millis = int(timestamp_seconds * 1000)

    return timestamp_millis
