document.addEventListener('DOMContentLoaded', () => {
    const modelId = window.VIEWER_CONFIG.modelId;
    const CAN_EDIT = window.VIEWER_CONFIG.canEdit;

        // ===================================================================
        // SAVE CHANGES
        // ===================================================================
        // VERSION HISTORY
        // ===================================================================
        const versionList = document.getElementById('versionList');
        const refreshVersions = document.getElementById('refreshVersions');
        const compareVersionsBtn = document.getElementById('compareVersionsBtn');
        const versionCompareResult = document.getElementById('versionCompareResult');
        let versionPreviewItems = [];
        let selectedForCompare = [];

        function updateCompareButton() {
            if (compareVersionsBtn) compareVersionsBtn.disabled = selectedForCompare.length !== 2;
        }

        function formatDelta(value, suffix) {
            if (value === null || value === undefined) return 'n/a';
            const sign = value > 0 ? '+' : '';
            return sign + value + (suffix || '');
        }

        compareVersionsBtn?.addEventListener('click', async () => {
            if (selectedForCompare.length !== 2) return;
            const [a, b] = [...selectedForCompare].sort((x, y) => x - y);
            if (versionCompareResult) versionCompareResult.innerHTML = '<p class="tp-note">Comparing…</p>';
            try {
                const res = await fetch('/api/versions/' + modelId + '/compare/' + a + '/' + b);
                const data = await res.json();
                if (!data.success) {
                    if (versionCompareResult) versionCompareResult.innerHTML = '<p class="tp-note">' + escapeHtml(data.error || 'Comparison failed') + '</p>';
                    return;
                }
                const d = data.diff;
                const rows = [
                    ['Width (cm)', formatDelta(d.dimensions.x)],
                    ['Height (cm)', formatDelta(d.dimensions.y)],
                    ['Depth (cm)', formatDelta(d.dimensions.z)],
                    ['Vertices', formatDelta(d.vertices)],
                    ['Faces', formatDelta(d.faces)],
                    ['File size (bytes)', formatDelta(d.file_size)],
                ].map(([label, value]) =>
                    '<div class="tp-dim-row"><span>' + label + '</span><span>' + value + '</span></div>'
                ).join('');
                if (versionCompareResult) {
                    versionCompareResult.innerHTML =
                        '<p class="tp-note" style="margin:0.4rem 0 0.2rem;">v' + a + ' &rarr; v' + b + '</p>' + rows;
                }
            } catch (e) {
                if (versionCompareResult) versionCompareResult.innerHTML = '<p class="tp-note">Comparison failed.</p>';
            }
        });

        function loadVersions() {
            if (!versionList) return;
            versionList.innerHTML = '<p class="tp-note" style="text-align:center;padding:0.5rem 0;">Loading...</p>';

            selectedForCompare = [];
            if (versionCompareResult) versionCompareResult.innerHTML = '';
            updateCompareButton();

            fetch('/api/versions/' + modelId)
                .then(r => r.json())
                .then(data => {
                    versionPreviewItems = data.versions || [];
                    if (!data.success || !data.versions || data.versions.length === 0) {
                        versionList.innerHTML = '<p class="tp-note" style="text-align:center;padding:0.5rem 0;">No version history</p>';

                        return;
                    }
                    versionList.innerHTML = '';
                    data.versions.forEach(v => {
                        const div = document.createElement('div');
                        div.className = 'tp-version-card';

                        div.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.25rem;">' +
                            '<div style="display:flex;align-items:center;gap:0.35rem;">' +
                            '<input type="checkbox" class="compare-checkbox" title="Select to compare">' +
                            '<span style="font-weight:700;font-size:0.72rem;color:var(--color-gray-200);">v' + v.version_number + '</span>' +
                            '<span class="tp-version-badge">' + escapeHtml(v.operation_type) + '</span>' +
                            '</div>' +
                            '<span style="font-size:0.6rem;color:var(--color-gray-500);">' + escapeHtml(v.created_at || '') + '</span>' +
                            '</div>' +
                            (v.comment ? '<p style="font-size:0.68rem;color:var(--color-gray-500);margin-bottom:0.2rem;">' + escapeHtml(v.comment) + '</p>' : '') +
                            (v.file_size_formatted ? '<p style="font-size:0.6rem;color:var(--color-gray-500);margin-bottom:0.3rem;">Size: ' + v.file_size_formatted + '</p>' : '') +
                            '<div style="display:flex;gap:3px;">' +
                            (CAN_EDIT ? '<button class="restore-btn tp-btn-sm" style="flex:1;">Restore</button>' : '') +
                            '<button class="download-btn tp-btn-sm" style="flex:1;">Download</button>' +
                            (CAN_EDIT ? '<button class="delete-btn tp-btn-sm" style="color:var(--color-gray-500);">Del</button>' : '') +
                            '</div>';

                        div.querySelector('.compare-checkbox').addEventListener('change', (e) => {
                            if (e.target.checked) {
                                if (selectedForCompare.length >= 2) {
                                    e.target.checked = false;
                                    return;
                                }
                                selectedForCompare.push(v.version_number);
                            } else {
                                selectedForCompare = selectedForCompare.filter(n => n !== v.version_number);
                            }
                            updateCompareButton();
                        });

                        div.querySelector('.restore-btn')?.addEventListener('click', async () => {
                            if (!confirm('Restore to version ' + v.version_number + '? Current model will be replaced.')) return;
                            try {
                                const res = await fetch('/api/versions/' + modelId + '/restore/' + v.version_number, { method: 'POST' });
                                const result = await res.json();
                                if (result.success) window.location.reload();
                                else alert('Restore failed: ' + (result.error || ''));
                            } catch (e) { alert('Restore failed.'); }
                        });

                        div.querySelector('.download-btn').addEventListener('click', () => {
                            window.open('/api/versions/' + modelId + '/download/' + v.version_number, '_blank');
                        });

                        div.querySelector('.delete-btn')?.addEventListener('click', async () => {
                            if (!confirm('Delete version ' + v.version_number + '?')) return;
                            try {
                                const res = await fetch('/api/versions/' + modelId + '/delete/' + v.version_number, { method: 'DELETE' });
                                const result = await res.json();
                                if (result.success) loadVersions();
                                else alert('Delete failed: ' + (result.error || ''));
                            } catch (e) { alert('Delete failed.'); }
                        });

                        versionList.appendChild(div);
                    });
    
                })
                .catch(err => {
                    console.error('Failed to load versions:', err);
                    versionPreviewItems = [];
    
                    versionList.innerHTML = '<p class="tp-note" style="text-align:center;padding:0.5rem 0;">Failed to load versions</p>';
                });
        }

        loadVersions();
        refreshVersions?.addEventListener('click', loadVersions);
});
