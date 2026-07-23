// Session-only undo/redo for the material and transform editors (Faz 2:
// "Görüntüleyicide undo/redo"). Snapshots the combined editable state
// (material color/metalness/roughness/opacity + transform scale/rotation)
// on every committed edit (the DOM "change" event -- fires once per slider
// release/input blur, not on every drag tick) and lets Ctrl+Z / Ctrl+Shift+Z
// or the toolbar buttons step through that history. Not persisted -- a page
// reload starts a fresh history, same as the rest of the live preview state.
document.addEventListener('DOMContentLoaded', () => {
    if (!window.VIEWER_CONFIG.canEdit) return;

    const MAX_HISTORY = 50;
    const history = [];
    let pointer = -1; // index of the currently-applied snapshot
    let restoring = false; // guards against re-capturing a snapshot we just applied

    const undoButton = document.getElementById('undoButton');
    const redoButton = document.getElementById('redoButton');

    function captureSnapshot() {
        return {
            material: window._captureMaterialSnapshot?.() || null,
            transform: window._captureTransformSnapshot?.() || null,
        };
    }

    function snapshotsEqual(a, b) {
        return JSON.stringify(a) === JSON.stringify(b);
    }

    function updateButtons() {
        if (undoButton) undoButton.disabled = pointer <= 0;
        if (redoButton) redoButton.disabled = pointer >= history.length - 1;
    }

    function pushSnapshot() {
        if (restoring) return;
        const snap = captureSnapshot();
        if (pointer >= 0 && snapshotsEqual(history[pointer], snap)) return;
        history.length = pointer + 1; // drop any redo branch
        history.push(snap);
        if (history.length > MAX_HISTORY) history.shift();
        pointer = history.length - 1;
        updateButtons();
    }

    function applySnapshot(snap) {
        restoring = true;
        try {
            if (snap.material) {
                // Restoring the baseline (pointer 0) puts the model back at
                // its saved appearance — nothing material-wise left to
                // persist, so the material dirty flag must clear, or a later
                // transform-only save would still send a material block and
                // flatten multi-material models.
                const atBaseline = history.length > 0 &&
                    JSON.stringify(snap.material) === JSON.stringify(history[0].material);
                window._applyMaterialSnapshot?.(snap.material, { dirty: !atBaseline });
            }
            if (snap.transform) window._applyTransformSnapshot?.(snap.transform);
        } finally {
            restoring = false;
        }
    }

    function undo() {
        if (pointer <= 0) return;
        pointer -= 1;
        applySnapshot(history[pointer]);
        updateButtons();
    }

    function redo() {
        if (pointer >= history.length - 1) return;
        pointer += 1;
        applySnapshot(history[pointer]);
        updateButtons();
    }

    // Seed a baseline synchronously, before any change listeners are
    // attached below, so pointer 0 always exists and a user edit can never
    // race ahead of it and be mistaken for the baseline itself.
    history.push(captureSnapshot());
    pointer = 0;
    updateButtons();

    // Material sync is async (model-viewer's 'load' + material-editor.js's
    // own load handling), so the sliders may not reflect the model's real
    // material state yet at the point above -- history[0].material is
    // whatever placeholder the HTML inputs start with (e.g. plain white),
    // not the model's actual baked-in color/texture. The old guard here
    // only refreshed history[0] "if the user hasn't edited anything yet",
    // which sounds safe but permanently locked in that white placeholder as
    // history[0] the moment a user made even one edit before this event
    // fired (e.g. while a texture was still downloading) -- from then on,
    // undoing all the way back to the start silently replaced the model's
    // real appearance with white, which read as "the material got deleted".
    // Always refresh just the material half of history[0] instead: it never
    // touches history[0].transform or any later (real) history entry, so
    // walking all the way back always lands on the model's true starting
    // material, not a placeholder.
    window.addEventListener('viewer:material-ready', () => {
        if (history.length > 0) {
            const original = window._originalMaterialSnapshot?.();
            if (original) history[0] = { ...history[0], material: original };
        }
    });

    const watchedElementIds = [
        'materialColor', 'materialColorHex', 'metalnessSlider', 'roughnessSlider', 'opacitySlider',
        'scaleSlider', 'scaleInput', 'rotateXSlider', 'rotateYSlider', 'rotateZSlider',
    ];
    watchedElementIds.forEach((id) => {
        document.getElementById(id)?.addEventListener('change', pushSnapshot);
    });

    undoButton?.addEventListener('click', undo);
    redoButton?.addEventListener('click', redo);

    document.addEventListener('keydown', (event) => {
        if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return;
        // Don't hijack undo/redo while the user is typing in a text field.
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        event.preventDefault();
        if (event.shiftKey) redo(); else undo();
    });
});
