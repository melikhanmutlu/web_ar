"""Golden tests for services/payments/paytr.py (OPS-21).

The expected token string / HMAC values below were computed independently of
the adapter (plain hmac/base64 over the literal PayTR field order) so a change
to the field order, the basket encoding or the kurus conversion is caught.
"""

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

import config
from models import Payment, User, db
from services.payments.paytr import PayTRProvider


@pytest.fixture(autouse=True)
def _paytr_config(monkeypatch):
    monkeypatch.setattr(config, "PAYTR_MERCHANT_ID", "123456")
    monkeypatch.setattr(config, "PAYTR_MERCHANT_KEY", "test-key")
    monkeypatch.setattr(config, "PAYTR_MERCHANT_SALT", "test-salt")
    monkeypatch.setattr(config, "PAYTR_TEST_MODE", "1")
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "paytr")


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


@pytest.fixture
def posted(monkeypatch):
    """Capture the POST to PayTR's get-token endpoint."""
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(SimpleNamespace(url=url, data=data, timeout=timeout))
        return _FakeResponse({"status": "success", "token": "TOKEN123"})

    monkeypatch.setattr("services.payments.paytr.requests.post", fake_post)
    return calls


def _payment(**overrides):
    base = dict(provider_ref="arvGOLDEN001", amount=Decimal("19.99"), currency="USD",
                charge_amount=None, charge_currency=None)
    base.update(overrides)
    return SimpleNamespace(**base)


def _checkout(payment, item_name="Business plan", email="buyer@example.com"):
    user = SimpleNamespace(username="buyer")
    return PayTRProvider().create_checkout(
        payment, user, ok_url="https://x/ok", fail_url="https://x/fail",
        client_ip="203.0.113.7", email=email, item_name=item_name)


def _hmac(message):
    return base64.b64encode(
        hmac.new(b"test-key", message.encode(), hashlib.sha256).digest()
    ).decode()


# --------------------------------------------------------------------------
# create_checkout
# --------------------------------------------------------------------------

GOLDEN_BASKET = "W1siQnVzaW5lc3MgcGxhbiIsICIxOS45OSIsIDFdXQ=="
GOLDEN_TOKEN = "AGZu+s606mXJiTR4Y9yGtx3aqyTSErJufdnqqIphd6Y="


def test_golden_token_string_field_order_and_hmac(posted):
    session = _checkout(_payment(currency="TRY"))
    sent = posted[0].data

    # Literal field order from PayTR's iframe-api spec; do not reorder.
    expected_token_str = (
        "123456" "203.0.113.7" "arvGOLDEN001" "buyer@example.com" "1999"
        + GOLDEN_BASKET + "0" "0" "TRY" "1" "test-salt"
    )
    assert _hmac(expected_token_str) == GOLDEN_TOKEN  # fixture self-check
    assert sent["paytr_token"] == GOLDEN_TOKEN
    assert sent["user_basket"] == GOLDEN_BASKET
    assert sent["payment_amount"] == 1999
    assert session.iframe_url == "https://www.paytr.com/odeme/guest/TOKEN123/"
    assert posted[0].url == "https://www.paytr.com/odeme/api/get-token"
    assert posted[0].timeout == 20


def test_payload_fields(posted):
    _checkout(_payment(currency="TRY"))
    sent = posted[0].data
    assert sent["merchant_id"] == "123456"
    assert sent["merchant_oid"] == "arvGOLDEN001"
    assert sent["user_ip"] == "203.0.113.7"
    assert sent["email"] == "buyer@example.com"
    assert sent["currency"] == "TRY"
    assert sent["test_mode"] == "1" and sent["debug_on"] == "1"
    assert sent["no_installment"] == "0" and sent["max_installment"] == "0"
    assert sent["merchant_ok_url"] == "https://x/ok"
    assert sent["merchant_fail_url"] == "https://x/fail"
    assert sent["user_name"] == "buyer"


def test_test_mode_off_changes_flag_and_token(posted, monkeypatch):
    monkeypatch.setattr(config, "PAYTR_TEST_MODE", "0")
    _checkout(_payment(currency="TRY"))
    sent = posted[0].data
    assert sent["test_mode"] == "0" and sent["debug_on"] == "0"
    assert sent["paytr_token"] != GOLDEN_TOKEN
    token_str = ("123456203.0.113.7arvGOLDEN001buyer@example.com1999"
                 + GOLDEN_BASKET + "00TRY0test-salt")
    assert sent["paytr_token"] == _hmac(token_str)


@pytest.mark.parametrize("amount,kurus", [
    ("19.995", 2000),   # half-kurus rounds up
    ("10.005", 1001),
    ("19.99", 1999),
    ("0.29", 29),       # 0.29 * 100 == 28.999999999999996 in floating point
    ("0.01", 1),
    ("1234.50", 123450),
    ("99", 9900),
])
def test_kurus_rounding(posted, amount, kurus):
    _checkout(_payment(amount=Decimal(amount), currency="TRY"))
    sent = posted[0].data
    assert sent["payment_amount"] == kurus
    assert isinstance(sent["payment_amount"], int)
    # The signed amount is the same integer that is sent.
    basket = sent["user_basket"]
    token_str = ("123456203.0.113.7arvGOLDEN001buyer@example.com"
                 f"{kurus}{basket}00TRY1test-salt")
    assert sent["paytr_token"] == _hmac(token_str)


def test_basket_encoding_is_base64_json_of_name_price_qty(posted):
    _checkout(_payment(amount=Decimal("19.99"), currency="TRY"),
              item_name="Pro çok güzel \"plan\"")
    raw = base64.b64decode(posted[0].data["user_basket"])
    assert json.loads(raw) == [["Pro çok güzel \"plan\"", "19.99", 1]]


def test_charge_amount_and_currency_override_list_price(posted):
    payment = _payment(amount=Decimal("19.99"), currency="USD",
                       charge_amount=Decimal("649.50"), charge_currency="TRY")
    _checkout(payment)
    sent = posted[0].data
    assert sent["payment_amount"] == 64950
    assert sent["currency"] == "TRY"
    assert json.loads(base64.b64decode(sent["user_basket"]))[0][1] == "649.50"
    assert "1999" not in sent["user_basket"]


def test_list_price_used_when_no_charge_amount(posted):
    _checkout(_payment(amount=Decimal("99.00"), currency="TRY"))
    assert posted[0].data["payment_amount"] == 9900
    assert posted[0].data["currency"] == "TRY"


def test_zero_charge_amount_is_not_treated_as_missing(posted):
    # `is not None`, not truthiness: an explicit 0.00 charge must not fall back
    # to the (possibly larger) list price.
    _checkout(_payment(amount=Decimal("50.00"), currency="TRY",
                       charge_amount=Decimal("0.00"), charge_currency="TRY"))
    assert posted[0].data["payment_amount"] == 0


def test_username_is_truncated_and_defaulted(posted):
    provider = PayTRProvider()
    provider.create_checkout(_payment(currency="TRY"), SimpleNamespace(username="u" * 100),
                             ok_url="o", fail_url="f", client_ip="1.1.1.1",
                             email="a@b.c", item_name="x")
    assert len(posted[0].data["user_name"]) == 60
    provider.create_checkout(_payment(currency="TRY"), SimpleNamespace(username=None),
                             ok_url="o", fail_url="f", client_ip="1.1.1.1",
                             email="a@b.c", item_name="x")
    assert posted[1].data["user_name"] == "customer"


def test_unconfigured_provider_refuses_checkout(posted, monkeypatch):
    monkeypatch.setattr(config, "PAYTR_MERCHANT_SALT", "")
    with pytest.raises(RuntimeError, match="not configured"):
        _checkout(_payment())
    assert posted == []


def test_gateway_rejection_and_transport_errors_raise_runtime_error(monkeypatch):
    import requests

    monkeypatch.setattr("services.payments.paytr.requests.post",
                        lambda *a, **k: _FakeResponse({"status": "failed", "reason": "bad ip"}))
    with pytest.raises(RuntimeError, match="bad ip"):
        _checkout(_payment())

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("services.payments.paytr.requests.post", boom)
    with pytest.raises(RuntimeError, match="token request failed"):
        _checkout(_payment())


# --------------------------------------------------------------------------
# verify_callback
# --------------------------------------------------------------------------

GOLDEN_CALLBACK_HASH = "ip7zRRLke575767PnYKepUGi/BEN9fuyRy7jTFQNGSc="


def _form(**overrides):
    form = {"merchant_oid": "arvGOLDEN001", "status": "success", "total_amount": "1999",
            "hash": GOLDEN_CALLBACK_HASH}
    form.update(overrides)
    return form


def test_golden_callback_hash_is_accepted():
    assert _hmac("arvGOLDEN001" "test-salt" "success" "1999") == GOLDEN_CALLBACK_HASH
    result = PayTRProvider().verify_callback(_form())
    assert result.valid and result.paid
    assert result.reference == "arvGOLDEN001"
    assert result.amount == 1999 and result.raw_status == "success"


@pytest.mark.parametrize("tamper", [
    {"total_amount": "1"},            # pay less, keep the hash
    {"total_amount": "199900"},
    {"status": "failed"},
    {"merchant_oid": "arvOTHER00001"},  # replay hash on another order
    {"hash": ""},
    {"hash": GOLDEN_CALLBACK_HASH[:-4] + "AAAA"},
])
def test_tampered_callback_is_rejected(tamper):
    result = PayTRProvider().verify_callback(_form(**tamper))
    assert result.valid is False
    assert result.paid is False


def test_missing_fields_are_rejected():
    provider = PayTRProvider()
    assert provider.verify_callback({}).valid is False
    form = _form()
    del form["hash"]
    assert provider.verify_callback(form).valid is False


def test_failed_status_with_valid_hash_is_valid_but_not_paid():
    form = _form(status="failed", hash=_hmac("arvGOLDEN001test-saltfailed1999"))
    result = PayTRProvider().verify_callback(form)
    assert result.valid and not result.paid and result.raw_status == "failed"


# --------------------------------------------------------------------------
# callback endpoint: a tampered callback never grants a plan
# --------------------------------------------------------------------------

def _pending(oid="arvGOLDEN001"):
    user = User(username="payer", email="payer@example.com", plan="free")
    user.set_password("pw")
    db.session.add(user)
    db.session.commit()
    db.session.add(Payment(user_id=user.id, plan="business", amount=19.99, currency="TRY",
                           status="pending", provider="paytr", provider_ref=oid))
    db.session.commit()
    return user


@pytest.mark.parametrize("tamper", [{"total_amount": "1"}, {"status": "failed"}, {"hash": "x"}])
def test_endpoint_rejects_tampered_callback_and_changes_nothing(client, tamper):
    user = _pending()
    resp = client.post("/billing/paytr/callback", data=_form(**tamper))
    assert resp.status_code == 400
    assert resp.get_data() != b"OK"
    assert db.session.get(User, user.id).plan == "free"
    assert Payment.query.filter_by(provider_ref="arvGOLDEN001").one().status == "pending"


def test_endpoint_accepts_golden_callback_once(client):
    user = _pending()
    for _ in range(2):  # PayTR retries until it sees OK; replay must be harmless
        resp = client.post("/billing/paytr/callback", data=_form())
        assert resp.status_code == 200 and resp.get_data() == b"OK"
    db.session.expire_all()
    assert db.session.get(User, user.id).plan == "business"
    payments = Payment.query.filter_by(provider_ref="arvGOLDEN001").all()
    assert len(payments) == 1 and payments[0].status == "paid"
