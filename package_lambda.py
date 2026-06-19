"""Build Lambda deployment ZIP with Linux-compatible wheels on Windows.
Directly extracts downloaded Linux wheel ZIPs to avoid pip Windows compatibility checks.
"""
import os, shutil, subprocess, sys, zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR     = PROJECT_ROOT / "dist"
WHEEL_DIR    = PROJECT_ROOT / "wheelhouse"
ZIP_PATH     = PROJECT_ROOT / "build" / "lambda.zip"

def download_linux_wheels():
    """Download Linux manylinux2014_x86_64 wheels into wheelhouse/."""
    req_file = PROJECT_ROOT / "requirements-lambda.txt"
    if WHEEL_DIR.exists(): shutil.rmtree(WHEEL_DIR)
    WHEEL_DIR.mkdir()
    
    cmd = [
        sys.executable, "-m", "pip", "download",
        "-r", str(req_file),
        "--platform", "manylinux2014_x86_64",
        "--python-version", "3.12",
        "--implementation", "cp",
        "--only-binary=:all:",
        "-d", str(WHEEL_DIR),
        "--no-cache-dir",
        "-q"
    ]
    print("[1] Downloading Linux x86_64 wheels...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("STDERR:", r.stderr[:1000])
        print("  Retrying without --only-binary for pure python packages...")
        cmd2 = [c for c in cmd if c != "--only-binary=:all:"]
        r2 = subprocess.run(cmd2, capture_output=True, text=True)
        if r2.returncode != 0:
            print("STDERR:", r2.stderr[:1000])
            sys.exit(1)
    
    wheel_count = len(list(WHEEL_DIR.glob("*.whl")))
    print(f"  Downloaded {wheel_count} wheels")

def extract_wheels():
    """Unzip all wheels directly into dist/ directory."""
    if DIST_DIR.exists(): shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir()
    
    print("[2] Unzipping Linux wheels directly into dist/")
    for whl in WHEEL_DIR.glob("*.whl"):
        with zipfile.ZipFile(whl, 'r') as z:
            z.extractall(DIST_DIR)

def create_zip_with_permissions():
    """Copy app code and create ZIP with Linux permissions (0755 dirs, 0644 files)."""
    print("[3] Copying application code")
    shutil.copytree(PROJECT_ROOT / "src", DIST_DIR / "src", dirs_exist_ok=True)
    if (PROJECT_ROOT / "frontend").exists():
        shutil.copytree(PROJECT_ROOT / "frontend", DIST_DIR / "frontend")
    
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists(): os.remove(ZIP_PATH)
    
    print("[4] Creating lambda.zip")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(DIST_DIR):
            # Exclude pycache and unnecessary test dirs to keep zip small
            dirs[:] = [d for d in dirs if d not in ["__pycache__", "tests"]]
            
            # Add directories with 0755 permissions
            for d in dirs:
                dir_path = Path(root) / d
                rel = dir_path.relative_to(DIST_DIR)
                zip_dir = str(rel).replace(os.sep, '/') + '/'
                zinfo = zipfile.ZipInfo(zip_dir)
                zinfo.external_attr = (0o40000 | 0o755) << 16
                zf.writestr(zinfo, '')
            
            # Add files with 0644 permissions
            for fn in files:
                if fn.endswith(".pyc") or fn.endswith(".pyo"): continue
                fp = Path(root) / fn
                rel = fp.relative_to(DIST_DIR)
                zip_fn = str(rel).replace(os.sep, '/')
                
                with open(fp, 'rb') as f:
                    data = f.read()
                
                zinfo = zipfile.ZipInfo(zip_fn)
                zinfo.external_attr = (0o100000 | 0o644) << 16
                zf.writestr(zinfo, data)

def clean():
    for d in [DIST_DIR, WHEEL_DIR]:
        if d.exists(): shutil.rmtree(d)

def build():
    clean()
    download_linux_wheels()
    extract_wheels()
    create_zip_with_permissions()
    
    size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    clean()
    print(f"\nDone! ZIP: {ZIP_PATH} ({size_mb:.1f} MB)")

if __name__ == "__main__":
    build()
