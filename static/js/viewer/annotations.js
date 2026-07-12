document.addEventListener('DOMContentLoaded', () => {
    const modelViewer = document.querySelector('model-viewer');
    const modelId = window.VIEWER_CONFIG.modelId;
    const CAN_EDIT = window.VIEWER_CONFIG.canEdit;

        // ANNOTATIONS PANEL
        // ===================================================================
        let savedViews = [];
        let hotspotMode = false;
        let hotspotCount = 0;

        const saveCameraView = document.getElementById('saveCameraView');
        const cameraViewsList = document.getElementById('cameraViewsList');
        const toggleHotspotMode = document.getElementById('toggleHotspotMode');
        const hotspotsList = document.getElementById('hotspotsList');
        const clearAnnotations = document.getElementById('clearAnnotations');

        saveCameraView?.addEventListener('click', () => {
            if (!modelViewer) return;
            const orbit = modelViewer.getCameraOrbit();
            const target = modelViewer.getCameraTarget();
            const fov = modelViewer.getFieldOfView();
            const name = 'View ' + (savedViews.length + 1);

            // Save to DB
            fetch('/api/models/' + modelId + '/camera-views', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    orbit: { theta: parseFloat(orbit.theta) || 0, phi: parseFloat(orbit.phi) || 0, radius: parseFloat(orbit.radius) || 0 },
                    target: { x: parseFloat(target.x) || 0, y: parseFloat(target.y) || 0, z: parseFloat(target.z) || 0 },
                    fov: parseFloat(fov) || 24
                })
            })
            .then(r => r.json())
            .then(data => {
                if (!data.success) { console.error('Failed to save camera view:', data.error); return; }
                savedViews.push({ ...data.view, _orbit: orbit, _target: target, _fov: fov });
                renderCameraViews();
            })
            .catch(err => console.error('Error saving camera view:', err));
        });

        function loadCameraViewsFromDB() {
            fetch('/api/models/' + modelId + '/camera-views')
            .then(r => r.json())
            .then(data => {
                if (!data.success || !data.views) return;
                savedViews = data.views;
                renderCameraViews();
            })
            .catch(err => console.error('Error loading camera views:', err));
        }

        function renderCameraViews() {
            if (!cameraViewsList) return;
            if (savedViews.length === 0) {
                cameraViewsList.innerHTML = '<p class="tp-note">No saved views</p>';
                return;
            }
            cameraViewsList.innerHTML = '';
            savedViews.forEach((v, i) => {
                const div = document.createElement('div');
                div.className = 'tp-list-item';
                div.innerHTML = '<button class="load-view-btn" style="background:none;border:none;color:var(--color-gray-200);font-size:0.72rem;font-weight:600;cursor:pointer;text-decoration:underline;text-underline-offset:2px;">' + escapeHtml(v.name) + '</button>' +
                    (CAN_EDIT ? '<button class="delete-view-btn" style="background:none;border:none;color:var(--color-gray-500);cursor:pointer;padding:0;"><i data-lucide="x" style="width:0.7rem;height:0.7rem;"></i></button>' : '');
                div.querySelector('.load-view-btn').addEventListener('click', () => {
                    if (v._orbit) {
                        modelViewer.cameraOrbit = v._orbit.toString();
                        modelViewer.cameraTarget = v._target.toString();
                        modelViewer.fieldOfView = v._fov + 'deg';
                    } else {
                        const o = v.orbit;
                        modelViewer.cameraOrbit = o.theta + 'deg ' + o.phi + 'deg ' + o.radius + 'm';
                        const t = v.target;
                        modelViewer.cameraTarget = t.x + 'm ' + t.y + 'm ' + t.z + 'm';
                        if (v.fov) modelViewer.fieldOfView = v.fov + 'deg';
                    }
                });
                div.querySelector('.delete-view-btn')?.addEventListener('click', () => {
                    const viewId = v.id;
                    if (viewId) {
                        fetch('/api/models/' + modelId + '/camera-views/' + viewId, { method: 'DELETE' })
                        .then(r => r.json())
                        .then(data => {
                            if (!data.success) { console.error('Failed to delete view:', data.error); return; }
                            savedViews.splice(i, 1);
                            renderCameraViews();
                        })
                        .catch(err => console.error('Error deleting view:', err));
                    } else {
                        savedViews.splice(i, 1);
                        renderCameraViews();
                    }
                });
                cameraViewsList.appendChild(div);
            });
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }

        // Load camera views on page load
        loadCameraViewsFromDB();

        // Hotspot mode
        let _hsTapWasDisabled = false;
        function setHotspotMode(on) {
            hotspotMode = on;
            // Suppress model-viewer's tap-to-recenter while placing hotspots (a
            // tap otherwise moves the camera target), mirroring the measure tool.
            if (modelViewer) {
                if (on) {
                    _hsTapWasDisabled = modelViewer.hasAttribute('disable-tap');
                    modelViewer.setAttribute('disable-tap', '');
                } else if (!_hsTapWasDisabled) {
                    modelViewer.removeAttribute('disable-tap');
                }
            }
            if (!toggleHotspotMode) return;
            toggleHotspotMode.textContent = hotspotMode ? 'Hotspot Mode: ON (click model)' : 'Click Model to Add Hotspot';
            toggleHotspotMode.style.background = hotspotMode ? 'var(--color-gray-200)' : '';
            toggleHotspotMode.style.color = hotspotMode ? 'var(--color-gray-900)' : '';
            toggleHotspotMode.classList.toggle('text-white', hotspotMode);
        }
        // The slicer (separate script block) turns hotspot mode off when a clip
        // axis is enabled: the preview only *hides* geometry via shader discard,
        // so clicks would still land hotspots on invisible, clipped-away surfaces.
        window._disableHotspotMode = () => setHotspotMode(false);
        window._isHotspotModeActive = () => hotspotMode;

        toggleHotspotMode?.addEventListener('click', () => {
            if (!hotspotMode && window._slicerClippingActive?.()) {
                alert('Hotspots can\'t be placed while a slice preview is active — reset the slicer first.');
                return;
            }
            // Mutual exclusion with the measure tool (static/js/viewer/measure-tool.js)
            // -- both listen for clicks on the same <model-viewer>, so having both
            // modes active at once made every click ambiguously place both.
            if (!hotspotMode) window._disableMeasureMode?.();
            setHotspotMode(!hotspotMode);
        });

        // model-viewer fires `click` on pointerup even after an orbit drag —
        // without this, every rotate gesture in hotspot mode ended with an
        // unwanted "add hotspot" prompt. Only a genuine tap (little to no
        // pointer travel) may place a hotspot.
        let _hotspotPointerDown = null;
        modelViewer?.addEventListener('pointerdown', (e) => {
            _hotspotPointerDown = { x: e.clientX, y: e.clientY };
        });

        modelViewer?.addEventListener('click', (e) => {
            if (!hotspotMode || window._isMeasureModeActive?.()) return;
            if (_hotspotPointerDown) {
                const dx = e.clientX - _hotspotPointerDown.x;
                const dy = e.clientY - _hotspotPointerDown.y;
                if ((dx * dx + dy * dy) > 36) return; // >6px travel = drag, not a tap
            }
            const rect = modelViewer.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const hit = modelViewer.positionAndNormalFromPoint(x, y);
            if (!hit) return;

            hotspotCount++;
            const name = 'hotspot-' + Date.now();
            const label = prompt('Hotspot label:', 'Point ' + hotspotCount);
            if (!label) { hotspotCount--; return; }

            const pos = hit.position;
            const norm = hit.normal;

            // Save to DB
            fetch('/api/models/' + modelId + '/hotspots', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id: name,
                    title: label,
                    position: { x: pos.x, y: pos.y, z: pos.z },
                    normal: { x: norm.x, y: norm.y, z: norm.z }
                })
            })
            .then(r => r.json())
            .then(data => {
                if (!data.success) { console.error('Failed to save hotspot:', data.error); return; }
                renderHotspotOnViewer(name, label, pos, norm);
            })
            .catch(err => console.error('Error saving hotspot:', err));
        });

        // HOTSPOT DISCUSSION THREAD
        // ===================================================================
        const IS_AUTHENTICATED = window.VIEWER_CONFIG.isAuthenticated;
        const CURRENT_USER_ID = window.VIEWER_CONFIG.currentUserId;
        const IS_OWNER = window.VIEWER_CONFIG.isOwner;
        const discussionModal = document.getElementById('hotspotDiscussionModal');
        const discussionTitle = document.getElementById('hotspotDiscussionTitle');
        const discussionComments = document.getElementById('hotspotDiscussionComments');
        const discussionInput = document.getElementById('hotspotDiscussionInput');
        const discussionSubmit = document.getElementById('hotspotDiscussionSubmit');
        const discussionFormWrap = document.getElementById('hotspotDiscussionFormWrap');
        const discussionLoginNote = document.getElementById('hotspotDiscussionLoginNote');
        let activeDiscussionHotspotId = null;

        if (discussionFormWrap && discussionLoginNote) {
            discussionFormWrap.classList.toggle('hidden', !IS_AUTHENTICATED);
            discussionLoginNote.classList.toggle('hidden', IS_AUTHENTICATED);
        }

        function renderDiscussionComments(comments) {
            if (!discussionComments) return;
            if (!comments || comments.length === 0) {
                discussionComments.innerHTML = '<p class="tp-note">No comments yet.</p>';
                return;
            }
            discussionComments.innerHTML = '';
            comments.forEach((c) => {
                const canDelete = IS_AUTHENTICATED && (IS_OWNER || c.userId === CURRENT_USER_ID);
                const div = document.createElement('div');
                div.className = 'hotspot-comment';
                div.innerHTML =
                    '<div>' + escapeHtml(c.body) + '</div>' +
                    '<div class="hotspot-comment-meta"><span>' + escapeHtml(c.author) + ' &middot; ' + new Date(c.createdAt).toLocaleString() + '</span>' +
                    (canDelete ? '<button class="delete-comment-btn" style="background:none;border:none;color:var(--color-gray-400);cursor:pointer;padding:0;"><i data-lucide="x" style="width:0.65rem;height:0.65rem;"></i></button>' : '') +
                    '</div>';
                div.querySelector('.delete-comment-btn')?.addEventListener('click', () => {
                    fetch('/api/models/' + modelId + '/hotspots/' + activeDiscussionHotspotId + '/comments/' + c.id, { method: 'DELETE' })
                        .then(r => r.json())
                        .then(data => {
                            if (!data.success) { console.error('Failed to delete comment:', data.error); return; }
                            loadDiscussionComments(activeDiscussionHotspotId);
                        })
                        .catch(err => console.error('Error deleting comment:', err));
                });
                discussionComments.appendChild(div);
                if (typeof lucide !== 'undefined') lucide.createIcons();
            });
        }

        function loadDiscussionComments(hotspotId) {
            fetch('/api/models/' + modelId + '/hotspots/' + hotspotId + '/comments')
                .then(r => r.json())
                .then(data => {
                    if (!data.success) return;
                    renderDiscussionComments(data.comments);
                })
                .catch(err => console.error('Error loading comments:', err));
        }

        function openHotspotDiscussion(hotspotId, label) {
            activeDiscussionHotspotId = hotspotId;
            if (discussionTitle) discussionTitle.textContent = label;
            if (discussionInput) discussionInput.value = '';
            if (discussionComments) discussionComments.innerHTML = '<p class="tp-note">Loading…</p>';
            discussionModal?.classList.add('show');
            loadDiscussionComments(hotspotId);
        }

        document.getElementById('closeHotspotDiscussion')?.addEventListener('click', () => {
            discussionModal?.classList.remove('show');
        });

        discussionSubmit?.addEventListener('click', () => {
            const body = discussionInput?.value.trim();
            if (!body || !activeDiscussionHotspotId) return;
            fetch('/api/models/' + modelId + '/hotspots/' + activeDiscussionHotspotId + '/comments', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ body }),
            })
                .then(r => r.json())
                .then(data => {
                    if (!data.success) { console.error('Failed to post comment:', data.error); return; }
                    if (discussionInput) discussionInput.value = '';
                    loadDiscussionComments(activeDiscussionHotspotId);
                })
                .catch(err => console.error('Error posting comment:', err));
        });

        function renderHotspotOnViewer(name, label, pos, norm) {
            // Names are generated as 'hotspot-<ts>' already — model-viewer only
            // needs the slot to start with "hotspot-", so don't double the prefix.
            const slot = name.startsWith('hotspot-') ? name : 'hotspot-' + name;
            const hotspot = document.createElement('button');
            hotspot.slot = slot;
            hotspot.className = 'hotspot-dot';
            hotspot.dataset.position = pos.x + 'm ' + pos.y + 'm ' + pos.z + 'm';
            if (norm) hotspot.dataset.normal = norm.x + 'm ' + norm.y + 'm ' + norm.z + 'm';
            hotspot.dataset.visibility = 'visible';
            hotspot.style.cssText = 'background:rgba(76,175,80,0.9);color:white;border:2px solid white;border-radius:50%;width:28px;height:28px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:bold;box-shadow:0 2px 8px rgba(0,0,0,0.3);';
            hotspot.textContent = document.querySelectorAll('.hotspot-dot').length + 1;
            hotspot.addEventListener('click', (ev) => {
                ev.stopPropagation();
                openHotspotDiscussion(name, label);
            });

            const annotation = document.createElement('div');
            annotation.slot = slot;
            annotation.className = 'hotspot-annotation';
            annotation.style.cssText = 'background:rgba(0,0,0,0.75);color:white;padding:4px 10px;border-radius:6px;font-size:11px;white-space:nowrap;pointer-events:none;margin-top:-40px;';
            annotation.textContent = label;

            modelViewer.appendChild(hotspot);
            modelViewer.appendChild(annotation);

            addHotspotToList(name, label, hotspot, annotation);
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }

        function addHotspotToList(name, label, hotspotEl, annotationEl) {
            if (!hotspotsList) return;
            if (hotspotsList.querySelector('.italic') || hotspotsList.querySelector('.tp-note')) hotspotsList.innerHTML = '';

            const div = document.createElement('div');
            div.className = 'tp-list-item';
            div.dataset.hotspotId = name;
            div.innerHTML = '<span style="font-size:0.72rem;color:var(--color-gray-200);">' + escapeHtml(label) + '</span>' +
                (CAN_EDIT ? '<button class="delete-hotspot-btn" style="background:none;border:none;color:var(--color-gray-500);cursor:pointer;padding:0;"><i data-lucide="x" style="width:0.7rem;height:0.7rem;"></i></button>' : '');
            div.querySelector('.delete-hotspot-btn')?.addEventListener('click', () => {
                // Delete from DB
                fetch('/api/models/' + modelId + '/hotspots/' + name, { method: 'DELETE' })
                .then(r => r.json())
                .then(data => {
                    if (!data.success) { console.error('Failed to delete hotspot:', data.error); return; }
                    hotspotEl.remove();
                    annotationEl.remove();
                    div.remove();
                    if (hotspotsList.children.length === 0) {
                        hotspotsList.innerHTML = '<p class="tp-note">No hotspots yet</p>';
                    }
                })
                .catch(err => console.error('Error deleting hotspot:', err));
            });
            hotspotsList.appendChild(div);
        }

        // Load hotspots from DB on page load
        function loadHotspotsFromDB() {
            fetch('/api/models/' + modelId + '/hotspots')
            .then(r => r.json())
            .then(data => {
                if (!data.success || !data.hotspots || data.hotspots.length === 0) return;
                hotspotCount = data.hotspots.length;
                data.hotspots.forEach(h => {
                    renderHotspotOnViewer(h.id, h.title, h.position, h.normal);
                });
            })
            .catch(err => console.error('Error loading hotspots:', err));
        }

        // Load hotspots after model loads
        modelViewer?.addEventListener('load', () => {
            loadHotspotsFromDB();
        });

        clearAnnotations?.addEventListener('click', () => {
            if (!confirm('Clear all annotations and hotspots?')) return;
            // Camera views only have a per-id DELETE route; clearing them just
            // client-side made them reappear on the next page load.
            const viewDeletes = savedViews
                .filter(v => v.id)
                .map(v => fetch('/api/models/' + modelId + '/camera-views/' + v.id, { method: 'DELETE' }).catch(() => {}));
            Promise.all([
                fetch('/api/models/' + modelId + '/hotspots', { method: 'DELETE' }).then(r => r.json()),
                ...viewDeletes,
            ])
            .then(([data]) => {
                if (!data.success) { console.error('Failed to clear hotspots:', data.error); return; }
                savedViews = [];
                renderCameraViews();
                hotspotCount = 0;
                // Exclude measure-tool markers (slot "hotspot-measure-*") --
                // this selector used to remove them too, leaving measure-tool's
                // own markers[]/points[] arrays pointing at removed DOM nodes
                // while its result panel kept showing a stale distance.
                modelViewer?.querySelectorAll('[slot^="hotspot-"]:not([slot^="hotspot-measure-"])').forEach(el => el.remove());
                if (hotspotsList) hotspotsList.innerHTML = '<p class="tp-note">No hotspots yet</p>';
            })
            .catch(err => console.error('Error clearing annotations:', err));
        });

});
