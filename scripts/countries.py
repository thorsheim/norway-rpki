"""The countries on the dashboard: the single list every script reads.

To add a country: add a line here (ISO code, name, name inside a sentence if it needs "the",
adjective, IANA time zone), add its flag in make_pages.py, run make_pages.py, and start the
workflow. Norway lives at the site root; every other country at /<cc>/.
"""
COUNTRIES = {  # order of the country switcher
    "NO": {"name": "Norway", "adj": "Norwegian", "tz": "Europe/Oslo"},
    "SE": {"name": "Sweden", "adj": "Swedish", "tz": "Europe/Stockholm"},
    "FI": {"name": "Finland", "adj": "Finnish", "tz": "Europe/Helsinki"},
    "DK": {"name": "Denmark", "adj": "Danish", "tz": "Europe/Copenhagen"},
    "IS": {"name": "Iceland", "adj": "Icelandic", "tz": "Atlantic/Reykjavik"},
    "EE": {"name": "Estonia", "adj": "Estonian", "tz": "Europe/Tallinn"},
    "LV": {"name": "Latvia", "adj": "Latvian", "tz": "Europe/Riga"},
    "LT": {"name": "Lithuania", "adj": "Lithuanian", "tz": "Europe/Vilnius"},
    "CZ": {"name": "Czech Republic", "in": "the Czech Republic", "adj": "Czech", "tz": "Europe/Prague"},
}


def path(cc):
    """URL path of the country's page."""
    return "/" if cc == "NO" else f"/{cc.lower()}/"


def data_dir(cc):
    """Data folder, relative to the repository root."""
    return "docs/data" if cc == "NO" else f"docs/{cc.lower()}/data"
