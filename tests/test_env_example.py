"""Every env var the code reads must be documented in .env.example."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories that are not application code.
SKIP_DIRS = {
    "tests", "node_modules", "migrations", "static", "venv", ".venv", "docs",
}

# Read by the code but intentionally not documented as settings.
ALLOWLIST = {
    "LD_LIBRARY_PATH",  # inherited from the OS; the start command extends it
}

_READ = re.compile(
    r"""(?:os\.getenv|os\.environ\.get|os\.environ\.setdefault|os\.environ\.pop|environ\.get|getenv)"""
    r"""\(\s*['"]([A-Z][A-Za-z0-9_]*)['"]"""
    r"""|os\.environ\[\s*['"]([A-Z][A-Za-z0-9_]*)['"]\s*\]"""
)
_DOCUMENTED = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _code_env_vars():
    found = {}
    for path in ROOT.rglob("*.py"):
        parts = path.relative_to(ROOT).parts
        # Hidden dirs (.git, .claude worktrees, caches) hold copies, not this checkout's code.
        if SKIP_DIRS & set(parts) or any(p.startswith(".") for p in parts):
            continue
        for m in _READ.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            found.setdefault(m.group(1) or m.group(2), path.relative_to(ROOT).as_posix())
    return found


def test_all_env_vars_read_by_code_are_documented():
    documented = set(_DOCUMENTED.findall((ROOT / ".env.example").read_text(encoding="utf-8")))
    missing = {
        name: where for name, where in _code_env_vars().items()
        if name not in documented and name not in ALLOWLIST
    }
    assert not missing, f"Add these env vars to .env.example: {missing}"


def test_env_example_does_not_set_storage_dirs_by_default():
    """Relative WEB_AR_*_DIR values bypass the Railway volume; keep them commented out."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert not re.search(r"^WEB_AR_\w*_DIR=", text, re.MULTILINE)
