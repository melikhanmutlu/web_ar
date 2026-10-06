"""Pricing page: indexable meta, effective limits, trial + consistent prices."""
import re

import pytest

import site_settings
from services.plans import format_mb, format_money


def test_pricing_is_indexable_with_own_meta(client):
    html = client.get("/pricing").get_data(as_text=True)
    assert 'name="robots" content="index, follow"' in html
    assert 'property="og:title" content="Pricing' in html


def test_format_helpers():
    assert format_mb(500) == "500 MB"
    assert format_mb(1024) == "1 GB"
    assert format_mb(1536) == "1.5 GB"
    assert format_mb(0) == "—" and format_mb(None) == "—"
    assert format_money(19) == "$19"
    assert format_money(9, "USD") == "$9"
    assert format_money(19.5, "EUR") == "19.50 EUR"


@pytest.fixture
def restore_settings():
    yield
    for key in ("storage_quota_mb", "ai_monthly_limit", "free_ai_trial_count"):
        site_settings.set_setting(key, None)


def test_pricing_shows_effective_free_limits(client, restore_settings):
    site_settings.set_setting("storage_quota_mb", 500)
    site_settings.set_setting("ai_monthly_limit", 0)
    site_settings.set_setting("free_ai_trial_count", 0)
    html = client.get("/pricing").get_data(as_text=True)
    assert "500 MB storage" in html
    assert not re.search(r"(?<!\d)0 GB", html)
    # Zero AI is not presented as a checked feature.
    assert not re.search(r"(?<!\d)0 AI generations", html)
    assert "AI generation not included" in html

    site_settings.set_setting("ai_monthly_limit", 7)
    html = client.get("/pricing").get_data(as_text=True)
    assert "7 AI generations / month" in html


def test_pricing_business_trial_and_prices(client):
    html = client.get("/pricing").get_data(as_text=True)
    assert "14-day free trial, no card required" in html
    assert "/register?next=/billing" in html
    assert "/login?next=/billing" in html  # anonymous "Choose plan"
    assert "$19<small>/mo" in html and "$99<small>/mo" in html
    assert "TRY" not in html
    assert "mailto:" not in html
    assert re.search(r"/contact-sales\?reason=credits", html)
    assert "$9<" in html


def test_billing_page_has_no_try_and_uses_dollar_prices(client):
    client.post("/register", data={"username": "bill_u", "email": "bill_u@example.com",
                                   "password": "Passw0rd!x", "confirm_password": "Passw0rd!x"})
    client.post("/login", data={"username": "bill_u", "password": "Passw0rd!x"})
    html = client.get("/billing").get_data(as_text=True)
    assert "TRY" not in html
    assert "$19<small>/mo" in html
    assert "<b>$9</b>" in html


def test_marketing_copy_does_not_overpromise_ai(client):
    for path in ("/", "/vs/sketchfab", "/vs/meshy"):
        html = client.get(path).get_data(as_text=True)
        assert "Built-in AI" not in html, path
        assert "free trial generations" in html, path
