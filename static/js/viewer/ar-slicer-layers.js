        document.addEventListener('DOMContentLoaded', () => {
            // Bare `modelViewer` references below used to resolve only through
            // the id="modelViewer" named-element global — bind it explicitly.
            const modelViewer = document.querySelector('model-viewer');
            // Get modal elements
            const arButton = document.querySelector('#arButton');
            const qrButton = document.querySelector('#qrButton');
            const arModal = document.querySelector('#arModal');
            const qrModal = document.querySelector('#qrModal');
            const closeArModal = document.querySelector('#closeArModal');
            const closeQrModal = document.querySelector('#closeQrModal');
            let qrcode = null;

            // Function to check if AR is supported
            function isARSupported() {
                return modelViewer && modelViewer.canActivateAR;
            }

            // Function to show AR modal with QR code. `reason` picks a
            // specific title/message so a failure is explained instead of
            // always showing the generic "not supported" copy -- WebXR/Scene
            // Viewer/Quick Look unsupported, iOS USDZ still converting, or
            // the AR session itself failing to start (commonly a denied
            // camera permission).
            const AR_MODAL_REASONS = {
                unsupported: {
                    title: 'AR Not Supported',
                    message: "Your device doesn't support AR. Scan the QR code with a mobile device.",
                },
                usdz_not_ready: {
                    title: 'iOS AR Still Preparing',
                    message: 'This model is still being prepared for iOS AR. Try again in a moment, or scan the QR code to open it on another device.',
                },
                session_failed: {
                    title: "AR Couldn't Start",
                    message: 'AR failed to start -- this usually means camera access was denied, or the AR session was interrupted. Check your camera permission and try again.',
                },
            };

            function showArModal(reason) {
                const arModal = document.getElementById('arModal');
                if (!arModal) return;
                const copy = AR_MODAL_REASONS[reason] || AR_MODAL_REASONS.unsupported;
                const titleEl = document.getElementById('arModalTitle');
                const messageEl = document.getElementById('arModalMessage');
                if (titleEl) titleEl.textContent = copy.title;
                if (messageEl) messageEl.textContent = copy.message;
                arModal.classList.add('show');
                document.getElementById('arButton')?.classList.add('is-active');
                const qrContainer = document.getElementById('arModalQrCode');
                if (qrContainer) {
                    qrContainer.innerHTML = '';
                    new QRCode(qrContainer, {
                        text: window.location.href,
                        width: 200,
                        height: 200,
                        colorDark: '#000000',
                        colorLight: '#ffffff'
                    });
                }
            }

            // Function to hide AR modal
            function hideArModal() {
                document.getElementById('arModal')?.classList.remove('show');
                document.getElementById('arButton')?.classList.remove('is-active');
            }

            // Close on overlay click (the close button itself is wired below)
            document.getElementById('arModal')?.addEventListener('click', function(e) {
                if (e.target === this) hideArModal();
            });

            // Function to show QR modal
            function showQRModal() {
                fetch('/api/models/' + window.VIEWER_CONFIG.modelDbId + '/events', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({event_type: 'qr_open'})
                }).catch(() => {});
                const el = document.getElementById('qrcode');
                if (qrcode) { qrcode.clear(); el.innerHTML = ''; }
                qrcode = new QRCode(el, {
                    text: window.location.href,
                    width: 120,
                    height: 120,
                    colorDark: '#000000',
                    colorLight: '#ffffff',
                    correctLevel: QRCode.CorrectLevel.H
                });
                qrModal.classList.add('show');
                document.getElementById('qrButton')?.classList.add('is-active');
            }

            // Function to hide QR modal
            function hideQRModal() {
                qrModal.classList.remove('show');
                document.getElementById('qrButton')?.classList.remove('is-active');
            }

            // Close on overlay click
            qrModal?.addEventListener('click', function(e) {
                if (e.target === this) hideQRModal();
            });

            // Tracked by the USDZ status check below; used to pick a
            // reason-specific message when AR can't launch on an iOS device
            // (Quick Look needs a converted USDZ, which lags the GLB).
            const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
            let usdzReady = true;

            // Event Listeners
            arButton?.addEventListener('click', () => {
                fetch('/api/models/' + window.VIEWER_CONFIG.modelDbId + '/events', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({event_type: 'ar_launch'})
                }).catch(() => {});
                if (!isARSupported()) {
                    showArModal(isIOS && !usdzReady ? 'usdz_not_ready' : 'unsupported');
                } else {
                    modelViewer.activateAR();
                }
            });

            // model-viewer fires this on every AR state transition; 'failed'
            // covers a denied camera permission and any other session start
            // failure the browser doesn't expose a more specific reason for.
            modelViewer?.addEventListener('ar-status', (event) => {
                if (event.detail && event.detail.status === 'failed') {
                    showArModal('session_failed');
                }
            });

            qrButton?.addEventListener('click', showQRModal);
            closeArModal?.addEventListener('click', hideArModal);
            closeQrModal?.addEventListener('click', hideQRModal);

            // ===== USDZ STATUS CHECK (iOS AR) =====
            (function checkUsdzStatus() {
                fetch('/api/models/' + window.VIEWER_CONFIG.modelId + '/usdz_status')
                .then(r => r.json())
                .then(data => {
                    if (data.success && !data.usdz_ready) {
                        usdzReady = false;
                        // Show subtle indicator on AR button
                        const arBtn = document.getElementById('arButton');
                        if (arBtn) {
                            arBtn.title = 'View in AR (iOS AR converting...)';
                            const badge = document.createElement('span');
                            badge.id = 'usdzBadge';
                            badge.style.cssText = 'position:absolute;top:-2px;right:-2px;width:8px;height:8px;background:#f59e0b;border-radius:50%;border:1.5px solid var(--color-gray-900);';
                            badge.title = 'iOS AR (USDZ) is still being prepared';
                            arBtn.style.position = 'relative';
                            arBtn.appendChild(badge);
                            // Re-check after 30 seconds
                            setTimeout(() => {
                                fetch('/api/models/' + window.VIEWER_CONFIG.modelId + '/usdz_status')
                                .then(r => r.json())
                                .then(d => {
                                    if (d.success && d.usdz_ready) {
                                        usdzReady = true;
                                        document.getElementById('usdzBadge')?.remove();
                                        arBtn.title = 'View in AR';
                                    } else if (d.success && !d.usdz_ready) {
                                        const b = document.getElementById('usdzBadge');
                                        if (b) { b.style.background = '#ef4444'; b.title = 'iOS AR (USDZ) conversion may have failed'; }
                                        arBtn.title = 'View in AR (iOS AR may not be available)';
                                    }
                                }).catch(() => {});
                            }, 30000);
                        }
                    }
                }).catch(() => {});
            })();

            // ===== MULTI-AXIS SLICER (Panel-based, 3 independent axes) =====
            let meshBounds = null;
            let isClippingEnabled = false;

            // Per-axis state: { enabled, side, value, plane }
            const slicerAxes = {
                x: { enabled: false, side: 'positive', value: 0, plane: null },
                y: { enabled: false, side: 'positive', value: 0, plane: null },
                z: { enabled: false, side: 'positive', value: 0, plane: null }
            };

            // --- Model-viewer THREE.js internals ---
            let _mvRenderer = null;     // THREE.WebGLRenderer
            let _mvScene = null;        // THREE.Scene
            let _mvCamera = null;       // THREE.Camera
            let _InternalVector3 = null;
            let _InternalMatrix4 = null;
            let _internalsReady = false;

            let _discoveryAttempts = 0;
            const MAX_DISCOVERY_ATTEMPTS = 30;

            function discoverInternals() {
                if (_internalsReady) return true;
                _discoveryAttempts++;
                if (_discoveryAttempts > MAX_DISCOVERY_ATTEMPTS) return false;

                const mv = document.querySelector('model-viewer');
                if (!mv) return false;

                const symbols = Object.getOwnPropertySymbols(mv);

                // Helper: check if obj is a THREE.WebGLRenderer
                function isWebGLRenderer(obj) {
                    return obj && obj.domElement instanceof HTMLCanvasElement &&
                           typeof obj.render === 'function' && typeof obj.setSize === 'function';
                }

                // Helper: deep search for renderer in an object (max 3 levels)
                function findRendererDeep(obj, depth, visited) {
                    if (!obj || typeof obj !== 'object' || depth > 3) return null;
                    if (visited.has(obj)) return null;
                    visited.add(obj);

                    if (isWebGLRenderer(obj)) return obj;
                    if (obj.threeRenderer && isWebGLRenderer(obj.threeRenderer)) return obj.threeRenderer;

                    // Search own properties (named + symbols)
                    const keys = [];
                    try { keys.push(...Object.getOwnPropertyNames(obj)); } catch(e) {}
                    try { keys.push(...Object.getOwnPropertySymbols(obj)); } catch(e) {}

                    for (const key of keys) {
                        try {
                            const nested = obj[key];
                            if (nested && typeof nested === 'object') {
                                const found = findRendererDeep(nested, depth + 1, visited);
                                if (found) return found;
                            }
                        } catch(e) {}
                    }
                    return null;
                }

                // --- Pass 1: Search symbol values on model-viewer element ---
                for (const s of symbols) {
                    let val;
                    try { val = mv[s]; } catch(e) { continue; }
                    if (!val || typeof val !== 'object') continue;

                    // Scene
                    if (!_mvScene) {
                        if (val.isScene || (val.traverse && val.children && val.background !== undefined)) {
                            _mvScene = val;
                        } else if (val.scene && val.scene.traverse) {
                            _mvScene = val.scene;
                        }
                    }

                    // Renderer (shallow check first)
                    if (!_mvRenderer) {
                        if (isWebGLRenderer(val)) {
                            _mvRenderer = val;
                        } else if (val.threeRenderer && isWebGLRenderer(val.threeRenderer)) {
                            _mvRenderer = val.threeRenderer;
                        } else if (val.renderer && isWebGLRenderer(val.renderer)) {
                            _mvRenderer = val.renderer;
                        }
                    }
                }

                // --- Pass 2: Deep search for renderer through symbol values ---
                if (!_mvRenderer) {
                    const visited = new Set();
                    for (const s of symbols) {
                        let val;
                        try { val = mv[s]; } catch(e) { continue; }
                        if (!val || typeof val !== 'object') continue;
                        const found = findRendererDeep(val, 0, visited);
                        if (found) {
                            _mvRenderer = found;
                            console.log('[Slicer] Found renderer via deep search in symbol:', s.description);
                            break;
                        }
                    }
                }

                // --- Pass 3: Find renderer via shadow DOM canvas ---
                if (!_mvRenderer) {
                    const canvas = mv.shadowRoot?.querySelector('canvas');
                    if (canvas) {
                        const visited = new Set();
                        for (const s of symbols) {
                            let val;
                            try { val = mv[s]; } catch(e) { continue; }
                            if (!val || typeof val !== 'object') continue;
                            // Deep search specifically matching domElement === canvas
                            const found = findRendererDeep(val, 0, visited);
                            if (found && found.domElement === canvas) {
                                _mvRenderer = found;
                                console.log('[Slicer] Found renderer via canvas match');
                                break;
                            }
                        }
                    }
                }

                // --- Pass 4: Search scene for renderer reference ---
                if (!_mvRenderer && _mvScene) {
                    const visited = new Set();
                    const found = findRendererDeep(_mvScene, 0, visited);
                    if (found) {
                        _mvRenderer = found;
                        console.log('[Slicer] Found renderer via scene properties');
                    }
                }

                // --- Find camera ---
                if (_mvScene && !_mvCamera) {
                    _mvScene.traverse(node => {
                        if (_mvCamera) return;
                        if (node.isPerspectiveCamera || node.isOrthographicCamera || node.isCamera) {
                            _mvCamera = node;
                        }
                    });
                }
                if (!_mvCamera) {
                    for (const s of symbols) {
                        let val;
                        try { val = mv[s]; } catch(e) { continue; }
                        if (val && (val.isPerspectiveCamera || val.isCamera)) {
                            _mvCamera = val; break;
                        }
                        if (val && val.camera && val.camera.isCamera) {
                            _mvCamera = val.camera; break;
                        }
                    }
                }

                // --- Extract THREE constructors ---
                if (_mvScene && !_InternalVector3) {
                    _mvScene.traverse(node => {
                        if (_InternalVector3) return;
                        if (node.position && node.position.constructor) {
                            _InternalVector3 = node.position.constructor;
                            _InternalMatrix4 = node.matrixWorld.constructor;
                        }
                    });
                }

                // Scene is required; renderer is optional (shader clipping works without it)
                _internalsReady = !!_mvScene;

                if (_discoveryAttempts <= 3 || _internalsReady) {
                    console.log('[Slicer] Discovery (attempt ' + _discoveryAttempts + '):', {
                        renderer: !!_mvRenderer,
                        scene: !!_mvScene,
                        camera: !!_mvCamera,
                        ready: _internalsReady
                    });
                }

                return _internalsReady;
            }

            // Expose on window so first DOMContentLoaded scope can call it
            window._slicerDiscoverInternals = discoverInternals;

            // Shared accessor for other viewer features (e.g. the measure tool's
            // wireframe overlay + vertex snap) that also need model-viewer's
            // undocumented internal THREE scene. Runs the same lazy discovery on
            // demand and returns the live objects + scavenged constructors, or
            // null if discovery fails -- callers must guard and degrade.
            window._getMvInternals = function () {
                if (!discoverInternals()) return null;
                return {
                    scene: _mvScene,
                    camera: _mvCamera,
                    Vector3: _InternalVector3,
                    Matrix4: _InternalMatrix4,
                };
            };

            // ---- Shader-based clipping (bypasses renderer.localClippingEnabled) ----
            // We inject custom clipping code directly into material shaders via onBeforeCompile.
            // This works even when we can't access the renderer object.

            const _patchedMaterials = new Set();
            const _originalSides = new Map();  // Store original material.side for restore

            // Global clip plane uniforms (shared across all materials)
            const _clipUniforms = {
                slicerPlaneNX: { value: [0, 0, 0] },  // plane normals (x components)
                slicerPlaneNY: { value: [0, 0, 0] },  // plane normals (y components)
                slicerPlaneNZ: { value: [0, 0, 0] },  // plane normals (z components)
                slicerPlaneD:  { value: [0, 0, 0] },   // plane constants
                slicerNumPlanes: { value: 0 }
            };

            function patchMaterialForClipping(mat) {
                // Always force DoubleSide so clipped back-faces are visible
                if (!_originalSides.has(mat.uuid)) {
                    _originalSides.set(mat.uuid, mat.side);
                }
                mat.side = 2; // THREE.DoubleSide
                mat.needsUpdate = true;

                if (_patchedMaterials.has(mat.uuid)) return;
                _patchedMaterials.add(mat.uuid);

                const origOBC = mat.onBeforeCompile;
                mat.onBeforeCompile = function(shader, renderer) {
                    if (origOBC) origOBC.call(mat, shader, renderer);

                    // Add our uniforms
                    shader.uniforms.slicerPlaneNX = _clipUniforms.slicerPlaneNX;
                    shader.uniforms.slicerPlaneNY = _clipUniforms.slicerPlaneNY;
                    shader.uniforms.slicerPlaneNZ = _clipUniforms.slicerPlaneNZ;
                    shader.uniforms.slicerPlaneD = _clipUniforms.slicerPlaneD;
                    shader.uniforms.slicerNumPlanes = _clipUniforms.slicerNumPlanes;

                    // Vertex shader: pass world-space position to fragment
                    // Uses modelMatrix to match the coordinate system of
                    // get_mesh_bounds (trimesh dump with concatenated transforms).
                    shader.vertexShader = shader.vertexShader.replace(
                        'void main() {',
                        'varying vec3 vSlicerWorldPos;\nvoid main() {'
                    );
                    if (shader.vertexShader.includes('#include <worldpos_vertex>')) {
                        shader.vertexShader = shader.vertexShader.replace(
                            '#include <worldpos_vertex>',
                            '#include <worldpos_vertex>\nvSlicerWorldPos = (modelMatrix * vec4(transformed, 1.0)).xyz;'
                        );
                    } else if (shader.vertexShader.includes('#include <fog_vertex>')) {
                        shader.vertexShader = shader.vertexShader.replace(
                            '#include <fog_vertex>',
                            'vSlicerWorldPos = (modelMatrix * vec4(transformed, 1.0)).xyz;\n#include <fog_vertex>'
                        );
                    } else {
                        shader.vertexShader = shader.vertexShader.replace(
                            /}\s*$/,
                            'vSlicerWorldPos = (modelMatrix * vec4(transformed, 1.0)).xyz;\n}'
                        );
                    }

                    // Fragment shader: discard fragments outside clip planes
                    shader.fragmentShader = shader.fragmentShader.replace(
                        'void main() {',
                        `varying vec3 vSlicerWorldPos;
uniform float slicerPlaneNX[3];
uniform float slicerPlaneNY[3];
uniform float slicerPlaneNZ[3];
uniform float slicerPlaneD[3];
uniform int slicerNumPlanes;
void main() {
  for (int i = 0; i < 3; i++) {
    if (i >= slicerNumPlanes) break;
    float d = vSlicerWorldPos.x * slicerPlaneNX[i] + vSlicerWorldPos.y * slicerPlaneNY[i] + vSlicerWorldPos.z * slicerPlaneNZ[i] + slicerPlaneD[i];
    if (d < 0.0) discard;
  }
`
                    );
                };

                // Force shader recompilation (dynamic key so toggling on/off recompiles)
                let _slicerCacheVersion = 1;
                mat.customProgramCacheKey = function() {
                    return 'slicer-v' + _slicerCacheVersion + '-p' + _clipUniforms.slicerNumPlanes.value;
                };
                mat.needsUpdate = true;
            }

            // Build clip plane data from current slicer state
            function buildClipPlaneData() {
                const nx = [0, 0, 0], ny = [0, 0, 0], nz = [0, 0, 0], d = [0, 0, 0];
                let count = 0;
                for (const axis of ['x', 'y', 'z']) {
                    const state = slicerAxes[axis];
                    if (!state.enabled) continue;
                    const sign = state.side === 'negative' ? -1 : 1;
                    nx[count] = axis === 'x' ? sign : 0;
                    ny[count] = axis === 'y' ? sign : 0;
                    nz[count] = axis === 'z' ? sign : 0;
                    d[count] = -state.value * sign;
                    count++;
                }
                return { nx, ny, nz, d, count };
            }

            // Apply clipping via shader injection
            function applyClippingPlanes() {
                discoverInternals();
                const _slicerWarnEl = document.getElementById('slicerPreviewWarn');
                if (!_mvScene) {
                    console.error('[Slicer] Scene not ready yet');
                    // The scene may just not be ready yet (render pump retries discovery).
                    // Only surface a warning if it's STILL unreachable shortly after.
                    if (!_previewWarnTimer) {
                        _previewWarnTimer = setTimeout(() => {
                            _previewWarnTimer = null;
                            discoverInternals();
                            if (!_mvScene && _slicerWarnEl) _slicerWarnEl.classList.remove('hidden');
                        }, 1200);
                    }
                    return;
                }
                if (_slicerWarnEl) _slicerWarnEl.classList.add('hidden');

                // Patch all mesh materials with our custom shader clipping
                let meshCount = 0;
                _mvScene.traverse(child => {
                    if (child.isMesh && child.material) {
                        const mats = Array.isArray(child.material) ? child.material : [child.material];
                        mats.forEach(mat => patchMaterialForClipping(mat));
                        meshCount++;
                    }
                });

                // Update uniform values
                const clip = buildClipPlaneData();
                _clipUniforms.slicerPlaneNX.value = clip.nx;
                _clipUniforms.slicerPlaneNY.value = clip.ny;
                _clipUniforms.slicerPlaneNZ.value = clip.nz;
                _clipUniforms.slicerPlaneD.value = clip.d;
                _clipUniforms.slicerNumPlanes.value = clip.count;

                isClippingEnabled = clip.count > 0;
                console.log('[Slicer] Applied', clip.count, 'shader clip planes to', meshCount, 'meshes');

                // Also try native clipping if renderer is available
                if (_mvRenderer) {
                    _mvRenderer.localClippingEnabled = true;
                }

                // Force model-viewer to re-render
                forceModelViewerRender();
                if (isClippingEnabled) startRenderPump();
            }

            // Update a single axis (called on slider input)
            function updateAxisPlane(axis) {
                // State is already updated in slicerAxes by caller
                // Just update the shared uniforms
                const clip = buildClipPlaneData();
                _clipUniforms.slicerPlaneNX.value = clip.nx;
                _clipUniforms.slicerPlaneNY.value = clip.ny;
                _clipUniforms.slicerPlaneNZ.value = clip.nz;
                _clipUniforms.slicerPlaneD.value = clip.d;
                _clipUniforms.slicerNumPlanes.value = clip.count;
            }

            // While the user is dragging to orbit/zoom, model-viewer already
            // re-renders every frame on its own, so the fallback camera-nudge
            // below is unnecessary then -- and actively harmful: setting
            // cameraOrbit + jumpCameraToGoal every frame fought the user's drag,
            // so the model barely rotated with the slicer open. Track active
            // interaction and skip the nudge during it.
            let _userInteractingWithCamera = false;
            (function trackCameraInteraction() {
                const mv = document.querySelector('model-viewer');
                if (!mv) return;
                const start = () => { _userInteractingWithCamera = true; };
                const end = () => { _userInteractingWithCamera = false; };
                mv.addEventListener('pointerdown', start);
                window.addEventListener('pointerup', end);
                window.addEventListener('pointercancel', end);
                // Wheel-zoom has no pointerup; clear shortly after the last wheel.
                let wheelTimer = null;
                mv.addEventListener('wheel', () => {
                    _userInteractingWithCamera = true;
                    clearTimeout(wheelTimer);
                    wheelTimer = setTimeout(end, 200);
                }, { passive: true });
            })();

            // Force model-viewer to re-render (works with or without renderer access)
            let _nudgeDirection = 1;
            function forceModelViewerRender() {
                // Method 1: Direct render if we have full access
                if (_mvRenderer && _mvScene && _mvCamera) {
                    _mvScene.updateMatrixWorld(true);
                    _mvRenderer.render(_mvScene, _mvCamera);
                    return;
                }

                // Method 2: Nudge camera to trigger model-viewer's internal render
                // Alternates direction to prevent drift. Skipped during user
                // interaction (model-viewer renders every frame then anyway).
                if (_userInteractingWithCamera) return;
                const mv = document.querySelector('model-viewer');
                if (mv) {
                    try {
                        const orbit = mv.getCameraOrbit();
                        if (orbit) {
                            _nudgeDirection *= -1;
                            const nudge = _nudgeDirection * 0.0001;
                            mv.cameraOrbit = (orbit.theta + nudge) + 'rad ' + orbit.phi + 'rad ' + orbit.radius + 'm';
                            mv.jumpCameraToGoal();
                        }
                    } catch(e) {}
                }
            }

            // Deferred "preview unavailable" warning timer (avoids false alarms while
            // model-viewer's internal scene is still initialising).
            let _previewWarnTimer = null;

            // Render pump - continuously re-renders while clipping is active
            let _renderPumpId = null;
            function startRenderPump() {
                if (_renderPumpId) return;
                let frameCount = 0;
                function pump() {
                    if (!isClippingEnabled) { _renderPumpId = null; return; }

                    // Keep trying to discover renderer on first few frames
                    if (!_mvRenderer && frameCount < 10) {
                        discoverInternals();
                    }

                    forceModelViewerRender();
                    frameCount++;
                    _renderPumpId = requestAnimationFrame(pump);
                }
                _renderPumpId = requestAnimationFrame(pump);
            }

            // A backgrounded tab gets no rAF, but on return the pump must resume
            // (and if the browser DOES keep ticking rAF, don't render unseen
            // frames at full speed forever while a preview is just left open).
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    if (_renderPumpId) { cancelAnimationFrame(_renderPumpId); _renderPumpId = null; }
                } else if (isClippingEnabled) {
                    startRenderPump();
                }
            });

            // Cross-script-block hooks: the annotations code (separate scope)
            // needs to know whether a clip preview is active, and the material
            // editor re-applies clipping after material changes so recompiled/
            // replaced materials regain the clip shader patch.
            window._slicerClippingActive = () => isClippingEnabled;
            window._reapplyClipping = () => { if (isClippingEnabled) applyClippingPlanes(); };

            // ===== LAYERS PANEL (visibility, per-layer color, explode) =====
            // Reuses the THREE internals discovered above for the slicer —
            // no server round-trip needed to enumerate a model's parts.
            let modelLayers = [];
            let layersBuiltForModel = false;
            let layersExplodeDiagonal = 1;

            function getMvMaterialsForLayers() {
                try { return document.querySelector('model-viewer')?.model?.materials || []; } catch (e) { return []; }
            }

            function layersRgbToHex(r, g, b) {
                const c = v => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0');
                return '#' + c(r) + c(g) + c(b);
            }

            function layersHexToRgb(hex) {
                hex = hex.replace('#', '');
                return [
                    parseInt(hex.substring(0, 2), 16) / 255,
                    parseInt(hex.substring(2, 4), 16) / 255,
                    parseInt(hex.substring(4, 6), 16) / 255
                ];
            }

            async function buildLayersList() {
                if (layersBuiltForModel) return;
                if (!discoverInternals() || !_mvScene) return;

                const meshes = [];
                _mvScene.traverse(child => {
                    if (child.isMesh && child.geometry && child.geometry.attributes && child.geometry.attributes.position) {
                        meshes.push(child);
                    }
                });

                // A single-part model (e.g. any STL — always flattened to one mesh
                // by the converter) has nothing to break into layers.
                if (meshes.length <= 1) return;

                layersBuiltForModel = true;
                _mvScene.updateMatrixWorld(true);

                const mvMats = getMvMaterialsForLayers();
                await Promise.all(mvMats.map(m => { try { return m.ensureLoaded ? m.ensureLoaded() : null; } catch (e) { return null; } }));

                // Count how many layers reference each material NAME so a color
                // change can target the public per-material API when a material
                // belongs to exactly one layer, and safely fall back to cloning
                // the THREE material when several layers share one material.
                const matNameCounts = {};
                meshes.forEach(mesh => {
                    const mat = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
                    const matName = mat?.name || '';
                    if (matName) matNameCounts[matName] = (matNameCounts[matName] || 0) + 1;
                });

                // World-space bounds of the whole model (union of every mesh's
                // local bbox corners transformed to world space) — used to scale
                // the explode offsets and to derive each layer's explode direction.
                let worldMin = [Infinity, Infinity, Infinity];
                let worldMax = [-Infinity, -Infinity, -Infinity];
                meshes.forEach(mesh => {
                    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
                    const bb = mesh.geometry.boundingBox;
                    for (let xi = 0; xi <= 1; xi++) for (let yi = 0; yi <= 1; yi++) for (let zi = 0; zi <= 1; zi++) {
                        const corner = new _InternalVector3(
                            xi ? bb.max.x : bb.min.x,
                            yi ? bb.max.y : bb.min.y,
                            zi ? bb.max.z : bb.min.z
                        ).applyMatrix4(mesh.matrixWorld);
                        worldMin[0] = Math.min(worldMin[0], corner.x); worldMax[0] = Math.max(worldMax[0], corner.x);
                        worldMin[1] = Math.min(worldMin[1], corner.y); worldMax[1] = Math.max(worldMax[1], corner.y);
                        worldMin[2] = Math.min(worldMin[2], corner.z); worldMax[2] = Math.max(worldMax[2], corner.z);
                    }
                });
                const modelCenter = new _InternalVector3(
                    (worldMin[0] + worldMax[0]) / 2,
                    (worldMin[1] + worldMax[1]) / 2,
                    (worldMin[2] + worldMax[2]) / 2
                );
                const dx = worldMax[0] - worldMin[0], dy = worldMax[1] - worldMin[1], dz = worldMax[2] - worldMin[2];
                layersExplodeDiagonal = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;

                const occurrenceCounts = {};
                modelLayers = meshes.map((mesh, idx) => {
                    const rawNodeName = mesh.name || '';
                    const occurrence = occurrenceCounts[rawNodeName] || 0;
                    occurrenceCounts[rawNodeName] = occurrence + 1;
                    const displayName = mesh.name || mesh.parent?.name || ('Layer ' + (idx + 1));

                    const mat = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
                    const matName = mat?.name || '';
                    const isExclusive = !!matName && matNameCounts[matName] === 1;
                    const mvMaterial = isExclusive ? (mvMats.find(m => m.name === matName) || null) : null;

                    let origColorHex = '#ffffff';
                    try {
                        if (mvMaterial) {
                            const cf = mvMaterial.pbrMetallicRoughness?.baseColorFactor || [1, 1, 1, 1];
                            origColorHex = layersRgbToHex(cf[0], cf[1], cf[2]);
                        } else if (mat && mat.color) {
                            origColorHex = '#' + mat.color.getHexString();
                        }
                    } catch (e) { /* material not loaded yet — keep default swatch */ }

                    const localCenter = new _InternalVector3(
                        (mesh.geometry.boundingBox.min.x + mesh.geometry.boundingBox.max.x) / 2,
                        (mesh.geometry.boundingBox.min.y + mesh.geometry.boundingBox.max.y) / 2,
                        (mesh.geometry.boundingBox.min.z + mesh.geometry.boundingBox.max.z) / 2
                    );
                    const worldCenter = localCenter.clone().applyMatrix4(mesh.matrixWorld);
                    const dirWorld = worldCenter.clone().sub(modelCenter).normalize();

                    return {
                        node: mesh,
                        rawNodeName: rawNodeName,
                        occurrence: occurrence,
                        name: displayName,
                        origVisible: mesh.visible,
                        origLocalPos: mesh.position.clone(),
                        origWorldPos: new _InternalVector3().setFromMatrixPosition(mesh.matrixWorld),
                        dirWorld: dirWorld,
                        matMode: mvMaterial ? 'exclusive' : 'clone',
                        mvMaterial: mvMaterial,
                        origColorHex: origColorHex,
                        colorChanged: false
                    };
                });

                renderLayersList();

                // An active AnimationMixer overwrites node transforms every
                // frame, so explode (which offsets node.position) can't coexist
                // with playback — disable the slider on animated models instead
                // of showing an effect that instantly snaps back.
                const mv = document.querySelector('model-viewer');
                const hasAnims = (mv?.availableAnimations || []).length > 0;
                const explodeSliderEl = document.getElementById('explodeSlider');
                const explodeAnimNoteEl = document.getElementById('explodeAnimNote');
                if (hasAnims) {
                    explodeSliderEl?.setAttribute('disabled', 'disabled');
                    explodeAnimNoteEl?.classList.remove('hidden');
                } else {
                    explodeSliderEl?.removeAttribute('disabled');
                    explodeAnimNoteEl?.classList.add('hidden');
                }
            }

            function renderLayersList() {
                const container = document.getElementById('layersContainer');
                const list = document.getElementById('layersList');
                if (!list || !container) return;
                if (modelLayers.length === 0) { container.classList.add('hidden'); return; }
                container.classList.remove('hidden');

                list.innerHTML = '';
                modelLayers.forEach((layer, i) => {
                    const row = document.createElement('div');
                    row.style.cssText = 'display:flex;align-items:center;gap:0.4rem;padding:0.25rem 0.35rem;background:var(--color-gray-800);border:1px solid var(--color-gray-700);';
                    row.innerHTML =
                        '<button type="button" class="layer-vis-btn" data-idx="' + i + '" style="background:none;border:none;color:var(--color-gray-300);cursor:pointer;display:flex;padding:0;">' +
                            '<i data-lucide="eye" class="layer-eye-on' + (layer.node.visible ? '' : ' hidden') + '" style="width:0.85rem;height:0.85rem;"></i>' +
                            '<i data-lucide="eye-off" class="layer-eye-off' + (layer.node.visible ? ' hidden' : '') + '" style="width:0.85rem;height:0.85rem;"></i>' +
                        '</button>' +
                        '<span style="flex:1;font-size:0.72rem;color:var(--color-gray-200);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + window.escapeHtml(layer.name) + '</span>' +
                        '<input type="color" class="tp-color-swatch layer-color-input" data-idx="' + i + '" value="' + window.escapeHtml(layer.origColorHex) + '" style="width:1.6rem;height:1.6rem;padding:0;">';
                    list.appendChild(row);
                });
                if (window.lucide?.createIcons) lucide.createIcons();

                list.querySelectorAll('.layer-vis-btn').forEach(btn => {
                    btn.addEventListener('click', () => toggleLayerVisibility(parseInt(btn.dataset.idx, 10)));
                });
                list.querySelectorAll('.layer-color-input').forEach(inp => {
                    inp.addEventListener('input', (e) => applyLayerColor(parseInt(inp.dataset.idx, 10), e.target.value));
                });
            }

            function toggleLayerVisibility(i) {
                const layer = modelLayers[i];
                if (!layer) return;
                layer.node.visible = !layer.node.visible;
                const btn = document.querySelector('.layer-vis-btn[data-idx="' + i + '"]');
                btn?.querySelector('.layer-eye-on')?.classList.toggle('hidden', !layer.node.visible);
                btn?.querySelector('.layer-eye-off')?.classList.toggle('hidden', layer.node.visible);
                forceModelViewerRender();
            }

            function applyLayerColor(i, hex) {
                const layer = modelLayers[i];
                if (!layer) return;
                layer.colorChanged = true;
                const rgb = layersHexToRgb(hex);
                if (layer.matMode === 'exclusive' && layer.mvMaterial) {
                    try {
                        const currentAlpha = layer.mvMaterial.pbrMetallicRoughness?.baseColorFactor?.[3] ?? 1;
                        layer.mvMaterial.pbrMetallicRoughness.setBaseColorFactor([rgb[0], rgb[1], rgb[2], currentAlpha]);
                    } catch (e) { console.warn('[Layers] color apply failed', e); }
                } else {
                    // Material shared by multiple layers (or not publicly
                    // addressable) — clone it client-side once so recoloring
                    // this layer can never bleed into a sibling layer.
                    const mesh = layer.node;
                    if (!mesh.userData._layerMaterialCloned) {
                        mesh.material = Array.isArray(mesh.material) ? mesh.material.map(m => m.clone()) : mesh.material.clone();
                        mesh.userData._layerMaterialCloned = true;
                    }
                    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
                    mats.forEach(m => { if (m.color) { m.color.setRGB(rgb[0], rgb[1], rgb[2]); m.needsUpdate = true; } });
                    // A cloned material can lose the slicer's clip-shader patch —
                    // same reasoning as the global material editor (see markMaterialChanged).
                    window._reapplyClipping?.();
                }
                forceModelViewerRender();
            }

            function applyExplode(t) {
                modelLayers.forEach(layer => {
                    if (!layer.node.parent) return;
                    const worldTarget = layer.origWorldPos.clone().add(
                        layer.dirWorld.clone().multiplyScalar(t * layersExplodeDiagonal * 0.5)
                    );
                    const parentInv = new _InternalMatrix4().copy(layer.node.parent.matrixWorld).invert();
                    layer.node.position.copy(worldTarget.applyMatrix4(parentInv));
                });
                _mvScene.updateMatrixWorld(true);
                forceModelViewerRender();
            }

            document.getElementById('explodeSlider')?.addEventListener('input', (e) => {
                const t = parseFloat(e.target.value);
                const explodeValueEl = document.getElementById('explodeValue');
                if (explodeValueEl) explodeValueEl.textContent = Math.round(t * 100) + '%';
                if (t > 0) {
                    const mv = document.querySelector('model-viewer');
                    if ((mv?.availableAnimations || []).length > 0) mv.pause();
                }
                applyExplode(t);
                document.getElementById('saveExplodedLayout')?.classList.toggle('hidden', t <= 0);
            });

            document.getElementById('resetLayers')?.addEventListener('click', () => {
                modelLayers.forEach(layer => {
                    layer.node.visible = layer.origVisible;
                    layer.node.position.copy(layer.origLocalPos);
                    layer.colorChanged = false;
                    const rgb = layersHexToRgb(layer.origColorHex);
                    if (layer.matMode === 'exclusive' && layer.mvMaterial) {
                        try {
                            const alpha = layer.mvMaterial.pbrMetallicRoughness?.baseColorFactor?.[3] ?? 1;
                            layer.mvMaterial.pbrMetallicRoughness.setBaseColorFactor([rgb[0], rgb[1], rgb[2], alpha]);
                        } catch (e) { /* not loaded */ }
                    } else if (layer.node.userData._layerMaterialCloned) {
                        const mats = Array.isArray(layer.node.material) ? layer.node.material : [layer.node.material];
                        mats.forEach(m => { if (m.color) { m.color.setRGB(rgb[0], rgb[1], rgb[2]); m.needsUpdate = true; } });
                    }
                });
                _mvScene.updateMatrixWorld(true);
                const explodeSliderEl = document.getElementById('explodeSlider');
                const explodeValueEl = document.getElementById('explodeValue');
                if (explodeSliderEl) explodeSliderEl.value = 0;
                if (explodeValueEl) explodeValueEl.textContent = '0%';
                document.getElementById('saveExplodedLayout')?.classList.add('hidden');
                renderLayersList();
                window._reapplyClipping?.();
                forceModelViewerRender();
            });

            // Called from the "Save Exploded Layout" button (separate script
            // scope) to bake the CURRENT explode offsets as permanent node
            // translations. Unlike _layersGatherMods, this is never included
            // in the default Save & Apply to AR payload — explode only
            // becomes permanent when the user explicitly asks for it.
            window._layersGatherExplodeMods = function() {
                const t = parseFloat(document.getElementById('explodeSlider')?.value || 0);
                if (!modelLayers.length || !(t > 0)) return null;
                const positions = modelLayers.map(layer => ({
                    name: layer.rawNodeName,
                    occurrence: layer.occurrence,
                    translation: [layer.node.position.x, layer.node.position.y, layer.node.position.z]
                }));
                return { positions: positions };
            };

            // Called from the save-changes flow (separate script scope) to
            // collect per-layer state to persist into the GLB. Returns null
            // when nothing was changed from the model's loaded state.
            window._layersGatherMods = function() {
                if (!modelLayers.length) return null;
                const hidden = [];
                const colors = [];
                modelLayers.forEach(layer => {
                    if (!layer.node.visible) {
                        hidden.push({ name: layer.rawNodeName, occurrence: layer.occurrence });
                    }
                    if (layer.colorChanged) {
                        let hex = layer.origColorHex;
                        try {
                            if (layer.matMode === 'exclusive' && layer.mvMaterial) {
                                const cf = layer.mvMaterial.pbrMetallicRoughness?.baseColorFactor || [1, 1, 1, 1];
                                hex = layersRgbToHex(cf[0], cf[1], cf[2]);
                            } else {
                                const mat = Array.isArray(layer.node.material) ? layer.node.material[0] : layer.node.material;
                                if (mat?.color) hex = '#' + mat.color.getHexString();
                            }
                        } catch (e) { /* keep original hex */ }
                        colors.push({ name: layer.rawNodeName, occurrence: layer.occurrence, color: layersHexToRgb(hex) });
                    }
                });
                if (!hidden.length && !colors.length) return null;
                return { hidden: hidden, colors: colors };
            };

            window._buildLayersList = buildLayersList;

            function disableAllClipping() {
                for (const axis of ['x', 'y', 'z']) {
                    slicerAxes[axis].enabled = false;
                }
                isClippingEnabled = false;
                if (_renderPumpId) { cancelAnimationFrame(_renderPumpId); _renderPumpId = null; }

                // Reset shader uniforms to disable clipping
                _clipUniforms.slicerNumPlanes.value = 0;
                _clipUniforms.slicerPlaneNX.value = [0, 0, 0];
                _clipUniforms.slicerPlaneNY.value = [0, 0, 0];
                _clipUniforms.slicerPlaneNZ.value = [0, 0, 0];
                _clipUniforms.slicerPlaneD.value = [0, 0, 0];

                // Restore original material.side values
                if (_mvScene) {
                    _mvScene.traverse(child => {
                        if (child.isMesh && child.material) {
                            const mats = Array.isArray(child.material) ? child.material : [child.material];
                            mats.forEach(mat => {
                                if (_originalSides.has(mat.uuid)) {
                                    mat.side = _originalSides.get(mat.uuid);
                                    mat.needsUpdate = true;
                                }
                            });
                        }
                    });
                }

                if (_mvRenderer) _mvRenderer.localClippingEnabled = false;
                forceModelViewerRender();
            }

            // The History tab can swap the live model out from under this
            // tab via modelViewer.setAttribute('src', ...) (preview/exit an
            // older version) WITHOUT a full page reload. discoverInternals()
            // and buildLayersList() both permanently short-circuit once
            // they've succeeded once (_internalsReady / layersBuiltForModel
            // are never reset elsewhere), so without this they'd keep
            // pointing at the THREE.js scene graph of the model that was
            // just replaced — clip toggles and layer edits would silently
            // act on a detached, no-longer-rendered scene while the UI shows
            // a different model. Every model-viewer 'load' after the first
            // means the underlying model actually changed, so re-arm
            // discovery and drop any clip/layer state computed from the old
            // scene's bounds.
            let _slicerLayersModelLoaded = false;
            modelViewer?.addEventListener('load', () => {
                if (_slicerLayersModelLoaded) {
                    document.getElementById('slicerReset')?.click();
                    _internalsReady = false;
                    _mvScene = null;
                    _mvRenderer = null;
                    _mvCamera = null;
                    _discoveryAttempts = 0;
                    meshBounds = null;
                    layersBuiltForModel = false;
                    modelLayers = [];
                    const layersList = document.getElementById('layersList');
                    if (layersList) layersList.innerHTML = '';
                }
                _slicerLayersModelLoaded = true;
            });

            // Load mesh bounds and initialize slider UI for all axes
            async function loadMeshBounds() {
                if (meshBounds) return true;
                try {
                    const res = await fetch('/get_mesh_bounds/' + window.VIEWER_CONFIG.modelId);
                    const data = await res.json();
                    if (data.success) {
                        meshBounds = data.bounds;
                        return true;
                    }
                } catch (e) {
                    console.error('[Slicer] Failed to load mesh bounds:', e);
                }
                return false;
            }

            function initSliderForAxis(axis) {
                if (!meshBounds) return;
                const minVal = meshBounds.min[axis];
                const maxVal = meshBounds.max[axis];
                const centerVal = meshBounds.center[axis];

                const slider = document.querySelector('.slicer-slider[data-axis="' + axis + '"]');
                const minDisp = document.querySelector('.slicer-min[data-axis="' + axis + '"]');
                const maxDisp = document.querySelector('.slicer-max[data-axis="' + axis + '"]');
                const valDisp = document.querySelector('.slicer-val[data-axis="' + axis + '"]');

                if (slider) {
                    slider.min = minVal;
                    slider.max = maxVal;
                    slider.step = (maxVal - minVal) / 200;
                    slider.value = centerVal;
                }
                if (minDisp) minDisp.textContent = (minVal * 100).toFixed(1) + ' cm';
                if (maxDisp) maxDisp.textContent = (maxVal * 100).toFixed(1) + ' cm';
                if (valDisp) valDisp.textContent = (centerVal * 100).toFixed(1) + ' cm';

                slicerAxes[axis].value = centerVal;
            }

            // --- Panel Event Handlers ---

            // Axis toggle checkboxes
            document.querySelectorAll('.slicer-axis-toggle').forEach(cb => {
                cb.addEventListener('change', async (e) => {
                    const axis = e.target.dataset.axis;
                    const enabled = e.target.checked;

                    if (enabled && !meshBounds) {
                        const loaded = await loadMeshBounds();
                        if (!loaded) { e.target.checked = false; return; }
                        // Init all sliders on first load
                        for (const a of ['x', 'y', 'z']) initSliderForAxis(a);
                    }

                    slicerAxes[axis].enabled = enabled;

                    // Enable/disable slider
                    const slider = document.querySelector('.slicer-slider[data-axis="' + axis + '"]');
                    if (slider) slider.disabled = !enabled;

                    // Highlight border
                    const container = document.getElementById('slicerAxis' + axis.toUpperCase());
                    const colors = { x: 'border-red-500', y: 'border-green-500', z: 'border-blue-500' };
                    if (container) {
                        container.classList.toggle(colors[axis], enabled);
                        container.classList.toggle('border-gray-200', !enabled);
                        container.classList.toggle('dark:border-gray-600', !enabled);
                    }

                    // Set default side button highlight
                    if (enabled) {
                        const posBtn = document.querySelector('.slicer-side-btn[data-axis="' + axis + '"][data-side="positive"]');
                        if (posBtn) {
                            posBtn.classList.add('active');
                            posBtn.classList.remove('bg-gray-100', 'dark:bg-gray-700', 'text-gray-500');
                        }

                        // NOTE: the camera is intentionally NOT reset here. The
                        // clip planes are axis-aligned in the model's own space
                        // (see buildClipPlaneData) and applied in the shader by
                        // world position, so the cut is identical from any camera
                        // angle. Snapping the camera on slice-enable just yanked
                        // the model to a side view for no functional reason.

                        // The clip planes are computed from the SAVED model's
                        // bounds, but an unsaved transform preview (scale/rotate
                        // sliders) moves the geometry in world space — the
                        // preview would cut in the wrong place while the actual
                        // server slice stays in the model's own frame. Reset the
                        // preview so what you see is what gets cut.
                        window._resetTransformPreview?.();

                        // Shader clipping only HIDES geometry — raycasts still hit
                        // the clipped-away surfaces, so hotspot placement (and
                        // point measurement, same raycast-based hazard) while a
                        // slice preview is active lands pins on invisible faces.
                        window._disableHotspotMode?.();
                        window._disableMeasureMode?.();
                    }

                    updateAxisPlane(axis);
                    applyClippingPlanes();
                });
            });

            // Slider input - update clip plane uniforms and force re-render
            document.querySelectorAll('.slicer-slider').forEach(slider => {
                slider.addEventListener('input', (e) => {
                    const axis = e.target.dataset.axis;
                    const val = parseFloat(e.target.value);
                    slicerAxes[axis].value = val;

                    const valDisp = document.querySelector('.slicer-val[data-axis="' + axis + '"]');
                    if (valDisp) valDisp.textContent = (val * 100).toFixed(1) + ' cm';

                    // Apply clipping with updated value (ensures uniforms synced and pump running)
                    applyClippingPlanes();
                });
            });

            // Side buttons
            document.querySelectorAll('.slicer-side-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const axis = btn.dataset.axis;
                    const side = btn.dataset.side;
                    slicerAxes[axis].side = side;

                    // Update button highlights
                    document.querySelectorAll('.slicer-side-btn[data-axis="' + axis + '"]').forEach(b => {
                        b.classList.remove('active');
                        b.classList.add('bg-gray-100', 'dark:bg-gray-700', 'text-gray-500');
                    });
                    btn.classList.add('active');
                    btn.classList.remove('bg-gray-100', 'dark:bg-gray-700', 'text-gray-500');

                    if (slicerAxes[axis].enabled) {
                        updateAxisPlane(axis);
                        applyClippingPlanes();
                    }
                });
            });

            window.applySectionPreset = async function(axis, percent, side) {
                const toggle = document.querySelector('.slicer-axis-toggle[data-axis="' + axis + '"]');
                if (!toggle) return;
                if (!toggle.checked) {
                    toggle.checked = true;
                    toggle.dispatchEvent(new Event('change', {bubbles: true}));
                    await new Promise(resolve => setTimeout(resolve, 120));
                }
                const slider = document.querySelector('.slicer-slider[data-axis="' + axis + '"]');
                if (!slider) return;
                const min = parseFloat(slider.min), max = parseFloat(slider.max);
                slider.value = min + (max - min) * ((Number(percent) + 100) / 200);
                slider.dispatchEvent(new Event('input', {bubbles: true}));
                document.querySelector('.slicer-side-btn[data-axis="' + axis + '"][data-side="' + side + '"]')?.click();
            };

            // Reset button
            document.getElementById('slicerReset')?.addEventListener('click', () => {
                disableAllClipping();
                document.querySelectorAll('.slicer-axis-toggle').forEach(cb => { cb.checked = false; });
                document.querySelectorAll('.slicer-slider').forEach(sl => { sl.disabled = true; });
                for (const axis of ['x', 'y', 'z']) {
                    slicerAxes[axis].side = 'positive';
                    if (meshBounds) initSliderForAxis(axis);
                    const container = document.getElementById('slicerAxis' + axis.toUpperCase());
                    if (container) {
                        container.classList.remove('border-red-500', 'border-green-500', 'border-blue-500');
                        container.classList.add('border-gray-200', 'dark:border-gray-600');
                    }
                    // Reset side button highlights
                    document.querySelectorAll('.slicer-side-btn[data-axis="' + axis + '"]').forEach(b => {
                        b.classList.remove('active');
                        b.classList.add('bg-gray-100', 'dark:bg-gray-700', 'text-gray-500');
                    });
                }
            });

            // Apply slice - sends each enabled axis as a separate slice operation
            document.getElementById('slicerApply')?.addEventListener('click', async () => {
                const enabledAxes = ['x', 'y', 'z'].filter(a => slicerAxes[a].enabled);
                if (enabledAxes.length === 0) { alert('Enable at least one axis to slice.'); return; }

                const applyBtn = document.getElementById('slicerApply');
                const spinner = document.getElementById('slicerSpinner');
                applyBtn.disabled = true;
                applyBtn.classList.add('opacity-50');
                spinner?.classList.remove('hidden');

                try {
                    // Build every enabled axis as one atomic multi-plane slice so the
                    // whole operation produces a SINGLE backup + version.
                    const planes = enabledAxes.map(axis => {
                        const state = slicerAxes[axis];
                        const planeNormal = [0, 0, 0];
                        const planeOrigin = [0, 0, 0];
                        const idx = { x: 0, y: 1, z: 2 }[axis];
                        planeNormal[idx] = 1;
                        planeOrigin[idx] = state.value;
                        return { plane_origin: planeOrigin, plane_normal: planeNormal, keep_side: state.side };
                    });

                    const response = await fetch('/slice_model', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ model_id: window.VIEWER_CONFIG.modelId, planes: planes })
                    });
                    const result = await response.json();
                    if (!result.success) {
                        alert('Slice failed: ' + (result.error || result.message || 'Unknown error'));
                        return;
                    }
                    if (result.warning) {
                        alert(result.warning);
                    }
                    window.location.reload();
                } catch (error) {
                    console.error('[Slicer] Error:', error);
                    alert('An error occurred while slicing.');
                } finally {
                    applyBtn.disabled = false;
                    applyBtn.classList.remove('opacity-50');
                    spinner?.classList.add('hidden');
                }
            });

            // NOTE: QR modal open/close lives above (showQRModal/hideQRModal,
            // `.show`-class based — the CSS uses `display:none !important`, so
            // an inline-style mechanism can't drive this modal). The model-info
            // modal handlers live in the first script block. A second wiring of
            // both existed here and double-fired every open/close.
        });
