"""Regenerate the static JSON Schema files under ``schemas/``.

Run from the repo root::

    python scripts/generate_schemas.py

The committed files are for non-Python consumers (other-language clients,
schema-driven UIs, documentation tools) that read the repository on
GitHub. Python consumers should call
``agent_interface_protocol.schema.json_schemas()`` at runtime instead —
that's always in sync with the package version they have installed.

A test asserts the committed files match what this script generates, so
forgetting to regenerate after editing the schema module will surface
on the next ``pytest`` run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repo root importable when this script is run directly without
# an editable install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent_interface_protocol.schema import json_schemas  # noqa: E402

SCHEMAS_DIR = _REPO_ROOT / "schemas"


def main() -> None:
    SCHEMAS_DIR.mkdir(exist_ok=True)
    for name, schema in json_schemas().items():
        path = SCHEMAS_DIR / f"{name}.json"
        text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(SCHEMAS_DIR.parent)}")


if __name__ == "__main__":
    main()
