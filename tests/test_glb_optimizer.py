"""converters/glb_optimizer.py: gltfpack meshopt compression + the
edit-time guard that must detect it (blueprints/model_editing.py).

Two real bugs fixed here:
  1. Neither templates/view.html, embed.html, compare.html, nor index.html
     ever registered a meshopt decoder with <model-viewer>, so a model
     converted with "Web Compression: Meshopt" produced a valid GLB that
     silently never rendered (DRACO has a built-in default decoder
     location in model-viewer; meshopt does not).
  2. glb_requires_meshopt() checked for the extension name
     "KHR_meshopt_compression", which gltfpack never emits -- the real
     name is "EXT_meshopt_compression" -- so the guard that's supposed to
     block editing (and silently corrupting) a meshopt-compressed model
     never actually triggered.
"""

import os
import shutil
from pathlib import Path

import pytest
import trimesh

from converters.glb_optimizer import glb_requires_meshopt, optimize_glb

GLTFPACK_AVAILABLE = shutil.which("gltfpack") is not None or os.path.exists(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "node_modules", ".bin", "gltfpack")
)


@pytest.fixture
def sample_glb(tmp_path):
    path = tmp_path / "cube.glb"
    trimesh.creation.box(extents=[0.2, 0.2, 0.2]).export(path)
    return str(path)


@pytest.fixture
def dense_sample_glb(tmp_path):
    # A single box is too small for gltfpack's meshopt output to beat --
    # compression overhead exceeds the savings on trivial geometry. A denser
    # mesh gives genuine, verifiable size reduction.
    path = tmp_path / "sphere.glb"
    trimesh.creation.icosphere(subdivisions=4, radius=1.0).export(path)
    return str(path)


def test_glb_requires_meshopt_is_false_for_a_plain_glb(sample_glb):
    assert glb_requires_meshopt(sample_glb) is False


@pytest.mark.skipif(not GLTFPACK_AVAILABLE, reason="gltfpack binary not available in this environment")
def test_optimize_glb_meshopt_produces_a_file_glb_requires_meshopt_detects(dense_sample_glb, monkeypatch):
    # gltfpack isn't necessarily on PATH in every environment, but this repo
    # vendors it via package.json/node_modules -- point _resolve_gltfpack at
    # the local copy the same way npx would.
    import converters.glb_optimizer as glb_optimizer_module

    local_bin = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "node_modules", ".bin", "gltfpack"
    )
    if shutil.which("gltfpack") is None and os.path.exists(local_bin):
        monkeypatch.setattr(glb_optimizer_module, "_resolve_gltfpack", lambda: [local_bin])

    before_size = os.path.getsize(dense_sample_glb)
    ok = optimize_glb(dense_sample_glb, enabled=True, mode="meshopt")
    assert ok is True
    # This is the actual regression check: before the fix, this returned
    # False for every real meshopt-compressed file, so the edit-blocking
    # guard in blueprints/model_editing.py never fired.
    assert glb_requires_meshopt(dense_sample_glb) is True
    assert os.path.getsize(dense_sample_glb) <= before_size


def test_optimize_glb_disabled_leaves_file_untouched(sample_glb):
    before = Path(sample_glb).read_bytes()
    ok = optimize_glb(sample_glb, enabled=False, mode="meshopt")
    assert ok is False
    assert Path(sample_glb).read_bytes() == before


@pytest.mark.skipif(not GLTFPACK_AVAILABLE, reason="gltfpack binary not available in this environment")
def test_save_modifications_decompresses_a_meshopt_compressed_model(client, monkeypatch, dense_sample_glb):
    """Editing a meshopt-compressed model used to be hard-blocked. It now
    decompresses the file in place first (trimesh can't read meshopt) and
    applies the edit, leaving the model uncompressed/editable — a color edit
    should succeed and the stored file should no longer require decompression."""
    import shutil as shutil_module

    import converters.glb_optimizer as glb_optimizer_module
    from converters.glb_optimizer import glb_needs_decompression
    from app import app, db
    from models import UserModel

    local_bin = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "node_modules", ".bin", "gltfpack"
    )
    if shutil_module.which("gltfpack") is None and os.path.exists(local_bin):
        monkeypatch.setattr(glb_optimizer_module, "_resolve_gltfpack", lambda: [local_bin])
    assert optimize_glb(dense_sample_glb, enabled=True, mode="meshopt") is True

    model_id = "meshopt-guard-model"
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    dest = os.path.join(model_dir, "model.glb")
    shutil_module.copyfile(dense_sample_glb, dest)
    assert glb_needs_decompression(dest)  # precondition: it is compressed
    model = UserModel(id=model_id, filename=dest, file_type="glb",
                       file_size=os.path.getsize(dest), user_id=None, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"material": {"color": "#ff0000"}},
    })
    data = resp.get_json()
    assert data["success"] is True, data
    # The edit decompressed it in place, so it's now editable going forward.
    assert not glb_needs_decompression(dest)
