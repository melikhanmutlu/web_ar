"""Default viewer presentation settings and per-model resolution."""

DEFAULT_VIEWER_SETTINGS = {
    "environment": "neutral",
    "background_color": "#1a1a2e",
    "exposure": 0.96,
    "shadow_intensity": 1.2,
    "auto_rotate": False,
    "auto_rotate_delay": 3000,
    "camera_orbit": "30deg 70deg auto",
    "field_of_view": "24deg",
    "show_dimensions": True,
    "show_ar": True,
    "branding": {"name": "ARVision", "logo_url": None, "primary_color": "#ffffff", "hide_powered_by": False},
    "section_presets": [],
}


def resolved_viewer_settings(model):
    settings = dict(DEFAULT_VIEWER_SETTINGS)
    stored = model.viewer_settings or {}
    settings.update({key: value for key, value in stored.items() if key != "branding"})
    settings["branding"] = {**DEFAULT_VIEWER_SETTINGS["branding"], **(stored.get("branding") or {})}
    return settings
