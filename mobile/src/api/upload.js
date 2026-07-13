import { apiFetch } from './client';

const CHUNK_SIZE = 4 * 1024 * 1024; // 4MB

// Matches config.py's ALLOWED_EXTENSIONS minus 'zip' -- the chunked-upload
// route rejects ZIP/MTL/texture companions itself (see upload.py's
// init_chunked_upload), so this app doesn't offer them either.
const ALLOWED_EXTENSIONS = new Set(['stl', 'fbx', 'obj', 'step', 'stp', 'glb', 'gltf']);

export function isAllowedModelFile(file) {
  const ext = (file.extension || '').replace('.', '').toLowerCase();
  return ALLOWED_EXTENSIONS.has(ext);
}

// Uploads `file` (an expo-file-system File instance from File.pickFileAsync)
// via the mobile chunked-upload routes, then returns the /complete response
// ({job_id, status, status_url, status_token, ...}).
export async function uploadModelFile(token, file, { onProgress } = {}) {
  const totalSize = file.size;
  const totalChunks = Math.max(1, Math.ceil(totalSize / CHUNK_SIZE));

  const init = await apiFetch('/api/v1/uploads/chunked/init', {
    method: 'POST',
    token,
    json: { filename: file.name, total_size: totalSize, total_chunks: totalChunks },
  });
  const uploadId = init.upload_id;

  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end = Math.min(start + CHUNK_SIZE, totalSize);
    await apiFetch(`/api/v1/uploads/chunked/${uploadId}/chunks/${i}`, {
      method: 'PUT',
      token,
      body: file.slice(start, end),
    });
    onProgress?.((i + 1) / totalChunks);
  }

  return apiFetch(`/api/v1/uploads/chunked/${uploadId}/complete`, {
    method: 'POST',
    token,
    json: {},
  });
}

// Polls the existing (unmodified, unauthenticated-by-design) job-status route
// using the status_token returned by uploadModelFile, until the conversion
// reaches a terminal state.
export async function pollJobStatus(jobId, statusToken, { onUpdate, intervalMs = 1500, timeoutMs = 10 * 60 * 1000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const status = await apiFetch(`/api/upload-jobs/${jobId}`, {
      headers: { 'X-Job-Status-Token': statusToken },
    });
    onUpdate?.(status);
    if (['completed', 'failed', 'dead_letter'].includes(status.status)) {
      return status;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error('Conversion is taking longer than expected. Check My Models later.');
}
