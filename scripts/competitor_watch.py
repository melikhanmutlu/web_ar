"""Competitor pricing/feature watch (growth F3.7).

Periodically snapshots competitor pricing pages, normalizes the visible text,
and diffs against the previous snapshot — emailing admins when something
changes. Automates the COMPETITOR-REPORT "monitoring plan".

The fetch step is egress-dependent and therefore injectable: the pure
normalize/diff/price-extraction logic below is unit-tested offline, and
`run()` accepts a `fetcher` so a test (or a restricted network) can drive it
without real HTTP.

Storage: snapshots live in a JSON file (WEB_AR_DATA_DIR or the repo root) so
the script is self-contained and needs no DB migration.
"""

import json
import os
import re
import sys

# Competitor pricing pages to watch. Kept here (not in the DB) because this is
# an ops script, not a product feature.
COMPETITORS = {
    "sketchfab": "https://sketchfab.com/plans",
    "vectary": "https://www.vectary.com/pricing/",
    "meshy": "https://www.meshy.ai/pricing",
}

_PRICE_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?(?:\s?/\s?(?:mo|month|yr|year))?", re.I)
_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def normalize(html):
    """Strip tags and collapse whitespace so cosmetic markup churn doesn't read
    as a pricing change."""
    text = _TAG_RE.sub(" ", html or "")
    text = text.replace("&nbsp;", " ")
    return _WS_RE.sub(" ", text).strip()


def extract_prices(text):
    """Ordered, de-duplicated list of price tokens found in the text."""
    seen, out = set(), []
    for match in _PRICE_RE.findall(text or ""):
        token = _WS_RE.sub("", match)
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def diff_snapshot(old, new):
    """Compare two {name: {"prices": [...]}} snapshots. Returns a list of
    human-readable change strings (empty when nothing changed)."""
    changes = []
    for name, new_entry in new.items():
        # A failed fetch is not a pricing change — never alert on it.
        if new_entry.get("fetch_failed"):
            continue
        old_entry = (old or {}).get(name)
        new_prices = new_entry.get("prices", [])
        if old_entry is None or old_entry.get("fetch_failed"):
            changes.append(f"{name}: first snapshot ({', '.join(new_prices) or 'no prices found'})")
            continue
        old_prices = old_entry.get("prices", [])
        added = [p for p in new_prices if p not in old_prices]
        removed = [p for p in old_prices if p not in new_prices]
        # Only report a real add/remove — a pure reorder is not a change.
        if added or removed:
            parts = []
            if added:
                parts.append("added " + ", ".join(added))
            if removed:
                parts.append("removed " + ", ".join(removed))
            changes.append(f"{name}: {'; '.join(parts)}")
    return changes


def _snapshot_path():
    base = os.environ.get("WEB_AR_DATA_DIR") or os.path.dirname(os.path.dirname(__file__))
    return os.path.join(base, "competitor_snapshot.json")


def _load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)


def _http_fetch(url):
    import requests
    resp = requests.get(url, timeout=20, headers={"User-Agent": "ARVision-CompetitorWatch/1.0"})
    resp.raise_for_status()
    return resp.text


def build_snapshot(fetcher=_http_fetch, competitors=None, previous=None):
    """Fetch every competitor page and reduce it to {name: {"prices": [...]}}.
    On a fetch failure, carry forward the previous entry (so a transient blip
    doesn't read as "all prices removed" now and "all prices added back" next
    run); if there's no previous entry, mark it fetch_failed so the diff skips
    it instead of alerting."""
    previous = previous or {}
    snapshot = {}
    for name, url in (competitors or COMPETITORS).items():
        try:
            snapshot[name] = {"prices": extract_prices(normalize(fetcher(url)))}
        except Exception:
            prior = previous.get(name)
            snapshot[name] = dict(prior) if prior else {"prices": [], "fetch_failed": True}
    return snapshot


def run(fetcher=_http_fetch, competitors=None, notify=None, path=None):
    """One watch pass: build a new snapshot, diff against the stored one,
    persist, and hand any changes to `notify`. Returns the change list."""
    path = path or _snapshot_path()
    old = _load(path)
    new = build_snapshot(fetcher, competitors, previous=old)
    changes = diff_snapshot(old, new)
    _save(path, new)
    if changes and notify:
        notify(changes)
    return changes


if __name__ == "__main__":
    detected = run()
    if detected:
        print("Competitor changes detected:")
        for line in detected:
            print(" -", line)
        sys.exit(0)
    print("No competitor changes.")
