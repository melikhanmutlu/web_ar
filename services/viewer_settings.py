"""Default viewer presentation settings and per-model resolution."""

DEFAULT_VIEWER_SETTINGS = {
    "environment": "neutral",
    # Dark is the default stage; owners can still override it per model via
    # the Embed panel, while the viewer toolbar remembers a visitor choice.
    "background_color": "#111318",
    # Slightly above 1.0 so models (especially matte STL uploads under the
    # neutral environment) read bright by default instead of a touch dim.
    # Owners can still lower it per model via the Lighting panel.
    "exposure": 1.15,
    "shadow_intensity": 1.2,
    "shadow_softness": 0.72,
    "auto_rotate": False,
    "auto_rotate_delay": 3000,
    "camera_orbit": "30deg 70deg auto",
    "field_of_view": "24deg",
    "show_dimensions": True,
    "show_ar": True,
    "ar_placement": "floor",
    "branding": {"name": "ARVision", "logo_url": None, "primary_color": "#ffffff", "hide_powered_by": False},
    "section_presets": [],
}


def resolved_viewer_settings(model):
    settings = dict(DEFAULT_VIEWER_SETTINGS)
    stored = model.viewer_settings or {}
    settings.update({key: value for key, value in stored.items() if key != "branding"})
    settings["branding"] = {**DEFAULT_VIEWER_SETTINGS["branding"], **(stored.get("branding") or {})}
    # model-viewer's engine only implements "floor" and "wall" — "ceiling"
    # was briefly offered in the UI but silently behaved as floor (the
    # string doesn't exist anywhere in the model-viewer bundle). Coerce any
    # stored value so the rendered attribute is always a real one.
    if settings.get("ar_placement") not in ("floor", "wall"):
        settings["ar_placement"] = "floor"
    return settings
