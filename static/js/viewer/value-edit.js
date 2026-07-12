// Click-to-type for the Tools-panel slider value readouts. Each `.tp-val`
// span (Metalness / Roughness / Opacity / Explode / Rotate X-Y-Z) mirrors a
// range slider; clicking the number turns it into a small input so a precise
// value can be typed instead of dragged. Committing writes the slider and
// dispatches its 'input' + 'change' events, so every existing handler
// (material-editor live preview, undo/redo snapshot) runs exactly as if the
// slider had been dragged there. Scale already has its own number input.
document.addEventListener('DOMContentLoaded', () => {
    if (!window.VIEWER_CONFIG || !window.VIEWER_CONFIG.canEdit) return;

    function wire(valueId) {
        const span = document.getElementById(valueId);
        const slider = document.getElementById(valueId.replace(/Value$/, 'Slider'));
        if (!span || !slider) return;

        span.classList.add('tp-val-editable');
        span.title = 'Click to type an exact value';

        span.addEventListener('click', () => {
            if (slider.disabled || span.dataset.editing === '1') return;
            span.dataset.editing = '1';

            const input = document.createElement('input');
            input.type = 'number';
            input.min = slider.min;
            input.max = slider.max;
            input.step = slider.step;
            input.value = slider.value;
            input.className = 'tp-val-edit';

            span.style.display = 'none';
            span.parentNode.insertBefore(input, span);
            input.focus();
            input.select();

            const finish = (apply) => {
                if (span.dataset.editing !== '1') return;
                span.dataset.editing = '';
                if (apply) {
                    let v = parseFloat(input.value);
                    if (!isNaN(v)) {
                        const min = parseFloat(slider.min);
                        const max = parseFloat(slider.max);
                        v = Math.min(max, Math.max(min, v));
                        slider.value = v;
                        // 'input' drives the live preview + span text; 'change'
                        // drives the undo/redo history snapshot.
                        slider.dispatchEvent(new Event('input', { bubbles: true }));
                        slider.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
                input.remove();
                span.style.display = '';
            };

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); finish(true); }
                else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
            });
            input.addEventListener('blur', () => finish(true));
        });
    }

    [
        'metalnessValue', 'roughnessValue', 'opacityValue', 'explodeValue',
        'rotateXValue', 'rotateYValue', 'rotateZValue',
    ].forEach(wire);
});
