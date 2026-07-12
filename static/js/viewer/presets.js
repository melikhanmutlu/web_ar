// Material + lighting presets and manual lighting controls for the Tools panel.
//
// Material presets drive the EXISTING material inputs (color / metalness /
// roughness / opacity) and dispatch their 'input'+'change' events, so the
// material-editor's live preview, dirty tracking and undo/redo all run exactly
// as if the user had moved the sliders themselves — no separate apply path.
//
// Lighting presets + manual sliders write model-viewer's presentation
// attributes (exposure / shadow-intensity / shadow-softness / environment)
// directly for live preview, and owners can persist them via the existing
// viewer-settings API.
document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.getElementById('modelViewer');
    if (!modelViewer) return;

    const CAN_EDIT = !!(window.VIEWER_CONFIG && window.VIEWER_CONFIG.canEdit);
    const modelId = window.VIEWER_CONFIG && window.VIEWER_CONFIG.modelId;

    // ── Material presets ──────────────────────────────────────────────────
    // Values that read as the named real-world material. Presets that describe
    // a finish (plastic/glass/…) leave the base color alone so they compose
    // with whatever color the user already chose; metal presets set a color
    // because the color IS the material.
    const MATERIAL_PRESETS = {
        gold:    { color: '#E6B800', metalness: 1.0, roughness: 0.28, opacity: 1 },
        chrome:  { color: '#E8E8E8', metalness: 1.0, roughness: 0.05, opacity: 1 },
        copper:  { color: '#B87333', metalness: 1.0, roughness: 0.32, opacity: 1 },
        plastic: { metalness: 0.0, roughness: 0.45, opacity: 1 },
        rubber:  { metalness: 0.0, roughness: 0.95, opacity: 1 },
        glass:   { metalness: 0.0, roughness: 0.04, opacity: 0.28 },
        ceramic: { metalness: 0.0, roughness: 0.25, opacity: 1 },
        matte:   { metalness: 0.0, roughness: 1.0, opacity: 1 },
    };

    function setSliderValue(id, value) {
        const slider = document.getElementById(id);
        if (!slider) return;
        slider.value = value;
        // 'input' drives live preview + the value readout; 'change' drives the
        // undo/redo history snapshot.
        slider.dispatchEvent(new Event('input', { bubbles: true }));
        slider.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function applyMaterialPreset(name) {
        const preset = MATERIAL_PRESETS[name];
        if (!preset) return;
        if (preset.color) {
            const hexInput = document.getElementById('materialColorHex');
            const colorInput = document.getElementById('materialColor');
            if (colorInput) colorInput.value = preset.color;
            if (hexInput) {
                hexInput.value = preset.color.toUpperCase();
                hexInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }
        setSliderValue('metalnessSlider', preset.metalness);
        setSliderValue('roughnessSlider', preset.roughness);
        setSliderValue('opacitySlider', preset.opacity);
    }

    document.querySelectorAll('.material-preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            applyMaterialPreset(btn.dataset.preset);
            document.querySelectorAll('.material-preset-btn').forEach(b => b.classList.remove('is-active'));
            btn.classList.add('is-active');
        });
    });
    // A manual material tweak means the model no longer matches any preset.
    ['metalnessSlider', 'roughnessSlider', 'opacitySlider', 'materialColorHex', 'materialColor'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', (e) => {
            if (e.isTrusted) {
                document.querySelectorAll('.material-preset-btn.is-active').forEach(b => b.classList.remove('is-active'));
            }
        });
    });

    // ── Lighting ──────────────────────────────────────────────────────────
    const LIGHTING_PRESETS = {
        studio:   { exposure: 1.0, shadow: 1.2, softness: 0.70, environment: 'neutral' },
        soft:     { exposure: 1.1, shadow: 0.6, softness: 1.00, environment: 'neutral' },
        dramatic: { exposure: 0.7, shadow: 2.2, softness: 0.20, environment: 'neutral' },
        bright:   { exposure: 1.6, shadow: 0.8, softness: 0.80, environment: 'neutral' },
        flat:     { exposure: 1.0, shadow: 0.0, softness: 1.00, environment: 'legacy' },
        dim:      { exposure: 0.5, shadow: 1.5, softness: 0.50, environment: 'neutral' },
    };

    const exposureSlider = document.getElementById('exposureSlider');
    const exposureValue = document.getElementById('exposureValue');
    const shadowIntensitySlider = document.getElementById('shadowIntensitySlider');
    const shadowIntensityValue = document.getElementById('shadowIntensityValue');
    const shadowSoftnessSlider = document.getElementById('shadowSoftnessSlider');
    const shadowSoftnessValue = document.getElementById('shadowSoftnessValue');
    const environmentSelect = document.getElementById('environmentSelect');
    const shadowToggle = document.getElementById('shadowToggle');
    // Remembers the last non-zero shadow so toggling the shadow back ON restores
    // the user's chosen intensity instead of a hardcoded default.
    let _lastShadow = shadowIntensitySlider ? (parseFloat(shadowIntensitySlider.value) || 1.2) : 1.2;

    function syncLightingReadouts() {
        if (exposureSlider && exposureValue) exposureValue.textContent = parseFloat(exposureSlider.value).toFixed(2);
        if (shadowIntensitySlider && shadowIntensityValue) shadowIntensityValue.textContent = parseFloat(shadowIntensitySlider.value).toFixed(2);
        if (shadowSoftnessSlider && shadowSoftnessValue) shadowSoftnessValue.textContent = parseFloat(shadowSoftnessSlider.value).toFixed(2);
        // The "Ground shadow" checkbox reflects the slider: any shadow > 0 = on.
        if (shadowToggle && shadowIntensitySlider) {
            const v = parseFloat(shadowIntensitySlider.value);
            shadowToggle.checked = v > 0;
            if (v > 0) _lastShadow = v;
        }
    }
    syncLightingReadouts();

    // On/off convenience toggle: off drops shadow intensity to 0, on restores it.
    shadowToggle?.addEventListener('change', () => {
        if (!shadowIntensitySlider) return;
        if (shadowToggle.checked) {
            shadowIntensitySlider.value = _lastShadow > 0 ? _lastShadow : 1.2;
        } else {
            const v = parseFloat(shadowIntensitySlider.value);
            if (v > 0) _lastShadow = v;
            shadowIntensitySlider.value = 0;
        }
        applyShadowIntensity();
        document.querySelectorAll('.lighting-preset-btn.is-active').forEach(b => b.classList.remove('is-active'));
    });

    function applyExposure() {
        if (exposureSlider) modelViewer.exposure = parseFloat(exposureSlider.value);
        syncLightingReadouts();
    }
    function applyShadowIntensity() {
        if (shadowIntensitySlider) modelViewer.shadowIntensity = parseFloat(shadowIntensitySlider.value);
        syncLightingReadouts();
    }
    function applyShadowSoftness() {
        if (shadowSoftnessSlider) modelViewer.shadowSoftness = parseFloat(shadowSoftnessSlider.value);
        syncLightingReadouts();
    }
    function applyEnvironment() {
        if (environmentSelect) modelViewer.environmentImage = environmentSelect.value;
    }

    exposureSlider?.addEventListener('input', applyExposure);
    shadowIntensitySlider?.addEventListener('input', applyShadowIntensity);
    shadowSoftnessSlider?.addEventListener('input', applyShadowSoftness);
    environmentSelect?.addEventListener('change', applyEnvironment);

    // Clear the active preset highlight once the user adjusts anything by hand.
    [exposureSlider, shadowIntensitySlider, shadowSoftnessSlider, environmentSelect].forEach(el => {
        el?.addEventListener('input', (e) => {
            if (e.isTrusted) document.querySelectorAll('.lighting-preset-btn.is-active').forEach(b => b.classList.remove('is-active'));
        });
    });

    function applyLightingPreset(name) {
        const preset = LIGHTING_PRESETS[name];
        if (!preset) return;
        if (exposureSlider) exposureSlider.value = preset.exposure;
        if (shadowIntensitySlider) shadowIntensitySlider.value = preset.shadow;
        if (shadowSoftnessSlider) shadowSoftnessSlider.value = preset.softness;
        if (environmentSelect) environmentSelect.value = preset.environment;
        applyExposure();
        applyShadowIntensity();
        applyShadowSoftness();
        applyEnvironment();
    }

    document.querySelectorAll('.lighting-preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            applyLightingPreset(btn.dataset.preset);
            document.querySelectorAll('.lighting-preset-btn').forEach(b => b.classList.remove('is-active'));
            btn.classList.add('is-active');
        });
    });

    // Owner-only: persist the current lighting to the model's viewer settings
    // (the same store the /embed and public viewer resolve against).
    const saveLighting = document.getElementById('saveLighting');
    const saveLightingStatus = document.getElementById('saveLightingStatus');
    if (CAN_EDIT && saveLighting && modelId) {
        saveLighting.addEventListener('click', () => {
            fetch('/api/models/' + modelId + '/viewer-settings', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    exposure: parseFloat(exposureSlider.value),
                    shadow_intensity: parseFloat(shadowIntensitySlider.value),
                    shadow_softness: parseFloat(shadowSoftnessSlider.value),
                    environment: environmentSelect.value,
                }),
            })
                .then(r => r.json())
                .then(data => {
                    if (!saveLightingStatus) return;
                    saveLightingStatus.textContent = data.success ? 'Lighting saved.' : (data.error || 'Failed to save.');
                    saveLightingStatus.classList.remove('hidden');
                    setTimeout(() => saveLightingStatus.classList.add('hidden'), 3000);
                })
                .catch(() => {
                    if (saveLightingStatus) {
                        saveLightingStatus.textContent = 'Failed to save.';
                        saveLightingStatus.classList.remove('hidden');
                    }
                });
        });
    }
});
