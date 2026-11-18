#!/usr/bin/env python3
"""Sum the latest update of every country into docs/run.json: requests and bytes per data source
for one full daily update. The country pages show it under Method & caveats."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = {"NO": "docs/data", "SE": "docs/se/data", "FI": "docs/fi/data", "DK": "docs/dk/data",
        "IS": "docs/is/data", "CZ": "docs/cz/data"}


def main():
    hosts, countries = {}, {}
    for cc, d in DATA.items():
        try:
            meta = json.load(open(os.path.join(ROOT, d, "meta.json")))
        except FileNotFoundError:
            continue
        t = meta.get("traffic")
        if not t:
            continue
        countries[cc] = {"generated": meta["generated"], "requests": t["requests"], "bytes": t["bytes"],
                         "seconds": t.get("seconds"), "pub_pages": meta.get("pub_pages")}
        for h, v in t["hosts"].items():
            x = hosts.setdefault(h, {"requests": 0, "bytes": 0})
            x["requests"] += v["requests"]
            x["bytes"] += v["bytes"]
    out = {"countries": countries, "hosts": hosts,
           "requests": sum(v["requests"] for v in hosts.values()), "bytes": sum(v["bytes"] for v in hosts.values()),
           "seconds": sum(c["seconds"] or 0 for c in countries.values()),
           "complete": len(countries) == len(DATA)}
    json.dump(out, open(os.path.join(ROOT, "docs", "run.json"), "w"), indent=1)
    print(f"run.json: {out['requests']} requests, {out['bytes'] / 1e6:.1f} MB, {len(countries)} countries")


if __name__ == "__main__":
    main()
