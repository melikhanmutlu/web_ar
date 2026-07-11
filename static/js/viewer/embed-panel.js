// Owner-only embed customization panel (Faz 4: "Embed özelleştirme paneli").
// Reads/writes the same viewer-settings API that /embed already resolves
// against, and surfaces the existing (previously UI-less)
// /api/models/<id>/integration-snippets endpoint as a copyable snippet box.
document.addEventListener('DOMContentLoaded', () => {
    const modelId = window.VIEWER_CONFIG.modelId;

    const showDimensions = document.getElementById('embedShowDimensions');
    const showAr = document.getElementById('embedShowAr');
    const autoRotate = document.getElementById('embedAutoRotate');
    const backgroundColor = document.getElementById('embedBackgroundColor');
    const primaryColor = document.getElementById('embedPrimaryColor');
    const hidePoweredBy = document.getElementById('embedHidePoweredBy');
    const saveBtn = document.getElementById('embedSaveSettings');
    const saveStatus = document.getElementById('embedSaveStatus');
    const snippetType = document.getElementById('embedSnippetType');
    const snippetOutput = document.getElementById('embedSnippetOutput');
    const copyBtn = document.getElementById('embedCopySnippet');

    if (!saveBtn && !copyBtn) return;

    let snippets = null;

    function loadSettings() {
        fetch('/api/models/' + modelId + '/viewer-settings')
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;
                const s = data.settings;
                if (showDimensions) showDimensions.checked = !!s.show_dimensions;
                if (showAr) showAr.checked = !!s.show_ar;
                if (autoRotate) autoRotate.checked = !!s.auto_rotate;
                if (backgroundColor) backgroundColor.value = s.background_color || '#ffffff';
                if (primaryColor) primaryColor.value = (s.branding && s.branding.primary_color) || '#4CAF50';
                if (hidePoweredBy) hidePoweredBy.checked = !!(s.branding && s.branding.hide_powered_by);
            })
            .catch(() => {});
    }

    saveBtn?.addEventListener('click', () => {
        fetch('/api/models/' + modelId + '/viewer-settings', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                show_dimensions: !!showDimensions?.checked,
                show_ar: !!showAr?.checked,
                auto_rotate: !!autoRotate?.checked,
                background_color: backgroundColor?.value,
                branding: {
                    primary_color: primaryColor?.value,
                    hide_powered_by: !!hidePoweredBy?.checked,
                },
            }),
        })
            .then(r => r.json())
            .then(data => {
                if (!saveStatus) return;
                saveStatus.textContent = data.success ? 'Saved.' : (data.error || 'Failed to save.');
                saveStatus.classList.remove('hidden');
                setTimeout(() => saveStatus.classList.add('hidden'), 3000);
            })
            .catch(() => {});
    });

    function loadSnippets() {
        fetch('/api/models/' + modelId + '/integration-snippets')
            .then(r => r.json())
            .then(data => {
                if (!data.success) return;
                snippets = data;
                renderSnippet();
            })
            .catch(() => {});
    }

    function renderSnippet() {
        if (!snippetOutput || !snippets || !snippetType) return;
        snippetOutput.value = snippets[snippetType.value] || '';
    }

    snippetType?.addEventListener('change', renderSnippet);

    copyBtn?.addEventListener('click', () => {
        if (!snippetOutput || !snippetOutput.value) return;
        navigator.clipboard?.writeText(snippetOutput.value).then(() => {
            const original = copyBtn.textContent;
            copyBtn.textContent = 'Copied!';
            setTimeout(() => { copyBtn.textContent = original; }, 1500);
        }).catch(() => {});
    });

    loadSettings();
    loadSnippets();
});
