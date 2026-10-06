/* Studio page: tab switching + AI generation. Server values come from <script id="studio-config"> (JSON). */
var STUDIO_CONFIG = JSON.parse(document.getElementById('studio-config').textContent);

(function () {
    // Top-level tabs: Upload | Generate
    document.querySelectorAll('.av-tabs:not(.av-tabs--sub) .av-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.av-tabs:not(.av-tabs--sub) .av-tab').forEach(b => b.classList.remove('is-active'));
            btn.classList.add('is-active');
            const panel = btn.dataset.panel;
            document.getElementById('panel-upload')?.classList.toggle('hidden', panel !== 'panel-upload');
            document.getElementById('panel-generate')?.classList.toggle('hidden', panel !== 'panel-generate');
        });
    });

    const genBtn = document.getElementById('generateBtn');
    if (!genBtn) return; // not authenticated -> no generate UI

    let genMode = 'image';
    let imageDataUri = null;

    // Sub-tabs: From Text | From Image
    document.querySelectorAll('.av-tabs--sub .av-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.av-tabs--sub .av-tab').forEach(b => b.classList.remove('is-active'));
            btn.classList.add('is-active');
            genMode = btn.dataset.genmode;
            document.getElementById('genText').classList.toggle('hidden', genMode !== 'text');
            document.getElementById('genImage').classList.toggle('hidden', genMode !== 'image');
        });
    });

    // Pre-processing selections (Meshy image-gen task references; the
    // server re-resolves them by task id — raw URLs are never sent)
    let t2iSelection = null;   // {kind:'t2i', task_id, index}
    let i2iSelection = null;   // {kind:'i2i', task_id, index}
    let originalDataUri = null;

    // Image selection -> data URI + preview
    const aiImageDrop = document.getElementById('aiImageDrop');
    const aiImage = document.getElementById('ai-image');
    const aiImagePreview = document.getElementById('aiImagePreview');
    aiImageDrop?.addEventListener('click', () => aiImage.click());
    aiImage?.addEventListener('change', (e) => {
        const f = e.target.files[0];
        if (!f) return;
        if (f.size > 10 * 1024 * 1024) { window.arToast('Image too large (max 10MB).', 'error'); return; }
        const reader = new FileReader();
        reader.onload = () => {
            imageDataUri = reader.result;
            originalDataUri = reader.result;
            i2iSelection = null;
            document.getElementById('i2iNote').classList.add('hidden');
            aiImagePreview.src = reader.result;
            aiImagePreview.classList.remove('hidden');
            document.getElementById('i2iTools').classList.remove('hidden');
        };
        reader.readAsDataURL(f);
    });

    const statusDiv = document.getElementById('generationStatus');
    const bar = document.getElementById('generationBar');
    const txt = document.getElementById('generationText');
    const label = document.getElementById('generationLabel');
    const errBox = document.getElementById('generationError');

    function setProgress(p, msg) {
        bar.style.width = p + '%';
        txt.textContent = Math.round(p) + '%';
        if (msg) label.textContent = msg;
    }

    function showGenError(message) {
        bar.classList.add('error');
        errBox.textContent = message;
        errBox.classList.remove('hidden');
        setProgress(0, 'Failed');
    }

    // Human-readable labels per pipeline stage so the bar never looks
    // "stuck" at the preview→refine boundary (~49%) while Meshy queues
    // the texturing task under concurrent load.
    const STAGE_LABELS = {
        preview: 'Generating base mesh…',
        refining: 'Base mesh done — queueing texture stage…',
        refine: 'Texturing…',
        finalizing: 'Downloading & saving model…',
        image: 'Generating 3D model…'
    };

    // Start a task; if Meshy itself is at its concurrent-task limit
    // (surfaced as 502 + rate-limit message), retry with backoff
    // instead of failing — daily-quota 429s are NOT retried.
    async function startTask(url, body, busyLabel) {
        for (let attempt = 0; ; attempt++) {
            const r = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const d = await r.json();
            if (d.success) return d;
            const busy = r.status === 502 && /rate limit|429|try again shortly/i.test(d.error || '');
            if (!busy || attempt >= 3) throw new Error(d.error || 'Failed to start');
            const wait = 10 * (attempt + 1);
            setProgress(2, busyLabel + ' — busy, retrying in ' + wait + 's…');
            await new Promise(res => setTimeout(res, wait * 1000));
        }
    }

    // Poll a Meshy image-generation task until it yields image URLs.
    async function pollImageTask(taskId, kind, labelMsg) {
        let tries = 0;
        while (tries < 90) {
            await new Promise(res => setTimeout(res, 2000));
            tries++;
            const r = await fetch('/api/generate-image/' + taskId + '/status?kind=' + kind);
            const d = await r.json();
            if (!d.success) throw new Error(d.error || 'Status check failed');
            if (d.status === 'ready') return d.image_urls || [];
            if (d.status === 'failed') throw new Error(d.error || 'Image generation failed');
            setProgress(Math.max(3, d.progress || 0), labelMsg);
        }
        throw new Error('Image generation timed out.');
    }

    // ---- Text mode pre-step: visualize prompt as image(s), pick one ----
    const t2iResults = document.getElementById('t2iResults');
    const t2iNote = document.getElementById('t2iSelectedNote');

    function clearT2iSelection() {
        t2iSelection = null;
        t2iNote.classList.add('hidden');
        t2iResults.querySelectorAll('.imgen-item').forEach(b => b.classList.remove('selected'));
        genBtn.lastChild.textContent = ' Generate 3D Model';
    }
    document.getElementById('t2iClear')?.addEventListener('click', (e) => {
        e.preventDefault();
        clearT2iSelection();
    });

    document.getElementById('visualizeBtn')?.addEventListener('click', async () => {
        const visualizeBtn = document.getElementById('visualizeBtn');
        const p = document.getElementById('aiPrompt').value.trim();
        if (!p) { window.arToast('Please enter a prompt.', 'info'); return; }
        // Unlike transformBtn/genBtn, this button wasn't disabled during
        // its task -- a double click started two Meshy image-gen tasks
        // (both burning AI quota) racing on the shared progress bar.
        if (visualizeBtn.disabled) return;
        visualizeBtn.disabled = true;
        errBox.classList.add('hidden'); errBox.textContent = '';
        clearT2iSelection();
        t2iResults.classList.add('hidden');
        t2iResults.innerHTML = '';
        statusDiv.classList.remove('hidden');
        bar.classList.remove('error');
        setProgress(2, 'Generating image…');
        try {
            const d = await startTask('/api/generate-image',
                { mode: 'text', prompt: p }, 'Generating image');
            const urls = await pollImageTask(d.task_id, d.kind, 'Generating image…');
            if (!urls.length) throw new Error('No images were generated.');
            setProgress(100, 'Pick an image');
            urls.forEach((u, i) => {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'imgen-item';
                // Build the image via the DOM so the (server-provided) URL
                // can never break out of the attribute into markup.
                const imgEl = document.createElement('img');
                imgEl.src = u;
                imgEl.alt = 'Generated option ' + (i + 1);
                item.appendChild(imgEl);
                item.addEventListener('click', () => {
                    t2iResults.querySelectorAll('.imgen-item').forEach(b => b.classList.remove('selected'));
                    item.classList.add('selected');
                    t2iSelection = { kind: d.kind, task_id: d.task_id, index: i };
                    t2iNote.classList.remove('hidden');
                    genBtn.lastChild.textContent = ' Generate 3D from selected image';
                });
                t2iResults.appendChild(item);
            });
            t2iResults.classList.remove('hidden');
        } catch (e) {
            showGenError(e.message);
        } finally {
            visualizeBtn.disabled = false;
        }
    });

    // ---- Image mode pre-step: transform the uploaded photo ----
    const transformBtn = document.getElementById('transformBtn');
    document.getElementById('i2iRevert')?.addEventListener('click', (e) => {
        e.preventDefault();
        i2iSelection = null;
        document.getElementById('i2iNote').classList.add('hidden');
        if (originalDataUri) aiImagePreview.src = originalDataUri;
    });

    transformBtn?.addEventListener('click', async () => {
        const p = document.getElementById('i2iPrompt').value.trim();
        if (!originalDataUri) { window.arToast('Please choose an image first.', 'info'); return; }
        if (!p) { window.arToast('Describe how to transform the image.', 'info'); return; }
        errBox.classList.add('hidden'); errBox.textContent = '';
        transformBtn.disabled = true;
        statusDiv.classList.remove('hidden');
        bar.classList.remove('error');
        setProgress(2, 'Transforming image…');
        try {
            const d = await startTask('/api/generate-image',
                { mode: 'image', image: originalDataUri, prompt: p }, 'Transforming image');
            const urls = await pollImageTask(d.task_id, d.kind, 'Transforming image…');
            if (!urls.length) throw new Error('No image was generated.');
            setProgress(100, 'Image ready');
            aiImagePreview.src = urls[0];
            i2iSelection = { kind: d.kind, task_id: d.task_id, index: 0 };
            document.getElementById('i2iNote').classList.remove('hidden');
        } catch (e) {
            showGenError(e.message);
        } finally {
            transformBtn.disabled = false;
        }
    });

    // Collect the collapsed "Advanced options" panel into a plain object;
    // blank/default fields are omitted so the server sees no options at
    // all when the panel was never touched (identical to pre-Advanced-
    // options behavior).
    function collectAdvancedOptions(mode) {
        const opts = {};
        if (mode === 'text') {
            const neg = document.getElementById('optNegativePrompt').value.trim();
            if (neg) opts.negative_prompt = neg;
            const topology = document.getElementById('optTopology').value;
            if (topology) opts.topology = topology;
            const symmetry = document.getElementById('optSymmetry').value;
            if (symmetry) opts.symmetry_mode = symmetry;
            const polycount = document.getElementById('optPolycount').value;
            if (polycount) opts.target_polycount = parseInt(polycount, 10);
            const seed = document.getElementById('optSeed').value;
            if (seed) opts.seed = parseInt(seed, 10);
            const texturePrompt = document.getElementById('optTexturePrompt').value.trim();
            if (texturePrompt) opts.texture_prompt = texturePrompt;
            opts.moderation = document.getElementById('optModeration').checked;
        } else {
            const topology = document.getElementById('optTopologyImg').value;
            if (topology) opts.topology = topology;
            const symmetry = document.getElementById('optSymmetryImg').value;
            if (symmetry) opts.symmetry_mode = symmetry;
            const polycount = document.getElementById('optPolycountImg').value;
            if (polycount) opts.target_polycount = parseInt(polycount, 10);
            const pose = document.getElementById('optPoseMode').value;
            if (pose) opts.pose_mode = pose;
            const removeLighting = document.getElementById('optRemoveLighting');
            if (removeLighting && removeLighting.checked) opts.remove_lighting = true;
            opts.should_texture = document.getElementById('optShouldTexture').checked;
            opts.moderation = document.getElementById('optModerationImg').checked;
        }
        return opts;
    }

    // model-viewer is only needed once a generation actually finishes, so
    // it's loaded on demand rather than unconditionally in <head> (kept
    // out of pure-upload visits' page weight).
    let modelViewerLoading = null;
    function ensureModelViewerLoaded() {
        if (customElements.get('model-viewer')) return Promise.resolve();
        if (!modelViewerLoading) {
            modelViewerLoading = new Promise((resolve, reject) => {
                const s = document.createElement('script');
                s.type = 'module';
                s.src = STUDIO_CONFIG.assets.modelViewer;
                s.onload = () => {
                    // Meshopt-compressed GLBs need this decoder registered
                    // before any model loads, same as templates/view.html.
                    customElements.whenDefined('model-viewer').then(() => {
                        customElements.get('model-viewer').meshoptDecoderLocation =
                            STUDIO_CONFIG.assets.meshoptDecoder;
                        customElements.get('model-viewer').dracoDecoderLocation = STUDIO_CONFIG.assets.dracoDecoder;
                        customElements.get('model-viewer').ktx2TranscoderLocation = STUDIO_CONFIG.assets.ktx2Transcoder;
                    });
                    resolve();
                };
                s.onerror = () => reject(new Error('Failed to load 3D preview.'));
                document.head.appendChild(s);
            });
        }
        return modelViewerLoading;
    }

    const genResultPreview = document.getElementById('genResultPreview');
    const genPreviewViewer = document.getElementById('genPreviewViewer');
    const genKeepBtn = document.getElementById('genKeepBtn');
    const genDiscardBtn = document.getElementById('genDiscardBtn');
    const genQuotaRemaining = document.getElementById('genQuotaRemaining');

    function decrementQuota() {
        if (!genQuotaRemaining) return;
        const n = parseInt(genQuotaRemaining.textContent, 10);
        if (!isNaN(n) && n > 0) genQuotaRemaining.textContent = n - 1;
    }

    async function showGenResult(sd) {
        await ensureModelViewerLoaded();
        genPreviewViewer.src = sd.model_glb_url;
        genResultPreview.classList.remove('hidden');
        genKeepBtn.onclick = () => { window.location.href = sd.viewer_url; };
        genDiscardBtn.onclick = async () => {
            genDiscardBtn.disabled = true;
            try {
                await fetch('/delete_model/' + sd.model_id, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
            } catch (e) { /* best-effort; model just stays until the user retries from My Models */ }
            genResultPreview.classList.add('hidden');
            statusDiv.classList.add('hidden');
        };
    }

    genBtn.addEventListener('click', async () => {
        errBox.classList.add('hidden'); errBox.textContent = '';
        const body = { mode: genMode, options: collectAdvancedOptions(genMode) };
        if (genMode === 'text') {
            if (t2iSelection) {
                // build 3D from the AI-generated reference image
                body.mode = 'image';
                body.image_task = t2iSelection;
            } else {
                const p = document.getElementById('aiPrompt').value.trim();
                if (!p) { window.arToast('Please enter a prompt.', 'info'); return; }
                body.prompt = p;
            }
        } else {
            if (i2iSelection) {
                body.image_task = i2iSelection;
            } else {
                if (!imageDataUri) { window.arToast('Please choose an image.', 'info'); return; }
                body.image = imageDataUri;
            }
        }

        genBtn.disabled = true;
        genResultPreview.classList.add('hidden');
        statusDiv.classList.remove('hidden');
        bar.classList.remove('error');
        setProgress(2, 'Starting…');

        try {
            const d = await startTask('/api/generate-3d', body, 'Starting 3D generation');
            const jobId = d.job_id;
            decrementQuota();

            let done = false, tries = 0;
            while (!done && tries < 200) {
                await new Promise(res => setTimeout(res, 2500));
                tries++;
                const sr = await fetch('/api/generate-3d/' + jobId + '/status');
                const sd = await sr.json();
                if (!sd.success) throw new Error(sd.error || 'Status check failed');
                setProgress(Math.max(2, sd.progress || 0),
                    STAGE_LABELS[sd.stage] || 'Generating 3D model…');
                if (sd.status === 'ready' && sd.viewer_url) {
                    setProgress(100, 'Done');
                    if (sd.model_glb_url) {
                        await showGenResult(sd);
                    } else {
                        window.location.href = sd.viewer_url;
                    }
                    done = true;
                } else if (sd.status === 'failed') {
                    throw new Error(sd.error || 'Generation failed');
                }
            }
            if (!done) throw new Error('Generation timed out. Please try again.');
        } catch (e) {
            bar.classList.add('error');
            errBox.textContent = e.message;
            errBox.classList.remove('hidden');
            setProgress(0, 'Failed');
        } finally {
            genBtn.disabled = genBtn.dataset.locked === '1';
        }
    });
})();
