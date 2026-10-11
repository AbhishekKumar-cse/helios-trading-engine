"""Export only DeepLOB source and checksums for a GPU notebook; no secrets or datasets."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "research/helios/__init__.py",
    "research/helios/common/__init__.py",
    "research/helios/common/config.py",
    "research/helios/common/seed.py",
    "research/helios/ml/__init__.py",
    "research/helios/ml/deeplob.py",
    "research/helios/ml/deeplob_training.py",
    "research/helios/ml/deeplob_evaluation.py",
    "research/helios/ml/fi2010.py",
    "scripts/fi2010_deeplob_full.py",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "reports_out/helios_deeplob_gpu.zip")
    args = parser.parse_args(argv)
    manifest = {
        "code_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
        ),
        "files": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / name, name)
        archive.writestr("source_manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(f"Created {args.out}; {len(FILES)} source files, no dataset or credentials")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
