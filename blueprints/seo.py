"""robots.txt and a hand-rolled XML sitemap."""

from flask import Blueprint, Response, url_for

from config import SITE_URL

seo_bp = Blueprint("seo", __name__)

# Endpoints listed in the sitemap. Segment landing pages are added below.
SITEMAP_STATIC_ENDPOINTS = [
    "main.index", "main.features", "main.pricing", "main.developers",
    "main.security", "main.contact_sales",
]


@seo_bp.route("/robots.txt")
def robots_txt():
    """Hand-rolled robots.txt — no dependency needed for a few lines.
    Deliberately has no Disallow for HTML pages that use meta-tag noindex
    (/view, /embed, /vr, /login, ...): Googlebot must be able to crawl a
    page to see its noindex tag, and blocking the crawl instead can leave a
    bare URL indexed with no snippet if it has external backlinks. Only
    non-HTML/closed areas that never rely on that mechanism are disallowed.
    """
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /api/",
        "",
        f"Sitemap: {SITE_URL}{url_for('seo.sitemap_xml')}",
    ]
    return Response(response="\n".join(lines) + "\n", status=200, mimetype="text/plain")


@seo_bp.route("/sitemap.xml")
def sitemap_xml():
    """Hand-rolled XML sitemap (no flask-sitemap dependency needed for a
    handful of URLs). Lists SITEMAP_STATIC_ENDPOINTS only."""
    from xml.sax.saxutils import escape as xml_escape

    from blueprints.main import SEGMENT_SLUGS

    locs = [SITE_URL + url_for(endpoint) for endpoint in SITEMAP_STATIC_ENDPOINTS]
    locs += [SITE_URL + url_for("main.segment_landing", segment=slug) for slug in SEGMENT_SLUGS]
    entries = [
        f"  <url>\n    <loc>{xml_escape(loc)}</loc>\n  </url>" for loc in locs
    ]
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    return Response(response=body, status=200, mimetype="application/xml")
