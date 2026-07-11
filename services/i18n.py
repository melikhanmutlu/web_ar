"""i18n foundation (Faz 5: "TR/EN dil tutarlılığı ve i18n katmanı").

Wires up Flask-Babel with a session-backed language switch (falls back to
the browser's Accept-Language header, then English). The UI is still
overwhelmingly English source strings -- only the persistent site header
and the handful of stray Turkish strings that were mixed into an
otherwise-English UI are wrapped in gettext() so far (see
translations/tr/LC_MESSAGES/messages.po). This establishes the layer;
translating the rest of the UI is a separate, much larger follow-up.
"""

from flask import request, session
from flask_babel import Babel

SUPPORTED_LANGUAGES = ("en", "tr")
DEFAULT_LANGUAGE = "en"

babel = Babel()


def get_locale():
    lang = session.get("lang")
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return request.accept_languages.best_match(SUPPORTED_LANGUAGES) or DEFAULT_LANGUAGE


def init_babel(app):
    babel.init_app(app, locale_selector=get_locale)
    # Babel's Jinja i18n extension exposes _()/gettext() to templates
    # automatically, but not get_locale() itself -- the language-switch
    # link in _site_header.html needs it to show "the other" language.
    app.jinja_env.globals['get_locale'] = get_locale
