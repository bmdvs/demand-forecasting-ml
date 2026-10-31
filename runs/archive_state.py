"""Archive a checkout's generated state with a checksum manifest.
Usage: python runs/archive_state.py <source checkout> <destination dir> [note]"""
import hashlib, json, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

src, dest = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
note = sys.argv[3] if len(sys.argv) > 3 else ""
if dest.exists():
    sys.exit(f"{dest} already exists; refusing to overwrite")
for rel in ["data_source/raw", "data_source/truth", "ml/data", "runs/seq"]:
    if (src / rel).exists():
        shutil.copytree(src / rel, dest / rel)
shutil.copy2(src / "data_source" / "demand_forecasting.duckdb", dest / "data_source" / "demand_forecasting.duckdb")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


commit = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
files = sorted(p for p in dest.rglob("*") if p.is_file())
manifest = {"archived_at": datetime.now().isoformat(timespec="seconds"), "git_commit": commit, "note": note,
            "config_sha256": sha(src / "data_source/generate/config.py"),
            "lock_sha256": sha(src / "requirements-lock.txt"),
            "files": {p.relative_to(dest).as_posix(): {"bytes": p.stat().st_size, "sha256": sha(p)} for p in files}}
(dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=1))
print(f"archived {len(files)} files, {sum(p.stat().st_size for p in files)/1e6:.1f} MB -> {dest} (commit {commit[:7]})")
