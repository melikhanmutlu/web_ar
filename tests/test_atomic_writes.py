"""Regression coverage for the Railway-redeploy corruption bug: background
threads (thumbnail/USDZ generation) that get killed mid-write must never
leave a truncated file sitting at the path serve routes trust.

Root cause: img.save(dest, ...) / Blender's own file writer targeted the
live path directly, so a SIGKILL mid-write (a redeploy killing the daemon
thread/subprocess) left a corrupt file that `os.path.exists()` checks in
serve_thumbnail/generate_thumbnail_async would then serve forever. Fix:
write to a temp file next to the destination, then os.replace() onto it
(the same pattern save_modifications/slice_model already used)."""

import os

import pytest

import app as app_module
from app import _atomic_replace, app, convert_to_usdz


def test_atomic_replace_moves_tmp_onto_dest(tmp_path):
    dest = tmp_path / "thumbnail.png"
    tmp = tmp_path / "thumbnail.png.tmp123"
    tmp.write_bytes(b"complete-content")

    _atomic_replace(str(dest), str(tmp))

    assert dest.read_bytes() == b"complete-content"
    assert not tmp.exists()


def test_atomic_replace_cleans_up_tmp_and_reraises_on_failure(tmp_path):
    dest = tmp_path / "sub" / "thumbnail.png"  # parent dir doesn't exist -> os.replace fails
    tmp = tmp_path / "thumbnail.png.tmp123"
    tmp.write_bytes(b"partial")

    with pytest.raises(OSError):
        _atomic_replace(str(dest), str(tmp))

    assert not tmp.exists()
    assert not dest.exists()


def test_atomic_replace_never_touches_dest_if_tmp_missing(tmp_path):
    dest = tmp_path / "thumbnail.png"
    dest.write_bytes(b"still-good")
    missing_tmp = tmp_path / "thumbnail.png.tmp999"  # never created

    with pytest.raises(OSError):
        _atomic_replace(str(dest), str(missing_tmp))

    # A prior, valid thumbnail must survive a failed regeneration attempt.
    assert dest.read_bytes() == b"still-good"


def test_convert_to_usdz_writes_to_temp_path_not_final_path(client, tmp_path, monkeypatch):
    """The Blender subprocess must be pointed at a temp path so a kill
    mid-export can't truncate an existing, previously-good model.usdz."""
    final_path = str(tmp_path / "model.usdz")
    with open(final_path, "wb") as f:
        f.write(b"original-good-usdz")

    captured_cmd = {}

    class FakeProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        # Simulate Blender actually writing its output to whatever path it
        # was told to (the last cmd arg), not the final destination.
        with open(cmd[-1], "wb") as f:
            f.write(b"freshly-exported-usdz")
        return FakeProcess()

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    with app.app_context():
        result = convert_to_usdz("input.glb", final_path)

    assert result is True
    # Blender was pointed at a temp path, distinct from the live file.
    assert captured_cmd["cmd"][-1] != final_path
    assert captured_cmd["cmd"][-1].startswith(final_path)
    # The live path now holds the freshly-exported content, and the temp
    # file used to get it there is gone.
    with open(final_path, "rb") as f:
        assert f.read() == b"freshly-exported-usdz"
    assert not os.path.exists(captured_cmd["cmd"][-1])


def test_convert_to_usdz_failure_leaves_existing_file_untouched(client, tmp_path, monkeypatch):
    """If Blender crashes (or gets killed) mid-export, a previously-good
    model.usdz for an existing model must survive unmodified."""
    final_path = str(tmp_path / "model.usdz")
    with open(final_path, "wb") as f:
        f.write(b"original-good-usdz")

    class FakeProcess:
        returncode = 1
        stdout = ""
        stderr = "boom"

    def fake_run(cmd, **kwargs):
        # Blender died before producing any output at all.
        return FakeProcess()

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    with app.app_context():
        result = convert_to_usdz("input.glb", final_path)

    assert result is False
    with open(final_path, "rb") as f:
        assert f.read() == b"original-good-usdz"
