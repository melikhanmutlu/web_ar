"""Fail if the committed Tailwind CSS is stale (`npm run check:css`).

Rebuilds each stylesheet to a temp file with the repo's tailwindcss and diffs it
against the committed copy under static/css/. Run `npm run build:css` and commit
the result when this reports a mismatch (templates/JS gained or lost a class).
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (config, input css, committed output)
BUILDS = [
    ("tailwind/base.config.js", "tailwind/base.css", "static/css/tailwind-base.min.css"),
    ("tailwind/view.config.js", "tailwind/view.css", "static/css/tailwind-view.min.css"),
]


def find_tailwind():
    local = ROOT / "node_modules" / ".bin" / "tailwindcss"
    if local.exists():
        return str(local)
    return shutil.which("tailwindcss")


def main():
    binary = find_tailwind()
    if not binary:
        print("tailwindcss not found; run `npm ci` first", file=sys.stderr)
        return 2
    stale = []
    with tempfile.TemporaryDirectory() as tmp:
        for config, src, committed in BUILDS:
            out = Path(tmp) / Path(committed).name
            subprocess.run(
                [binary, "-c", config, "-i", src, "-o", str(out), "--minify"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            existing = ROOT / committed
            if not existing.exists() or existing.read_bytes() != out.read_bytes():
                stale.append(committed)
    if stale:
        print("Stale Tailwind CSS: " + ", ".join(stale))
        print("Run `npm run build:css` and commit the result.")
        return 1
    print("Tailwind CSS is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
