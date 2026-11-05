"""Install optional component dependencies for a clean native HA test runner."""

import json
from pathlib import Path
import subprocess
import sys

import homeassistant

root = Path(homeassistant.__file__).parent / "components"
seen = set()
requirements = set()


def collect(component):
    if component in seen:
        return
    seen.add(component)
    manifest = json.loads((root / component / "manifest.json").read_text())
    requirements.update(manifest.get("requirements", []))
    for dependency in manifest.get("dependencies", []):
        collect(dependency)


for component in ("bluetooth", "event"):
    collect(component)

subprocess.check_call([sys.executable, "-m", "pip", "install", *sorted(requirements)])
