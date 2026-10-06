document.addEventListener('DOMContentLoaded', () => {
    const modelId = window.VIEWER_CONFIG.modelId;

        // SAVE CHANGES
        // ===================================================================
        const saveChangesBtn = document.getElementById('saveChanges');
        // Capture the button's real initial markup (check-circle icon, per the
        // template) instead of hardcoding a different icon name -- the old
        // hardcoded "circle" markup left the button showing a blank icon
        // after a failed save until the tools panel was reopened re-ran lucide.
        const defaultSaveButtonMarkup = saveChangesBtn ? saveChangesBtn.innerHTML : '';

        function gatherModifications() {
            const mods = {};

            // Material modifications — ONLY the fields the user actually
            // touched. The backend applies each present field to every
            // material in the GLB, so sending an untouched field (e.g.
            // `color` on a roughness-only edit) would permanently overwrite
            // other materials' values for it — including per-layer colors
            // saved earlier via the Layers panel.
            const mats = window.getMaterials();
            // Build one material block from a material's live values + the
            // fields the user touched for that target.
            const buildMaterialBlock = (mat, dirtyFields) => {
                const cf = mat.pbrMetallicRoughness?.baseColorFactor;
                const material = {};
                if (dirtyFields.has('color') && cf) {
                    material.color = [cf[0], cf[1], cf[2]];
                    // Color and opacity share baseColorFactor's alpha
                    // channel server-side, so a color write must carry
                    // the current alpha or it would reset to opaque.
                    material.opacity = cf[3];
                } else if (dirtyFields.has('opacity') && cf) {
                    material.opacity = cf[3];
                }
                if (dirtyFields.has('metalness')) {
                    material.metalness = mat.pbrMetallicRoughness?.metallicFactor ?? 0;
                }
                if (dirtyFields.has('roughness')) {
                    material.roughness = mat.pbrMetallicRoughness?.roughnessFactor ?? 1;
                }
                return material;
            };
            if (materialDirty && mats.length > 0) {
                try {
                    // "All parts" edits: the whole-model block, read from mat[0]
                    // exactly as before (backward-compatible payload).
                    const dirtyFields = window._materialDirtyFields?.() ||
                        new Set(['color', 'metalness', 'roughness', 'opacity']);
                    const material = buildMaterialBlock(mats[0], dirtyFields);
                    if (Object.keys(material).length > 0) {
                        mods.material = material;
                    }
                    // Per-material edits: one block per edited material, tagged
                    // with its index (server: `material_targets[].target`).
                    const targets = [];
                    (window._materialDirtyTargets?.() || []).forEach(([idx, fields]) => {
                        if (!mats[idx]) return;
                        const block = buildMaterialBlock(mats[idx], fields);
                        if (Object.keys(block).length > 0) targets.push(Object.assign({ target: idx }, block));
                    });
                    if (targets.length > 0) mods.material_targets = targets;
                } catch (e) { /* material not loaded — skip material mods */ }
            }
            // A pending texture upload is a material change in its own right,
            // scoped to the target that was selected when it was chosen.
            const _textureUpload = document.getElementById('textureUpload');
            if (_textureUpload?.files?.length > 0) {
                const texTarget = window._textureTarget;
                let block;
                if (Number.isInteger(texTarget)) {
                    if (!mods.material_targets) mods.material_targets = [];
                    block = mods.material_targets.find(b => b.target === texTarget);
                    if (!block) { block = { target: texTarget }; mods.material_targets.push(block); }
                } else {
                    if (!mods.material) mods.material = {};
                    block = mods.material;
                }
                block._pendingTextureFile = _textureUpload.files[0];
            }

            // Transform modifications
            const scale = parseFloat(document.getElementById('scaleSlider')?.value || 1);
            const rx = parseFloat(document.getElementById('rotateXSlider')?.value || 0);
            const ry = parseFloat(document.getElementById('rotateYSlider')?.value || 0);
            const rz = parseFloat(document.getElementById('rotateZSlider')?.value || 0);

            if (scale !== 1 || rx !== 0 || ry !== 0 || rz !== 0) {
                mods.transform = {
                    scale: scale,
                    rotation: { x: rx, y: ry, z: rz }
                };
            }

            // Layer visibility/color — gathered from the Layers panel's own
            // scope (separate <script> block, see window._layersGatherMods).
            const layerMods = window._layersGatherMods?.();
            if (layerMods) {
                mods.layers = layerMods;
            }

            return mods;
        }

        saveChangesBtn?.addEventListener('click', async () => {
            const modifications = gatherModifications();
            const hasModifications = Object.keys(modifications).length > 0;
            // "Front" is rotation 0/0/0 — identical to the default, so
            // gatherModifications() never includes it in `modifications`
            // (there's nothing to bake). But the preset still queued a
            // canonical camera framing (window._pendingPresetCamera) that
            // the user DOES want persisted: picking "Front" and hitting
            // Save should swap the model's default view from the general
            // perspective framing to this flat, straight-on one, even
            // though no geometry needs to change. Treat a queued camera as
            // "something to save" too, independent of `modifications`.
            const pendingCamera = window._pendingPresetCamera;
            if (!hasModifications && !pendingCamera) {
                window.arToast('No changes to save.', 'info');
                return;
            }

            saveChangesBtn.disabled = true;
            saveChangesBtn.innerHTML = '<i data-lucide="circle"></i> Saving...';

            try {
                if (hasModifications) {
                    // Convert pending texture file to base64 if present
                    const _texBlocks = [modifications.material, ...(modifications.material_targets || [])]
                        .filter(b => b && b._pendingTextureFile);
                    for (const block of _texBlocks) {
                        const file = block._pendingTextureFile;
                        const base64 = await new Promise((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onload = () => resolve(reader.result);
                            reader.onerror = reject;
                            reader.readAsDataURL(file);
                        });
                        block.texture = base64;
                        delete block._pendingTextureFile;
                    }

                    const response = await fetch('/save_modifications', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ model_id: modelId, modifications })
                    });
                    const result = await response.json();
                    if (!result.success) {
                        window.arToast('Save failed: ' + (result.error || 'Unknown error'), 'error');
                        return;
                    }
                }

                // A transform preset ("hazır görünüm") re-frames the live
                // preview to a canonical camera angle that isn't part of
                // the GLB bake — persist it now so the view the user
                // prepared is what they see after the reload below.
                if (pendingCamera) {
                    try {
                        const camResp = await fetch(`/api/models/${modelId}/viewer-settings`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(pendingCamera)
                        });
                        if (!camResp.ok) throw new Error('HTTP ' + camResp.status);
                    } catch (e) {
                        // Persisting the prepared framing failed — warn the user
                        // rather than silently reloading and losing the view.
                        console.error('Camera framing save error:', e);
                        window.arToast('Your changes were saved, but the prepared camera view could not be applied. Try setting it again.', 'error', { duration: 6000 });
                        // The reload below would wipe the toast; give it time to be read.
                        await new Promise(r => setTimeout(r, 3000));
                    }
                    window._pendingPresetCamera = null;
                }
                window.location.reload();
            } catch (err) {
                console.error('Save error:', err);
                window.arToast('Failed to save changes.', 'error');
            } finally {
                saveChangesBtn.disabled = false;
                saveChangesBtn.innerHTML = defaultSaveButtonMarkup;
                // lucide swaps <i data-lucide> tags for inline <svg> at page
                // load; restoring raw innerHTML brings back the unrendered
                // <i> tag, so re-run it or the icon stays blank until the
                // tools panel is closed and reopened.
                window.lucide?.createIcons();
            }
        });

        // ===================================================================
        // SAVE EXPLODED LAYOUT — separate from Save & Apply to AR: bakes the
        // current explode offsets as permanent node translations. Also
        // includes any other pending changes (material/transform/layers)
        // via the same gatherModifications(), so it's a superset save.
        // ===================================================================
        const saveExplodedBtn = document.getElementById('saveExplodedLayout');
        saveExplodedBtn?.addEventListener('click', async () => {
            const explodeMods = window._layersGatherExplodeMods?.();
            if (!explodeMods) {
                window.arToast('Drag Explode above 0% first, then save the layout.', 'info');
                return;
            }
            if (!await window.arConfirm('This permanently moves the exploded parts in the saved model, including in AR. Continue?', { confirmLabel: 'Save layout', danger: true })) {
                return;
            }

            const modifications = gatherModifications();

            // Explode offsets are captured from the live scene, where a
            // pending rotation is only a root-level preview (not baked into
            // the nodes). Baking both in one request applies unrotated
            // offsets to rotated geometry — parts fly out in directions that
            // don't match the preview. Force the rotation through its own
            // save first.
            const rot = modifications.transform?.rotation;
            if (rot && (rot.x !== 0 || rot.y !== 0 || rot.z !== 0)) {
                window.arToast('Save the rotation first (Save & Apply to AR), then save the exploded layout — combining them in one save would misplace the exploded parts.', 'info', { duration: 7000 });
                return;
            }

            modifications.explode = explodeMods;

            const defaultExplodeButtonMarkup = saveExplodedBtn.innerHTML;
            saveExplodedBtn.disabled = true;
            saveExplodedBtn.innerHTML = '<i data-lucide="circle"></i> Saving...';

            try {
                if (modifications.material?._pendingTextureFile) {
                    const file = modifications.material._pendingTextureFile;
                    const base64 = await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(reader.result);
                        reader.onerror = reject;
                        reader.readAsDataURL(file);
                    });
                    modifications.material.texture = base64;
                    delete modifications.material._pendingTextureFile;
                }

                const response = await fetch('/save_modifications', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model_id: modelId, modifications })
                });
                const result = await response.json();
                if (result.success) {
                    window.location.reload();
                } else {
                    window.arToast('Save failed: ' + (result.error || 'Unknown error'), 'error');
                }
            } catch (err) {
                console.error('Save exploded layout error:', err);
                window.arToast('Failed to save exploded layout.', 'error');
            } finally {
                saveExplodedBtn.disabled = false;
                saveExplodedBtn.innerHTML = defaultExplodeButtonMarkup;
            }
        });

});
