"""The FBX metadata probe must contain assimp failures/OOM in a child process
and never crash the caller — the converter falls back to FBX2glTF on any error.
"""
import os
import tempfile

from converters import fbx_probe


def test_run_isolated_missing_file_returns_error():
    m = fbx_probe.run_isolated("/no/such/file.fbx", timeout=60)
    assert isinstance(m, dict) and m.get("error"), m


def test_run_isolated_garbage_file_returns_error():
    d = tempfile.mkdtemp()
    junk = os.path.join(d, "junk.fbx")
    with open(junk, "wb") as f:
        f.write(b"this is not an fbx file")
    m = fbx_probe.run_isolated(junk, timeout=60)
    assert isinstance(m, dict) and m.get("error"), m


def test_run_isolated_tiny_memcap_does_not_crash_caller():
    """An impossibly small address-space cap kills the child cleanly; the
    runner returns an error dict rather than raising."""
    d = tempfile.mkdtemp()
    junk = os.path.join(d, "junk.fbx")
    with open(junk, "wb") as f:
        f.write(b"x")
    m = fbx_probe.run_isolated(junk, mem_mb=32, timeout=60)
    assert isinstance(m, dict) and m.get("error"), m


def test_run_isolated_cleans_up_workdir():
    """No fbxprobe_* temp dirs should leak after a run."""
    before = set(os.listdir(tempfile.gettempdir()))
    fbx_probe.run_isolated("/no/such/file.fbx", timeout=60)
    after = set(os.listdir(tempfile.gettempdir()))
    leaked = [d for d in (after - before) if d.startswith("fbxprobe_")]
    assert not leaked, leaked
