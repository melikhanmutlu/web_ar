// Points at the production ARVision backend by default -- the same Flask app
// and database the web UI uses, via the Bearer-token /api/v1/... surface
// (see blueprints/api_tokens.py, blueprints/auth.py, blueprints/upload.py).
// Override with EXPO_PUBLIC_API_BASE_URL (e.g. http://localhost:5000 for a
// local dev server) -- Expo inlines EXPO_PUBLIC_* env vars automatically.
export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL || 'https://webar.up.railway.app';

export const BRAND = {
  primary: '#1F2937',
  accent: '#00B2CC',
  accentDark: '#008FA3',
  danger: '#dc2626',
  border: '#d1d5db',
  muted: '#6b7280',
};
