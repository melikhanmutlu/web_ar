"""Fail on high/critical npm advisories in production dependencies, except
the reviewed ones listed in ACCEPTED below.

`npm audit` has no ignore list, and one accepted advisory with no fixed
release kept CI red for months, which hid every other failure behind it.
"""

import json
import subprocess
import sys

# advisory URL -> why it's accepted. Remove an entry once a fixed version ships.
ACCEPTED = {
    "https://github.com/advisories/GHSA-vfj7-8cjw-p6xm": (
        "braces stack exhaustion on deeply nested patterns; no fixed release "
        "exists. Only reached through @gltf-transform/cli's glob handling of "
        "file paths the server builds itself, never user-supplied patterns."
    ),
}


def _advisory_urls(vuln, vulns, seen=None):
    """Advisory URLs behind a vulnerability, following transitive 'via' links."""
    seen = seen if seen is not None else set()
    urls = set()
    for via in vuln.get("via", []):
        if isinstance(via, dict):
            urls.add(via.get("url", ""))
        elif via not in seen and via in vulns:
            seen.add(via)
            urls |= _advisory_urls(vulns[via], vulns, seen)
    return urls


def main():
    out = subprocess.run(["npm", "audit", "--omit=dev", "--json"],
                         capture_output=True, text=True).stdout
    vulns = json.loads(out).get("vulnerabilities", {})
    failing = {}
    for name, vuln in vulns.items():
        if vuln.get("severity") not in ("high", "critical"):
            continue
        unaccepted = _advisory_urls(vuln, vulns) - set(ACCEPTED)
        if unaccepted:
            failing[name] = sorted(unaccepted)
    for name, urls in sorted(failing.items()):
        print(f"{name}: {', '.join(urls)}")
    if failing:
        print(f"{len(failing)} package(s) with unaccepted high/critical advisories")
        return 1
    print("npm audit: no unaccepted high/critical advisories")
    return 0


if __name__ == "__main__":
    sys.exit(main())
