"""Offline unit tests for the competitor-watch diff logic (growth F3.7).

The HTTP fetch is injected, so these run with no network."""

import os
import tempfile

from scripts import competitor_watch as cw


def test_normalize_strips_tags_and_whitespace():
    html = "<div>  Pro   <b>$15</b>/mo\n\n</div>"
    assert cw.normalize(html) == "Pro $15 /mo"


def test_extract_prices_dedupes_and_orders():
    text = "Free $0 Pro $15/mo Business $60 / month Pro $15/mo"
    prices = cw.extract_prices(text)
    assert prices[0] == "$0"
    assert "$15/mo" in prices
    # de-duplicated
    assert prices.count("$15/mo") == 1


def test_diff_reports_first_snapshot():
    changes = cw.diff_snapshot({}, {"sketchfab": {"prices": ["$15/mo"]}})
    assert len(changes) == 1
    assert "first snapshot" in changes[0]


def test_diff_reports_added_and_removed_prices():
    old = {"vectary": {"prices": ["$12/mo", "$40/mo"]}}
    new = {"vectary": {"prices": ["$15/mo", "$40/mo"]}}
    changes = cw.diff_snapshot(old, new)
    assert len(changes) == 1
    assert "added $15/mo" in changes[0]
    assert "removed $12/mo" in changes[0]


def test_diff_silent_when_unchanged():
    snap = {"meshy": {"prices": ["$20/mo"]}}
    assert cw.diff_snapshot(snap, snap) == []


def test_run_persists_and_notifies_only_on_change(tmp_path):
    path = str(tmp_path / "snap.json")
    pages = {"x": "<b>$10/mo</b>"}
    fetcher = lambda url: pages["x"]
    notified = []

    first = cw.run(fetcher=fetcher, competitors={"x": "http://x"},
                   notify=notified.append, path=path)
    assert first and "first snapshot" in first[0]
    assert os.path.exists(path)

    # Same content -> no change, no notify.
    second = cw.run(fetcher=fetcher, competitors={"x": "http://x"},
                    notify=notified.append, path=path)
    assert second == []

    # Price changes -> change detected + notified.
    pages["x"] = "<b>$12/mo</b>"
    third = cw.run(fetcher=fetcher, competitors={"x": "http://x"},
                   notify=notified.append, path=path)
    assert third and "added $12/mo" in third[0]
    assert len(notified) == 2  # first snapshot + the change


def test_build_snapshot_survives_fetch_failure():
    def boom(url):
        raise RuntimeError("network down")
    snap = cw.build_snapshot(fetcher=boom, competitors={"x": "http://x"})
    assert snap == {"x": {"prices": []}}
