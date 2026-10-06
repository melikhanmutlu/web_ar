"""convert_to_usdz must work with a Blender script that appends ".usdz" to
paths that do not already end with it (tools/blender_usdz_export.py)."""
import os
import stat
import sys

import app as app_module
from services import usdz as usdz_service


FAKE_BLENDER = """#!{python}
import sys
args = sys.argv[sys.argv.index('--') + 1:]
out = args[1]
# Same path behaviour as tools/blender_usdz_export.py
if not out.lower().endswith('.usdz'):
    out += '.usdz'
open(out, 'wb').write(b'PK-fake-usdz')
"""


def _install_fake_blender(tmp_path, monkeypatch, body=None):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "blender"
    exe.write_text((body or FAKE_BLENDER).format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")


def test_convert_to_usdz_succeeds_and_leaves_no_temp(tmp_path, monkeypatch):
    _install_fake_blender(tmp_path, monkeypatch)
    glb = tmp_path / "model.glb"
    glb.write_bytes(b"glb")
    out = tmp_path / "model.usdz"
    assert usdz_service.convert_to_usdz(str(glb), str(out)) is True
    assert out.read_bytes() == b"PK-fake-usdz"
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".usdz") == ["model.usdz"]
    assert not [p for p in tmp_path.iterdir() if ".tmp" in p.name]


def test_convert_to_usdz_failure_cleans_up(tmp_path, monkeypatch):
    _install_fake_blender(
        tmp_path, monkeypatch,
        "#!{python}\nimport sys\nopen(sys.argv[-1] + '.usdz', 'wb').write(b'x')\nsys.exit(1)\n",
    )
    glb = tmp_path / "model.glb"
    glb.write_bytes(b"glb")
    out = tmp_path / "model.usdz"
    assert usdz_service.convert_to_usdz(str(glb), str(out)) is False
    assert not out.exists()


def test_stale_temp_files_are_swept(tmp_path, monkeypatch):
    _install_fake_blender(tmp_path, monkeypatch)
    old_a = tmp_path / "model.usdz.tmp123.usdz"
    old_b = tmp_path / "model.tmp77.usdz"
    for p in (old_a, old_b):
        p.write_bytes(b"x")
        os.utime(p, (1, 1))
    glb = tmp_path / "model.glb"
    glb.write_bytes(b"glb")
    assert usdz_service.convert_to_usdz(str(glb), str(tmp_path / "model.usdz"))
    assert not old_a.exists() and not old_b.exists()


def test_usdz_status_ignores_temp_leftovers(client):
    from models import db, UserModel
    import uuid
    mid = "t-" + uuid.uuid4().hex[:8]
    conv = os.path.join(app_module.app.config["CONVERTED_FOLDER"], mid)
    os.makedirs(conv, exist_ok=True)
    with open(os.path.join(conv, "model.tmp1.usdz"), "wb") as f:
        f.write(b"x")
    db.session.add(UserModel(id=mid, filename=f"{mid}/model.glb", file_type="glb",
                             user_id=None, cumulative_scale=1.0))
    db.session.commit()
    r = client.get(f"/api/models/{mid}/usdz_status")
    assert r.get_json()["usdz_ready"] is False
