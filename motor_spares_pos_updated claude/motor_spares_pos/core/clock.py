"""Single source of truth for "now" across the whole POS.

Everything in this application — sales, stock movements, product edits,
sync queue entries — should be timestamped using the PC's own local clock,
not UTC and not a cached value. Python's datetime.now() already reads the
operating system clock, so this module exists mainly so every part of the
app asks the same place for the time, in the same format, instead of each
file rolling its own datetime.now()/strftime() calls.

If this PC's clock is ever wrong, everything the app timestamps will be
wrong too — the POS has no way to correct that on its own, it can only be
consistent about reading whatever the clock currently says.
"""

from datetime import datetime

SQLITE_FORMAT = "%Y-%m-%d %H:%M:%S"


def now() -> datetime:
    """The current local date/time, read straight from the PC's clock."""
    return datetime.now()


def now_str() -> str:
    """Current local time as a string in the same format SQLite stores."""
    return now().strftime(SQLITE_FORMAT)


def display_str() -> str:
    """Human-friendly current time for showing in the UI (e.g. dashboard)."""
    return now().strftime("%a, %d %b %Y  %H:%M:%S")
