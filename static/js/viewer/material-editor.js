// Global initialization state variables (must be accessible from all script blocks)
let materialEditorInitialized = false;
let transformEditorInitialized = false;
// Set when the user actually touches a material control. Saving sends
// mat[0]'s values and the backend applies them to EVERY material, so a
// save must never include a material block the user didn't ask for —
// on a multi-material model that would silently overwrite materials
// 1..N with material 0's appearance.
// Tracked per FIELD, not just as one boolean: the backend applies each
// present field to every material, so a roughness-only tweak must not
// also send `color` — that would wipe previously saved per-layer colors
// (Layers panel clones) with material 0's color.
let materialDirty = false;
const materialDirtyFields = new Set();
function markMaterialChanged(field) {
    materialDirty = true;
    if (field) materialDirtyFields.add(field);
    // If a slice preview is active, re-patch materials: a material change
    // can recompile/replace the THREE material and lose the clip shader.
    window._reapplyClipping?.();
}
function clearMaterialDirty() {
    materialDirty = false;
    materialDirtyFields.clear();
}

document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.querySelector('model-viewer');

        // MATERIAL EDITOR
        // ===================================================================
        // Store original material state for reset
        let originalMaterials = [];

        function getMaterials() {
            try {
                return modelViewer?.model?.materials || [];
            } catch { return []; }
        }

        // model-viewer 4.x lazily loads materials; accessing `pbrMetallicRoughness`
        // before the material is loaded throws ("Material has not been loaded...").
        // Pre-load every material once on model load so the sync editor handlers are safe.
        async function ensureMaterialsLoaded() {
            const mats = getMaterials();
            await Promise.all(mats.map(m => {
                try { return m.ensureLoaded ? m.ensureLoaded() : null; }
                catch { return null; }
            }));
            return mats;
        }

        // Iterate materials defensively — if one isn't loaded yet, skip it instead of
        // letting the pbrMetallicRoughness getter throw an uncaught error.
        function forEachMaterial(cb) {
            getMaterials().forEach((mat, i) => {
                try { cb(mat, i); } catch (e) { /* material not loaded yet */ }
            });
        }

        function captureOriginalMaterials() {
            try {
                const mats = getMaterials();
                originalMaterials = mats.map(mat => ({
                    baseColor: mat.pbrMetallicRoughness?.baseColorFactor ? [...mat.pbrMetallicRoughness.baseColorFactor] : [1, 1, 1, 1],
                    metallic: mat.pbrMetallicRoughness?.metallicFactor ?? 0,
                    roughness: mat.pbrMetallicRoughness?.roughnessFactor ?? 1
                }));

                // Sync UI sliders/inputs with the model's actual material values
                if (originalMaterials.length > 0) {
                    const om = originalMaterials[0];

                    // Query elements at runtime (may be in Tools Panel after DOM restructuring)
                    const _matColor = document.getElementById('materialColor');
                    const _matColorHex = document.getElementById('materialColorHex');
                    const _metalnessSlider = document.getElementById('metalnessSlider');
                    const _metalnessValue = document.getElementById('metalnessValue');
                    const _roughnessSlider = document.getElementById('roughnessSlider');
                    const _roughnessValue = document.getElementById('roughnessValue');
                    const _opacitySlider = document.getElementById('opacitySlider');
                    const _opacityValue = document.getElementById('opacityValue');

                    // Base Color → color picker + hex input
                    const r = Math.round(om.baseColor[0] * 255);
                    const g = Math.round(om.baseColor[1] * 255);
                    const b = Math.round(om.baseColor[2] * 255);
                    const hex = '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
                    if (_matColor) _matColor.value = hex;
                    if (_matColorHex) _matColorHex.value = hex.toUpperCase();

                    // Metalness
                    if (_metalnessSlider) _metalnessSlider.value = om.metallic;
                    if (_metalnessValue) _metalnessValue.textContent = om.metallic.toFixed(2);

                    // Roughness
                    if (_roughnessSlider) _roughnessSlider.value = om.roughness;
                    if (_roughnessValue) _roughnessValue.textContent = om.roughness.toFixed(2);

                    // Opacity
                    const alpha = om.baseColor[3] ?? 1;
                    if (_opacitySlider) _opacitySlider.value = alpha;
                    if (_opacityValue) _opacityValue.textContent = alpha.toFixed(2);
                }

                // Normalize fully-opaque materials to OPAQUE alpha mode on load.
                // Some GLBs ship an untextured, full-alpha material stuck in
                // BLEND mode, which renders with pointless transparency blending
                // (the model looks "not quite 100%") until the user nudges the
                // opacity slider — which is exactly what flips it to OPAQUE. Do
                // it up front so the model is truly opaque, matching the 1.0 the
                // slider already shows. Skip textured materials (their alpha may
                // come from the texture) and genuinely translucent ones (a < 1)
                // so we never make an intentionally transparent model opaque.
                mats.forEach(mat => {
                    const pbr = mat.pbrMetallicRoughness;
                    if (!pbr) return;
                    const a = pbr.baseColorFactor?.[3] ?? 1;
                    const hasBaseTex = !!(pbr.baseColorTexture && pbr.baseColorTexture.texture);
                    if (a >= 1 && !hasBaseTex) {
                        try { mat.setAlphaMode('OPAQUE'); } catch (e) { /* older API */ }
                    }
                });
            } catch (e) { console.warn('Could not capture original materials:', e); }
        }

        modelViewer?.addEventListener('load', async () => {
            await ensureMaterialsLoaded();
            captureOriginalMaterials();
            // Lets undo-redo.js capture its baseline snapshot only once the
            // sliders actually reflect the model's real material state,
            // instead of guessing with a fixed delay.
            window.dispatchEvent(new CustomEvent('viewer:material-ready'));
        });

        // Auto-capture viewer screenshot as thumbnail (owner only, once per model)
        if (window.VIEWER_CONFIG.isOwner) {
        modelViewer?.addEventListener('load', function() {
            // Small delay to let the model fully render
            setTimeout(async function() {
                try {
                    const blob = await modelViewer.toBlob({ idealAspect: true });
                    const reader = new FileReader();
                    reader.onloadend = function() {
                        fetch('/api/thumbnail/' + window.VIEWER_CONFIG.modelId, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ image: reader.result })
                        }).catch(() => {});
                    };
                    reader.readAsDataURL(blob);
                } catch (e) {
                    console.warn('Could not capture viewer thumbnail:', e);
                }
            }, 1500);
        });
        }

        function hexToRgb(hex) {
            hex = hex.replace('#', '');
            return {
                r: parseInt(hex.substring(0, 2), 16) / 255,
                g: parseInt(hex.substring(2, 4), 16) / 255,
                b: parseInt(hex.substring(4, 6), 16) / 255
            };
        }

        function applyMaterialColor(hex) {
            const rgb = hexToRgb(hex);
            forEachMaterial(mat => {
                const currentAlpha = mat.pbrMetallicRoughness?.baseColorFactor?.[3] ?? 1;
                mat.pbrMetallicRoughness.setBaseColorFactor([rgb.r, rgb.g, rgb.b, currentAlpha]);
            });
        }

        // Material editor initialization (called AFTER DOM restructuring)
        function initMaterialEditor() {
            const matColor = document.getElementById('materialColor');
            const matColorHex = document.getElementById('materialColorHex');
            const metalnessSlider = document.getElementById('metalnessSlider');
            const roughnessSlider = document.getElementById('roughnessSlider');
            const opacitySlider = document.getElementById('opacitySlider');
            const metalnessValue = document.getElementById('metalnessValue');
            const roughnessValue = document.getElementById('roughnessValue');
            const opacityValue = document.getElementById('opacityValue');
            const textureUpload = document.getElementById('textureUpload');
            const texturePreview = document.getElementById('texturePreview');
            const texturePreviewImg = document.getElementById('texturePreviewImg');
            const resetMaterial = document.getElementById('resetMaterial');

            matColor?.addEventListener('input', (e) => {
                const hex = e.target.value;
                if (matColorHex) matColorHex.value = hex.toUpperCase();
                applyMaterialColor(hex);
                markMaterialChanged('color');
            });

            matColorHex?.addEventListener('input', (e) => {
                let hex = e.target.value;
                if (!hex.startsWith('#')) hex = '#' + hex;
                if (/^#[0-9A-F]{6}$/i.test(hex)) {
                    if (matColor) matColor.value = hex;
                    applyMaterialColor(hex);
                    markMaterialChanged('color');
                }
            });

            metalnessSlider?.addEventListener('input', (e) => {
                const val = parseFloat(e.target.value);
                if (metalnessValue) metalnessValue.textContent = val.toFixed(2);
                forEachMaterial(mat => {
                    mat.pbrMetallicRoughness.setMetallicFactor(val);
                });
                markMaterialChanged('metalness');
            });

            roughnessSlider?.addEventListener('input', (e) => {
                const val = parseFloat(e.target.value);
                if (roughnessValue) roughnessValue.textContent = val.toFixed(2);
                forEachMaterial(mat => {
                    mat.pbrMetallicRoughness.setRoughnessFactor(val);
                });
                markMaterialChanged('roughness');
            });

            opacitySlider?.addEventListener('input', (e) => {
                const val = parseFloat(e.target.value);
                if (opacityValue) opacityValue.textContent = val.toFixed(2);
                forEachMaterial(mat => {
                    const cf = mat.pbrMetallicRoughness?.baseColorFactor || [1, 1, 1, 1];
                    mat.pbrMetallicRoughness.setBaseColorFactor([cf[0], cf[1], cf[2], val]);
                    if (val < 1) {
                        mat.setAlphaMode('BLEND');
                    } else {
                        mat.setAlphaMode('OPAQUE');
                    }
                });
                markMaterialChanged('opacity');
            });

            // Texture upload
            textureUpload?.addEventListener('change', async (e) => {
                const file = e.target.files[0];
                if (!file) return;
                try {
                    const url = URL.createObjectURL(file);
                    if (texturePreviewImg) texturePreviewImg.src = url;
                    if (texturePreview) texturePreview.classList.remove('hidden');

                    const texture = await modelViewer.createTexture(url);
                    forEachMaterial(mat => {
                        // glTF multiplies the texture by baseColorFactor, so any
                        // applied color would tint the image — reset to white
                        // (keep current alpha) so the texture shows true colors.
                        const cf = mat.pbrMetallicRoughness?.baseColorFactor || [1, 1, 1, 1];
                        mat.pbrMetallicRoughness.setBaseColorFactor([1, 1, 1, cf[3]]);
                        mat.pbrMetallicRoughness.baseColorTexture.setTexture(texture);
                    });
                    markMaterialChanged('texture');
                    markMaterialChanged('color');
                    // Sync color pickers with the reset tint
                    if (matColor) matColor.value = '#ffffff';
                    if (matColorHex) matColorHex.value = '#FFFFFF';

                    // Models without a UV map can't preview a texture correctly
                    // (the whole surface samples one texel). Saving generates
                    // proper UVs server-side — tell the user instead of looking broken.
                    checkModelHasUVs().then(hasUVs => {
                        const note = document.getElementById('textureUvNote');
                        if (note) note.classList.toggle('hidden', hasUVs !== false);
                    });
                } catch (err) {
                    console.error('Texture upload error:', err);
                    alert('Failed to apply texture.');
                }
            });

            // Parse the GLB's JSON chunk (from HTTP cache) to see if any
            // primitive carries TEXCOORD_0. Returns true/false, or null on error.
            let _uvCheckCache = null;
            async function checkModelHasUVs() {
                if (_uvCheckCache !== null) return _uvCheckCache;
                try {
                    const resp = await fetch(modelViewer.src, { cache: 'force-cache' });
                    const buf = await resp.arrayBuffer();
                    const dv = new DataView(buf);
                    if (dv.getUint32(0, true) !== 0x46546C67) return (_uvCheckCache = null); // not glTF
                    const jsonLen = dv.getUint32(12, true);
                    const jsonText = new TextDecoder().decode(new Uint8Array(buf, 20, jsonLen));
                    const json = JSON.parse(jsonText);
                    _uvCheckCache = (json.meshes || []).some(m =>
                        (m.primitives || []).some(p => p.attributes && 'TEXCOORD_0' in p.attributes)
                    );
                    return _uvCheckCache;
                } catch (e) {
                    console.warn('UV check failed:', e);
                    return (_uvCheckCache = null);
                }
            }

            // Remove texture (global function for onclick)
            window.removeTexture = function() {
                forEachMaterial(mat => {
                    mat.pbrMetallicRoughness.baseColorTexture.setTexture(null);
                });
                if (texturePreview) texturePreview.classList.add('hidden');
                if (textureUpload) textureUpload.value = '';
            };

            // Reset material
            resetMaterial?.addEventListener('click', () => {
                forEachMaterial((mat, i) => {
                    const orig = originalMaterials[i] || { baseColor: [1, 1, 1, 1], metallic: 0, roughness: 1 };
                    mat.pbrMetallicRoughness.setBaseColorFactor(orig.baseColor);
                    mat.pbrMetallicRoughness.setMetallicFactor(orig.metallic);
                    mat.pbrMetallicRoughness.setRoughnessFactor(orig.roughness);
                    mat.setAlphaMode('OPAQUE');
                    mat.pbrMetallicRoughness.baseColorTexture.setTexture(null);
                });
                if (matColor) matColor.value = '#ffffff';
                if (matColorHex) matColorHex.value = '#FFFFFF';
                if (metalnessSlider) { metalnessSlider.value = 0; if (metalnessValue) metalnessValue.textContent = '0.0'; }
                if (roughnessSlider) { roughnessSlider.value = 1; if (roughnessValue) roughnessValue.textContent = '1.0'; }
                if (opacitySlider) { opacitySlider.value = 1; if (opacityValue) opacityValue.textContent = '1.0'; }
                if (texturePreview) texturePreview.classList.add('hidden');
                if (textureUpload) textureUpload.value = '';
                // Back at the model's saved appearance — nothing material-wise
                // left to persist, so a later save must not send a material block.
                clearMaterialDirty();
                window._reapplyClipping?.();
            });

            materialEditorInitialized = true;
        }


        // Cross-file bridge: save-flow.js needs to read the current
        // material list to build the "Save & Apply to AR" payload.
        window.getMaterials = getMaterials;

        // Cross-file bridge: undo-redo.js snapshots/restores editor state
        // without knowing how the material editor itself applies changes.
        window._captureMaterialSnapshot = function() {
            return {
                color: document.getElementById('materialColorHex')?.value || '#FFFFFF',
                metalness: parseFloat(document.getElementById('metalnessSlider')?.value ?? 0),
                roughness: parseFloat(document.getElementById('roughnessSlider')?.value ?? 1),
                opacity: parseFloat(document.getElementById('opacitySlider')?.value ?? 1),
                // Which fields the user had actually touched at this point in
                // history. Captured so undo/redo restores the exact dirty set
                // instead of blanket-marking all four — otherwise a
                // roughness-only edit, once undone/redone, would save a full
                // material block and flatten every other material's color.
                dirtyFields: Array.from(materialDirtyFields),
            };
        };
        // Exposed for save-flow.js: which material fields the user actually
        // touched, so the save payload only carries those fields.
        window._materialDirtyFields = function() {
            return new Set(materialDirtyFields);
        };

        window._applyMaterialSnapshot = function(snap, opts) {
            const matColor = document.getElementById('materialColor');
            const matColorHex = document.getElementById('materialColorHex');
            const metalnessSlider = document.getElementById('metalnessSlider');
            const roughnessSlider = document.getElementById('roughnessSlider');
            const opacitySlider = document.getElementById('opacitySlider');
            const metalnessValue = document.getElementById('metalnessValue');
            const roughnessValue = document.getElementById('roughnessValue');
            const opacityValue = document.getElementById('opacityValue');

            if (matColor) matColor.value = snap.color;
            if (matColorHex) matColorHex.value = snap.color.toUpperCase();
            applyMaterialColor(snap.color);

            if (metalnessSlider) metalnessSlider.value = snap.metalness;
            if (metalnessValue) metalnessValue.textContent = snap.metalness.toFixed(2);
            if (roughnessSlider) roughnessSlider.value = snap.roughness;
            if (roughnessValue) roughnessValue.textContent = snap.roughness.toFixed(2);
            if (opacitySlider) opacitySlider.value = snap.opacity;
            if (opacityValue) opacityValue.textContent = snap.opacity.toFixed(2);

            forEachMaterial(mat => {
                mat.pbrMetallicRoughness.setMetallicFactor(snap.metalness);
                mat.pbrMetallicRoughness.setRoughnessFactor(snap.roughness);
                const cf = mat.pbrMetallicRoughness?.baseColorFactor || [1, 1, 1, 1];
                mat.pbrMetallicRoughness.setBaseColorFactor([cf[0], cf[1], cf[2], snap.opacity]);
                mat.setAlphaMode(snap.opacity < 1 ? 'BLEND' : 'OPAQUE');
            });
            // Restore the exact dirty-field set this snapshot was taken with,
            // so a later save only carries the fields the user genuinely
            // changed. Falls back to the older opts.dirty flag for snapshots
            // captured before dirtyFields existed.
            if (Array.isArray(snap.dirtyFields)) {
                materialDirtyFields.clear();
                snap.dirtyFields.forEach((f) => materialDirtyFields.add(f));
                materialDirty = materialDirtyFields.size > 0;
                window._reapplyClipping?.();
            } else if (opts && opts.dirty === false) {
                clearMaterialDirty();
            } else {
                ['color', 'metalness', 'roughness', 'opacity'].forEach(markMaterialChanged);
            }
        };

        // Initialize editors
        if (!materialEditorInitialized) initMaterialEditor();
});
