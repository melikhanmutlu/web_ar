import { API_BASE_URL } from '../config';

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

// No CSRF header here on purpose: every route this client calls is a
// Bearer-token-only /api/v1/... route, csrf.exempt()'d server-side (see
// app.py) precisely because a Bearer header isn't ambient the way a session
// cookie is. That's different from the web app's fetch wrapper
// (templates/_security_head.html), which does need to attach one.
export async function apiFetch(path, { method = 'GET', token, json, body, headers = {} } = {}) {
  const finalHeaders = { ...headers };
  if (token) finalHeaders.Authorization = `Bearer ${token}`;
  let finalBody = body;
  if (json !== undefined) {
    finalHeaders['Content-Type'] = 'application/json';
    finalBody = JSON.stringify(json);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: finalHeaders,
    body: finalBody,
  });

  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const message = data?.error || data?.errors || `Request failed (${response.status})`;
    throw new ApiError(typeof message === 'string' ? message : JSON.stringify(message), response.status, data);
  }
  return data;
}
