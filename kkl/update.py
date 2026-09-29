"""Ask GitHub whether a newer release exists. Silent on any failure: offline, timeout,
rate limit, or a private repository (GitHub answers 404 without a login)."""

import json
import re
import urllib.request

from . import __version__

REPO = "Alb7C4/mitsu-kkl"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(text):
    """'v0.1.10' -> (0, 1, 10); anything without digits -> ()."""
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def check_latest(current=__version__, timeout=4.0):
    """Return (tag, page_url) of a release newer than `current`, else None."""
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"mitsu-kkl/{current}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception:
        return None
    tag = str(data.get("tag_name", ""))
    if data.get("draft") or data.get("prerelease") or parse_version(tag) <= parse_version(current):
        return None
    return tag, data.get("html_url") or RELEASES_URL
