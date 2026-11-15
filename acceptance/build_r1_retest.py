"""Builds ``r1-retest.pyz``, the one-file form of the r1-retest harness in ``acceptance/r1_retest``.

Usage, anywhere with this repository and Python 3.11 or newer::

    python3 acceptance/build_r1_retest.py [--out DIR]

Every build gets a new build id (its UTC time) and its own directories; nothing is overwritten:

- ``DIR/dist/<build id>/`` holds ``r1-retest.pyz``, ``r1-retest.pyz.sha256`` and ``GUIDE.md``;
- ``DIR/build/<build id>/`` holds the staged tree that was archived.

``DIR`` defaults to ``acceptance/``, whose ``build/`` and ``dist/`` git ignores. The archive
carries ``r1_retest/BUILD.json`` with the version, the build id and ``source_digest``: the same
digest that ``r1-retest init`` records for this source tree when the harness runs from it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipapp
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE / "r1_retest"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build r1-retest.pyz from acceptance/r1_retest.")
    parser.add_argument(
        "--out", type=Path, default=HERE, help="where build/ and dist/ go (default: acceptance/)"
    )
    args = parser.parse_args()
    sys.path.insert(0, str(HERE))
    from r1_retest.utils import HARNESS_VERSION, tree_digest

    build_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    staging = args.out.resolve() / "build" / build_id
    target = args.out.resolve() / "dist" / build_id
    staging.mkdir(parents=True)
    target.mkdir(parents=True)
    shutil.copytree(
        PACKAGE, staging / "r1_retest", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    manifest = {
        "version": HARNESS_VERSION,
        "build_id": build_id,
        "source_digest": tree_digest(PACKAGE),
        "requires_python": ">=3.11",
        "dependencies": "standard library only; orbital (repository copy)",
    }
    (staging / "r1_retest" / "BUILD.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copy2(PACKAGE / "__main__.py", staging / "__main__.py")
    archive = target / "r1-retest.pyz"
    zipapp.create_archive(staging, archive, interpreter="/usr/bin/env python3", compressed=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (target / "r1-retest.pyz.sha256").write_text(f"{digest}  r1-retest.pyz\n")
    shutil.copy2(PACKAGE / "GUIDE.md", target / "GUIDE.md")
    print(json.dumps({"archive": str(archive), "sha256": digest, **manifest}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
