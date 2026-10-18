"""GitHub release update discovery for GhostRunner."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

REPOSITORY = "Xiamo-vip/Fuckrun"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"


def version_tuple(value: str) -> tuple[int, ...]:
    """Return a numeric tuple suitable for the project's release tags."""
    parts = re.findall(r"\d+", str(value).lstrip("vV"))
    return tuple(int(part) for part in parts) if parts else (0,)


def is_newer(candidate: str, current: str) -> bool:
    left, right = version_tuple(candidate), version_tuple(current)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def latest_release(current: str, timeout: int = 8, fetch=None):
    """Return a normalized newer release or ``None``.

    The request deliberately bypasses the Windows system proxy so an interrupted
    capture session cannot make update discovery look like a network outage.
    """
    if fetch is None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def fetch(request):
            with opener.open(request, timeout=timeout) as response:
                return response.read(2 * 1024 * 1024)

    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"GhostRunner/{current}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        payload = json.loads(fetch(request).decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    url = str(payload.get("html_url") or "").strip()
    if not tag or not url or not url.startswith("https://github.com/") or not is_newer(tag, current):
        return None
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "url": url,
        "name": str(payload.get("name") or tag),
        "notes": str(payload.get("body") or "").strip()[:4000],
    }
