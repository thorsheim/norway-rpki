#!/usr/bin/env python3
"""Write docs/version.json for the page footers: the dashboard (code) version, i.e. the number of
commits that changed anything other than the daily data, plus the latest such commit and its date.
Needs the git history (actions/checkout with fetch-depth: 0)."""
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = ["--", ".", ":(exclude)docs/data", ":(exclude)docs/*/data/*", ":(exclude)docs/run.json", ":(exclude)docs/version.json"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main():
    sha, date, subject = git("log", "-1", "--format=%H%x00%cI%x00%s", *CODE).split("\0")
    out = {"version": int(git("rev-list", "--count", "HEAD", *CODE)), "commit": sha, "short": sha[:7],
           "date": date, "subject": subject}
    json.dump(out, open(os.path.join(ROOT, "docs", "version.json"), "w"), indent=1)
    print("version.json:", out)


if __name__ == "__main__":
    main()
