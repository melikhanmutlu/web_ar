import { apiFetch } from './client';

export function register({ username, email, password, confirmPassword }) {
  return apiFetch('/api/v1/auth/register', {
    method: 'POST',
    json: { username, email, password, confirm_password: confirmPassword },
  });
}

export function login({ username, password }) {
  return apiFetch('/api/v1/auth/login', {
    method: 'POST',
    json: { username, password },
  });
}

export function logout(token) {
  return apiFetch('/api/v1/auth/logout', { method: 'POST', token });
}
