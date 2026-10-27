"""Calendar and lot-size constants the forecast and the reorder policy read.

The values are those of the source-system extracts' calendar; tests/test_config.py asserts they equal
the extract generator's configuration.
"""
from datetime import date

FORWARD_START = date(2026, 1, 1)       # first day of the planning window the policy schedules
END_DATE = date(2026, 6, 30)           # last day of the extracts' history
AS_OF_DATE = date(2026, 6, 30)         # the reorder queue's as-of date
ORDER_COVER_DAYS = 135                 # the buyers' standing lot, in days of average demand
