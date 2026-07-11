document.addEventListener('DOMContentLoaded', () => {
    const modelId = window.VIEWER_CONFIG.modelId;

        // SAVE CHANGES
        // ===================================================================
        const saveChangesBtn = document.getElementById('saveChanges');
        const defaultSaveButtonMarkup = '<i data-lucide="circle"></i> Save & Apply to AR';

        function gatherModifications() {
            const mods = {};

            // Material modifications — ONLY when the user actually touched a
            // material control. The backend applies this single value set to
            // every material in the GLB, so sending mat[0]'s current state on
            // an untouched save (e.g. transform-only) would permanently
            // overwrite all other materials on a multi-material model.
            const mats = window.getMaterials();
            if (materialDirty && mats.length > 0) {
                try {
                    const mat = mats[0];
                    const cf = mat.pbrMetallicRoughness?.baseColorFactor;
                    mods.material = {
                        color: cf ? [cf[0], cf[1], cf[2]] : null,
                        metalness: mat.pbrMetallicRoughness?.metallicFactor ?? 0,
                        roughness: mat.pbrMetallicRoughness?.roughnessFactor ?? 1,
                        opacity: cf ? cf[3] : 1
                    };
                } catch (e) { /* material not loaded — skip material mods */ }
            }
            // A pending texture upload is a material change in its own right.
            const _textureUpload = document.getElementById('textureUpload');
            if (_textureUpload?.files?.length > 0) {
                if (!mods.material) mods.material = {};
                mods.material._pendingTextureFile = _textureUpload.files[0];
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
            if (Object.keys(modifications).length === 0) {
                alert('No changes to save.');
                return;
            }

            saveChangesBtn.disabled = true;
            saveChangesBtn.innerHTML = '<i data-lucide="circle"></i> Saving...';

            try {
                // Convert pending texture file to base64 if present
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
                    alert('Save failed: ' + (result.error || 'Unknown error'));
                }
            } catch (err) {
                console.error('Save error:', err);
                alert('Failed to save changes.');
            } finally {
                saveChangesBtn.disabled = false;
                saveChangesBtn.innerHTML = defaultSaveButtonMarkup;
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
                alert('Drag Explode above 0% first, then save the layout.');
                return;
            }
            if (!confirm('This permanently moves the exploded parts in the saved model, including in AR. Continue?')) {
                return;
            }

            const modifications = gatherModifications();
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
                    alert('Save failed: ' + (result.error || 'Unknown error'));
                }
            } catch (err) {
                console.error('Save exploded layout error:', err);
                alert('Failed to save exploded layout.');
            } finally {
                saveExplodedBtn.disabled = false;
                saveExplodedBtn.innerHTML = defaultExplodeButtonMarkup;
            }
        });

});
