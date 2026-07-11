document.addEventListener('DOMContentLoaded', () => {
        // INLINE EDIT — Title & Description (owner only)
        // ===================================================================
        const MODEL_ID = window.VIEWER_CONFIG.modelDbId;

        function patchMetadata(payload) {
            return fetch('/api/models/' + MODEL_ID + '/metadata', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
        }

        function startEditTitle(el) {
            if (el.querySelector('input')) return;
            const current = el.textContent.trim();
            const input = document.createElement('input');
            input.value = current;
            input.style.cssText = 'width:100%;background:var(--color-gray-800);border:1px solid var(--color-gray-600);color:var(--color-gray-200);font-size:inherit;font-weight:inherit;padding:0.1rem 0.3rem;outline:none;';
            el.textContent = '';
            el.appendChild(input);
            input.focus();
            const save = () => {
                const val = input.value.trim() || current;
                el.textContent = val;
                el.title = 'Click to edit';
                patchMetadata({ display_name: val });
            };
            input.addEventListener('blur', save);
            input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); input.blur(); } if (e.key === 'Escape') { el.textContent = current; } });
        }

        function startEditDescription(el) {
            if (el.querySelector('textarea')) return;
            const current = el.textContent.trim();
            const ta = document.createElement('textarea');
            ta.value = current === 'Click to add a description...' ? '' : current;
            ta.rows = 3;
            ta.style.cssText = 'width:100%;background:var(--color-gray-800);border:1px solid var(--color-gray-600);color:var(--color-gray-200);font-size:inherit;padding:0.3rem;outline:none;resize:vertical;';
            el.textContent = '';
            el.appendChild(ta);
            ta.focus();
            const save = () => {
                const val = ta.value.trim();
                el.textContent = val || 'Click to add a description...';
                patchMetadata({ description: val });
            };
            ta.addEventListener('blur', save);
            ta.addEventListener('keydown', e => { if (e.key === 'Escape') { el.textContent = current; } });
        }
        window.startEditTitle = startEditTitle;
        window.startEditDescription = startEditDescription;

});
