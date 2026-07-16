document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.querySelector('model-viewer');
    const modelId = window.VIEWER_CONFIG.modelId;

        // TRANSFORM PANEL
        // ===================================================================

        // Load initial dimensions (called AFTER DOM restructuring)
        function loadDimensions() {
            const dimWidth = document.getElementById('dimWidth');
            const dimHeight = document.getElementById('dimHeight');
            const dimDepth = document.getElementById('dimDepth');
            const cumulativeScale = document.getElementById('cumulativeScale');
            const scaleWarning = document.getElementById('scaleWarning');

            fetch('/get_model_dimensions/' + modelId)
                .then(r => r.json())
                .then(data => {
                    if (data.success && data.dimensions) {
                        const d = data.dimensions;
                        if (dimWidth) dimWidth.textContent = parseFloat(d.width).toFixed(2) + ' cm';
                        if (dimHeight) dimHeight.textContent = parseFloat(d.height).toFixed(2) + ' cm';
                        if (dimDepth) dimDepth.textContent = parseFloat(d.depth).toFixed(2) + ' cm';
                        // Keep the info sidebar in sync: it renders DB bounds which
                        // go stale after transform/slice saves — the GLB file
                        // (this endpoint) is the source of truth for both displays.
                        const sw = document.getElementById('sideDimW');
                        const sh = document.getElementById('sideDimH');
                        const sd = document.getElementById('sideDimD');
                        if (sw) sw.textContent = parseFloat(d.width).toFixed(1);
                        if (sh) sh.textContent = parseFloat(d.height).toFixed(1);
                        if (sd) sd.textContent = parseFloat(d.depth).toFixed(1);
                    }
                    if (scaleWarning) {
                        if (data.scale_warning) {
                            scaleWarning.textContent = data.scale_warning;
                            scaleWarning.classList.remove('hidden');
                        } else {
                            scaleWarning.classList.add('hidden');
                        }
                    }
                })
                .catch(() => {});

            // Load cumulative scale from model data
            if (window.VIEWER_CONFIG.cumulativeScale) {
            if (cumulativeScale) cumulativeScale.textContent = window.VIEWER_CONFIG.cumulativeScale + 'x';
            }
        }

        let transformRenderNudge = 1;

        function forceModelViewerRefresh() {
            if (!modelViewer) return;

            const scene = modelViewer.model?.scene;
            if (scene) {
                scene.updateMatrixWorld?.(true);
            }

            const orbit = typeof modelViewer.getCameraOrbit === 'function' ? modelViewer.getCameraOrbit() : null;
            if (typeof modelViewer.requestUpdate === 'function') {
                modelViewer.requestUpdate();
            }

            if (orbit && typeof modelViewer.jumpCameraToGoal === 'function') {
                transformRenderNudge *= -1;
                const nudgedOrbit = (orbit.theta + (transformRenderNudge * 0.0001)) + 'rad ' + orbit.phi + 'rad ' + orbit.radius + 'm';
                modelViewer.cameraOrbit = nudgedOrbit;
                modelViewer.jumpCameraToGoal();
                requestAnimationFrame(() => {
                    modelViewer.cameraOrbit = orbit.toString();
                    if (typeof modelViewer.requestUpdate === 'function') {
                        modelViewer.requestUpdate();
                    }
                });
            }
        }

        // Re-center the (rotated) model in a clean front view. Rotating the
        // model via `orientation` moves its bounding box, but model-viewer's
        // auto camera-target isn't recomputed on its own — so the model drifts
        // off-center and looks skewed. updateFraming() recomputes the centered
        // target + ideal distance; then we snap the camera face-on (like the
        // View-tab presets) so every orientation lands framed the same way.
        function frameModelCentered() {
            if (!modelViewer) return;
            // Rotating the model shifts its bounds, so we can't just keep the
            // current camera — the model drifts off-center or (if we preserve a
            // stale zoom/FOV) ends up tiny. Instead reproduce the Reset View
            // button's standard framing (auto radius + default FOV + auto
            // target), which reliably frames the model, but face it front.
            // updateFraming() first forces a bounds recompute so the auto
            // target/radius reflect the new orientation.
            const applyFront = () => {
                modelViewer.cameraTarget = 'auto auto auto';
                modelViewer.cameraOrbit = '0deg 90deg auto';
                modelViewer.fieldOfView = '24deg';
                modelViewer.jumpCameraToGoal?.();
            };
            const framed = modelViewer.updateFraming?.();
            if (framed && typeof framed.then === 'function') {
                framed.then(applyFront);
            } else {
                applyFront();
            }
        }

        function applyTransform(reframe) {
            if (!modelViewer) return;

            // Query sliders dynamically (they may not exist yet)
            const scaleSlider = document.getElementById('scaleSlider');
            const rotateXSlider = document.getElementById('rotateXSlider');
            const rotateYSlider = document.getElementById('rotateYSlider');
            const rotateZSlider = document.getElementById('rotateZSlider');

            const s = parseFloat(scaleSlider?.value || 1);
            const rx = parseFloat(rotateXSlider?.value || 0);
            const ry = parseFloat(rotateYSlider?.value || 0);
            const rz = parseFloat(rotateZSlider?.value || 0);

            // model-viewer's public scene-graph API (v1.1+): `scale` and
            // `orientation` ("roll pitch yaw" = Z X Y in degrees). The old code
            // poked modelViewer.model.scene — that internal isn't exposed in
            // v4.x, so the preview silently did nothing.
            modelViewer.scale = s + ' ' + s + ' ' + s;
            modelViewer.orientation = rz + 'deg ' + rx + 'deg ' + ry + 'deg';

            if (reframe) {
                // Preset buttons: recenter + snap to a clean framed front view.
                frameModelCentered();
            } else {
                // Slider drags: just force a redraw. model-viewer renders on
                // demand and doesn't always flag these property changes dirty —
                // without this nudge the change only shows up on the next user
                // interaction (click/drag). Reframing on every input is jittery.
                forceModelViewerRefresh();
            }
        }

        // Transform editor initialization (called AFTER DOM restructuring)
        function initTransformEditor() {
            const scaleInput = document.getElementById('scaleInput');
            const scaleSlider = document.getElementById('scaleSlider');
            const rotateXSlider = document.getElementById('rotateXSlider');
            const rotateYSlider = document.getElementById('rotateYSlider');
            const rotateZSlider = document.getElementById('rotateZSlider');
            const rotateXValue = document.getElementById('rotateXValue');
            const rotateYValue = document.getElementById('rotateYValue');
            const rotateZValue = document.getElementById('rotateZValue');
            const resetTransform = document.getElementById('resetTransform');

            scaleSlider?.addEventListener('input', (e) => {
                const val = parseFloat(e.target.value);
                if (scaleInput) scaleInput.value = val.toFixed(1);
                applyTransform();
            });
            // Re-frame the camera once the user releases the slider so large
            // scale-ups don't overflow the viewport (not during drag — jittery).
            scaleSlider?.addEventListener('change', () => modelViewer?.updateFraming?.());

            scaleInput?.addEventListener('input', (e) => {
                let val = parseFloat(e.target.value);
                if (isNaN(val) || val < 0.1) val = 0.1;
                if (val > 10) val = 10;
                if (scaleSlider) scaleSlider.value = val;
                applyTransform();
            });
            scaleInput?.addEventListener('change', () => modelViewer?.updateFraming?.());

            rotateXSlider?.addEventListener('input', (e) => {
                if (rotateXValue) rotateXValue.textContent = e.target.value + '\u00B0';
                applyTransform();
            });

            rotateYSlider?.addEventListener('input', (e) => {
                if (rotateYValue) rotateYValue.textContent = e.target.value + '\u00B0';
                applyTransform();
            });

            rotateZSlider?.addEventListener('input', (e) => {
                if (rotateZValue) rotateZValue.textContent = e.target.value + '\u00B0';
                applyTransform();
            });

            // Orientation presets: set the rotate sliders to a canonical angle and
            // dispatch 'input' so the readouts + applyTransform run. Unlike the View
            // tab's camera presets (which only move the camera), these feed the same
            // save/bake path (save-flow.js -> /save_modifications), so hitting Save
            // persists the rotation into the GLB and AR.
            function setRotateSlider(slider, valueEl, value) {
                if (!slider) return;
                slider.value = value;
                if (valueEl) valueEl.textContent = value + '\u00B0';
            }
            document.querySelectorAll('.transform-preset-btn').forEach((btn) => {
                btn.addEventListener('click', () => {
                    setRotateSlider(rotateXSlider, rotateXValue, parseInt(btn.dataset.rx, 10) || 0);
                    setRotateSlider(rotateYSlider, rotateYValue, parseInt(btn.dataset.ry, 10) || 0);
                    setRotateSlider(rotateZSlider, rotateZValue, parseInt(btn.dataset.rz, 10) || 0);
                    applyTransform(true);
                });
            });

            function resetTransformPreview() {
                if (scaleSlider) scaleSlider.value = 1;
                if (scaleInput) scaleInput.value = '1.0';
                if (rotateXSlider) rotateXSlider.value = 0;
                if (rotateYSlider) rotateYSlider.value = 0;
                if (rotateZSlider) rotateZSlider.value = 0;
                if (rotateXValue) rotateXValue.textContent = '0\u00B0';
                if (rotateYValue) rotateYValue.textContent = '0\u00B0';
                if (rotateZValue) rotateZValue.textContent = '0\u00B0';
                // Apply the reset values to the actual THREE.js scene (applyTransform
                // reads the sliders and calls forceModelViewerRefresh internally).
                applyTransform();
            }

            resetTransform?.addEventListener('click', resetTransformPreview);

            // The slicer (separate script block) neutralizes any unsaved
            // transform preview when a clip axis is enabled \u2014 its clip planes
            // are computed from the SAVED model's bounds, so a live scale/
            // rotation preview would make the cut appear in the wrong place.
            window._resetTransformPreview = () => {
                const active =
                    parseFloat(scaleSlider?.value || 1) !== 1 ||
                    parseFloat(rotateXSlider?.value || 0) !== 0 ||
                    parseFloat(rotateYSlider?.value || 0) !== 0 ||
                    parseFloat(rotateZSlider?.value || 0) !== 0;
                if (!active) return;
                resetTransformPreview();
            };

            transformEditorInitialized = true;
        }


        if (!transformEditorInitialized) initTransformEditor();
        loadDimensions();

        // Cross-file bridge: undo-redo.js snapshots/restores editor state
        // without knowing how the transform editor itself applies changes.
        window._captureTransformSnapshot = function() {
            return {
                scale: parseFloat(document.getElementById('scaleSlider')?.value ?? 1),
                rotateX: parseFloat(document.getElementById('rotateXSlider')?.value ?? 0),
                rotateY: parseFloat(document.getElementById('rotateYSlider')?.value ?? 0),
                rotateZ: parseFloat(document.getElementById('rotateZSlider')?.value ?? 0),
            };
        };
        window._applyTransformSnapshot = function(snap) {
            const scaleInput = document.getElementById('scaleInput');
            const scaleSlider = document.getElementById('scaleSlider');
            const rotateXSlider = document.getElementById('rotateXSlider');
            const rotateYSlider = document.getElementById('rotateYSlider');
            const rotateZSlider = document.getElementById('rotateZSlider');
            const rotateXValue = document.getElementById('rotateXValue');
            const rotateYValue = document.getElementById('rotateYValue');
            const rotateZValue = document.getElementById('rotateZValue');

            if (scaleSlider) scaleSlider.value = snap.scale;
            if (scaleInput) scaleInput.value = snap.scale.toFixed(1);
            if (rotateXSlider) rotateXSlider.value = snap.rotateX;
            if (rotateYSlider) rotateYSlider.value = snap.rotateY;
            if (rotateZSlider) rotateZSlider.value = snap.rotateZ;
            if (rotateXValue) rotateXValue.textContent = snap.rotateX + '°';
            if (rotateYValue) rotateYValue.textContent = snap.rotateY + '°';
            if (rotateZValue) rotateZValue.textContent = snap.rotateZ + '°';
            applyTransform();
        };
});
