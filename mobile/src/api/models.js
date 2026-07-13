import { apiFetch } from './client';

export function listFolders(token, parentId) {
  const query = parentId != null ? `?parent_id=${parentId}` : '';
  return apiFetch(`/api/v1/folders${query}`, { token });
}

// folderId omitted -> unfiltered; null -> root only; a folder id -> that folder.
export function listModels(token, folderId) {
  let query = '';
  if (folderId !== undefined) {
    query = `?folder_id=${folderId === null ? '' : folderId}`;
  }
  return apiFetch(`/api/v1/models${query}`, { token });
}

export function getModel(token, modelId) {
  return apiFetch(`/api/v1/models/${modelId}`, { token });
}
