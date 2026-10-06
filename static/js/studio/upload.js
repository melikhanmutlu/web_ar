/* Studio page: upload form, batch upload, conversion polling. Server values come from <script id="studio-config"> (JSON). */
var STUDIO_CONFIG = JSON.parse(document.getElementById('studio-config').textContent);

document.addEventListener('DOMContentLoaded', function() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('file-upload');
    const selectedFileName = document.getElementById('selectedFileName');
    const uploadForm = document.getElementById('uploadForm');
    const uploadResult = document.getElementById('uploadResult');

    // Initialize color picker functionality
    const colorPickerCheckbox = document.getElementById('useColor');
    const colorPickerContainer = document.getElementById('colorPickerContainer');
    const colorPicker = document.getElementById('colorPicker');
    const colorInput = document.getElementById('colorInput');

    if (colorPickerCheckbox && colorPickerContainer) {
        colorPickerCheckbox.addEventListener('change', function() {
            if (this.checked) {
                colorPickerContainer.classList.remove('hidden');
            } else {
                colorPickerContainer.classList.add('hidden');
            }
        });
    }

    // Sync color picker and text input
    if (colorPicker && colorInput) {
        colorPicker.addEventListener('input', function() {
            colorInput.value = this.value.toUpperCase();
        });

        colorInput.addEventListener('input', function() {
            const value = this.value.trim();
            if (/^#[0-9A-Fa-f]{6}$/.test(value)) {
                colorPicker.value = value;
                this.classList.remove('is-invalid');
            } else {
                this.classList.add('is-invalid');
            }
        });
    }

    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    // Highlight drop zone when item is dragged over it
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });

    // Handle dropped files
    dropZone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;

        if (files.length > 0) {
            fileInput.files = files; // Set the files to the input element
            handleFiles(files); // may clear the input again if the selection is rejected
        }
    });

    // Handle clicked files
    dropZone.addEventListener('click', () => {
        fileInput.click();
    });

    // Handle selected files
    const submitBtn = document.getElementById('submitBtn');
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            // handleFiles enables/disables the submit button itself.
            handleFiles(e.target.files);
        }
    });

    // Handle MTL file selection
    const mtlInput = document.getElementById('mtl-upload');
    const selectedMtlFileName = document.getElementById('selectedMtlFileName');
    const mtlUploadText = document.getElementById('mtlUploadText');

    mtlInput.addEventListener('change', (e) => {
        // Remove existing MTL color warning if any
        document.getElementById('mtlColorWarning')?.remove();

        if (e.target.files.length > 0) {
            const file = e.target.files[0];
            const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
            selectedMtlFileName.innerHTML = `Selected: ${escapeHtml(file.name)}<br>(${fileSizeMB} MB)`;
            selectedMtlFileName.classList.remove('hidden');
            mtlUploadText.classList.add('hidden');

            // Show warning that color will be ignored when MTL is present
            const warning = document.createElement('div');
            warning.id = 'mtlColorWarning';
            warning.className = 'av-note';
            warning.innerHTML = '<strong>Note:</strong> When an MTL file is provided, the selected color will be ignored. The model will use materials defined in the MTL file.';
            selectedMtlFileName.parentElement.appendChild(warning);
        } else {
            selectedMtlFileName.classList.add('hidden');
            mtlUploadText.classList.remove('hidden');
        }
    });

    // Handle texture files selection
    const textureInput = document.getElementById('texture-upload');
    const selectedTextureFileNames = document.getElementById('selectedTextureFileNames');
    const textureUploadText = document.getElementById('textureUploadText');

    textureInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            const files = Array.from(e.target.files);
            const totalSizeMB = (files.reduce((total, file) => total + file.size, 0) / (1024 * 1024)).toFixed(2);
            const fileList = files.map(file => escapeHtml(file.name)).join('<br>');
            selectedTextureFileNames.innerHTML = `Selected ${files.length} file(s):<br>${fileList}<br>Total: ${totalSizeMB} MB`;
            selectedTextureFileNames.classList.remove('hidden');
            textureUploadText.classList.add('hidden');
        } else {
            selectedTextureFileNames.classList.add('hidden');
            textureUploadText.classList.remove('hidden');
        }
    });

    // Derived from the backend's ALLOWED_EXTENSIONS (single source of
    // truth) so the client never rejects a type the server accepts — the
    // hardcoded list previously omitted .zip, blocking the very ZIP bundle
    // workflow the UI instructs users to use.
    const VALID_UPLOAD_EXTENSIONS = STUDIO_CONFIG.uploadExtensions.map((e) => '.' + e);
    const UPLOAD_MAX_BYTES = STUDIO_CONFIG.uploadMaxBytes;

    function fileExtensionOf(file) {
        return '.' + file.name.split('.').pop().toLowerCase();
    }

    // Returns true when the selection is usable. On rejection the specific
    // error is shown (displayError also clears the input and keeps the
    // submit button disabled) so a later submit can't overwrite it with a
    // generic "select a file" message.
    function handleFiles(files) {
        if (files.length > 1) {
            handleMultipleFiles(files);
            return pendingBatchFiles.length > 0;
        }
        const file = files[0];
        if (file) {
            // Check file type
            const fileExtension = fileExtensionOf(file);

            if (!VALID_UPLOAD_EXTENSIONS.includes(fileExtension)) {
                displayError('Invalid file type. Supported: ' + STUDIO_CONFIG.uploadExtensions.map((e) => e.toUpperCase()).join(', ') + '.');
                return false;
            }

            // Upload policy is rendered from the backend's single source of truth.
            if (file.size > UPLOAD_MAX_BYTES) {
                displayError('File size exceeds your plan\'s ' + STUDIO_CONFIG.uploadMaxMb + 'MB limit. Please choose a smaller file.');
                return false;
            }

            // Update the filename display
            const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
            selectedFileName.innerHTML = `Selected: ${escapeHtml(file.name)}<br>(${fileSizeMB} MB)`;
            selectedFileName.classList.remove('hidden');
            document.getElementById('batchNote')?.classList.add('hidden');

            // A valid new selection replaces any earlier rejection message.
            uploadForm.querySelector('.av-alert--error')?.remove();
            // Enable submit button
            const submitBtn = document.getElementById('submitBtn');
            if (submitBtn) submitBtn.disabled = false;

            // Show/hide MTL and texture upload based on file type
            const mtlUpload = document.getElementById('mtlUpload');
            const textureUpload = document.getElementById('textureUpload');

            if (fileExtension === '.obj') {
                mtlUpload?.classList.remove('hidden');
                textureUpload?.classList.remove('hidden');
            } else {
                mtlUpload?.classList.add('hidden');
                textureUpload?.classList.add('hidden');
                // Clear any previously-selected MTL/texture files -- the
                // submit handler appends them whenever they're non-empty,
                // so selecting OBJ+MTL then re-selecting e.g. an STL used
                // to silently submit the STL with the leftover MTL.
                const mtlInputEl = document.getElementById('mtl-upload');
                const textureInputEl = document.getElementById('texture-upload');
                if (mtlInputEl) mtlInputEl.value = '';
                if (textureInputEl) textureInputEl.value = '';
            }

            // Source-unit selector is only meaningful for unitless STL/OBJ files.
            // Default to cm (same as the API and batch upload); "Auto-detect"
            // is an explicit option that measures the raw extents.
            const sourceUnitSection = document.getElementById('sourceUnitSection');
            const sourceUnitSelect = document.getElementById('sourceUnit');
            const unitlessType = (fileExtension === '.stl' || fileExtension === '.obj');
            sourceUnitSection?.classList.toggle('hidden', !unitlessType);
            if (sourceUnitSelect && unitlessType) {
                sourceUnitSelect.value = 'cm';
            }
        }
    }

    // Multi-file selection: each file becomes its own independent
    // conversion job via /api/uploads/batch (no MTL/texture companions,
    // no per-file source unit -- those need the single-file form).
    let pendingBatchFiles = [];
    function handleMultipleFiles(fileList) {
        const files = Array.from(fileList);
        const valid = [];
        const rejected = [];
        for (const file of files) {
            const ext = fileExtensionOf(file);
            if (!VALID_UPLOAD_EXTENSIONS.includes(ext)) {
                rejected.push(`${file.name} (unsupported type)`);
            } else if (file.size > UPLOAD_MAX_BYTES) {
                rejected.push(`${file.name} (exceeds ${STUDIO_CONFIG.uploadMaxMb}MB)`);
            } else {
                valid.push(file);
            }
        }

        pendingBatchFiles = valid;
        const submitBtn = document.getElementById('submitBtn');

        if (valid.length === 0) {
            // Escape: rejected[] contains raw, attacker-influenceable
            // filenames and displayError injects into innerHTML.
            displayError(`No valid files selected. ${escapeHtml(rejected.join(', '))}`);
            if (submitBtn) submitBtn.disabled = true;
            return;
        }

        const totalMB = (valid.reduce((sum, f) => sum + f.size, 0) / (1024 * 1024)).toFixed(2);
        let summary = `Selected ${valid.length} file(s) (${totalMB} MB total)`;
        if (rejected.length > 0) summary += `<br><span class="av-text-error">Skipped: ${escapeHtml(rejected.join(', '))}</span>`;
        selectedFileName.innerHTML = summary;
        selectedFileName.classList.remove('hidden');
        document.getElementById('batchNote')?.classList.remove('hidden');
        uploadForm.querySelector('.av-alert--error')?.remove();
        if (submitBtn) submitBtn.disabled = false;

        // Batch mode has no per-file MTL/texture/source-unit controls.
        document.getElementById('mtlUpload')?.classList.add('hidden');
        document.getElementById('textureUpload')?.classList.add('hidden');
        document.getElementById('sourceUnitSection')?.classList.add('hidden');
    }

    function displayError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'av-alert av-alert--error';
        errorDiv.innerHTML = `
            <div class="av-alert-title">Upload Failed</div>
            <div style="margin-top:0.25rem;font-size:0.85rem;">${message}</div>
        `;

        // Remove any existing error messages
        const existingError = uploadForm.querySelector('.av-alert--error');
        if (existingError) {
            existingError.remove();
        }

        // Insert error message at the top of the form
        uploadForm.insertBefore(errorDiv, uploadForm.firstChild);

        // Clear the file input
        fileInput.value = '';
        selectedFileName.classList.add('hidden');
        pendingBatchFiles = [];
        document.getElementById('batchNote')?.classList.add('hidden');
        const failedSubmitBtn = document.getElementById('submitBtn');
        if (failedSubmitBtn) failedSubmitBtn.disabled = true;
    }

    function highlight(e) {
        dropZone.classList.add('is-dragover');
    }

    function unhighlight(e) {
        dropZone.classList.remove('is-dragover');
    }

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    function formatBytes(bytes) {
        const units = ['B', 'KB', 'MB', 'GB'];
        let size = bytes;
        let unitIndex = 0;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
    }

    // Render one progress row per name into #batchUploadList and return the
    // row refs (position-indexed). Shared by multi-file upload and the
    // multi-model-ZIP flow so both show the same progress list.
    function renderBatchRows(names) {
        const batchList = document.getElementById('batchUploadList');
        const uploadStatus = document.getElementById('uploadStatus');
        uploadStatus.classList.add('hidden');
        uploadStatus.style.display = 'none';
        batchList.innerHTML = '';
        batchList.classList.remove('hidden');
        const rows = [];
        names.forEach((name) => {
            const row = document.createElement('div');
            row.className = 'batch-row';
            row.innerHTML = `
                <div class="batch-row-head">
                    <span class="batch-row-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
                    <span class="batch-row-status">Uploading…</span>
                </div>
                <div class="progress-bar-container"><div class="progress-bar" style="width:5%;"></div></div>
            `;
            batchList.appendChild(row);
            rows.push({
                el: row,
                statusEl: row.querySelector('.batch-row-status'),
                barEl: row.querySelector('.progress-bar'),
            });
        });
        return rows;
    }

    // Attach polling (and any errors) to already-rendered rows from a
    // batch-style response ({jobs:[{index,...}], errors:[{index,...}]}).
    function trackBatchJobs(rows, data) {
        (data.errors || []).forEach((err) => {
            const refs = rows[err.index];
            if (!refs) return;
            refs.statusEl.textContent = err.error;
            refs.statusEl.classList.add('is-error');
            refs.barEl.classList.add('error');
        });
        (data.jobs || []).forEach((job) => {
            const refs = rows[job.index];
            if (!refs) return;
            pollBatchJob(refs, job.job_id, job.status_token, job.edit_token);
        });
    }

    // Multi-file upload: each file becomes its own independent
    // ConversionJob via /api/uploads/batch (blueprints/upload.py), tracked
    // with its own progress row instead of the single-file progress bar.
    async function submitBatchUpload(files) {
        const batchList = document.getElementById('batchUploadList');
        const rows = renderBatchRows(files.map((f) => f.name));

        const formData = new FormData();
        files.forEach((file) => formData.append('files', file));
        const useColorCheckbox = document.getElementById('useColor');
        formData.append('useColor', (useColorCheckbox && useColorCheckbox.checked) ? 'true' : 'false');
        formData.append('color', document.getElementById('colorPicker').value);
        const useMaxDimensionCheckbox = document.getElementById('useMaxDimension');
        formData.append('useMaxDimension', (useMaxDimensionCheckbox && useMaxDimensionCheckbox.checked) ? 'true' : 'false');
        formData.append('maxDimension', document.getElementById('max-dimension').value);
        const compressionSelect = document.getElementById('compression');
        if (compressionSelect) formData.append('compression', compressionSelect.value);

        let data;
        try {
            const response = await fetch('/api/uploads/batch', { method: 'POST', body: formData });
            data = await response.json();
            if (!response.ok && !(data.jobs && data.jobs.length)) {
                displayError(data.error || 'Batch upload failed.');
                batchList.classList.add('hidden');
                return;
            }
        } catch (err) {
            rows.forEach(({ statusEl, barEl }) => {
                statusEl.textContent = 'Network error';
                statusEl.classList.add('is-error');
                barEl.classList.add('error');
            });
            return;
        }

        // Rows and jobs share the backend's request-order index.
        trackBatchJobs(rows, data);
    }

    // Tracks one batch row's job to completion (mirrors pollUploadJob's
    // SSE-with-polling-fallback approach, but updates a specific row's
    // elements instead of the single-file progress UI).
    function pollBatchJob(refs, jobId, statusToken, editToken) {
        const stageText = { pending: 'Queued', processing: 'Converting', completed: 'Complete', failed: 'Failed' };

        function apply(job) {
            if (!job.success) return false;
            if (job.status === 'completed' && job.viewer_url) {
                const viewerUrl = editToken ? `${job.viewer_url}?edit_token=${encodeURIComponent(editToken)}` : job.viewer_url;
                refs.statusEl.textContent = 'Ready';
                refs.statusEl.classList.add('is-done');
                refs.barEl.style.width = '100%';
                const link = document.createElement('a');
                link.href = viewerUrl;
                link.target = '_blank';
                link.rel = 'noopener';
                link.className = 'batch-row-link';
                link.textContent = 'View model →';
                refs.el.appendChild(link);
                return true;
            } else if (job.status === 'failed' || job.status === 'dead_letter') {
                refs.statusEl.textContent = job.error || 'Conversion failed';
                refs.statusEl.classList.add('is-error');
                refs.barEl.classList.add('error');
                return true;
            }
            const progress = typeof job.progress === 'number' ? job.progress : (job.status === 'processing' ? 60 : 20);
            refs.barEl.style.width = Math.min(progress, 96) + '%';
            refs.statusEl.textContent = job.stage || stageText[job.status] || job.status || 'Processing';
            return false;
        }

        function pollFallback() {
            const poll = setInterval(() => {
                fetch(`/api/upload-jobs/${jobId}`, {headers: {'X-Job-Status-Token': statusToken}})
                    .then(r => r.json())
                    .then(job => { if (apply(job)) clearInterval(poll); })
                    .catch(() => { /* transient network error; keep polling */ });
            }, STUDIO_CONFIG.workerPollIntervalMs);
        }

        if (typeof EventSource === 'undefined') {
            pollFallback();
            return;
        }
        const source = new EventSource(`/api/upload-jobs/${jobId}/stream?status_token=${encodeURIComponent(statusToken)}`);
        let fellBack = false;
        source.onmessage = (event) => {
            try {
                const job = JSON.parse(event.data);
                if (apply(job)) source.close();
            } catch (e) { /* ignore malformed event */ }
        };
        source.onerror = () => {
            source.close();
            if (!fellBack) {
                fellBack = true;
                pollFallback();
            }
        };
    }

    // Handle form submission
    let uploadInProgress = false; // guards against duplicate single-file submits
    uploadForm.addEventListener('submit', async function(e) {
        e.preventDefault();

        const fileInput = document.getElementById('file-upload');

        if (fileInput.files.length > 1) {
            if (pendingBatchFiles.length === 0) {
                displayError('Please select at least one valid file to upload.');
                return;
            }
            submitBatchUpload(pendingBatchFiles);
            return;
        }

        const file = fileInput.files[0];

        if (!file) {
            displayError('Please select a file to upload.');
            return;
        }

        // Prevent a second click from starting a duplicate conversion job
        // (both would convert, then race to redirect). The button is
        // re-enabled by endUpload() on any error terminal; the success
        // path navigates away, so it intentionally stays disabled.
        const submitBtnEl = document.getElementById('submitBtn');
        if (uploadInProgress) return;
        uploadInProgress = true;
        if (submitBtnEl) submitBtnEl.disabled = true;
        const endUpload = () => {
            uploadInProgress = false;
            if (submitBtnEl) submitBtnEl.disabled = false;
        };

        const formData = new FormData();
        formData.append('file', file);

        // Check if color should be applied
        const useColorCheckbox = document.getElementById('useColor');
        const shouldApplyColor = useColorCheckbox && useColorCheckbox.checked;
        formData.append('useColor', shouldApplyColor ? 'true' : 'false');
        formData.append('color', document.getElementById('colorPicker').value);

        const useMaxDimensionCheckbox = document.getElementById('useMaxDimension');
        const shouldLimitDimension = useMaxDimensionCheckbox && useMaxDimensionCheckbox.checked;
        formData.append('useMaxDimension', shouldLimitDimension ? 'true' : 'false');
        formData.append('maxDimension', document.getElementById('max-dimension').value);

        // Source unit for unitless STL/OBJ (ignored by the backend for other types)
        const sourceUnitSelect = document.getElementById('sourceUnit');
        if (sourceUnitSelect) formData.append('sourceUnit', sourceUnitSelect.value);
        const compressionSelect = document.getElementById('compression');
        if (compressionSelect) formData.append('compression', compressionSelect.value);

        console.log('Upload settings:', {
            useColor: shouldApplyColor,
            color: document.getElementById('colorPicker').value,
            useMaxDimension: shouldLimitDimension,
            maxDimension: document.getElementById('max-dimension').value
        });

        // Add MTL file if present (for OBJ files)
        const mtlInput = document.getElementById('mtl-upload');
        if (mtlInput && mtlInput.files.length > 0) {
            formData.append('mtl', mtlInput.files[0]);
            console.log('MTL file added:', mtlInput.files[0].name);
        }

        // Add texture files if present (for OBJ files)
        const textureInput = document.getElementById('texture-upload');
        if (textureInput && textureInput.files.length > 0) {
            for (let i = 0; i < textureInput.files.length; i++) {
                formData.append('textures', textureInput.files[i]);
                console.log('Texture file added:', textureInput.files[i].name);
            }
        }

        // Reset progress bar and show upload status
        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        const statusText = document.getElementById('uploadStatusText');
        const statusDetail = document.getElementById('uploadStatusDetail');
        const progressFileName = document.getElementById('progressFileName');
        const progressStage = document.getElementById('progressStage');
        const progressElapsed = document.getElementById('progressElapsed');
        const uploadStatus = document.getElementById('uploadStatus');
        const uploadResult = document.getElementById('uploadResult');

        progressBar.style.width = '0%';
        progressBar.classList.remove('error');
        progressText.textContent = '0%';
        statusText.textContent = 'Preparing upload';
        statusDetail.textContent = `Validating ${file.name} and staging conversion options.`;
        progressFileName.textContent = file.name;
        progressStage.textContent = 'Preparing';
        progressElapsed.textContent = '0s';
        uploadStatus.classList.remove('hidden');
        uploadStatus.style.display = 'block';
        uploadResult.style.display = 'none';

        let currentProgress = 0;
        const startedAt = Date.now();
        const elapsedTimer = setInterval(() => {
            progressElapsed.textContent = `${Math.max(1, Math.round((Date.now() - startedAt) / 1000))}s`;
        }, 1000);

        const stageText = {
            pending: 'Queued',
            processing: 'Converting',
            completed: 'Complete',
            failed: 'Failed'
        };

        function setProgress(percent, label, detail, stage) {
            currentProgress = Math.max(currentProgress, Math.min(100, percent));
            progressBar.style.width = currentProgress + '%';
            progressText.textContent = Math.round(currentProgress) + '%';
            if (label) statusText.textContent = label;
            if (detail) statusDetail.textContent = detail;
            if (stage) progressStage.textContent = stage;
        }

        // Shows success UI then redirects to the viewer
        function finishUpload(message, viewerUrl) {
            clearInterval(elapsedTimer);
            uploadResult.className = 'upload-result success';
            uploadResult.style.display = 'block';

            setProgress(100, 'Upload completed', 'Model is ready. Opening the viewer now.', 'Ready');

            setTimeout(() => {
                uploadResult.innerHTML = `<div>${escapeHtml(message)}</div>`;
                setTimeout(() => {
                    window.location.href = viewerUrl;
                }, 1000);
            }, 500);
        }

        // Applies one job-status update to the progress UI. Returns true
        // once the job reaches a terminal state (caller stops watching).
        function applyJobUpdate(job, editToken) {
            if (!job.success) {
                // Terminal: an expired/invalid status token or a GC'd job
                // returns success:false. Returning false here left the
                // poll interval / SSE running forever with the bar stuck.
                clearInterval(elapsedTimer);
                progressBar.classList.add('error');
                uploadResult.className = 'upload-result error';
                uploadResult.style.display = 'block';
                setProgress(currentProgress, 'Conversion status unavailable',
                    job.error || 'The upload job could not be tracked. Please check My Models or try again.', 'Failed');
                uploadResult.innerHTML = `<div class="av-text-error">${escapeHtml(job.error || 'Upload job status unavailable')}</div>`;
                endUpload();
                return true;
            }
            const jobProgress = typeof job.progress === 'number' ? job.progress : null;
            const nextProgress = jobProgress !== null ? jobProgress : (job.status === 'processing' ? 72 : currentProgress);
            const stage = job.stage || stageText[job.status] || job.status || 'Processing';
            const attempts = job.attempts ? ` Attempt ${job.attempts}.` : '';

            if (job.status === 'completed' && job.viewer_url) {
                const viewerUrl = editToken ? `${job.viewer_url}?edit_token=${encodeURIComponent(editToken)}` : job.viewer_url;
                finishUpload('Model converted successfully', viewerUrl);
                return true;
            } else if (job.status === 'failed' || job.status === 'dead_letter') {
                clearInterval(elapsedTimer);
                progressBar.classList.add('error');
                uploadResult.className = 'upload-result error';
                uploadResult.style.display = 'block';
                setProgress(currentProgress, 'Conversion failed', job.error || 'The model could not be converted.', 'Failed');
                uploadResult.innerHTML = `<div class="av-text-error">${escapeHtml(job.error || 'Conversion failed')}</div>`;
                endUpload();
                return true;
            }
            setProgress(
                Math.min(nextProgress, 96),
                stage,
                `${job.detail || 'Processing model geometry, materials, and viewer assets.'}${attempts}`,
                stage
            );
            return false;
        }

        // Falls back to 2s polling if SSE isn't available or drops --
        // e.g. the stream hit its server-side max duration for a
        // long-running conversion, or a proxy buffered/killed it.
        function pollUploadJobFallback(jobId, statusToken, editToken) {
            const poll = setInterval(() => {
                fetch(`/api/upload-jobs/${jobId}`, {headers: {'X-Job-Status-Token': statusToken}})
                    .then(r => r.json())
                    .then(job => { if (applyJobUpdate(job, editToken)) clearInterval(poll); })
                    .catch(() => { /* transient network error; keep polling */ });
            }, STUDIO_CONFIG.workerPollIntervalMs);
        }

        // Real-time job progress (Faz 4: SSE), falling back to polling
        // if EventSource isn't available or the connection errors out.
        function pollUploadJob(jobId, statusToken, editToken) {
            setProgress(Math.max(currentProgress, 45), 'Conversion queued', 'Waiting for the conversion worker to pick up the model.', 'Queued');

            if (typeof EventSource === 'undefined') {
                pollUploadJobFallback(jobId, statusToken, editToken);
                return;
            }

            const source = new EventSource(`/api/upload-jobs/${jobId}/stream?status_token=${encodeURIComponent(statusToken)}`);
            let fellBack = false;
            source.onmessage = (event) => {
                try {
                    const job = JSON.parse(event.data);
                    if (applyJobUpdate(job, editToken)) source.close();
                } catch (e) { /* ignore malformed event */ }
            };
            source.onerror = () => {
                source.close();
                if (!fellBack && currentProgress < 100) {
                    fellBack = true;
                    pollUploadJobFallback(jobId, statusToken, editToken);
                }
            };
        }

        // Large single files (no MTL/texture companions -- those still
        // need the single-shot multipart path) go through the chunked,
        // resumable-within-session upload endpoint instead of one big
        // XHR, so a dropped connection only costs the current chunk.
        const CHUNK_THRESHOLD_BYTES = 20 * 1024 * 1024;
        const hasCompanions = (mtlInput && mtlInput.files.length > 0) ||
            (textureInput && textureInput.files.length > 0);
        // ZIPs go through the regular multipart path even when large: the
        // chunked endpoint can't accept archives (it needs to fan a
        // multi-model ZIP into several jobs, which /upload_model does).
        const isZip = /\.zip$/i.test(file.name);
        if (file.size > CHUNK_THRESHOLD_BYTES && !hasCompanions && !isZip) {
            uploadFileChunked(file, {
                useColor: shouldApplyColor,
                color: document.getElementById('colorPicker').value,
                useMaxDimension: shouldLimitDimension,
                maxDimension: document.getElementById('max-dimension').value,
                sourceUnit: sourceUnitSelect ? sourceUnitSelect.value : undefined,
                compression: compressionSelect ? compressionSelect.value : undefined,
            });
            return;
        }

        // Uploads `file` in chunks with per-chunk retry, then completes
        // the session to hand off into the same job/polling flow as a
        // regular upload. Only called for large, companion-free files.
        async function uploadFileChunked(file, options) {
            const CHUNK_SIZE = 5 * 1024 * 1024;
            const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
            try {
                const initResp = await fetch('/api/uploads/chunked/init', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: file.name, total_size: file.size, total_chunks: totalChunks }),
                });
                const initData = await initResp.json();
                if (!initResp.ok || !initData.success) throw new Error(initData.error || 'Could not start upload');
                const uploadId = initData.upload_id;

                setProgress(4, 'Uploading model', `Sending ${file.name} in ${totalChunks} chunk(s).`, 'Uploading');
                let uploaded = 0;
                for (let i = 0; i < totalChunks; i++) {
                    const chunk = file.slice(i * CHUNK_SIZE, Math.min((i + 1) * CHUNK_SIZE, file.size));
                    let lastError = null;
                    let ok = false;
                    for (let attempt = 0; attempt < 3 && !ok; attempt++) {
                        if (attempt > 0) await new Promise(r => setTimeout(r, 1000 * attempt));
                        try {
                            const chunkResp = await fetch(`/api/uploads/chunked/${uploadId}/chunks/${i}`, {
                                method: 'PUT', body: chunk,
                            });
                            if (!chunkResp.ok) throw new Error('Chunk upload failed');
                            ok = true;
                        } catch (err) {
                            lastError = err;
                        }
                    }
                    if (!ok) throw lastError || new Error('Chunk upload failed');
                    uploaded += chunk.size;
                    const uploadPercent = Math.round((uploaded / file.size) * 38);
                    setProgress(uploadPercent, 'Uploading model', `${formatBytes(uploaded)} of ${formatBytes(file.size)} transferred.`, 'Uploading');
                }

                setProgress(40, 'Finalizing upload', 'Assembling chunks and starting conversion.', 'Finalizing');
                const completeResp = await fetch(`/api/uploads/chunked/${uploadId}/complete`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(options),
                });
                const completeData = await completeResp.json();
                if (!completeResp.ok || !completeData.success) throw new Error(completeData.error || 'Upload failed');

                if (completeData.viewer_url) {
                    finishUpload(completeData.message, completeData.viewer_url);
                } else if (completeData.job_id) {
                    pollUploadJob(completeData.job_id, completeData.status_token, completeData.edit_token);
                }
            } catch (error) {
                clearInterval(elapsedTimer);
                progressBar.classList.add('error');
                uploadResult.className = 'upload-result error';
                uploadResult.style.display = 'block';
                setProgress(currentProgress, 'Upload failed', error.message, 'Failed');
                uploadResult.innerHTML = `<div class="av-text-error">${escapeHtml(error.message)}</div>`;
            }
        }

        // Upload file
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload_model');
        // XHR isn't covered by the global fetch CSRF wrapper, so set the
        // token header here explicitly.
        (function () {
            const m = document.querySelector('meta[name="csrf-token"]');
            if (m) xhr.setRequestHeader('X-CSRFToken', m.getAttribute('content'));
        })();
        xhr.upload.addEventListener('progress', (event) => {
            if (!event.lengthComputable) {
                setProgress(18, 'Uploading model', 'Sending file to the local server.', 'Uploading');
                return;
            }
            const uploadPercent = Math.round((event.loaded / event.total) * 38);
            setProgress(uploadPercent, 'Uploading model', `${formatBytes(event.loaded)} of ${formatBytes(event.total)} transferred.`, 'Uploading');
        });
        xhr.onreadystatechange = () => {
            if (xhr.readyState !== XMLHttpRequest.DONE) return;
            try {
                const response = JSON.parse(xhr.responseText || '{}');
                if (xhr.status >= 200 && xhr.status < 300 && response.success && response.multi) {
                    // A single ZIP held several models -> the backend fanned
                    // them into one job each; show the batch progress list.
                    clearInterval(elapsedTimer);
                    endUpload();
                    const uploadStatusEl = document.getElementById('uploadStatus');
                    if (uploadStatusEl) { uploadStatusEl.classList.add('hidden'); uploadStatusEl.style.display = 'none'; }
                    const names = (response.jobs || []).map((j) => j.filename);
                    trackBatchJobs(renderBatchRows(names), response);
                } else if (xhr.status >= 200 && xhr.status < 300 && response.success && response.viewer_url) {
                    setProgress(96, 'Finalizing model', 'Conversion finished; preparing the viewer route.', 'Finalizing');
                    finishUpload(response.message, response.viewer_url);
                } else if (xhr.status >= 200 && xhr.status < 300 && response.success && response.job_id) {
                    pollUploadJob(response.job_id, response.status_token, response.edit_token);
                } else {
                    throw new Error(response.error || 'Upload failed');
                }
            } catch (error) {
                clearInterval(elapsedTimer);
                progressBar.classList.add('error');
                uploadResult.className = 'upload-result error';
                uploadResult.style.display = 'block';
                setProgress(currentProgress, 'Upload failed', error.message, 'Failed');
                uploadResult.innerHTML = `<div class="av-text-error">${escapeHtml(error.message)}</div>`;
                endUpload();
            }
        };
        xhr.onerror = () => {
            clearInterval(elapsedTimer);
            progressBar.classList.add('error');
            uploadResult.className = 'upload-result error';
            uploadResult.style.display = 'block';
            setProgress(currentProgress, 'Network error', 'Could not reach the local upload endpoint.', 'Failed');
            uploadResult.innerHTML = '<div class="av-text-error">Network error while uploading.</div>';
            endUpload();
        };
        setProgress(4, 'Preparing upload', 'Packaging selected file, materials, textures, and options.', 'Preparing');
        xhr.send(formData);
    });

    // Limit Model Size toggle
    const useMaxDimension = document.getElementById('useMaxDimension');
    const maxDimensionInput = document.getElementById('maxDimensionInput');
    if (useMaxDimension && maxDimensionInput) {
        useMaxDimension.addEventListener('change', function() {
            maxDimensionInput.classList.toggle('hidden', !this.checked);
        });
    }
});
