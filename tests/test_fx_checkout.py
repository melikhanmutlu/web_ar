"""PayTR checkout: USD list price stays what the customer sees, the TRY charge
uses the day's TCMB rate, and no rate means no checkout."""

import pytest

import config
from models import Payment, User, db
from services import fx
from services.payments.paytr import PayTRProvider

TCMB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Tarih_Date Tarih="06.10.2026" Date="10/06/2026">
  <Currency CrossOrder="0" Kod="USD" CurrencyCode="USD">
    <Unit>1</Unit><Isim>ABD DOLARI</Isim><CurrencyName>US DOLLAR</CurrencyName>
    <ForexBuying>41.1000</ForexBuying><ForexSelling>41.2500</ForexSelling>
  </Currency>
  <Currency CrossOrder="1" Kod="JPY" CurrencyCode="JPY">
    <Unit>100</Unit><ForexBuying>27.0</ForexBuying><ForexSelling>27.5000</ForexSelling>
  </Currency>
</Tarih_Date>"""


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    # site_settings caches values in-process; a rate cached by one test must
    # not leak into the next one's empty database.
    from site_settings import invalidate_cache
    invalidate_cache()
    yield
    invalidate_cache()


class _Resp:
    def __init__(self, text=None, payload=None):
        self.text, self._payload = text, payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_tcmb_xml_parsing():
    assert fx._rate_from_tcmb_xml(TCMB_XML, "USD") == 41.25
    assert fx._rate_from_tcmb_xml(TCMB_XML, "JPY") == 0.275
    assert fx._rate_from_tcmb_xml(TCMB_XML, "EUR") is None


def test_rate_prefers_tcmb_and_caches(client, monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return _Resp(text=TCMB_XML)

    monkeypatch.setattr(fx.requests, "get", fake_get)
    assert fx.get_try_rate("USD") == 41.25
    assert fx.get_try_rate("USD") == 41.25
    assert calls == [fx._TCMB_URL]


def test_rate_falls_back_to_backup_source(client, monkeypatch):
    def fake_get(url, timeout):
        if "tcmb" in url:
            raise fx.requests.ConnectionError("down")
        return _Resp(payload={"rates": {"TRY": 40.5}})

    monkeypatch.setattr(fx.requests, "get", fake_get)
    assert fx.get_try_rate("USD") == 40.5


def test_no_rate_anywhere_raises_instead_of_guessing(client, monkeypatch):
    def down(url, timeout):
        raise fx.requests.ConnectionError("down")

    monkeypatch.setattr(fx.requests, "get", down)
    with pytest.raises(fx.FxUnavailable):
        fx.get_try_rate("USD")


def _paytr_user(client, monkeypatch):
    monkeypatch.setattr(config, "PAYTR_MERCHANT_ID", "123456")
    monkeypatch.setattr(config, "PAYTR_MERCHANT_KEY", "test-key")
    monkeypatch.setattr(config, "PAYTR_MERCHANT_SALT", "test-salt")
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "paytr")
    user = User(username="fxbuyer", email="fxbuyer@example.com")
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "fxbuyer", "password": "password"})
    return user


def test_checkout_keeps_usd_price_and_charges_try(client, monkeypatch):
    user = _paytr_user(client, monkeypatch)
    monkeypatch.setattr(fx, "get_try_rate", lambda code="USD": 41.25)
    sent = {}

    def fake_post(url, data, timeout):
        sent.update(data)
        return _Resp(payload={"status": "success", "token": "tok"})

    monkeypatch.setattr("services.payments.paytr.requests.post", fake_post)

    resp = client.post("/billing/checkout/pro")

    assert resp.status_code == 200
    payment = Payment.query.filter_by(user_id=user.id).one()
    assert (float(payment.amount), payment.currency) == (19.0, "USD")
    assert (float(payment.charge_amount), payment.charge_currency) == (783.75, "TRY")
    assert float(payment.fx_rate) == 41.25
    assert payment.method == "paytr"
    assert sent["payment_amount"] == 78375 and sent["currency"] == "TRY"


def test_checkout_refused_without_rate(client, monkeypatch):
    user = _paytr_user(client, monkeypatch)

    def no_rate(code="USD"):
        raise fx.FxUnavailable("down")

    monkeypatch.setattr(fx, "get_try_rate", no_rate)
    monkeypatch.setattr(PayTRProvider, "create_checkout",
                        lambda *a, **k: pytest.fail("must not reach PayTR"))

    resp = client.post("/billing/checkout/pro", follow_redirects=True)

    assert b"briefly unavailable" in resp.data
    assert Payment.query.filter_by(user_id=user.id).count() == 0
