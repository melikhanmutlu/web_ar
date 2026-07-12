"""Best-effort real thumbnail rendering from GLB files.

Software rasterizer using only trimesh + Pillow + numpy (no GL/GPU needed, so
it works on headless deploys). Ported from the AcademicAR poster pipeline,
extended to use the model's own colors (vertex colors or flat material
baseColorFactor per part) instead of a fixed gray.

If rendering fails the caller falls back to the existing placeholder cards.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = (512, 512)
BG_COLOR = (245, 245, 245, 255)
DEFAULT_MESH_COLOR = (160, 170, 180)

# The painter's-algorithm draw loop is pure Python; beyond this many faces it
# gets too slow for the on-the-fly /thumbnail route, so give up and let the
# caller fall back to a placeholder.
MAX_RENDER_FACES = int(os.environ.get("MAX_THUMBNAIL_FACES", 500_000))
THUMBNAIL_RENDER_VERSION = "2-texture-sampling"


def _version_path(png_path: str) -> str:
    return f"{png_path}.render-version"


def thumbnail_is_current(png_path: str) -> bool:
    try:
        return Path(_version_path(png_path)).read_text(encoding="utf-8") == THUMBNAIL_RENDER_VERSION
    except OSError:
        return False


def mark_thumbnail_current(png_path: str) -> None:
    marker = _version_path(png_path)
    tmp_marker = f"{marker}.tmp{os.getpid()}"
    Path(tmp_marker).write_text(THUMBNAIL_RENDER_VERSION, encoding="utf-8")
    os.replace(tmp_marker, marker)


def render_thumbnail(glb_path: str, png_path: str) -> bool:
    """Render a real shaded view of the GLB to png_path. Returns True on success."""
    if not os.path.isfile(glb_path):
        return False
    try:
        rendered = _rasterize(glb_path, png_path)
        if rendered:
            mark_thumbnail_current(png_path)
        return rendered
    except Exception:
        logger.warning("Thumbnail rasterization failed for %s", glb_path, exc_info=True)
        return False


def _geometry_face_colors(geometry, n_faces):
    """Per-face RGB (linear, 0-255) from a part's own colors, or default gray.

    Tries vertex/face colors first, then a flat material baseColorFactor
    (textures are not sampled — those parts fall back to gray).
    """
    try:
        uv = np.asarray(geometry.visual.uv, dtype=np.float64)
        material = geometry.visual.material
        texture = getattr(material, "baseColorTexture", None)
        if texture is None:
            texture = getattr(material, "image", None)
        if uv.shape == (len(geometry.vertices), 2) and texture is not None:
            from PIL import Image

            image = texture.convert("RGB") if isinstance(texture, Image.Image) else Image.open(texture).convert("RGB")
            pixels = np.asarray(image, dtype=np.float64)
            face_uv = uv[np.asarray(geometry.faces, dtype=np.int64)]
            # Preserve triangles crossing a repeat seam (0.99 -> 0.01).
            angles = face_uv * (2.0 * np.pi)
            centers = np.mod(
                np.arctan2(np.sin(angles).mean(axis=1), np.cos(angles).mean(axis=1))
                / (2.0 * np.pi),
                1.0,
            )
            x = np.clip(np.rint(centers[:, 0] * (image.width - 1)), 0, image.width - 1).astype(int)
            # glTF UV origin is bottom-left; Pillow's origin is top-left.
            y = np.clip(np.rint((1.0 - centers[:, 1]) * (image.height - 1)), 0, image.height - 1).astype(int)
            sampled = pixels[y, x, :3]
            factor = getattr(material, "baseColorFactor", None)
            if factor is not None:
                factor = np.asarray(factor, dtype=np.float64).flatten()[:3]
                if factor.size == 3:
                    if factor.max() > 1.0:
                        factor = factor / 255.0
                    sampled = sampled * factor
            return np.clip(sampled, 0, 255)
    except Exception:
        logger.debug("Could not sample thumbnail texture", exc_info=True)

    try:
        face_colors = np.asarray(geometry.visual.face_colors, dtype=np.float64)
        if face_colors.shape[0] == n_faces:
            return face_colors[:, :3]
    except Exception:
        pass
    try:
        factor = getattr(geometry.visual.material, "baseColorFactor", None)
        if factor is not None:
            arr = np.asarray(factor, dtype=np.float64).flatten()
            if arr.size >= 3:
                if arr.max() <= 1.0:
                    arr = arr * 255.0
                return np.tile(arr[:3], (n_faces, 1))
    except Exception:
        pass
    return np.tile(np.array(DEFAULT_MESH_COLOR, dtype=np.float64), (n_faces, 1))


def _flatten_scene(glb_path):
    """Load a GLB into flat (vertices, faces, per-face linear RGB) arrays."""
    import trimesh

    loaded = trimesh.load(glb_path, file_type="glb")
    if isinstance(loaded, trimesh.Trimesh):
        loaded = trimesh.Scene([loaded])
    if not isinstance(loaded, trimesh.Scene):
        return None

    verts_list, faces_list, colors_list = [], [], []
    vert_offset = 0
    for node_name in loaded.graph.nodes_geometry:
        transform, geom_name = loaded.graph[node_name]
        geometry = loaded.geometry.get(geom_name)
        if not isinstance(geometry, trimesh.Trimesh) or len(geometry.faces) == 0:
            continue
        part = geometry.copy()
        part.apply_transform(transform)
        verts_list.append(np.array(part.vertices, dtype=np.float64))
        faces_list.append(np.array(part.faces, dtype=np.int64) + vert_offset)
        colors_list.append(_geometry_face_colors(geometry, len(part.faces)))
        vert_offset += len(part.vertices)

    if not verts_list:
        return None
    return (
        np.vstack(verts_list),
        np.vstack(faces_list),
        np.vstack(colors_list),
    )


def _rasterize(glb_path: str, png_path: str) -> bool:
    """Software rasterizer: orthographic projection + painter's algorithm."""
    from PIL import Image, ImageDraw

    flattened = _flatten_scene(glb_path)
    if flattened is None:
        return False
    verts, faces, base_colors = flattened

    if faces.shape[0] > MAX_RENDER_FACES:
        logger.info(
            "Skipping thumbnail render for %s: %d faces exceeds limit %d",
            glb_path,
            faces.shape[0],
            MAX_RENDER_FACES,
        )
        return False

    bounds = verts.min(axis=0), verts.max(axis=0)
    center = (bounds[0] + bounds[1]) / 2.0
    extent = (bounds[1] - bounds[0]).max()
    if extent < 1e-10:
        return False

    verts_centered = verts - center

    angle_y = np.radians(35)
    angle_x = np.radians(25)
    cy, sy = np.cos(angle_y), np.sin(angle_y)
    cx, sx = np.cos(angle_x), np.sin(angle_x)

    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    rot = rx @ ry
    verts_rot = verts_centered @ rot.T

    w, h = THUMBNAIL_SIZE
    margin = 0.12
    usable = min(w, h) * (1 - 2 * margin)
    proj_extent = max(
        verts_rot[:, 0].ptp(),
        verts_rot[:, 1].ptp(),
    )
    if proj_extent < 1e-10:
        return False
    scale = usable / proj_extent
    ox = w / 2.0
    oy = h / 2.0

    screen_x = verts_rot[:, 0] * scale + ox
    screen_y = -verts_rot[:, 1] * scale + oy

    face_z = verts_rot[faces, 2].mean(axis=1)
    order = np.argsort(face_z)

    light_dir = np.array([0.4, 0.6, 0.7])
    light_dir /= np.linalg.norm(light_dir)
    v0 = verts_rot[faces[:, 0]]
    v1 = verts_rot[faces[:, 1]]
    v2 = verts_rot[faces[:, 2]]
    normals_rot = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(normals_rot, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    normals_rot = normals_rot / norms

    # Backfacing normals still light the surface (abs) so meshes with
    # inconsistent winding don't render half-black.
    dots = np.clip(np.abs(np.sum(normals_rot * light_dir, axis=1)), 0, 1)
    ambient = 0.35
    intensity = ambient + (1.0 - ambient) * dots

    # Shade in linear space (glTF colors are linear), then encode to sRGB for
    # display so the thumbnail matches the color seen in model-viewer.
    shaded = np.clip(base_colors * intensity[:, None] / 255.0, 0.0, 1.0)
    srgb = np.where(
        shaded <= 0.0031308,
        shaded * 12.92,
        1.055 * np.power(shaded, 1.0 / 2.4) - 0.055,
    )
    face_colors = np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)

    img = Image.new("RGBA", THUMBNAIL_SIZE, BG_COLOR)
    draw = ImageDraw.Draw(img)

    for idx in order:
        f = faces[idx]
        tri = [
            (float(screen_x[f[0]]), float(screen_y[f[0]])),
            (float(screen_x[f[1]]), float(screen_y[f[1]])),
            (float(screen_x[f[2]]), float(screen_y[f[2]])),
        ]
        c = face_colors[idx]
        draw.polygon(tri, fill=(int(c[0]), int(c[1]), int(c[2]), 255))

    img = img.convert("RGB")
    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    tmp_path = f"{png_path}.tmp{os.getpid()}"
    img.save(tmp_path, "PNG", optimize=True)
    os.replace(tmp_path, png_path)
    return True
