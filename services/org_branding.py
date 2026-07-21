"""Organization-level white-label theme resolution.

A tenant theme (logo, display name, accent color, and whether to hide the
"Powered by ARVision" line) applied to the org's custom-domain gallery. Stored
as JSON on Organization.branding; None falls back to the default look with the
organization's own name.
"""

DEFAULT_ORG_BRANDING = {
    "name": None,          # None -> fall back to the organization's name
    "logo_url": None,
    "primary_color": "#6366f1",
    "hide_powered_by": False,
}


def resolved_org_branding(organization):
    """Merge an organization's stored branding over the defaults, resolving a
    blank name to the organization's own name."""
    settings = dict(DEFAULT_ORG_BRANDING)
    settings.update({
        key: value
        for key, value in (organization.branding or {}).items()
        if key in DEFAULT_ORG_BRANDING
    })
    if not settings["name"]:
        settings["name"] = organization.name
    return settings
