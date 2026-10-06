"""Branded 404/403/500 pages, JSON for API callers, no soft-404, and the
maintenance Retry-After header (UIP-05, UIA-14, UIP-27)."""
import uuid
from unittest.mock import patch

from flask import abort

from app import app

HTML = {'Accept': 'text/html,application/xhtml+xml'}


def test_404_is_branded_html_with_exit_links(client):
    r = client.get('/this-page-does-not-exist', headers=HTML)
    assert r.status_code == 404
    html = r.get_data(as_text=True)
    assert 'Page not found' in html
    for href in ('href="/"', 'href="/studio"', 'href="/pricing"'):
        assert href in html


def test_404_returns_json_for_api_and_json_accept(client):
    r = client.get('/api/v1/definitely-missing', headers=HTML)
    assert r.status_code == 404 and r.is_json
    r = client.get('/nope', headers={'Accept': 'application/json'})
    assert r.status_code == 404 and r.get_json()['error']
    r = client.get('/nope', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert r.status_code == 404 and r.is_json


def test_missing_model_is_a_real_404_not_a_redirect(client):
    r = client.get(f'/view/{uuid.uuid4()}', headers=HTML)
    assert r.status_code == 404
    assert 'Page not found' in r.get_data(as_text=True)


def test_403_page_suggests_sign_in_for_anonymous(client):
    def _t403():
        abort(403)
    with patch.dict(app.view_functions, {'main.pricing': _t403}):
        r = client.get('/pricing', headers=HTML)
        html = r.get_data(as_text=True)
        assert r.status_code == 403
        assert 'Access denied' in html and 'Sign in' in html
        assert 'ask the owner for a share link' in html
        assert 'next=/pricing' in html
        assert client.get('/pricing', headers={'Accept': 'application/json'}).is_json


def test_500_is_branded_html_for_browsers_and_never_leaks(client):
    def _t500():
        raise RuntimeError('secret-db-password-hunter2')
    prev = app.config.get('PROPAGATE_EXCEPTIONS'), app.config.get('TESTING')
    app.config['PROPAGATE_EXCEPTIONS'] = False
    app.config['TESTING'] = False
    try:
        with patch.dict(app.view_functions, {'main.pricing': _t500}):
            html_resp = client.get('/pricing', headers=HTML)
            json_resp = client.get('/pricing', headers={'Accept': 'application/json'})
            bare = client.get('/pricing')  # non-browser */*: keep the old JSON contract
    finally:
        app.config['PROPAGATE_EXCEPTIONS'], app.config['TESTING'] = prev
    assert html_resp.status_code == 500
    assert 'Something went wrong' in html_resp.get_data(as_text=True)
    assert 'hunter2' not in html_resp.get_data(as_text=True)
    assert json_resp.status_code == 500 and json_resp.is_json
    assert 'hunter2' not in json_resp.get_data(as_text=True)
    assert bare.status_code == 500 and bare.is_json


def test_maintenance_mode_503_has_retry_after(client):
    with patch('app.setting_bool', side_effect=lambda k, d=False: True if k == 'maintenance_mode' else d):
        r = client.get('/pricing')
    assert r.status_code == 503
    assert r.headers.get('Retry-After') == '600'
