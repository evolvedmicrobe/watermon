from datetime import datetime, timedelta


def enumerate_weekly_times(start_date_str="2022-01-01"):
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.now()

    weekly_times = []

    current_date = start_date
    utc_offset = 8
    while current_date <= end_date:
        start_of_week = current_date - timedelta(days=current_date.weekday())
        end_of_week = start_of_week + timedelta(days=6)
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


# Example usage
weekly_times = enumerate_weekly_times()
for time_range in weekly_times:
    print(f"Start Time: {time_range['start_time']}, End Time: {time_range['end_time']}")
