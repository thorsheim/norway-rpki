#!/usr/bin/env python3
"""Build the Norway RPKI dashboard datasets.

Collects:
  * every validated ROA and ASPA (rpki-client console, rpki.json, all five RIR trust anchors)
  * Norwegian ASNs (RIPEstat country-resource-list NO + ipverse asn-info country NO)
  * exact announcements per ASN (RIPEstat announced-prefixes, RIS, >=10 peers, last 24h)
  * upstream-side neighbours per routed ASN (RIPEstat asn-neighbours)
  * publication hosts of each ASN's ROAs/ASPAs (rpki-client console AS pages)

Then validates every announcement (RFC 6811) against the full VRP set and writes
docs/data/*.json for the static dashboard, plus a daily history of headline figures.

Usage:
  python scripts/build_data.py --out docs/data            # full run (needs internet)
  python scripts/build_data.py --out X --from-raw raw.json  # re-analyse a saved raw snapshot
"""
import argparse
import collections
import csv
import datetime as dt
import io
import ipaddress as ip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "norway-rpki-dashboard/1.0 (+https://github.com/thorsheim/norway-rpki)"
SOURCEAPP = "norway-rpki-dashboard"
RIPESTAT = "https://stat.ripe.net/data"
CONSOLE = "https://console.rpki-client.org"
IPVERSE_ASINFO = "https://raw.githubusercontent.com/ipverse/asn-info/master/as.csv"
MIN_PEERS = 10


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def get(url, tries=5, timeout=300, as_json=True):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            return json.loads(body) if as_json else body.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            time.sleep(min(60, 3 * 2 ** i))
        except Exception as e:  # network hiccup
            last = e
            time.sleep(min(60, 3 * 2 ** i))
    raise RuntimeError(f"GET failed after {tries} tries: {url}: {last}")


def pmap(fn, items, workers=6):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


# ---------------------------------------------------------------- validation
def _parts(prefix):
    n = ip.ip_network(prefix, strict=False)
    bits = 32 if n.version == 4 else 128
    return n.version, int(n.network_address), n.prefixlen, bits


def build_index(roas):
    idx = collections.defaultdict(list)
    for r in roas:
        v, a, L, bits = _parts(r["prefix"])
        idx[(v, a >> (bits - L) if L else 0, L)].append(r)
    return idx


def rov(idx, prefix, origin):
    v, a, L, bits = _parts(prefix)
    cov = []
    for k in range(L + 1):
        cov.extend(idx.get((v, a >> (bits - k) if k else 0, k), ()))
    if not cov:
        return {"s": "N"}
    if any(r["asn"] == origin and r["maxLength"] >= L for r in cov):
        return {"s": "V"}
    same = [r for r in cov if r["asn"] == origin]
    return {"s": "I", "r": "maxLength" if same else "origin",
            "c": [[r["asn"], r["prefix"], r["maxLength"]] for r in cov[:6]]}


# ---------------------------------------------------------------- collection
def collect():
    now = dt.datetime.now(dt.timezone.utc)
    log("downloading rpki.json")
    rpki = get(f"{CONSOLE}/rpki.json", timeout=900)
    log("rpki.json:", len(rpki["roas"]), "VRPs,", len(rpki.get("aspas", [])), "ASPAs, built", rpki["metadata"]["buildtime"])

    log("ASN lists")
    ascsv = get(IPVERSE_ASINFO, as_json=False)
    names, ipverse_no = {}, set()
    for row in csv.DictReader(io.StringIO(ascsv)):
        names[row["asn"]] = row["description"]
        if row["country-code"] == "NO":
            ipverse_no.add(int(row["asn"]))
    cr = get(f"{RIPESTAT}/country-resource-list/data.json?resource=NO&sourceapp={SOURCEAPP}")
    rir_no = set()
    for x in cr["data"]["resources"]["asn"]:
        s = str(x)
        if "-" in s:
            lo, hi = map(int, s.split("-"))
            rir_no.update(range(lo, hi + 1))
        else:
            rir_no.add(int(s))
    universe = sorted(ipverse_no | rir_no)
    log("universe:", len(universe), "ASNs")

    start = (now - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

    def announced(a):
        j = get(f"{RIPESTAT}/announced-prefixes/data.json?resource=AS{a}&starttime={start}"
                f"&min_peers_seeing={MIN_PEERS}&sourceapp={SOURCEAPP}")
        return a, [p["prefix"] for p in j["data"].get("prefixes", [])], j["data"].get("query_endtime")

    log("announced prefixes")
    ann = {a: (p, qt) for a, p, qt in pmap(announced, universe)}

    log("validating")
    idx = build_index(rpki["roas"])
    U = set(universe)
    vrp_by, aspa_by = collections.defaultdict(list), collections.defaultdict(list)
    for r in rpki["roas"]:
        if r["asn"] in U:
            vrp_by[r["asn"]].append(r)
    for x in rpki.get("aspas", []):
        if x["customer_asid"] in U:
            aspa_by[x["customer_asid"]].append(x["providers"])
    routed = [a for a in universe if ann[a][0]]

    def neighbours(a):
        j = get(f"{RIPESTAT}/asn-neighbours/data.json?resource=AS{a}&sourceapp={SOURCEAPP}")
        nb = [[n["asn"], n["power"]] for n in j["data"].get("neighbours", []) if n.get("type") == "left"]
        return a, nb, j["data"].get("query_endtime")

    log("neighbours")
    nbs = {a: (nb, qt) for a, nb, qt in pmap(neighbours, routed)}

    def hosts(a):
        try:
            h = get(f"{CONSOLE}/AS{a}.html", as_json=False, tries=3, timeout=60)
        except Exception:
            return a, []
        return a, sorted({m.group(1) for m in re.finditer(r'<a href="/([^/"]+)/[^"]+\.(?:roa|asa)\.html"', h)})

    log("publication hosts")
    need = [a for a in universe if a in vrp_by or a in aspa_by]
    ca = dict(pmap(hosts, need, workers=4))

    raw = {"meta": {"rpki_buildtime": rpki["metadata"]["buildtime"],
                    "ris_query": next((qt for p, qt in ann.values() if qt), None),
                    "nb_query": next((qt for nb, qt in nbs.values() if qt), None),
                    "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "global_vrps": len(rpki["roas"]), "global_aspas": len(rpki.get("aspas", []))},
           "names": {str(a): names.get(str(a), "") for a in set(universe) | {p for v in aspa_by.values() for s in v for p in s}},
           "asns": {}}
    for a in universe:
        prefixes = ann[a][0]
        raw["asns"][str(a)] = {
            "ri": int(a in rir_no), "ip": int(a in ipverse_no),
            "ann": [{"p": p, **rov(idx, p, a)} for p in prefixes],
            "v": [[r["prefix"], r["maxLength"], r.get("ta", "")] for r in vrp_by.get(a, [])],
            "aspa": aspa_by.get(a, []),
            "nb": nbs.get(a, ([], None))[0],
            "ca": ca.get(a, []),
        }
    return raw


# ---------------------------------------------------------------- analysis
def analyze(raw, prev_rows):
    A, names = raw["asns"], raw.get("names", {})
    prev = {r["asn"]: r for r in prev_rows}
    N = lambda p: ip.ip_network(p, strict=False)

    def size(n):
        if n.version == 4:
            return n.num_addresses // 256 if n.prefixlen <= 24 else 0
        return n.num_addresses // 2 ** 80 if n.prefixlen <= 48 else 0

    ann = {a: [(N(x["p"]), x) for x in d["ann"]] for a, d in A.items()}
    allann = [(n, int(a)) for a, L in ann.items() for n, _ in L]

    def ca_model(hs):
        if not hs:
            return ""
        if any(h in ("rsync.paas.rpki.ripe.net", "cloudie-repo.rpki.app") or "krill" in h for h in hs):
            return "Delegated CA (own publication)"
        if all(h == "rpki.ripe.net" for h in hs):
            return "RIPE NCC hosted"
        return "Hosted at other RIR / NIR"

    rows, F, V, ASP = [], [], [], []

    def add(sev, cat, a, objs, detail, n=None):
        F.append({"id": f"{len(F):04d}-{a}", "severity": sev, "category": cat, "asn": int(a), "name": names.get(a, ""),
                  "count": n if n is not None else len(objs),
                  "objects": ", ".join(objs[:8]) + (f" (+{len(objs) - 8} more)" if len(objs) > 8 else ""),
                  "detail": detail, "v4_24s": 0, "_objs": list(objs)})

    for a, d in A.items():
        L = ann[a]
        ai = int(a)
        nm = names.get(a, "")
        st = collections.Counter(x["s"] for _, x in L)
        v4 = [(n, x) for n, x in L if n.version == 4]
        v6 = [(n, x) for n, x in L if n.version == 6]

        def top(S):
            return [(n, x) for n, x in S if not any(m != n and m.version == n.version and n.subnet_of(m) for m, _ in S)]

        t4, t6 = top(v4), top(v6)
        s4, s6 = sum(size(n) for n, _ in t4), sum(size(n) for n, _ in t6)
        c4 = sum(size(n) for n, x in t4 if x["s"] == "V")
        c6 = sum(size(n) for n, x in t6 if x["s"] == "V")
        vr = [(N(p), ml, ta) for p, ml, ta, *_ in d["v"]]
        wide, loose, l6, mig, unann = [], [], [], [], []
        for n, ml, ta in vr:
            own = [m for m, _ in L if m.version == n.version and (m.subnet_of(n) or n.subnet_of(m))]
            spread = ml - n.prefixlen
            others = []
            if not own:
                others = sorted({o for m, o in allann if o != ai and m.version == n.version and (m.subnet_of(n) or n.subnet_of(m))})
                (mig.append((n, ml, others)) if others else unann.append((n, ml)))
            elif spread > 0:
                inrange = [m for m in own if m.subnet_of(n) and n.prefixlen < m.prefixlen <= ml]
                if len(inrange) < 2 ** (spread + 1) - 2:
                    if n.version == 4:
                        (wide if spread >= 4 else loose).append((n, ml, len(inrange)))
                    elif spread >= 16:
                        l6.append((n, ml, len(inrange)))
            V.append({"asn": ai, "prefix": str(n), "afi": "IPv6" if n.version == 6 else "IPv4", "len": n.prefixlen,
                      "maxlen": ml, "spread": spread, "ta": ta, "unannounced": "no" if own else "yes",
                      "originated_by_other": " ".join(f"AS{o}" for o in others)})
        routed = bool(L)
        if not routed:
            status = "Not routed"
        elif st["V"] == len(L):
            status = "All valid"
        elif st["V"]:
            status = "Partly valid"
        else:
            status = "None valid"
        nb = sorted(d["nb"], key=lambda x: -x[1])
        provs = sorted({p for s in d["aspa"] for p in s})
        unl = [(b, pw) for b, pw in nb if b not in provs] if d["aspa"] else []
        notseen = [p for p in provs if p and p not in {b for b, _ in nb}] if (d["aspa"] and routed) else []
        pv = prev.get(ai, {})
        rows.append({"asn": ai, "name": nm, "routed": "yes" if routed else "no", "roa_status": status,
                     "prefixes_v4": len(v4), "prefixes_v6": len(v6), "valid": st["V"], "invalid": st["I"], "notfound": st["N"],
                     "valid_pct": round(100 * st["V"] / len(L), 1) if L else None,
                     "v4_24s": s4, "v4_valid_24s": c4, "v6_48s": s6, "v6_valid_48s": c6,
                     "cov_v4_pct": round(100 * c4 / s4, 1) if s4 else None,
                     "vrps": len(vr), "wide_maxlen_v4": len(wide), "loose_maxlen_v4": len(loose),
                     "unannounced_vrps": len(unann) + len(mig),
                     "aspa": "yes" if d["aspa"] else "no",
                     "aspa_providers": ", ".join("AS0" if p == 0 else f"AS{p}" for p in provs),
                     "upstreams_seen": ", ".join(f"AS{b}" for b, _ in nb[:6]),
                     "ca_model": ca_model(d["ca"]), "ca_hosts": ";".join(d["ca"]),
                     "vrps_prev": pv.get("vrps"), "aspa_prev": pv.get("aspa"),
                     "in_rir_list": "yes" if d["ri"] else "no"})
        for n, x in L:
            if x["s"] == "I":
                why = "origin AS not in any covering ROA" if x.get("r") == "origin" else "prefix longer than the ROA maxLength"
                add("High", "RPKI-invalid announcement", a,
                    [f"{n} (ROA: {', '.join(f'AS{v[0]} {v[1]}-{v[2]}' for v in x.get('c', [])[:3])})"],
                    f"AS{a} announces {n}, which validates INVALID ({why}). Networks doing ROV drop it — fix the ROA or the announcement.")
        if routed and st["V"] == 0 and st["I"] == 0:
            add("Medium", "Routed with no ROA", a, [str(n) for n, _ in L],
                f"All {len(L)} announcements from AS{a} are RPKI NotFound: route-origin validation gives them no hijack protection.")
        elif routed and st["V"] and st["N"]:
            add("Medium", "Some announcements not covered", a, [str(n) for n, x in L if x["s"] == "N"],
                f"{st['N']} of {len(L)} announcements from AS{a} have no covering ROA (NotFound).")
        f = lambda t: f"{t[0]}→/{t[1]} ({t[2]} announced)"
        if wide:
            add("High", "Wide maxLength (IPv4)", a, [f(t) for t in wide],
                f"ROA maxLength 4+ bits past the prefix while most more-specifics are not announced: a forged-origin more-specific with AS{a} validates and wins on longest match (RFC 9319).")
        if loose:
            add("Medium", "Loose maxLength (IPv4)", a, [f(t) for t in loose],
                "maxLength 1–3 bits past the prefix with unannounced more-specifics in range; tighten to what is announced (RFC 9319).")
        if l6:
            add("Low", "Loose maxLength (IPv6)", a, [f(t) for t in l6],
                "IPv6 maxLength 16+ bits past the prefix (e.g. /32→/48) with most more-specifics unannounced.")
        if mig:
            add("Medium", "ROA for space another AS originates", a,
                [f"{n}-{ml} (now {', '.join('AS' + str(o) for o in os_)})" for n, ml, os_ in mig],
                f"ROAs authorise AS{a} for space that another Norwegian AS announces — a typical leftover after a migration. AS{a}, or anyone forging it, stays valid there.")
        if unann:
            add("Low", "ROA for unannounced space", a, [f"{n}-{ml}" for n, ml in unann],
                "ROAs cover space nobody in Norway announces. Fine for backup/DDoS-scrubbing; otherwise an AS0 ROA or removal is safer.")
        if d["aspa"]:
            if provs == [0]:
                add("High" if routed and nb else "Info", "ASPA declares no providers (AS0)", a, ["AS0"],
                    "ASPA lists only AS0 (no upstreams)." + (" But this AS is announced via upstreams — its routes are ASPA-invalid wherever ASPA is enforced." if routed and nb else " Good hygiene for an unused ASN."))
            if unl:
                add("Low", "Observed neighbour not in ASPA", a, [f"AS{b} (seen by {pw} RIS peers)" for b, pw in unl],
                    "RIS sees these ASNs directly upstream-side of this AS but they are not in its ASPA. Fine if they are peers; if any is a transit provider, add it or routes via it will fail ASPA checks.")
            if notseen:
                add("Info", "ASPA provider not observed", a, [f"AS{p}" for p in notseen],
                    "Listed as a provider but not seen as a neighbour in RIS today. Fine for backup links; otherwise remove stale entries.")
            ASP.append({"customer": ai, "name": nm, "routed": "yes" if routed else "no",
                        "providers": ", ".join("AS0" if p == 0 else f"AS{p}" for p in provs),
                        "provider_names": "; ".join(f"AS{p} {names.get(str(p), '')}" for p in provs if p),
                        "provider_count": len([p for p in provs if p]),
                        "neighbours_seen": ", ".join(f"AS{b} ({pw})" for b, pw in nb),
                        "unlisted_neighbours": ", ".join(f"AS{b}" for b, _ in unl),
                        "unobserved_providers": ", ".join(f"AS{p}" for p in notseen),
                        "new_since_prev": "yes" if (prev and pv.get("aspa") != "yes") else "no"})
    v4map = {r["asn"]: r["v4_24s"] for r in rows}
    sev = collections.defaultdict(collections.Counter)
    for x in F:
        x["v4_24s"] = v4map[x["asn"]]
        sev[x["asn"]][x["severity"]] += 1
    for r in rows:
        r["high"], r["medium"], r["low"] = sev[r["asn"]]["High"], sev[r["asn"]]["Medium"], sev[r["asn"]]["Low"]
    return rows, V, ASP, F


# ---------------------------------------------------------------- change tracking
STATUS_RANK = {"None valid": 0, "Partly valid": 1, "All valid": 2}
ROV_RANK = {"I": 0, "N": 1, "V": 2}
ROV_NAME = {"V": "Valid", "N": "NotFound", "I": "Invalid"}
DELTA_FIELDS = ["prefixes_v4", "prefixes_v6", "valid", "notfound", "invalid", "valid_pct", "cov_v4_pct", "v4_24s",
                "vrps", "wide_maxlen_v4", "loose_maxlen_v4", "unannounced_vrps", "high", "medium", "low"]


def make_state(raw, rows, F):
    st = {r["asn"]: {"st": r["roa_status"], "ann": {}, "v": [], "aspa": [], "f": {}} for r in rows}
    for a, d in raw["asns"].items():
        s = st[int(a)]
        s["ann"] = {x["p"]: x["s"] for x in d["ann"]}
        s["v"] = sorted({f"{p}-{ml}" for p, ml, *_ in d["v"]})
        s["aspa"] = sorted({p for x in d["aspa"] for p in x})
    for f in F:
        st[f["asn"]]["f"].setdefault(f"{f['severity']}|{f['category']}", []).extend(f["_objs"])
    return {"generated": raw["meta"]["generated"], "rpki_buildtime": raw["meta"]["rpki_buildtime"],
            "asns": {str(k): v for k, v in st.items()}}


def state_from_files(rows, vrps, aspa, findings, meta):
    """Fallback when no state.json exists yet: rebuild what we can from the published files."""
    st = {r["asn"]: {"st": r["roa_status"], "ann": None, "v": [], "aspa": [], "f": {}} for r in rows}
    for v in vrps:
        if v["asn"] in st:
            st[v["asn"]]["v"].append(f"{v['prefix']}-{v['maxlen']}")
    for x in aspa:
        if x["customer"] in st:
            st[x["customer"]]["aspa"] = sorted(int(p[2:]) for p in x["providers"].split(", ") if p.startswith("AS"))
    for f in findings:
        if f["asn"] in st:
            st[f["asn"]]["f"].setdefault(f"{f['severity']}|{f['category']}", []).append(f"__count__{f['count']}")
    return {"generated": meta.get("generated"), "rpki_buildtime": meta.get("rpki_buildtime"),
            "asns": {str(k): v for k, v in st.items()}, "partial": True}


_VOLATILE = re.compile(r" \((?:\d+ announced|seen by \d+ RIS peers)\)")


def _norm(o):
    return _VOLATILE.sub("", o)


def diff_state(prev, cur):
    """Per-ASN list of change events. k: '+', '-' or '~'; g: 1 better, -1 worse, 0 neutral."""
    out = {}
    P, C = prev["asns"], cur["asns"]
    for a in sorted(set(P) | set(C), key=int):
        p, c, ev = P.get(a), C.get(a), []
        if p is None:
            ev.append({"k": "+", "g": 0, "c": "asn", "t": "Newly counted as a Norwegian ASN"})
            p = {"st": "Not routed", "ann": {}, "v": [], "aspa": [], "f": {}}
        if c is None:
            out[a] = [{"k": "-", "g": 0, "c": "asn", "t": "No longer in the list of Norwegian ASNs"}]
            continue
        if p["st"] != c["st"]:
            ra, rb = STATUS_RANK.get(p["st"]), STATUS_RANK.get(c["st"])
            g = 0 if ra is None or rb is None else (1 if rb > ra else -1)
            ev.append({"k": "~", "g": g, "c": "status", "t": f"Route validity: {p['st']} → {c['st']}"})
        if p["ann"] is not None:
            for pf in sorted(set(c["ann"]) - set(p["ann"])):
                s = c["ann"][pf]
                ev.append({"k": "+", "g": {"V": 1, "N": 0, "I": -1}[s], "c": "route", "t": f"Now announces {pf} ({ROV_NAME[s]})"})
            for pf in sorted(set(p["ann"]) - set(c["ann"])):
                s = p["ann"][pf]
                ev.append({"k": "-", "g": 1 if s == "I" else 0, "c": "route", "t": f"Stopped announcing {pf} (was {ROV_NAME[s]})"})
            for pf in sorted(set(p["ann"]) & set(c["ann"])):
                a1, b1 = p["ann"][pf], c["ann"][pf]
                if a1 != b1:
                    ev.append({"k": "~", "g": 1 if ROV_RANK[b1] > ROV_RANK[a1] else -1, "c": "route",
                               "t": f"{pf}: {ROV_NAME[a1]} → {ROV_NAME[b1]}"})
        for v in sorted(set(c["v"]) - set(p["v"])):
            pf, ml = v.rsplit("-", 1)
            ev.append({"k": "+", "g": 0, "c": "roa", "t": f"New ROA {pf} maxLength {ml}"})
        for v in sorted(set(p["v"]) - set(c["v"])):
            pf, ml = v.rsplit("-", 1)
            ev.append({"k": "-", "g": 0, "c": "roa", "t": f"ROA removed: {pf} maxLength {ml}"})
        pa, ca_ = set(p["aspa"]), set(c["aspa"])
        if pa != ca_:
            fmt = lambda x: "AS0" if x == 0 else f"AS{x}"
            if not pa:
                ev.append({"k": "+", "g": 1, "c": "aspa", "t": "ASPA published: " + ", ".join(fmt(x) for x in sorted(ca_))})
            elif not ca_:
                ev.append({"k": "-", "g": -1, "c": "aspa", "t": "ASPA removed (was " + ", ".join(fmt(x) for x in sorted(pa)) + ")"})
            else:
                for x in sorted(ca_ - pa):
                    ev.append({"k": "+", "g": 0, "c": "aspa", "t": f"ASPA provider added: {fmt(x)}"})
                for x in sorted(pa - ca_):
                    ev.append({"k": "-", "g": 0, "c": "aspa", "t": f"ASPA provider removed: {fmt(x)}"})
        for key in sorted(set(p["f"]) | set(c["f"])):
            sev, cat = key.split("|", 1)
            bad = sev in ("High", "Medium")
            po, co = p["f"].get(key, []), c["f"].get(key, [])
            partial = any(o.startswith("__count__") for o in po)
            if partial:  # previous objects unknown: compare at category level
                pn = int(po[0][9:]) if po else 0
                if not co:
                    ev.append({"k": "-", "g": 1 if bad else 0, "c": "finding", "t": f"Resolved: {cat} ({sev})"})
                elif not po:
                    ev.append({"k": "+", "g": -1 if bad else 0, "c": "finding", "t": f"New finding: {cat} ({sev})"})
                elif pn != len(co):
                    ev.append({"k": "~", "g": (1 if len(co) < pn else -1) if bad else 0, "c": "finding",
                               "t": f"{cat} ({sev}): {pn} → {len(co)} objects"})
                continue
            pn_, cn_ = {_norm(o) for o in po}, {_norm(o) for o in co}
            for o in [o for o in co if _norm(o) not in pn_]:
                ev.append({"k": "+", "g": -1 if bad else 0, "c": "finding", "t": f"New {sev.lower()} finding — {cat}: {o}"})
            for o in [o for o in po if _norm(o) not in cn_]:
                ev.append({"k": "-", "g": 1 if bad else 0, "c": "finding", "t": f"Resolved {sev.lower()} finding — {cat}: {o}"})
        if ev:
            out[a] = ev
    return out


def attach_changes(rows, F, ASP, events, prev_rows, prev_state, cur_state):
    prev = {r["asn"]: r for r in prev_rows}
    for r in rows:
        pv = prev.get(r["asn"])
        for k in DELTA_FIELDS:
            a, b = (pv or {}).get(k), r.get(k)
            r["d_" + k] = round(b - a, 1) if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b != a else None
        r["status_prev"] = (pv or {}).get("roa_status")
        ev = events.get(str(r["asn"]), [])
        r["changes"] = ev[:60]
        r["changes_more"] = max(0, len(ev) - 60)
        r["chg_plus"] = sum(e["k"] == "+" for e in ev)
        r["chg_minus"] = sum(e["k"] == "-" for e in ev)
        r["chg_other"] = sum(e["k"] == "~" for e in ev)
        r["chg_total"] = len(ev)
        r["chg_good"] = sum(e["g"] > 0 for e in ev)
        r["chg_bad"] = sum(e["g"] < 0 for e in ev)
    pf = prev_state["asns"] if prev_state else {}
    for f in F:
        key = f"{f['severity']}|{f['category']}"
        po = pf.get(str(f["asn"]), {}).get("f", {}).get(key)
        if not prev_state:
            f["is_new"] = "no"
        elif po is None:
            f["is_new"] = "yes"
        elif any(o.startswith("__count__") for o in po):
            f["is_new"] = "no"
        else:
            pn_ = {_norm(o) for o in po}
            f["is_new"] = "yes" if any(_norm(o) not in pn_ for o in f["_objs"]) else "no"
    pa = {int(a): set(s["aspa"]) for a, s in pf.items()}
    for x in ASP:
        ev = [e for e in events.get(str(x["customer"]), []) if e["c"] == "aspa"]
        x["changes"] = ev
        x["chg_total"] = len(ev)
    flat = []
    names = {r["asn"]: r["name"] for r in rows} | {r["asn"]: r["name"] for r in prev_rows if r["asn"] not in {x["asn"] for x in rows}}
    order = {"status": 0, "route": 1, "finding": 2, "aspa": 3, "roa": 4, "asn": 5}
    for a, ev in events.items():
        for i, e in enumerate(ev):
            flat.append({"id": f"{a}-{i}", "asn": int(a), "name": names.get(int(a), ""), "kind": e["k"], "good": e["g"],
                         "area": {"status": "Route validity", "route": "Announcement", "finding": "Finding", "aspa": "ASPA",
                                  "roa": "ROA", "asn": "ASN list"}[e["c"]], "text": e["t"], "_o": order[e["c"]]})
    flat.sort(key=lambda e: (-abs(e["good"]), e["_o"], e["asn"]))
    for e in flat:
        del e["_o"]
    return flat


def headline(rows, F, raw):
    R = [r for r in rows if r["routed"] == "yes"]
    s = lambda k: sum(r[k] or 0 for r in R)
    return {"date": raw["meta"]["generated"][:10], "rpki_buildtime": raw["meta"]["rpki_buildtime"],
            "registered": len(rows), "routed": len(R),
            "all_valid": sum(r["roa_status"] == "All valid" for r in R),
            "partly_valid": sum(r["roa_status"] == "Partly valid" for r in R),
            "none_valid": sum(r["roa_status"] == "None valid" for r in R),
            "valid": s("valid"), "invalid": s("invalid"), "notfound": s("notfound"),
            "v4_valid_pct": round(100 * s("v4_valid_24s") / max(1, s("v4_24s")), 2),
            "v6_valid_pct": round(100 * s("v6_valid_48s") / max(1, s("v6_48s")), 2),
            "aspa": sum(r["aspa"] == "yes" for r in rows), "aspa_routed": sum(r["aspa"] == "yes" for r in R),
            "high": sum(f["severity"] == "High" for f in F)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from-raw")
    ap.add_argument("--save-raw")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    raw = json.load(open(args.from_raw)) if args.from_raw else collect()
    if args.save_raw:
        json.dump(raw, open(args.save_raw, "w"))
    rd = lambda name, default: json.load(open(os.path.join(args.out, name))) if os.path.exists(os.path.join(args.out, name)) else default
    prev_rows = rd("no_asns_rpki.json", [])
    prev_meta = rd("meta.json", {})
    prev_state = rd("state.json", None)
    if prev_state is None and prev_rows:
        prev_state = state_from_files(prev_rows, rd("no_vrps.json", []), rd("no_aspa.json", []), rd("no_findings.json", []), prev_meta)
    rows, V, ASP, F = analyze(raw, prev_rows)
    # sanity guard: refuse to overwrite good data with an obviously broken run
    routed = sum(r["routed"] == "yes" for r in rows)
    if routed < 150 or len(V) < 500:
        log(f"sanity check failed (routed={routed}, vrps={len(V)}); keeping previous data")
        sys.exit(1)
    dump = lambda name, obj: json.dump(obj, open(os.path.join(args.out, name), "w"), separators=(",", ":"), ensure_ascii=False)
    cur_state = make_state(raw, rows, F)
    events = diff_state(prev_state, cur_state) if prev_state else {}
    changes = attach_changes(rows, F, ASP, events, prev_rows, prev_state, cur_state)
    for f in F:
        del f["_objs"]
    dump("no_asns_rpki.json", rows)
    dump("no_vrps.json", V)
    dump("no_aspa.json", ASP)
    dump("no_findings.json", F)
    dump("no_changes.json", changes)
    dump("state.json", cur_state)
    h = headline(rows, F, raw)
    hist_path = os.path.join(args.out, "history.json")
    hist = json.load(open(hist_path)) if os.path.exists(hist_path) else []
    hist = [x for x in hist if x["date"] != h["date"]] + [h]
    hist.sort(key=lambda x: x["date"])
    dump("history.json", hist)
    dump("meta.json", {**raw["meta"], "headline": h,
                       "prev_generated": (prev_state or {}).get("generated"),
                       "prev_rpki_buildtime": (prev_state or {}).get("rpki_buildtime"),
                       "prev_headline": prev_meta.get("headline"),
                       "changes_detail": "partial" if (prev_state or {}).get("partial") else ("full" if prev_state else "none")})
    log("done:", h)


if __name__ == "__main__":
    main()
