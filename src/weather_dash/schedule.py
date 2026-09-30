"""Refresh times calculated on the server using packaged IANA timezone data."""

from datetime import UTC, datetime, time, timedelta
from importlib.resources import files
from zoneinfo import ZoneInfo

REFRESH_TIMEZONE = "America/Los_Angeles"
REFRESH_HOURS = (7, 11, 15, 19)

# Read the locked tzdata package explicitly so host OS timezone data cannot
# silently override the version shipped in the server image.
with files("tzdata.zoneinfo").joinpath(*REFRESH_TIMEZONE.split("/")).open("rb") as data:
    REFRESH_ZONE = ZoneInfo.from_file(data, key=REFRESH_TIMEZONE)


def next_refresh(now: datetime) -> datetime:
    """Return the next scheduled instant in UTC, strictly after now."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(UTC)
    local_date = now.astimezone(REFRESH_ZONE).date()
    for day in range(2):
        for hour in REFRESH_HOURS:
            candidate = datetime.combine(
                local_date + timedelta(days=day), time(hour), REFRESH_ZONE
            ).astimezone(UTC)
            if candidate > now:
                return candidate
    raise ValueError("No refresh hours configured")


def previous_refresh(now: datetime) -> datetime:
    """Most recent scheduled check-in, including the current instant."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(UTC)
    local_date = now.astimezone(REFRESH_ZONE).date()
    for day in range(2):
        for hour in reversed(REFRESH_HOURS):
            candidate = datetime.combine(
                local_date - timedelta(days=day), time(hour), REFRESH_ZONE
            ).astimezone(UTC)
            if candidate <= now:
                return candidate
    raise ValueError("No refresh hours configured")


def refresh_headers(now: datetime | None = None) -> dict[str, str]:
    # Calculate after rendering so server-side screenshot delays do not shift
    # the device clock or make the chosen refresh time stale.
    if now is None:
        now = datetime.now(UTC)
    target = next_refresh(now)
    return {
        "X-Weather-Time": str(int(now.timestamp())),
        "X-Weather-Next-Refresh": str(int(target.timestamp())),
        "Cache-Control": "no-store",
    }
