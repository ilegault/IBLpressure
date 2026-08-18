"""
Headless smoke test.

Builds the entire window off-screen, runs the simulator flat out for a few
seconds, exercises every control, and confirms that CSV rows actually landed
on disk.  Nothing appears on screen -- it is meant for a quick "did I break
anything" check after editing the GUI.

    python smoke_test.py
"""
import os, sys, time, glob
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ibl.config import Settings
from ibl.mainwindow import MainWindow

app = QApplication(sys.argv)
s = Settings()
s.simulate = True
s.sample_hz = 20.0          # run fast so the test finishes quickly
s.csv_interval_s = 0.2
s.csv_dir = "/tmp/ibl_test_logs"
os.system("rm -rf /tmp/ibl_test_logs")

w = MainWindow(s)
w.show()

results = {}
def finish():
    results["rows_in_table"] = w.table.rowCount()
    results["series_points"] = {a: len(v.t) for a, v in w.series.items()}
    results["csv_rows_written"] = w._csv_rows
    results["csv_files"] = glob.glob("/tmp/ibl_test_logs/*.csv")
    results["status"] = w.lbl_status.text()
    results["csv_label"] = w.lbl_csv.text()
    # exercise the interactive bits
    w._set_plotted(lambda c: True)
    w._set_plotted(lambda c: c.is_ion)
    w.cmb_span.setCurrentIndex(4)
    w.chk_autoy.setChecked(False)
    w.chk_autoy.setChecked(True)
    w.spn_hz.setValue(2.0)
    w.chk_csvv.setChecked(True)
    w._clear_history()
    w._redraw_plot()
    results["after_toggles"] = "no exception"
    w.close()
    app.quit()

QTimer.singleShot(3000, finish)
app.exec()

print("=== SMOKE TEST ===")
for k, v in results.items():
    print(f"{k}: {v}")
for f in results.get("csv_files", []):
    print("\n--- head of", f, "---")
    with open(f) as fh:
        for i, line in enumerate(fh):
            if i > 4: break
            print(line.rstrip()[:200])
    print("... total lines:", sum(1 for _ in open(f)))
