document.addEventListener('DOMContentLoaded', () => {
        // INLINE EDIT — Title & Description (owner only)
        // ===================================================================
        const MODEL_ID = window.VIEWER_CONFIG.modelDbId;

        // Limits mirror blueprints/model_metadata.py (display_name 255, description 2000).
        const TITLE_MAX = 255;
        const DESC_MAX = 2000;
        const DESC_PLACEHOLDER = 'Click to add a description...';

        function patchMetadata(payload) {
            return fetch('/api/models/' + MODEL_ID + '/metadata', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
        }

        // Saves and returns true on success. On failure shows an error toast
        // with a retry action and calls onFail so the caller can restore the
        // previously saved value.
        async function saveMetadata(payload, onFail, retry) {
            let ok = false;
            try {
                const r = await patchMetadata(payload);
                ok = r.ok;
            } catch (e) { ok = false; }
            if (!ok) {
                onFail();
                window.arToast('Could not save your change. The previous value was restored.', 'error',
                    { actionLabel: 'Retry', onAction: retry });
            }
            return ok;
        }

        function addCounter(el, field, max) {
            const counter = document.createElement('div');
            counter.style.cssText = 'font-size:0.7rem;text-align:right;opacity:0.7;';
            const update = () => { counter.textContent = field.value.length + ' / ' + max; };
            field.addEventListener('input', update);
            update();
            el.appendChild(counter);
        }

        function startEditTitle(el) {
            if (el.querySelector('input')) return;
            const current = el.textContent.trim();
            const input = document.createElement('input');
            input.value = current;
            input.maxLength = TITLE_MAX;
            input.setAttribute('aria-label', 'Model title');
            input.style.cssText = 'width:100%;background:var(--color-gray-800);border:1px solid var(--color-gray-600);color:var(--color-gray-200);font-size:inherit;font-weight:inherit;padding:0.1rem 0.3rem;outline:none;';
            el.textContent = '';
            el.appendChild(input);
            addCounter(el, input, TITLE_MAX);
            input.focus();
            let cancelled = false;
            let done = false;
            const finish = (val) => { done = true; el.textContent = val; el.title = 'Click to edit'; };
            const save = () => {
                if (done) return;
                const val = input.value.trim() || current;
                finish(cancelled ? current : val);
                if (cancelled || val === current) return;
                const attempt = () => {
                    finish(val);
                    saveMetadata({ display_name: val }, () => finish(current), attempt);
                };
                attempt();
            };
            input.addEventListener('blur', save);
            input.addEventListener('keydown', e => {
                if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
                if (e.key === 'Escape') { e.preventDefault(); cancelled = true; input.blur(); }
            });
        }

        function startEditDescription(el) {
            if (el.querySelector('textarea')) return;
            const current = el.textContent.trim();
            const ta = document.createElement('textarea');
            ta.value = current === DESC_PLACEHOLDER ? '' : current;
            ta.rows = 3;
            ta.maxLength = DESC_MAX;
            ta.setAttribute('aria-label', 'Model description');
            ta.style.cssText = 'width:100%;background:var(--color-gray-800);border:1px solid var(--color-gray-600);color:var(--color-gray-200);font-size:inherit;padding:0.3rem;outline:none;resize:vertical;';
            el.textContent = '';
            el.appendChild(ta);
            addCounter(el, ta, DESC_MAX);
            ta.focus();
            let cancelled = false;
            let done = false;
            const finish = (val) => { done = true; el.textContent = val || DESC_PLACEHOLDER; };
            const previous = current === DESC_PLACEHOLDER ? '' : current;
            const save = () => {
                if (done) return;
                const val = ta.value.trim();
                finish(cancelled ? previous : val);
                if (cancelled || val === previous) return;
                const attempt = () => {
                    finish(val);
                    saveMetadata({ description: val }, () => finish(previous), attempt);
                };
                attempt();
            };
            ta.addEventListener('blur', save);
            ta.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); cancelled = true; ta.blur(); } });
        }
        window.startEditTitle = startEditTitle;
        window.startEditDescription = startEditDescription;

});
