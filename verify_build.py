"""
Post-build verification for the IBL Pressure one-folder build.

Why this exists
---------------
PyInstaller can finish with "Build complete!" and still leave you with a
folder that crashes on another PC.  The usual culprits:

  * antivirus quarantines a compiled extension (.pyd) after it is written,
  * a copy to a USB stick / network share silently skips files,
  * an interrupted unzip drops part of _internal\\.

The symptom is always the same shape: a ModuleNotFoundError for something
that is obviously installed, e.g.

    ModuleNotFoundError: No module named 'shiboken6.Shiboken'

That means Python found the package's __init__.py (which lives inside the
exe) but not the .pyd next to it on disk.

What this script does
---------------------
1. Reads PyInstaller's own build manifest, build\\<name>\\COLLECT-00.toc,
   which lists every file PyInstaller *intended* to place in dist\\.
2. Checks each one actually exists in dist\\ and is the right size.
3. Hard-checks a short list of files the app cannot start without.
4. Writes dist\\<name>\\MANIFEST.txt (file count, total bytes, and a
   SHA-256 per file) so the same folder can be re-checked after it has
   been copied to the control PC.

Usage
-----
    python verify_build.py              # verify a fresh build, write MANIFEST.txt
    python verify_build.py --check DIR  # re-verify a copied folder against its MANIFEST.txt

Exit code 0 = good, 1 = something is missing or damaged.
"""
from __future__ import annotations

import ast
import hashlib
import os
import sys
from pathlib import Path

APP_NAME = "IBLpressure"
HERE = Path(__file__).resolve().parent

# Files the app cannot start without.  These are the ones antivirus and
# half-finished copies tend to eat.
CRITICAL = [
    f"{APP_NAME}.exe",
    "_internal/shiboken6/Shiboken.pyd",
    "_internal/shiboken6/shiboken6.abi3.dll",
    "_internal/PySide6/pyside6.abi3.dll",
    "_internal/PySide6/QtCore.pyd",
    "_internal/PySide6/QtGui.pyd",
    "_internal/PySide6/QtWidgets.pyd",
    "_internal/PySide6/plugins/platforms/qwindows.dll",
]

MANIFEST_NAME = "MANIFEST.txt"


def fail(msg: str) -> None:
    print(f"  !! {msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_collect_toc(toc_path: Path) -> list[tuple[str, str, str]]:
    """PyInstaller writes the TOC as a repr of a Python object, so we can
    just parse it instead of guessing at the text format."""
    raw = ast.literal_eval(toc_path.read_text(encoding="utf-8"))
    # The file holds a 1-tuple wrapping the list of entries.
    entries = raw[0] if isinstance(raw, tuple) else raw
    return [tuple(e) for e in entries]


def expected_path(dist_app: Path, dest: str, typecode: str) -> Path:
    """Where a collected entry should land.  In one-folder mode the exe sits
    at the top and everything else goes under _internal\\."""
    rel = dest.replace("\\", "/")
    if typecode == "EXECUTABLE":
        return dist_app / rel
    return dist_app / "_internal" / rel


def verify_against_toc(dist_app: Path) -> int:
    toc_path = HERE / "build" / APP_NAME / "COLLECT-00.toc"
    if not toc_path.exists():
        fail(f"{toc_path} not found - did PyInstaller actually run?")
        return 1

    entries = read_collect_toc(toc_path)
    print(f"  PyInstaller collected {len(entries)} files")

    problems = 0
    for dest, src, typecode in entries:
        want = expected_path(dist_app, dest, typecode)
        if not want.exists():
            # Be forgiving about layout changes between PyInstaller versions.
            alt = dist_app / dest.replace("\\", "/")
            if alt.exists():
                want = alt
            else:
                fail(f"MISSING  {dest}")
                problems += 1
                continue
        try:
            src_size = os.path.getsize(src)
        except OSError:
            continue  # source is gone (temp build file); size check not possible
        if want.stat().st_size != src_size:
            fail(f"WRONG SIZE  {dest}  ({want.stat().st_size} vs {src_size} bytes)")
            problems += 1

    for rel in CRITICAL:
        if not (dist_app / rel).exists():
            fail(f"CRITICAL FILE MISSING  {rel}")
            problems += 1

    if problems:
        return problems

    print(f"  All {len(entries)} files present and the right size")
    print(f"  All {len(CRITICAL)} critical files present")
    return 0


def write_manifest(dist_app: Path) -> None:
    files = sorted(
        p for p in dist_app.rglob("*") if p.is_file() and p.name != MANIFEST_NAME
    )
    total = sum(p.stat().st_size for p in files)
    lines = [
        f"# IBL Pressure build manifest",
        f"# files: {len(files) + 1}   (this manifest included)",
        f"# bytes: {total}",
        f"#",
        f"# On the control PC, a quick sanity check from cmd:",
        f"#     dir /s /b /a-d  |  find /c /v \"\"",
        f"# should print {len(files) + 1}.",
        f"#",
        f"# size  sha256  path",
    ]
    for p in files:
        lines.append(f"{p.stat().st_size}  {sha256(p)}  {p.relative_to(dist_app).as_posix()}")
    (dist_app / MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Wrote {MANIFEST_NAME}: {len(files) + 1} files, {total / 1e6:.0f} MB")


def check_copied_folder(dist_app: Path) -> int:
    """Re-verify a folder that has already been copied somewhere else."""
    manifest = dist_app / MANIFEST_NAME
    if not manifest.exists():
        fail(f"No {MANIFEST_NAME} in {dist_app} - nothing to check against.")
        return 1

    expected: dict[str, tuple[int, str]] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        size, digest, rel = line.split("  ", 2)
        expected[rel] = (int(size), digest)

    problems = 0
    for rel, (size, digest) in expected.items():
        p = dist_app / rel
        if not p.exists():
            fail(f"MISSING  {rel}")
            problems += 1
        elif p.stat().st_size != size:
            fail(f"WRONG SIZE  {rel}")
            problems += 1
        elif sha256(p) != digest:
            fail(f"CORRUPT  {rel}")
            problems += 1

    if problems == 0:
        print(f"  All {len(expected)} files match the manifest")
    return problems


def main(argv: list[str]) -> int:
    if "--check" in argv:
        target = Path(argv[argv.index("--check") + 1]).resolve()
        print(f"=== Checking copied folder: {target}")
        problems = check_copied_folder(target)
    else:
        dist_app = HERE / "dist" / APP_NAME
        if not dist_app.is_dir():
            fail(f"{dist_app} does not exist.")
            return 1
        print(f"=== Verifying {dist_app}")
        problems = verify_against_toc(dist_app)
        if problems == 0:
            write_manifest(dist_app)

    if problems:
        print()
        print(f"  *** {problems} problem(s) found. ***")
        print("  If files are missing right after a build, check your antivirus")
        print("  quarantine - Defender sometimes removes PyInstaller .pyd files.")
        return 1

    print("  OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
