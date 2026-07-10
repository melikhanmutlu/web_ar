"""Syntax-check inline JavaScript embedded in Jinja templates."""

import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


def neutralize_jinja(source):
    source = re.sub(r"\{\{.*?\}\}", "null", source, flags=re.DOTALL)
    source = re.sub(r"\{%.*?%\}", "", source, flags=re.DOTALL)
    return source


def main():
    failures = []
    for template in sorted((ROOT / "templates").glob("*.html")):
        parser = ScriptCollector()
        parser.feed(template.read_text(encoding="utf-8"))
        for index, script in enumerate(parser.scripts, 1):
            candidate = neutralize_jinja(script).strip()
            if not candidate:
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
                handle.write(candidate)
                path = Path(handle.name)
            try:
                result = subprocess.run(
                    ["node", "--check", str(path)], capture_output=True, text=True
                )
                if result.returncode:
                    failures.append(f"{template.name} script #{index}:\n{result.stderr}")
            finally:
                path.unlink(missing_ok=True)
    if failures:
        raise SystemExit("\n".join(failures))
    print("Inline template JavaScript syntax is valid")


if __name__ == "__main__":
    main()
