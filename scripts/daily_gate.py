#!/usr/bin/env python3
"""Decide whether this workflow run should build new data.

Prints 'build=true' or 'build=false' (for $GITHUB_OUTPUT) and explains why on stderr.
Rules:
  * push                       -> no build (the page is redeployed with the existing data)
  * manual run (workflow_dispatch without scheduled=true) -> always build
  * scheduled run (cron, or workflow_dispatch with scheduled=true)
        -> build only if it is 08:00 or later in Norway and today's 08:00 update has not run yet
"""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")
UPDATE_HOUR = 8


def out(build, why):
    print(f"build={'true' if build else 'false'}")
    print(why, file=sys.stderr)
    sys.exit(0)


event = os.environ.get("EVENT", "")
scheduled = event == "schedule" or os.environ.get("SCHEDULED", "false").lower() == "true"
if event == "push":
    out(False, "push: redeploy only")
if not scheduled:
    out(True, f"{event}: manual run, always build")

now = dt.datetime.now(OSLO)
if now.hour < UPDATE_HOUR:
    out(False, f"scheduled run at {now:%H:%M} Norwegian time is before {UPDATE_HOUR:02d}:00; skipping")

today_slot = now.replace(hour=UPDATE_HOUR, minute=0, second=0, microsecond=0)
try:
    meta = json.load(open("docs/data/meta.json"))
    last = dt.datetime.strptime(meta["generated"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).astimezone(OSLO)
except Exception as e:  # no data yet
    out(True, f"no previous data ({e}); building")
if last >= today_slot:
    out(False, f"today's update already ran at {last:%H:%M} Norwegian time; skipping")
out(True, f"scheduled run at {now:%H:%M} Norwegian time; last update {last:%Y-%m-%d %H:%M}; building")
