"""
Thin Meshy REST client for AI text/image -> 3D generation.

Server-side only. The API key is read from config (MESHY_API_KEY) and must never
be exposed to the browser. All generation is asynchronous on Meshy's side; this
module only starts tasks, queries their status, and downloads finished assets.

Docs: https://docs.meshy.ai/en/api/text-to-3d , https://docs.meshy.ai/en/api/image-to-3d
"""

import logging
import requests
import config

logger = logging.getLogger(__name__)

# Meshy task statuses
PENDING = "PENDING"
IN_PROGRESS = "IN_PROGRESS"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELED = "CANCELED"


class MeshyError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(getattr(config, "MESHY_API_KEY", ""))


def _base() -> str:
    return getattr(config, "MESHY_API_BASE", "https://api.meshy.ai/openapi").rstrip("/")


def _headers() -> dict:
    key = getattr(config, "MESHY_API_KEY", "")
    if not key:
        raise MeshyError("MESHY_API_KEY is not configured")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _ai_model() -> str:
    return getattr(config, "MESHY_AI_MODEL", "meshy-5")


def _post(url: str, payload: dict) -> dict:
    try:
        r = requests.post(url, json=payload, headers=_headers(), timeout=60)
    except requests.RequestException as e:
        raise MeshyError(f"Meshy request failed: {e}")
    if r.status_code == 429:
        raise MeshyError("Meshy rate limit reached (429). Try again shortly.")
    if r.status_code >= 400:
        raise MeshyError(f"Meshy error {r.status_code}: {r.text[:300]}")
    return r.json()


def _get(url: str) -> dict:
    try:
        r = requests.get(url, headers=_headers(), timeout=60)
    except requests.RequestException as e:
        raise MeshyError(f"Meshy request failed: {e}")
    if r.status_code >= 400:
        raise MeshyError(f"Meshy error {r.status_code}: {r.text[:300]}")
    return r.json()


# --------------------------------------------------------------------------- #
#  Start tasks
# --------------------------------------------------------------------------- #
def start_text_to_3d(prompt: str) -> str:
    """Stage 1 (preview): untextured mesh from a text prompt. Returns task id."""
    payload = {
        "mode": "preview",
        "prompt": (prompt or "").strip()[:600],
        "ai_model": _ai_model(),
        "should_remesh": True,
        "target_formats": ["glb", "usdz"],
    }
    data = _post(f"{_base()}/v2/text-to-3d", payload)
    task_id = data.get("result")
    if not task_id:
        raise MeshyError(f"No task id in Meshy response: {data}")
    return task_id


def start_refine(preview_task_id: str) -> str:
    """Stage 2 (refine): apply texture to a finished preview. Returns task id."""
    payload = {
        "mode": "refine",
        "preview_task_id": preview_task_id,
        "enable_pbr": True,
        "target_formats": ["glb", "usdz"],
    }
    data = _post(f"{_base()}/v2/text-to-3d", payload)
    task_id = data.get("result")
    if not task_id:
        raise MeshyError(f"No task id in Meshy refine response: {data}")
    return task_id


def start_image_to_3d(image_data_uri: str) -> str:
    """Image -> 3D. image_data_uri is a base64 data URI (or public URL)."""
    payload = {
        "image_url": image_data_uri,
        "ai_model": _ai_model(),
        "should_texture": True,
        "enable_pbr": True,
        "auto_size": True,  # AI estimates real-world dimensions
        "target_formats": ["glb", "usdz"],
    }
    data = _post(f"{_base()}/v1/image-to-3d", payload)
    task_id = data.get("result")
    if not task_id:
        raise MeshyError(f"No task id in Meshy image response: {data}")
    return task_id


# --------------------------------------------------------------------------- #
#  Query + download
# --------------------------------------------------------------------------- #
def get_task(kind: str, task_id: str) -> dict:
    """kind: 'text' (v2/text-to-3d) or 'image' (v1/image-to-3d)."""
    if kind == "image":
        url = f"{_base()}/v1/image-to-3d/{task_id}"
    else:
        url = f"{_base()}/v2/text-to-3d/{task_id}"
    data = _get(url)
    return {
        "status": data.get("status"),
        "progress": int(data.get("progress") or 0),
        "model_urls": data.get("model_urls") or {},
        "thumbnail_url": data.get("thumbnail_url"),
        "task_error": (data.get("task_error") or {}).get("message"),
        "raw": data,
    }


def download(url: str, dest_path: str) -> bool:
    """Download a finished asset (GLB/USDZ) to dest_path."""
    try:
        with requests.get(url, stream=True, timeout=180) as r:
            if r.status_code >= 400:
                raise MeshyError(f"Download failed {r.status_code}: {url}")
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return True
    except requests.RequestException as e:
        raise MeshyError(f"Download failed: {e}")
