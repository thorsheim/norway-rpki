#!/usr/bin/env python3
"""Decide which countries this workflow run should build.

Prints 'countries=NO SE FI DK IS CZ' (possibly empty) and 'build=true|false' for $GITHUB_OUTPUT,
and explains why on stderr.
Rules:
  * push                       -> nothing (the pages are redeployed with the existing data)
  * manual run (workflow_dispatch without scheduled=true) -> every country
  * scheduled run (cron, or workflow_dispatch with scheduled=true)
        -> only after 08:00 Norwegian time, and only countries whose data has not been
           updated since 08:00 today (so a country that failed earlier is retried)
"""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")
UPDATE_HOUR = 8
DATA = {"NO": "docs/data", "SE": "docs/se/data", "FI": "docs/fi/data", "DK": "docs/dk/data", "IS": "docs/is/data", "CZ": "docs/cz/data"}


def out(countries, why):
    print(f"countries={' '.join(countries)}")
    print(f"build={'true' if countries else 'false'}")
    print(why, file=sys.stderr)
    sys.exit(0)


event = os.environ.get("EVENT", "")
scheduled = event == "schedule" or os.environ.get("SCHEDULED", "false").lower() == "true"
if event == "push":
    out([], "push: redeploy only")
if not scheduled:
    out(list(DATA), f"{event}: manual run, build every country")

now = dt.datetime.now(OSLO)
if now.hour < UPDATE_HOUR:
    out([], f"scheduled run at {now:%H:%M} Norwegian time is before {UPDATE_HOUR:02d}:00; skipping")

today_slot = now.replace(hour=UPDATE_HOUR, minute=0, second=0, microsecond=0)
todo = []
for cc, d in DATA.items():
    try:
        meta = json.load(open(os.path.join(d, "meta.json")))
        last = dt.datetime.strptime(meta["generated"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).astimezone(OSLO)
    except Exception as e:  # no data yet
        print(f"{cc}: no previous data ({e})", file=sys.stderr)
        todo.append(cc)
        continue
    if last < today_slot:
        print(f"{cc}: last update {last:%Y-%m-%d %H:%M}; building", file=sys.stderr)
        todo.append(cc)
    else:
        print(f"{cc}: already updated today at {last:%H:%M}", file=sys.stderr)
out(todo, f"scheduled run at {now:%H:%M} Norwegian time")
