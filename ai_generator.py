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


def _require_data_uri(image_data_uri: str) -> str:
    """Enforce that an image passed to Meshy is an inline base64 data URI.

    This is the SSRF guard: never let a raw http(s) URL (which could be
    client-supplied and point at an internal/metadata host) reach Meshy's
    server-side fetcher. Callers that legitimately have a remote image must
    resolve and inline it first (see fetch_image_as_data_uri).
    """
    value = (image_data_uri or "").strip()
    if not value.lower().startswith("data:image/"):
        raise MeshyError("image must be an inline data:image/* URI, not a URL")
    return value


def _post(url: str, payload: dict) -> dict:
    try:
        r = requests.post(url, json=payload, headers=_headers(), timeout=60)
    except requests.RequestException as e:
        raise MeshyError(f"Meshy request failed: {e}")
    if r.status_code == 429:
        raise MeshyError("Meshy rate limit reached (429). Try again shortly.")
    if r.status_code >= 400:
        # Log the upstream body server-side; never surface it to the client
        # (it can contain provider internals / request echoes).
        logger.error("Meshy POST %s -> %s: %s", url, r.status_code, r.text[:300])
        raise MeshyError(f"Meshy error {r.status_code}")
    return r.json()


def _get(url: str) -> dict:
    try:
        r = requests.get(url, headers=_headers(), timeout=60)
    except requests.RequestException as e:
        raise MeshyError(f"Meshy request failed: {e}")
    if r.status_code >= 400:
        logger.error("Meshy GET %s -> %s: %s", url, r.status_code, r.text[:300])
        raise MeshyError(f"Meshy error {r.status_code}")
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
    """Image -> 3D. image_data_uri MUST be an inline base64 data URI."""
    image_data_uri = _require_data_uri(image_data_uri)
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


# --------------------------------------------------------------------------- #
#  Image generation (pre-processing before 3D)
#  Docs: https://docs.meshy.ai/en/api/text-to-image ,
#        https://docs.meshy.ai/en/api/image-to-image
# --------------------------------------------------------------------------- #
_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4"}
_MAX_IMAGE_DOWNLOAD = 12 * 1024 * 1024  # bytes


def _image_model() -> str:
    return getattr(config, "MESHY_IMAGE_MODEL", "nano-banana-pro")


def start_text_to_image(prompt: str, aspect_ratio: str = "1:1") -> str:
    """Generate reference image(s) from a text prompt. Returns task id."""
    payload = {
        "ai_model": _image_model(),
        "prompt": (prompt or "").strip()[:600],
        "aspect_ratio": aspect_ratio if aspect_ratio in _ASPECT_RATIOS else "1:1",
    }
    data = _post(f"{_base()}/v1/text-to-image", payload)
    task_id = data.get("result")
    if not task_id:
        raise MeshyError(f"No task id in Meshy text-to-image response: {data}")
    return task_id


def start_image_to_image(image_data_uri: str, prompt: str) -> str:
    """Transform an uploaded image with a prompt (e.g. remove background,
    studio product shot). image_data_uri is a base64 data URI. Returns task id."""
    image_data_uri = _require_data_uri(image_data_uri)
    payload = {
        "ai_model": _image_model(),
        "image_url": image_data_uri,
        "prompt": (prompt or "").strip()[:600],
    }
    data = _post(f"{_base()}/v1/image-to-image", payload)
    task_id = data.get("result")
    if not task_id:
        raise MeshyError(f"No task id in Meshy image-to-image response: {data}")
    return task_id


def get_image_gen_task(kind: str, task_id: str) -> dict:
    """kind: 't2i' (text-to-image) or 'i2i' (image-to-image)."""
    path = "text-to-image" if kind == "t2i" else "image-to-image"
    data = _get(f"{_base()}/v1/{path}/{task_id}")
    return {
        "status": data.get("status"),
        "progress": int(data.get("progress") or 0),
        "image_urls": data.get("image_urls") or [],
        "task_error": (data.get("task_error") or {}).get("message"),
    }


def fetch_image_as_data_uri(url: str, max_bytes: int = _MAX_IMAGE_DOWNLOAD) -> str:
    """Download a generated image and return it as a base64 data URI.

    Meshy output URLs expire, so the chosen image is fetched server-side at
    3D-generation time. Only URLs resolved from Meshy task lookups are ever
    passed here — never client-supplied URLs.
    """
    import base64

    try:
        with requests.get(url, stream=True, timeout=120) as r:
            if r.status_code >= 400:
                raise MeshyError(f"Image download failed {r.status_code}")
            mime = (r.headers.get("Content-Type") or "image/png").split(";")[0]
            if not mime.startswith("image/"):
                mime = "image/png"
            chunks, total = [], 0
            for chunk in r.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise MeshyError("Generated image is too large.")
                chunks.append(chunk)
    except requests.RequestException as e:
        raise MeshyError(f"Image download failed: {e}")
    return f"data:{mime};base64," + base64.b64encode(b"".join(chunks)).decode()
