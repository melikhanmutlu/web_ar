"""UIA-12: the anonymous uploader's edit token must not live in the address bar
or QR/copy links; the session keeps edit access and a banner offers the
private edit link explicitly."""

from werkzeug.security import generate_password_hash

from models import UserModel, db
from tests.test_viewer_page import make_sized_box_model

TOKEN = "anon-edit-capability-token"


def _anon_model():
    model_id, _ = make_sized_box_model(0.5)
    model = db.session.get(UserModel, model_id)
    model.edit_token_hash = generate_password_hash(TOKEN)
    db.session.commit()
    return model_id


def test_viewer_strips_token_from_url_and_keeps_session_edit_access(client):
    model_id = _anon_model()
    first = client.get(f"/view/{model_id}?edit_token={TOKEN}")
    assert first.status_code == 200
    html = first.get_data(as_text=True)
    # Client strips the param and QR/copy use the canonical URL.
    assert "history.replaceState" in html and "canonicalViewerUrl" in html
    # Banner with the explicit save/claim actions.
    assert 'id="anonOwnerBanner"' in html
    assert "Save your edit link" in html
    assert f"/register?next=/view/{model_id}" in html.replace("%2F", "/")

    # Same browser session, no token anywhere: still the anonymous owner.
    again = client.get(f"/view/{model_id}")
    assert 'id="anonOwnerBanner"' in again.get_data(as_text=True)
    resp = client.patch(f"/api/models/{model_id}/viewer-settings", json={"show_ar": False})
    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_other_browser_gets_no_banner_and_cannot_edit(client):
    model_id = _anon_model()
    other = client.application.test_client()
    html = other.get(f"/view/{model_id}").get_data(as_text=True)
    assert 'id="anonOwnerBanner"' not in html
    assert TOKEN not in html
    assert other.patch(f"/api/models/{model_id}/viewer-settings", json={"show_ar": False}).status_code == 403


def test_qr_code_uses_canonical_url():
    from pathlib import Path
    js = Path("static/js/viewer/ar-slicer-layers.js").read_text()
    assert "window.location.href" not in js
    assert js.count("window.canonicalViewerUrl()") == 2
