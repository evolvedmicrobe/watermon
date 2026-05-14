"""Script to get data from Aquahawk.  Aquahawk data seems to be delayed by ~24 hours from current time, going to grab weekly intervals."""

import os
import requests
import time

import pandas as pd

from common import (
    get_creds,
    get_data_directory,
    enumerate_weekly_times,
    format_timeseries_filename,
)

AQUAHAWK_URL = "https://aquahawk.us"


def _get_aquahawk_data_directory():
    return get_data_directory("aquahawk")


AQUAHAWK_DATA_DIRECTORY = _get_aquahawk_data_directory()


def get_weeks_data(
    context: requests.Session, interval: dict[str, str], account_info: dict[str, str]
) -> bool:
    """Get data from a start/end time from aquahawk.

    Args:
        context (requests.Session): _description_
        interval (dict[str, str]): _description_
        account_info (dict[str, str]): _description_

    Returns:
        bool: Whether the interval was downloaded or was already in the cache.
    """
    start = interval["start_time"]
    end = interval["end_time"]
    file_name = format_timeseries_filename(start, "AquaHawk", AQUAHAWK_DATA_DIRECTORY)
    if os.path.exists(file_name):
        print(f"File: {file_name} already exists, not performing query")
        return False
    else:
        print(f"Attempting to download for: {start}")
        export_url = f"{AQUAHAWK_URL}/timeseries/export"
        body = {
            "firstTime": start,
            "lastTime": end,
            "interval": "1 hour",
            "districtName": account_info["districtName"],
            "accountNumber": account_info["accountNumber"],
        }
        response = context.post(
            export_url, data=body, headers={"Accept": "application/json"}
        )
        if not response.ok:
            print(f"Request failed to export CSV file for {start}.")
            response.raise_for_status()
        data = response.json()
        body = {
            "district": data["district"],
            "username": data["username"],
            "type": data["type"],
            "filename": data["filename"],
        }
        csv_url = f"{AQUAHAWK_URL}/download"
        csv_data = context.get(csv_url, data=body)
        output_csv(csv_data, file_name)
        print("Downloaded")
        return True


def download_aquahawk_data(start_date_str: str = "2022-01-01") -> int:
    """Top level method to login to the aquahawk site and download data.

    Grabs hourly data a week at a time to accomodate API restrictions.  Logins with credentials stored in credentials.json.
    Returns the number of newly downloaded weekly files.
    """
    os.makedirs(AQUAHAWK_DATA_DIRECTORY, exist_ok=True)
    url = f"{AQUAHAWK_URL}/login"
    login, account, _ = get_creds()
    # Use requests here as it caches the cookies the best, `httplib2` was just not working when
    # I tried to manually fuzz with the cookies.
    intervals = enumerate_weekly_times(start_date_str)
    print(f"Generated intervals of length {len(intervals)}")
    downloaded_count = 0
    with requests.session() as context:
        result = context.post(url, data=login)
        print(f"Result of login was {result}, and that is {result.ok}")
        if not result.ok:
            result.raise_for_status()
        for interval in intervals:
            if get_weeks_data(context, interval, account):
                downloaded_count += 1
                # Avoid hitting the server too hard.
                time.sleep(1)
    return downloaded_count


def output_csv(response: requests.Response, outfilename: str):
    with open(outfilename, "w") as ofh:
        data = response.content.decode()
        ofh.write(data)
        ofh.close()


def read_aquahawk_csvs() -> pd.DataFrame:
    """Concatenate all cached AquaHawk weekly CSVs into a single raw DataFrame.

    No timezone handling, no download. Returns an empty DataFrame if the
    cache directory is missing or contains no CSVs.
    """
    if not os.path.isdir(AQUAHAWK_DATA_DIRECTORY):
        return pd.DataFrame()
    files = sorted(
        os.path.join(AQUAHAWK_DATA_DIRECTORY, x)
        for x in os.listdir(AQUAHAWK_DATA_DIRECTORY)
        if x.endswith(".csv")
    )
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def load_aquahawk_data():
    download_aquahawk_data()
    return read_aquahawk_csvs()


if __name__ == "__main__":
    df = load_aquahawk_data()
    df.to_csv("aq.csv")
