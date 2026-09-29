"""The model and the cores that use it must import without a GUI toolkit."""
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

CODE = (
    "import sys, ibl.model, ibl.conversion, ibl.csvlogger, ibl.channels, ibl.config; "
    'print(any(m.startswith(("PySide6", "pyqtgraph")) for m in sys.modules))'
)


def test_core_modules_do_not_import_qt():
    env = dict(os.environ, PYTHONPATH=str(SRC))
    out = subprocess.run([sys.executable, "-c", CODE], env=env, capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "False"
