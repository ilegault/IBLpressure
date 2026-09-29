"""
LabJack LJM driver: is it here, and can we install it for the user?

The app talks to the T7 through the LJM C library (LabJackM.dll).  PyInstaller
cannot bundle that DLL, so on a fresh control PC it may be missing.  This
module answers two questions the GUI needs:

    check_ljm()        -> (ok, message)   is LJM installed AND responding?
    find_installer()   -> path | None     did we ship an installer alongside us?
    launch_installer() -> bool            run that installer (asks for admin)

Nothing here imports PySide6, so it is safe to call from anywhere.
"""
from __future__ import annotations

import glob
import os
import sys


# ---------------------------------------------------------------------------
def check_ljm() -> tuple[bool, str]:
    """
    True only if LJM is importable *and* actually answers.

    A plain `import` succeeding is not enough: the DLL can load while its
    constants file is missing, which would let openS work but break the named
    reads (AIN0 -> Modbus address) the app relies on.  Reading the library
    version is a cheap way to confirm LJM is really alive.
    """
    try:
        from labjack import ljm  # type: ignore
    except Exception as exc:
        return False, f"LabJack LJM driver not found ({exc})"

    try:
        version = ljm.readLibraryConfigS("LJM_LIBRARY_VERSION")
        return True, f"LJM library {version:.4f} ready"
    except Exception as exc:
        return False, f"LJM present but not responding ({exc})"


# ---------------------------------------------------------------------------
def _candidate_dirs() -> list[str]:
    """Folders that might hold a bundled installer, frozen or from source."""
    dirs: list[str] = []

    # The folder holding IBLpressure.exe (or the project root from source).
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs += [exe_dir, os.path.join(exe_dir, "vendor")]

    # Where PyInstaller unpacks bundled data files (varies by version).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs += [meipass, os.path.join(meipass, "vendor")]

    # De-duplicate while keeping order.
    seen: set[str] = set()
    unique: list[str] = []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def find_installer() -> str | None:
    """
    Return the path to a bundled LabJack installer, or None.

    Anything named like  LabJack*.exe  dropped into  vendor\\  (see README)
    counts.  If several match, the newest wins.
    """
    hits: list[str] = []
    for d in _candidate_dirs():
        hits += glob.glob(os.path.join(d, "LabJack*.exe"))
        hits += glob.glob(os.path.join(d, "labjack*.exe"))
    if not hits:
        return None
    hits.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return hits[0]


def launch_installer(path: str, silent: bool = False) -> bool:
    """
    Launch the installer with a UAC (administrator) prompt.

    We do NOT install anything ourselves - we hand off to LabJack's own
    installer, which needs admin rights to place the driver system-wide.
    Returns True if the launch was accepted (the install then runs on its own).
    """
    try:
        import ctypes  # Windows only; harmless to import elsewhere on failure
        params = "/S" if silent else ""
        # "runas" triggers the Windows elevation prompt.
        rc = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", path, params, os.path.dirname(path), 1
        )
        return int(rc) > 32  # ShellExecute returns >32 on success
    except Exception:
        return False
