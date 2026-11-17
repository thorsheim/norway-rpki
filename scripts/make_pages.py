#!/usr/bin/env python3
"""Write the dashboard pages from the templates in site/.

* site/template.html -> one page per country. Norway stays at the site root (docs/index.html,
  data in docs/data); the others live in docs/<cc>/index.html with data in docs/<cc>/data.
* site/nordic.html   -> docs/nordic/index.html, the four countries side by side. It reads the
  country data files in the browser and shares the country pages' styles.
Run after editing either template.
"""
import json
import os
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def flag(bg, cross, x, w, y, h, inner=None, border=False):
    """Nordic cross flag as an SVG data URI (32x32, rounded)."""
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
           f"<rect width='32' height='32' rx='7' fill='{bg}'{' stroke=\"#c9c5bc\" stroke-width=\"1.5\"' if border else ''}/>"
           f"<rect x='{x}' width='{w}' height='32' fill='{cross}'/><rect y='{y}' width='32' height='{h}' fill='{cross}'/>")
    if inner:
        c, ix, iw, iy, ih = inner
        svg += f"<rect x='{ix}' width='{iw}' height='32' fill='{c}'/><rect y='{iy}' width='32' height='{ih}' fill='{c}'/>"
    svg += "</svg>"
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="/:=' ")


COUNTRIES = [  # order of the switcher
    {"cc": "NO", "name": "Norway", "adj": "Norwegian", "tz": "Europe/Oslo", "path": "/", "dir": "docs",
     "flag": flag("#ba0c2f", "#fff", 9, 5, 13.5, 5, inner=("#00205b", 10.25, 2.5, 14.75, 2.5))},
    {"cc": "SE", "name": "Sweden", "adj": "Swedish", "tz": "Europe/Stockholm", "path": "/se/", "dir": "docs/se",
     "flag": flag("#006aa7", "#fecc02", 9, 5, 13.5, 5)},
    {"cc": "FI", "name": "Finland", "adj": "Finnish", "tz": "Europe/Helsinki", "path": "/fi/", "dir": "docs/fi",
     "flag": flag("#fff", "#002f6c", 8.5, 6, 13, 6, border=True)},
    {"cc": "DK", "name": "Denmark", "adj": "Danish", "tz": "Europe/Copenhagen", "path": "/dk/", "dir": "docs/dk",
     "flag": flag("#c8102e", "#fff", 9.5, 4, 14, 4)},
]


NORDIC_ICON = "data:image/svg+xml," + urllib.parse.quote(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='15' height='15' rx='4' fill='#ba0c2f'/><rect x='17' width='15' height='15' rx='4' fill='#006aa7'/>"
    "<rect y='17' width='15' height='15' rx='4' fill='#002f6c'/><rect x='17' y='17' width='15' height='15' rx='4' fill='#c8102e'/></svg>",
    safe="/:=' ")


def switcher(cur):
    links = (f'<a href="/nordic/"{" aria-current=\"page\"" if cur == "nordic" else ""}><img src="{NORDIC_ICON}" alt="">Nordic overview</a>'
             + "".join(
        f'<a href="{c["path"]}"{" aria-current=\"page\"" if c is cur else ""}><img src="{c["flag"]}" alt="">{c["name"]}</a>'
        for c in COUNTRIES))
    return f'    <nav class="nr-countries" aria-label="Country">{links}</nav>'


def main():
    tpl = open(os.path.join(ROOT, "site", "template.html"), encoding="utf-8").read()
    for c in COUNTRIES:
        page = tpl
        for k, v in {"{{SWITCHER}}": switcher(c), "{{FLAG}}": c["flag"], "{{PATH}}": c["path"], "{{TZ}}": c["tz"],
                     "{{ADJ}}": c["adj"], "{{NAME}}": c["name"], "{{CC}}": c["cc"], "{{cc}}": c["cc"].lower()}.items():
            page = page.replace(k, v)
        assert "{{" not in page, c["cc"]
        out = os.path.join(ROOT, c["dir"])
        os.makedirs(os.path.join(out, "data"), exist_ok=True)
        open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(page)
        print("wrote", os.path.relpath(os.path.join(out, "index.html"), ROOT))

    css = tpl[tpl.index("<style>") + 7:tpl.index("</style>")].strip("\n")
    nordic = open(os.path.join(ROOT, "site", "nordic.html"), encoding="utf-8").read()
    cj = [{"cc": c["cc"], "name": c["name"], "tz": c["tz"], "path": c["path"], "flag": c["flag"],
           "data": "../" + (c["dir"][len("docs/"):] + "/" if c["dir"] != "docs" else "") + "data/"} for c in COUNTRIES]
    for k, v in {"{{CSS}}": css, "{{SWITCHER}}": switcher("nordic"), "{{ICON}}": NORDIC_ICON,
                 "{{COUNTRIES_JSON}}": json.dumps(cj, ensure_ascii=False)}.items():
        nordic = nordic.replace(k, v)
    assert "{{" not in nordic, "nordic placeholders left"
    os.makedirs(os.path.join(ROOT, "docs", "nordic"), exist_ok=True)
    open(os.path.join(ROOT, "docs", "nordic", "index.html"), "w", encoding="utf-8").write(nordic)
    print("wrote docs/nordic/index.html")


if __name__ == "__main__":
    main()
