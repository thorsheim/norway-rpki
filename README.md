# Nordic RPKI: ROA & ASPA posture

Public dashboards showing RPKI deployment for every ASN in Norway, Sweden, Finland and
Denmark: route-origin validity of every announcement, ROA quality (maxLength exposure,
leftover ROAs) and ASPA records compared with observed upstreams.

| Country | Dashboard | Data |
|---|---|---|
| Norway | https://rpki.thorsheim.net/ | `docs/data/` |
| Sweden | https://rpki.thorsheim.net/se/ | `docs/se/data/` |
| Finland | https://rpki.thorsheim.net/fi/ | `docs/fi/data/` |
| Denmark | https://rpki.thorsheim.net/dk/ | `docs/dk/data/` |

**Nordic overview:** https://rpki.thorsheim.net/nordic/ ranks the four countries side by side
(sortable by each measure) and lists every routed network with full ROA coverage (all
announcements RPKI-valid) and an ASPA. It reads the country data files in the browser, so it
is always in step with the country dashboards.

Rebuilt daily by a GitHub Action (`.github/workflows/update.yml`). Each country is built
separately, so one country failing does not hold back the others; a later run the same day
retries only the countries that did not update.

## Data sources

- **ROAs and ASPAs:** the full validated output (`rpki.json`) of the
  [rpki-client console](https://console.rpki-client.org/), all five RIR trust anchors
  (downloaded once per run and shared by all countries).
- **The country's ASNs:** RIPEstat `country-resource-list` for the country code, plus ASNs
  with that registry country in [ipverse/asn-info](https://github.com/ipverse/asn-info).
- **Announcements:** RIPEstat `announced-prefixes` (RIPE RIS), routes seen by at least
  10 RIS peers during the last 24 hours.
- **Upstream-side neighbours:** RIPEstat `asn-neighbours`.

Every announcement is validated per RFC 6811 against every VRP worldwide.

## Files

- `scripts/build_data.py --country XX` collects the data for one country and writes
  `<out>/<cc>_*.json` (e.g. `docs/se/data/se_asns_rpki.json`).
- `site/template.html` is the dashboard page; `scripts/make_pages.py` writes one copy per
  country (`docs/index.html` for Norway, `docs/<cc>/index.html` for the others) with the
  country's name, time zone, flag and the country switcher. Edit the template, not the copies.
- `site/nordic.html` is the Nordic overview; `make_pages.py` writes it to `docs/nordic/index.html`.
- `scripts/daily_gate.py` decides which countries a run should build.
- In each data folder: `history.json` keeps one row of headline figures per day,
  `changes_log.json` every run's changes for the last 30 days, `state.json` the per-ASN
  snapshot the next run compares against, and `<cc>_changes.json` what changed since the
  previous run.

Run locally with `python scripts/build_data.py --country SE --out docs/se/data`
(Python 3.10+, no dependencies), then serve `docs/` with any static web server.
