"""Build the dfm wheel for a bundle deploy into dist/bundle/, emptied first, so the job attaches exactly one
wheel (the current version) whatever earlier builds left in dist/."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "bundle"

shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True)
build = ROOT / "build"
shutil.rmtree(build, ignore_errors=True)
subprocess.check_call([sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(OUT),
                       str(ROOT / "src")])
shutil.rmtree(ROOT / "src" / "build", ignore_errors=True)
for egg in (ROOT / "src").glob("*.egg-info"):
    shutil.rmtree(egg, ignore_errors=True)
wheels = sorted(p.name for p in OUT.glob("*.whl"))
if len(wheels) != 1:
    sys.exit(f"expected one wheel in {OUT}, found {wheels}")
print(f"built {wheels[0]}")
