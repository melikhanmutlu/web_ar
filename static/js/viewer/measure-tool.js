// Measure tool: click two points on the model to measure the distance between
// them. Draws the straight line (with the distance on it), an optional X/Y/Z
// axis-aligned breakdown (each component on its own coloured line), and lets
// owners SAVE measurements so they persist across visits.
//
// Lines are drawn as an SVG overlay. model-viewer positions slotted "anchor"
// elements at each 3D point's projected screen location, so we read those
// anchors' screen rects and connect them — the line then tracks the model as
// the camera orbits (redrawn on 'camera-change').
document.addEventListener('DOMContentLoaded', () => {
    const viewer = document.getElementById('modelViewer');
    const button = document.getElementById('measureToolButton');
    const panel = document.getElementById('measureToolResult');
    if (!viewer || !panel) return;

    const CAN_EDIT = !!(window.VIEWER_CONFIG && window.VIEWER_CONFIG.canEdit);
    const MODEL_ID = window.VIEWER_CONFIG && window.VIEWER_CONFIG.modelDbId;

    let active = false;
    let points = [];          // the two clicked 3D positions
    let anchors = [];         // slotted anchor elements (a, e1, e2, b)
    let markers = [];         // visible dot + label elements
    let current = null;       // { a, b, dx, dy, dz, total } once 2 points placed
    let showXYZ = false;
    let focusedAxis = null;   // 'total' | 'x' | 'y' | 'z' | null
    let saved = [];

    // ── SVG overlay (created once, sits over the model-viewer) ──
    const stage = viewer.parentElement;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'measure-overlay');
    const lines = {};
    ['total', 'x', 'y', 'z'].forEach(axis => {
        const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        ln.setAttribute('class', 'mt-line mt-line-' + axis);
        svg.appendChild(ln);
        lines[axis] = ln;
    });
    stage.appendChild(svg);

    function clearOverlay() {
        Object.values(lines).forEach(ln => ln.setAttribute('visibility', 'hidden'));
    }

    function clearMarkers() {
        markers.forEach(el => el.remove());
        anchors.forEach(el => el.remove());
        markers = [];
        anchors = [];
        points = [];
        current = null;
        clearOverlay();
    }

    function setActive(on) {
        active = on;
        button?.classList.toggle('is-active', active);
        panel.classList.toggle('hidden', !active);
        if (!active) clearMarkers();
        renderPanel();
        if (active) loadSaved();
    }

    // Mutual exclusion with hotspot mode -- both listen for model clicks.
    window._isMeasureModeActive = () => active;
    window._disableMeasureMode = () => setActive(false);

    button?.addEventListener('click', () => {
        if (!active) window._disableHotspotMode?.();
        setActive(!active);
    });

    function posStr(p) { return p.x + 'm ' + p.y + 'm ' + p.z + 'm'; }

    function addAnchor(pos) {
        const el = document.createElement('div');
        el.slot = 'measure-anchor-' + anchors.length + '-' + Date.now();
        el.className = 'measure-anchor';
        el.dataset.position = posStr(pos);
        viewer.appendChild(el);
        anchors.push(el);
        return el;
    }

    function addDot(pos, label) {
        const dot = document.createElement('div');
        dot.slot = 'measure-dot-' + markers.length + '-' + Date.now();
        dot.className = 'measure-dot';
        dot.dataset.position = posStr(pos);
        viewer.appendChild(dot);
        markers.push(dot);

        const labelEl = document.createElement('div');
        labelEl.slot = dot.slot;
        labelEl.className = 'measure-label';
        labelEl.style.marginTop = '-30px';
        labelEl.textContent = label;
        viewer.appendChild(labelEl);
        markers.push(labelEl);
    }

    function addAxisLabel(pos, text, axis) {
        const labelEl = document.createElement('div');
        labelEl.slot = 'measure-albl-' + markers.length + '-' + Date.now();
        labelEl.className = 'measure-label mt-label-' + axis;
        labelEl.dataset.position = posStr(pos);
        labelEl.dataset.axis = axis;
        labelEl.textContent = text;
        labelEl.addEventListener('click', () => focusAxis(axis));
        viewer.appendChild(labelEl);
        markers.push(labelEl);
        return labelEl;
    }

    function mid(a, b) { return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 }; }
    function cm(a, b) { return Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z) * 100; }

    function buildMeasurement(a, b) {
        // Axis-aligned elbow path a -> e1 -> e2 -> b decomposes the distance
        // into its X, Y and Z components, each drawable as its own segment.
        const e1 = { x: b.x, y: a.y, z: a.z };
        const e2 = { x: b.x, y: b.y, z: a.z };
        current = {
            a, b, e1, e2,
            total: cm(a, b),
            dx: Math.abs(b.x - a.x) * 100,
            dy: Math.abs(b.y - a.y) * 100,
            dz: Math.abs(b.z - a.z) * 100,
        };
        // Anchors (order matters for redraw): a, e1, e2, b.
        current.anchorA = addAnchor(a);
        current.anchorE1 = addAnchor(e1);
        current.anchorE2 = addAnchor(e2);
        current.anchorB = addAnchor(b);
        // Visible dots + total label.
        addDot(a, '1');
        addDot(b, '2');
        addAxisLabel(mid(a, b), fmt(current.total), 'total');
        // Axis labels (shown only in XYZ mode, but created once).
        current.labelX = addAxisLabel(mid(a, e1), 'X ' + fmt(current.dx), 'x');
        current.labelY = addAxisLabel(mid(e1, e2), 'Y ' + fmt(current.dy), 'y');
        current.labelZ = addAxisLabel(mid(e2, b), 'Z ' + fmt(current.dz), 'z');
        renderPanel();
        redraw();
    }

    function fmt(cmVal) {
        return cmVal.toFixed(2) + ' cm (' + (cmVal / 100).toFixed(3) + ' m)';
    }

    function screenOf(anchor) {
        const r = anchor.getBoundingClientRect();
        const base = svg.getBoundingClientRect();
        return { x: r.left + r.width / 2 - base.left, y: r.top + r.height / 2 - base.top };
    }

    function drawLine(ln, p1, p2, visible, focused, dimmed) {
        if (!visible) { ln.setAttribute('visibility', 'hidden'); return; }
        ln.setAttribute('x1', p1.x); ln.setAttribute('y1', p1.y);
        ln.setAttribute('x2', p2.x); ln.setAttribute('y2', p2.y);
        ln.setAttribute('visibility', 'visible');
        ln.setAttribute('opacity', dimmed ? '0.2' : '1');
        ln.setAttribute('stroke-width', focused ? '4' : '2');
    }

    function redraw() {
        if (!current) { clearOverlay(); return; }
        const A = screenOf(current.anchorA);
        const E1 = screenOf(current.anchorE1);
        const E2 = screenOf(current.anchorE2);
        const B = screenOf(current.anchorB);

        const totalVisible = !focusedAxis || focusedAxis === 'total' || !showXYZ;
        drawLine(lines.total, A, B, totalVisible,
            focusedAxis === 'total', showXYZ && focusedAxis && focusedAxis !== 'total');

        const axisVisible = showXYZ;
        drawLine(lines.x, A, E1, axisVisible, focusedAxis === 'x', focusedAxis && focusedAxis !== 'x');
        drawLine(lines.y, E1, E2, axisVisible, focusedAxis === 'y', focusedAxis && focusedAxis !== 'y');
        drawLine(lines.z, E2, B, axisVisible, focusedAxis === 'z', focusedAxis && focusedAxis !== 'z');

        // Axis labels only visible in XYZ mode.
        [current.labelX, current.labelY, current.labelZ].forEach(l => {
            if (l) l.style.display = showXYZ ? '' : 'none';
        });
    }

    // model-viewer moves the anchors as the camera orbits; keep the lines glued.
    let rafPending = false;
    function scheduleRedraw() {
        if (rafPending) return;
        rafPending = true;
        requestAnimationFrame(() => { rafPending = false; redraw(); });
    }
    viewer.addEventListener('camera-change', scheduleRedraw);
    window.addEventListener('resize', scheduleRedraw);

    function focusAxis(axis) {
        if (axis !== 'total') showXYZ = true;
        focusedAxis = (focusedAxis === axis) ? null : axis;
        renderPanel();
        redraw();
    }

    // ── Panel ──
    function renderPanel() {
        if (!active) return;
        if (!current) {
            panel.innerHTML = '<div class="mt-hint">Click two points on the model to measure the distance.</div>' +
                renderSavedList();
            return;
        }
        const row = (axis, text) =>
            '<button type="button" class="mt-row mt-row-' + axis +
            (focusedAxis === axis ? ' is-focused' : '') + '" data-axis="' + axis + '">' + text + '</button>';
        panel.innerHTML =
            '<div class="mt-rows">' +
            row('total', 'Distance: ' + fmt(current.total)) +
            row('x', 'X: ' + fmt(current.dx)) +
            row('y', 'Y: ' + fmt(current.dy)) +
            row('z', 'Z: ' + fmt(current.dz)) +
            '</div>' +
            '<label class="mt-toggle"><input type="checkbox" id="mtXYZ"' + (showXYZ ? ' checked' : '') + '> Show X/Y/Z lines</label>' +
            '<div class="mt-actions">' +
            (CAN_EDIT ? '<button type="button" id="mtSave" class="tp-btn-sm">Save</button>' : '') +
            '<button type="button" id="mtClear" class="tp-btn-sm">Clear</button>' +
            '</div>' +
            '<div id="mtSaveStatus" class="mt-status"></div>' +
            renderSavedList();

        panel.querySelectorAll('.mt-row').forEach(btn =>
            btn.addEventListener('click', () => focusAxis(btn.dataset.axis)));
        const xyz = panel.querySelector('#mtXYZ');
        if (xyz) xyz.addEventListener('change', () => {
            // Update state + lines only -- re-rendering the whole panel here
            // would detach this very checkbox mid-interaction.
            showXYZ = xyz.checked;
            if (!showXYZ) {
                focusedAxis = null;
                panel.querySelectorAll('.mt-row.is-focused').forEach(r => r.classList.remove('is-focused'));
            }
            redraw();
        });
        panel.querySelector('#mtClear')?.addEventListener('click', () => { clearMarkers(); renderPanel(); });
        panel.querySelector('#mtSave')?.addEventListener('click', saveCurrent);
        wireSavedList();
    }

    function renderSavedList() {
        if (!saved.length) return '';
        const items = saved.map(m =>
            '<div class="mt-saved-item" data-id="' + m.id + '">' +
            '<button type="button" class="mt-saved-load" data-id="' + m.id + '">' +
            escapeHtml(m.label || (m.distance_cm.toFixed(2) + ' cm')) + '</button>' +
            (CAN_EDIT ? '<button type="button" class="mt-saved-del" data-id="' + m.id + '" title="Delete">&times;</button>' : '') +
            '</div>'
        ).join('');
        return '<div class="mt-saved-title">Saved measurements</div><div class="mt-saved-list">' + items + '</div>';
    }

    function wireSavedList() {
        panel.querySelectorAll('.mt-saved-load').forEach(btn =>
            btn.addEventListener('click', () => {
                const m = saved.find(s => String(s.id) === btn.dataset.id);
                if (m) { clearMarkers(); buildMeasurement(m.a, m.b); }
            }));
        panel.querySelectorAll('.mt-saved-del').forEach(btn =>
            btn.addEventListener('click', () => deleteSaved(btn.dataset.id)));
    }

    // ── Persistence ──
    function loadSaved() {
        if (!MODEL_ID) return;
        fetch('/api/models/' + MODEL_ID + '/measurements')
            .then(r => r.json())
            .then(data => { if (data.success) { saved = data.measurements || []; renderPanel(); } })
            .catch(() => {});
    }

    function saveCurrent() {
        if (!current || !MODEL_ID) return;
        const label = (prompt('Name this measurement (optional):', '') || '').trim();
        const status = panel.querySelector('#mtSaveStatus');
        fetch('/api/models/' + MODEL_ID + '/measurements', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ a: current.a, b: current.b, distance_cm: current.total, label }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.success) { saved.push(data.measurement); if (status) status.textContent = 'Saved.'; renderPanel(); }
                else if (status) status.textContent = data.error || 'Save failed.';
            })
            .catch(() => { if (status) status.textContent = 'Save failed.'; });
    }

    function deleteSaved(id) {
        if (!MODEL_ID) return;
        fetch('/api/models/' + MODEL_ID + '/measurements/' + id, { method: 'DELETE' })
            .then(r => r.json())
            .then(data => { if (data.success) { saved = saved.filter(s => String(s.id) !== String(id)); renderPanel(); } })
            .catch(() => {});
    }

    viewer.addEventListener('click', (event) => {
        if (!active || window._isHotspotModeActive?.()) return;
        if (typeof viewer.positionAndNormalFromPoint !== 'function') return;
        const hit = viewer.positionAndNormalFromPoint(event.clientX, event.clientY);
        if (!hit?.position) return;

        if (points.length === 2) clearMarkers();   // start a fresh measurement
        const p = { x: hit.position.x, y: hit.position.y, z: hit.position.z };
        points.push(p);

        if (points.length === 1) {
            addDot(p, '1');
            renderPanel();
        } else {
            // Remove the temporary "1" dot; buildMeasurement re-adds both.
            clearMarkersKeepPoints();
            buildMeasurement(points[0], p);
        }
    });

    // Remove drawn elements but keep the two logical points (used between the
    // first and second click so buildMeasurement can render both cleanly).
    function clearMarkersKeepPoints() {
        markers.forEach(el => el.remove());
        anchors.forEach(el => el.remove());
        markers = [];
        anchors = [];
        clearOverlay();
    }
});
