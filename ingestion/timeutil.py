import datetime

from constants import LOCAL_TZ


def local_to_utc(ts: datetime.datetime) -> datetime.datetime:
    """
    Converts a naive local-time timestamp (as written by the measurement software) to the
    matching UTC instant. Timestamps that already carry a timezone are returned unchanged.

    The system records during the day only, so the repeated hour at the end of summer time
    never holds data; if it did, the first occurrence would be used.
    """
    if ts.tzinfo is not None:
        return ts
    return ts.replace(tzinfo=LOCAL_TZ).astimezone(datetime.timezone.utc)
