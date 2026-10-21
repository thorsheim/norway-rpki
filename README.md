# Norway RPKI: ROA & ASPA posture

A public dashboard showing RPKI deployment for every Norwegian ASN: route-origin
validity of every announcement, ROA quality (maxLength exposure, leftover ROAs) and
ASPA records compared with observed upstreams.

Live at **https://rpki.thorsheim.net/** — rebuilt every day by a GitHub Action (`.github/workflows/update.yml`).

## Data sources

- **ROAs and ASPAs:** the full validated output (`rpki.json`) of the
  [rpki-client console](https://console.rpki-client.org/), all five RIR trust anchors.
- **Norwegian ASNs:** RIPEstat `country-resource-list` (NO), plus ASNs with registry
  country NO in [ipverse/asn-info](https://github.com/ipverse/asn-info).
- **Announcements:** RIPEstat `announced-prefixes` (RIPE RIS), routes seen by at least
  10 RIS peers during the last 24 hours.
- **Upstream-side neighbours:** RIPEstat `asn-neighbours`.

Every announcement is validated per RFC 6811 against every VRP worldwide.

## Files

- `scripts/build_data.py` collects the data and writes `docs/data/*.json`.
- `docs/index.html` is the dashboard (static, no build step).
- `docs/data/history.json` keeps one row of headline figures per day.

Run locally with `python scripts/build_data.py --out docs/data` (Python 3.10+, no dependencies),
then serve `docs/` with any static web server.
