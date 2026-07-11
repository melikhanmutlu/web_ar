document.addEventListener('DOMContentLoaded', () => {
    const viewer = document.getElementById('modelViewer');
    const button = document.getElementById('measureToolButton');
    const result = document.getElementById('measureToolResult');
    let active = false;
    let points = [];
    let markers = [];

    function clearMarkers() {
        markers.forEach(el => el.remove());
        markers = [];
        points = [];
    }

    function setActive(on) {
        active = on;
        button?.classList.toggle('is-active', active);
        if (result) result.classList.toggle('hidden', !active);
        clearMarkers();
        if (result) result.textContent = 'Click a point on the model to start measuring.';
    }

    // Mutual exclusion with hotspot mode (static/js/viewer/annotations.js) --
    // both listen for clicks on the same <model-viewer>, so having both modes
    // active at once made every click ambiguously both place a hotspot and a
    // measure point.
    window._isMeasureModeActive = () => active;
    window._disableMeasureMode = () => setActive(false);

    button?.addEventListener('click', () => {
        if (!active) window._disableHotspotMode?.();
        setActive(!active);
    });

    function slotAt(pos) {
        const slot = 'hotspot-measure-' + markers.length + '-' + Date.now();
        return { slot, position: pos.x + 'm ' + pos.y + 'm ' + pos.z + 'm' };
    }

    function addPointMarker(pos, label) {
        const { slot, position } = slotAt(pos);
        const marker = document.createElement('div');
        marker.slot = slot;
        marker.className = 'measure-dot';
        marker.dataset.position = position;
        viewer.appendChild(marker);
        markers.push(marker);

        const labelEl = document.createElement('div');
        labelEl.slot = slot;
        labelEl.className = 'measure-label';
        labelEl.style.marginTop = '-30px';
        labelEl.textContent = label;
        viewer.appendChild(labelEl);
        markers.push(labelEl);
    }

    function addDistanceLabel(pos, text) {
        const { slot, position } = slotAt(pos);
        const labelEl = document.createElement('div');
        labelEl.slot = slot;
        labelEl.className = 'measure-label';
        labelEl.dataset.position = position;
        labelEl.textContent = text;
        viewer.appendChild(labelEl);
        markers.push(labelEl);
    }

    viewer?.addEventListener('click', (event) => {
        if (!active || window._isHotspotModeActive?.()) return;
        if (typeof viewer.positionAndNormalFromPoint !== 'function') return;
        const hit = viewer.positionAndNormalFromPoint(event.clientX, event.clientY);
        if (!hit?.position) return;

        if (points.length === 2) clearMarkers(); // start a new measurement

        points.push(hit.position);
        addPointMarker(hit.position, points.length === 1 ? '1' : '2');

        if (points.length === 2) {
            const [a, b] = points;
            const meters = Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z);
            const distanceText = `${(meters * 100).toFixed(2)} cm (${meters.toFixed(3)} m)`;
            addDistanceLabel(
                { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 },
                distanceText
            );
            if (result) result.textContent = distanceText + ' — click again to start a new measurement.';
        } else if (result) {
            result.textContent = 'Point 1 placed — click a second point to measure the distance.';
        }
    });
});
