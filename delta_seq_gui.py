"""
Delta Elektronika Sequence Builder - ControlDesk-style signal editor (PyQt5).

    pip install PyQt5 matplotlib
    python delta_seq_gui.py
"""
from __future__ import annotations

import copy
import math
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QToolBar,
    QVBoxLayout, QWidget, QHeaderView, QDialog, QDialogButtonBox,
    QAbstractItemView, QRadioButton, QButtonGroup,
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

import delta_seq_core as core

CHANNELS = {"Voltage (SV)": "SV", "Current (SC)": "SC", "Power (SP)": "SP"}
UNITS = {"SV": "V", "SC": "A", "SP": "W"}


class PlotCanvas(FigureCanvasQTAgg):
    def __init__(self):
        self.fig = Figure(figsize=(6, 4), tight_layout=True)
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)

    def plot(self, points, channel, repeat, seg_bounds, selected):
        ax = self.ax
        ax.clear()
        passes = 1 if repeat == 1 else (2 if repeat == 0 else min(repeat, 3))
        t, ts, vs = 0.0, [], []
        for _ in range(passes):
            for v, dt in points:
                ts.append(t); vs.append(v)
                t += dt
        if vs:
            ts.append(t); vs.append(vs[-1])
            ax.step(ts, vs, where="post", lw=1.6, color="#1f6fb2")
        one = sum(dt for _, dt in points)
        for p in range(1, passes):
            ax.axvline(p * one, color="grey", ls="--", lw=0.8)
        if selected is not None and 0 <= selected < len(seg_bounds):
            a, b = seg_bounds[selected]
            ax.axvspan(a, b, color="orange", alpha=0.2)
        if not vs:
            ax.text(0.5, 0.5, "No segments – add one on the left",
                    ha="center", va="center", transform=ax.transAxes, color="grey")
        ax.set_xlabel("Time [s]")
        ax.set_ylabel(f"{channel} [{UNITS[channel]}]")
        title = "Preview"
        if repeat == 0:
            title += " (infinite loop – 2 passes shown)"
        elif repeat > 1:
            title += f" ({repeat} passes, {passes} shown)"
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        self.draw_idle()


# --------------------------------------------------------------------------
# Segment parameter editors (shared by main window and child dialogs)
# --------------------------------------------------------------------------
def build_segment_form(form: QFormLayout, seg: dict, on_changed, parent):
    """Fill `form` with editors for `seg`; edits are written into `seg`
    and `on_changed()` is called after every change."""
    kind = seg["type"]
    if kind == "Table":
        _build_table_editor(form, seg, on_changed)
        return

    if kind == "Combine":
        cb = QComboBox(); cb.addItems(core.COMBINE_OPS)
        cb.setCurrentText(seg["op"])
        def op_changed(text):
            seg["op"] = text; on_changed()
        cb.currentTextChanged.connect(op_changed)
        form.addRow("Operation", cb)

    for key, label, _d, is_int in core.SEGMENT_TYPES[kind]:
        if is_int:
            w = QSpinBox(); w.setRange(1, 10000)
        else:
            w = QDoubleSpinBox(); w.setDecimals(3)
            w.setRange(-100000, 100000)
            w.setKeyboardTracking(False)
            if key == "dt": w.setSingleStep(0.01); w.setRange(0.001, 100000)
            if key == "duty": w.setRange(0, 100)
            if key in ("duration", "period", "freq"): w.setMinimum(0)
        w.setValue(seg[key])
        def changed(v, k=key):
            seg[k] = v; on_changed()
        w.valueChanged.connect(changed)
        form.addRow(label, w)

    if kind == "Combine":
        child_labels = {}
        for slot, name in (("a", "Signal A"), ("b", "Signal B")):
            box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(core.describe_segment(seg[slot])); lbl.setWordWrap(True)
            child_labels[slot] = lbl
            btn = QPushButton("Edit…"); btn.setFixedWidth(60)
            def edit(_=False, slot=slot, name=name):
                dlg = SegmentDialog(seg[slot], parent, f"Edit {name}")
                if dlg.exec_() == QDialog.Accepted:
                    seg[slot] = dlg.seg
                    child_labels[slot].setText(core.describe_segment(dlg.seg))
                    on_changed()
            btn.clicked.connect(edit)
            h.addWidget(lbl, 1); h.addWidget(btn)
            form.addRow(name, box)
        def swap():
            seg["a"], seg["b"] = seg["b"], seg["a"]
            for slot in ("a", "b"):
                child_labels[slot].setText(core.describe_segment(seg[slot]))
            on_changed()
        b = QPushButton("Swap A ↔ B"); b.clicked.connect(swap)
        form.addRow(b)
        note = QLabel("Duration = longer of A and B; the shorter one holds its "
                      "last value. Result is sampled every 'Sample time'.")
        note.setWordWrap(True); note.setStyleSheet("color: grey")
        form.addRow(note)


def _build_table_editor(form: QFormLayout, seg: dict, on_changed):
    tbl = QTableWidget(len(seg["points"]), 2)
    tbl.setHorizontalHeaderLabels(["Value", "Hold [s]"])
    tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    tbl.setMinimumHeight(180)
    for r, (v, t) in enumerate(seg["points"]):
        tbl.setItem(r, 0, QTableWidgetItem(f"{v:g}"))
        tbl.setItem(r, 1, QTableWidgetItem(f"{t:g}"))

    def read_back(*_):
        pts = []
        for r in range(tbl.rowCount()):
            try:
                pts.append([float(tbl.item(r, 0).text()),
                            float(tbl.item(r, 1).text())])
            except (AttributeError, ValueError):
                pass                       # skip incomplete / non-numeric rows
        seg["points"] = pts
        on_changed()

    def add_row():
        r = tbl.currentRow() + 1 if tbl.currentRow() >= 0 else tbl.rowCount()
        last = seg["points"][r - 1] if 0 < r <= len(seg["points"]) else [0, 1]
        tbl.blockSignals(True)
        tbl.insertRow(r)
        tbl.setItem(r, 0, QTableWidgetItem(f"{last[0]:g}"))
        tbl.setItem(r, 1, QTableWidgetItem(f"{last[1]:g}"))
        tbl.blockSignals(False)
        read_back()

    def del_rows():
        for r in sorted({i.row() for i in tbl.selectedIndexes()}, reverse=True):
            tbl.removeRow(r)
        read_back()

    def paste():
        text = QApplication.clipboard().text()
        rows = [ln.replace(",", "\t").replace(";", "\t").split()
                for ln in text.splitlines() if ln.strip()]
        rows = [r for r in rows if len(r) >= 2]
        if not rows: return
        tbl.blockSignals(True)
        tbl.setRowCount(len(rows))
        for r, (v, t, *_) in enumerate(rows):
            tbl.setItem(r, 0, QTableWidgetItem(v))
            tbl.setItem(r, 1, QTableWidgetItem(t))
        tbl.blockSignals(False)
        read_back()

    tbl.itemChanged.connect(read_back)
    btns = QWidget(); h = QHBoxLayout(btns); h.setContentsMargins(0, 0, 0, 0)
    for text, fn in [("Add row", add_row), ("Delete rows", del_rows),
                     ("Paste (Excel/CSV)", paste)]:
        b = QPushButton(text); b.clicked.connect(fn); h.addWidget(b)
    form.addRow(tbl)
    form.addRow(btns)


class SegmentDialog(QDialog):
    """Edit a child signal of a Combine segment (any type, can be nested)."""

    def __init__(self, seg: dict, parent=None, title="Edit signal"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 620)
        self.seg = copy.deepcopy(seg)
        v = QVBoxLayout(self)
        top = QFormLayout()
        self.cb = QComboBox(); self.cb.addItems(core.SEGMENT_TYPES)
        self.cb.setCurrentText(self.seg["type"])
        self.cb.currentTextChanged.connect(self._type_changed)
        top.addRow("Signal type", self.cb)
        v.addLayout(top)
        self.holder = QWidget(); self.form = QFormLayout(self.holder)
        v.addWidget(self.holder)
        self.canvas = PlotCanvas(); self.canvas.setMinimumHeight(220)
        v.addWidget(self.canvas, 1)
        self.lbl_err = QLabel(); self.lbl_err.setStyleSheet("color: #c00")
        v.addWidget(self.lbl_err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._rebuild()

    def _type_changed(self, kind):
        self.seg = core.default_segment(kind)
        self._rebuild()

    def _rebuild(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        build_segment_form(self.form, self.seg, self._preview, self)
        self._preview()

    def _preview(self):
        try:
            pts = core.sample_segment(self.seg)
            self.lbl_err.setText("")
        except (ValueError, ZeroDivisionError) as e:
            pts = []; self.lbl_err.setText(str(e))
        self.canvas.plot(pts, "SV", 1, [], None)
        self.canvas.ax.set_ylabel("Value"); self.canvas.ax.set_title("Signal preview")
        self.canvas.draw_idle()


class SampleImportDialog(QDialog):
    """Load timestamp/value samples and convert them to a Table segment."""

    def __init__(self, parent, channel: str):
        super().__init__(parent)
        self.setWindowTitle("Import samples")
        self.resize(1100, 720)
        self.rows: list[list[str]] = []
        self.samples: list[tuple[float, float]] = []
        self.points: list[list[float]] = []
        self.path = ""

        main = QHBoxLayout(self)
        left = QVBoxLayout(); main.addLayout(left, 0)

        # --- file
        gf = QGroupBox("1. Sample file"); ff = QFormLayout(gf)
        hb = QHBoxLayout()
        self.ed_path = QLineEdit(); self.ed_path.setReadOnly(True)
        b = QPushButton("Browse…"); b.clicked.connect(self.browse)
        hb.addWidget(self.ed_path, 1); hb.addWidget(b)
        ff.addRow(hb)
        self.chk_header = QCheckBox("First row is a header")
        self.cb_tcol = QComboBox(); self.cb_vcol = QComboBox()
        ff.addRow(self.chk_header)
        ff.addRow("Time column", self.cb_tcol)
        ff.addRow("Value column", self.cb_vcol)
        self.tbl_raw = QTableWidget(); self.tbl_raw.setMaximumHeight(140)
        self.tbl_raw.setEditTriggers(QAbstractItemView.NoEditTriggers)
        ff.addRow(self.tbl_raw)
        left.addWidget(gf)

        # --- time
        gt = QGroupBox("2. Time"); ft = QFormLayout(gt)
        self.cb_unit = QComboBox(); self.cb_unit.addItems(core.TIME_UNITS)
        self.cb_unit.setCurrentText("ms")
        self.cb_tmode = QComboBox()
        self.cb_tmode.addItems(["Timestamp (time of each sample)",
                                "Duration (hold time of each sample)"])
        self.chk_zero = QCheckBox("Start at t = 0 (shift first timestamp)")
        self.chk_zero.setChecked(True)
        self.sp_last = self._dspin(0.001, 1e6, 3, 1.0)
        ft.addRow("Time unit", self.cb_unit)
        ft.addRow("Time column is", self.cb_tmode)
        ft.addRow(self.chk_zero)
        ft.addRow("Hold last value [s]", self.sp_last)
        left.addWidget(gt)

        # --- signal shape
        gm = QGroupBox("3. Signal shape between samples"); fm = QFormLayout(gm)
        self.rb_step = QRadioButton("Step – hold each value until the next sample")
        self.rb_cont = QRadioButton("Continuous – linear interpolation, resampled")
        self.rb_step.setChecked(True)
        grp = QButtonGroup(self); grp.addButton(self.rb_step); grp.addButton(self.rb_cont)
        fm.addRow(self.rb_step); fm.addRow(self.rb_cont)
        self.sp_dt = self._dspin(1, 1e7, 1, 100.0)
        b_fit = QPushButton("Fit to 2000 steps"); b_fit.clicked.connect(self.fit_steps)
        fm.addRow("Resample step [ms]", self._row(self.sp_dt, b_fit))
        self.sp_minhold = self._dspin(1, 1e7, 1, 1.0)
        fm.addRow("Minimum hold [ms]", self.sp_minhold)
        self.sp_scale = self._dspin(-1e6, 1e6, 4, 1.0)
        self.sp_offset = self._dspin(-1e6, 1e6, 3, 0.0)
        fm.addRow("Value × scale + offset", self._row(self.sp_scale, self.sp_offset))
        left.addWidget(gm)

        # --- output
        go = QGroupBox("4. Output"); fo = QFormLayout(go)
        self.cb_ch = QComboBox(); self.cb_ch.addItems(CHANNELS)
        self.cb_ch.setCurrentIndex(list(CHANNELS.values()).index(channel))
        self.cb_rep = QComboBox()
        self.cb_rep.addItems(["Play once", "Repeat N times", "Continuous loop (∞)"])
        self.sp_n = QSpinBox(); self.sp_n.setRange(2, 65535); self.sp_n.setValue(2)
        self.cb_target = QComboBox()
        self.cb_target.addItems(["Replace current project", "Append as segment"])
        fo.addRow("Controlled", self.cb_ch)
        fo.addRow("Playback", self._row(self.cb_rep, self.sp_n))
        fo.addRow("Insert", self.cb_target)
        left.addWidget(go)
        left.addStretch()

        # --- right: preview
        right = QVBoxLayout(); main.addLayout(right, 1)
        self.canvas = PlotCanvas()
        right.addWidget(NavigationToolbar2QT(self.canvas, self))
        right.addWidget(self.canvas, 1)
        self.lbl = QLabel("Choose a file with time and value columns."); self.lbl.setWordWrap(True)
        right.addWidget(self.lbl)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText("Import")
        self.bb.accepted.connect(self.accept); self.bb.rejected.connect(self.reject)
        right.addWidget(self.bb)

        for w in (self.chk_header, self.chk_zero, self.rb_step, self.rb_cont):
            w.toggled.connect(self.update_preview)
        for w in (self.cb_tcol, self.cb_vcol, self.cb_unit, self.cb_tmode,
                  self.cb_ch, self.cb_rep):
            w.currentIndexChanged.connect(self.update_preview)
        for w in (self.sp_last, self.sp_dt, self.sp_minhold, self.sp_scale,
                  self.sp_offset):
            w.valueChanged.connect(self.update_preview)
        self.sp_n.valueChanged.connect(self.update_preview)
        self.update_preview()

    @staticmethod
    def _dspin(lo, hi, dec, val):
        s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(dec)
        s.setValue(val); s.setKeyboardTracking(False)
        return s

    @staticmethod
    def _row(*ws):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        for x in ws: h.addWidget(x)
        return w

    def browse(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "Open sample file", "",
            "Samples (*.csv *.txt *.tsv *.dat *.xlsx *.xlsm);;All files (*)")
        if not fn: return
        try:
            self.rows = core.read_table_file(fn)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Read failed", str(e)); return
        if not self.rows:
            QMessageBox.warning(self, "Read failed", "The file is empty."); return
        self.path = fn
        self.ed_path.setText(fn)
        hdr = core.detect_header(self.rows)
        ncol = max(len(r) for r in self.rows[:50])
        names = [(self.rows[0][i] if hdr and i < len(self.rows[0]) else f"Column {i + 1}")
                 for i in range(ncol)]
        for cb in (self.cb_tcol, self.cb_vcol):
            cb.blockSignals(True); cb.clear(); cb.addItems(names); cb.blockSignals(False)
        self.cb_vcol.setCurrentIndex(1 if ncol > 1 else 0)
        # guess the time unit from the header text
        h0 = names[0].lower()
        for key, unit in (("µs", "µs"), ("us]", "µs"), ("ms", "ms"), ("[s]", "s"),
                          ("sec", "s"), ("min", "min")):
            if key in h0:
                self.cb_unit.setCurrentText(unit); break
        if any(":" in r[0] for r in self.rows[1:5] if r):
            self.cb_unit.setCurrentText("hh:mm:ss / date-time")
        self.chk_header.blockSignals(True); self.chk_header.setChecked(hdr)
        self.chk_header.blockSignals(False)
        show = self.rows[:8]
        self.tbl_raw.setRowCount(len(show)); self.tbl_raw.setColumnCount(ncol)
        for r, row in enumerate(show):
            for c, val in enumerate(row):
                self.tbl_raw.setItem(r, c, QTableWidgetItem(val))
        self.update_preview()

    def options(self) -> core.SampleImportOptions:
        return core.SampleImportOptions(
            time_is_duration=self.cb_tmode.currentIndex() == 1,
            zero_start=self.chk_zero.isChecked(),
            continuous=self.rb_cont.isChecked(),
            resample_dt=self.sp_dt.value() / 1000.0,
            last_hold=self.sp_last.value(),
            min_hold=self.sp_minhold.value() / 1000.0,
            scale=self.sp_scale.value(), offset=self.sp_offset.value())

    def repeat(self) -> int:
        i = self.cb_rep.currentIndex()
        return 1 if i == 0 else (self.sp_n.value() if i == 1 else 0)

    def channel(self) -> str:
        return CHANNELS[self.cb_ch.currentText()]

    def fit_steps(self):
        if len(self.samples) < 2: return
        span = self.samples[-1][0] - self.samples[0][0]
        dt = max(0.001, span / 950)               # ~2 steps per point + margin
        self.sp_dt.setValue(math.ceil(dt * 1000))
        self.rb_cont.setChecked(True)

    def update_preview(self, *_):
        self.sp_dt.setEnabled(self.rb_cont.isChecked())
        self.sp_minhold.setEnabled(self.rb_step.isChecked())
        self.sp_n.setEnabled(self.cb_rep.currentIndex() == 1)
        self.cb_unit.setEnabled(True)
        ok_btn = self.bb.button(QDialogButtonBox.Ok)
        self.points = []
        ax = self.canvas.ax
        if not self.rows:
            ok_btn.setEnabled(False); return
        try:
            self.samples, skipped = core.extract_samples(
                self.rows, self.cb_tcol.currentIndex(), self.cb_vcol.currentIndex(),
                self.cb_unit.currentText(), self.chk_header.isChecked())
            self.points, warns = core.samples_to_points(self.samples, self.options())
        except (ValueError, ZeroDivisionError) as e:
            self.lbl.setText(f"<span style='color:#c00'>{e}</span>")
            ok_btn.setEnabled(False); return
        ch = self.channel()
        self.canvas.plot([tuple(p) for p in self.points], ch, self.repeat(), [], None)
        o = self.options()
        if self.samples:
            t0 = 0 if not o.zero_start or o.time_is_duration else self.samples[0][0]
            if o.time_is_duration:
                ts, acc = [], 0.0
                for d, _v in self.samples:
                    ts.append(acc); acc += d
            else:
                ts = [t - t0 for t, _ in self.samples]
            ax.plot(ts, [v * o.scale + o.offset for _, v in self.samples], "o",
                    ms=3, color="#ff7f0e", label="samples")
            ax.legend(loc="best", fontsize=8)
            self.canvas.draw_idle()
        n_steps = 2 * len(self.points) + 4
        dur = sum(p[1] for p in self.points)
        msg = [f"{len(self.samples)} samples → {len(self.points)} points ≈ "
               f"<b>{n_steps} steps</b> (max {core.MAX_STEPS}) · {dur:.3f} s per pass"]
        if skipped:
            msg.append(f"{skipped} row(s) without numeric time/value were skipped.")
        msg += warns
        if n_steps > core.MAX_STEPS:
            msg.append("<span style='color:#c00'>Too many steps – use Continuous "
                       "with a larger resample step (or 'Fit to 2000 steps'), or a "
                       "larger minimum hold.</span>")
        self.lbl.setText("<br>".join(msg))
        ok_btn.setEnabled(bool(self.points) and n_steps <= core.MAX_STEPS)


class ImportCanvas(FigureCanvasQTAgg):
    """Multi-channel plot of a simulated (imported) sequence."""
    COLORS = {"SV": "#1f6fb2", "SC": "#d62728", "SP": "#2ca02c",
              "SCN": "#9467bd", "SPN": "#8c564b"}

    def __init__(self):
        self.fig = Figure(figsize=(6, 4), tight_layout=True)
        super().__init__(self.fig)

    @staticmethod
    def _xy(trace, end):
        xs = [t for t, _ in trace] + [end]
        ys = [v for _, v in trace] + [trace[-1][1]]
        return xs, ys

    def plot(self, res: core.SimResult, title: str):
        self.fig.clear()
        tr, end = res.traces, max(res.end_time, 1e-3)
        extra = [c for c in ("SP", "SCN", "SPN") if c in tr]
        digital = sorted(c for c in tr if c.startswith("O"))
        rows = 1 + (1 if extra else 0) + (1 if digital else 0)
        ratios = [3] + ([2] if extra else []) + ([1.2] if digital else [])
        axes = self.fig.subplots(rows, 1, sharex=True,
                                 gridspec_kw={"height_ratios": ratios})
        axes = [axes] if rows == 1 else list(axes)

        ax = axes[0]
        x, y = self._xy(tr["SV"], end)
        ax.step(x, y, where="post", color=self.COLORS["SV"], lw=1.6, label="SV")
        ax.set_ylabel("SV [V]", color=self.COLORS["SV"])
        ax2 = ax.twinx()
        x, y = self._xy(tr["SC"], end)
        ax2.step(x, y, where="post", color=self.COLORS["SC"], lw=1.2, ls="--",
                 label="SC")
        ax2.set_ylabel("SC [A]", color=self.COLORS["SC"])
        ax.grid(True, alpha=0.3)
        ax.set_title(title, fontsize=10)

        i = 1
        if extra:
            a = axes[i]; i += 1
            for c in extra:
                x, y = self._xy(tr[c], end)
                a.step(x, y, where="post", color=self.COLORS[c], lw=1.3, label=c)
            a.legend(loc="upper right", fontsize=8); a.grid(True, alpha=0.3)
            a.set_ylabel("Power / sink")
        if digital:
            a = axes[i]
            for k, c in enumerate(digital):
                x, y = self._xy(tr[c], end)
                a.step(x, [v * 0.8 + k for v in y], where="post", lw=1.2)
            a.set_yticks([k + 0.4 for k in range(len(digital))])
            a.set_yticklabels(digital, fontsize=8)
            a.set_ylim(-0.2, len(digital)); a.grid(True, axis="x", alpha=0.3)
        axes[-1].set_xlabel("Time [s]")
        self.draw_idle()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Delta Elektronika Sequence Builder")
        self.resize(1300, 800)
        self.cfg = core.SequenceSettings(segments=[core.default_segment("Ramp")])
        self.current_file: str | None = None
        self._loading = False
        self._build_ui()
        self._load_settings_into_ui()
        self.settings_changed()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        tb = QToolBar("Main"); self.addToolBar(tb)
        for text, slot, sc in [
            ("New", self.new_project, "Ctrl+N"),
            ("Open…", self.open_project, "Ctrl+O"),
            ("Save", self.save_project, "Ctrl+S"),
            ("Save As…", self.save_project_as, None),
            (None, None, None),
            ("Export .txt…", self.export_txt, "Ctrl+E"),
            ("Open sequence .txt…", self.import_txt, "Ctrl+I"),
            ("Import samples (CSV/Excel)…", self.import_samples, "Ctrl+M"),
            ("Upload to PSU…", self.upload_psu, None),
        ]:
            if text is None:
                tb.addSeparator(); continue
            a = QAction(text, self); a.triggered.connect(slot)
            if sc: a.setShortcut(sc)
            tb.addAction(a)

        # ---- left: settings + segments
        left = QWidget(); lv = QVBoxLayout(left)

        g = QGroupBox("Sequence settings"); f = QFormLayout(g)
        self.ed_name = QLineEdit(); self.ed_name.setMaxLength(16)
        self.cb_channel = QComboBox(); self.cb_channel.addItems(CHANNELS)
        self.sp_vlim = self._dspin(0, 2000, 3); self.sp_clim = self._dspin(0, 2000, 3)
        self.sp_vmax = self._dspin(0, 2000, 3); self.sp_cmax = self._dspin(0, 2000, 3)
        self.sp_pmax = self._dspin(0, 100000, 1)
        self.sp_repeat = QSpinBox(); self.sp_repeat.setRange(0, 65535)
        self.sp_repeat.setSpecialValueText("∞ (infinite)")
        self.chk_final = QCheckBox("Set at end:")
        self.sp_final = self._dspin(0, 100000, 3)
        hf = QHBoxLayout(); hf.addWidget(self.chk_final); hf.addWidget(self.sp_final)
        self.sp_dec = QSpinBox(); self.sp_dec.setRange(0, 4)
        self.chk_merge = QCheckBox("Merge equal consecutive values")
        self.chk_nv = QCheckBox("Store non-volatile (PROG:SAV)")
        self.chk_clear = QCheckBox("Delete old sequence before upload")
        self.chk_run = QCheckBox("Run after upload")
        f.addRow("Name", self.ed_name)
        f.addRow("Controlled", self.cb_channel)
        f.addRow("Voltage limit [V]", self.sp_vlim)
        f.addRow("Current limit [A]", self.sp_clim)
        f.addRow("Model Vmax / Cmax", self._row(self.sp_vmax, self.sp_cmax))
        f.addRow("Model Pmax [W]", self.sp_pmax)
        f.addRow("Repeat", self.sp_repeat)
        f.addRow(hf)
        f.addRow("Decimals", self.sp_dec)
        for w in (self.chk_merge, self.chk_nv, self.chk_clear, self.chk_run):
            f.addRow(w)
        lv.addWidget(g)

        for w in (self.ed_name,):
            w.textChanged.connect(self.settings_changed)
        self.cb_channel.currentIndexChanged.connect(self.settings_changed)
        for w in (self.sp_vlim, self.sp_clim, self.sp_vmax, self.sp_cmax,
                  self.sp_pmax, self.sp_final):
            w.valueChanged.connect(self.settings_changed)
        for w in (self.sp_repeat, self.sp_dec):
            w.valueChanged.connect(self.settings_changed)
        for w in (self.chk_final, self.chk_merge, self.chk_nv, self.chk_clear,
                  self.chk_run):
            w.toggled.connect(self.settings_changed)

        gs = QGroupBox("Signal segments"); sv = QVBoxLayout(gs)
        self.lst = QListWidget()
        self.lst.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lst.currentRowChanged.connect(self.segment_selected)
        sv.addWidget(self.lst)
        hb = QHBoxLayout()
        self.cb_type = QComboBox(); self.cb_type.addItems(core.SEGMENT_TYPES)
        b_add = QPushButton("Add"); b_add.clicked.connect(self.add_segment)
        hb.addWidget(self.cb_type); hb.addWidget(b_add); sv.addLayout(hb)
        hb2 = QHBoxLayout()
        for text, slot in [("Duplicate", self.dup_segment), ("Remove", self.del_segment),
                           ("▲", lambda: self.move_segment(-1)),
                           ("▼", lambda: self.move_segment(1))]:
            b = QPushButton(text); b.clicked.connect(slot); hb2.addWidget(b)
        sv.addLayout(hb2)
        hb4 = QHBoxLayout()
        b = QPushButton("Combine selected (+ − ×)…")
        b.setToolTip("Ctrl+click two segments, then combine them into one signal")
        b.clicked.connect(self.combine_selected); hb4.addWidget(b)
        b = QPushButton("Split"); b.setToolTip("Turn a Combine segment back into A and B")
        b.clicked.connect(self.split_segment); hb4.addWidget(b)
        sv.addLayout(hb4)
        lv.addWidget(gs, 1)

        self.grp_params = QGroupBox("Segment parameters")
        self.form_params = QFormLayout(self.grp_params)
        lv.addWidget(self.grp_params)

        # ---- right: plot + output
        right = QSplitter(Qt.Vertical)
        self.plot_tabs = QTabWidget()
        pw = QWidget(); pv = QVBoxLayout(pw)
        self.canvas = PlotCanvas()
        pv.addWidget(NavigationToolbar2QT(self.canvas, self)); pv.addWidget(self.canvas)
        self.plot_tabs.addTab(pw, "Editor preview")

        iw = QWidget(); iv = QVBoxLayout(iw)
        self.imp_canvas = ImportCanvas()
        iv.addWidget(NavigationToolbar2QT(self.imp_canvas, self))
        iv.addWidget(self.imp_canvas, 1)
        hi = QHBoxLayout()
        hi.addWidget(QLabel("Sim. limit [s]"))
        self.sp_simtime = self._dspin(0.1, 1e6, 1); self.sp_simtime.setValue(600)
        hi.addWidget(self.sp_simtime)
        hi.addWidget(QLabel("Inputs"))
        self.ed_inputs = QLineEdit(); self.ed_inputs.setPlaceholderText("e.g. IA1=1, IB2=0")
        hi.addWidget(self.ed_inputs, 1)
        b = QPushButton("Re-simulate"); b.clicked.connect(self.run_import_sim)
        hi.addWidget(b)
        b = QPushButton("Convert to editable…"); b.clicked.connect(self.convert_import)
        hi.addWidget(b)
        iv.addLayout(hi)
        self.lbl_import = QLabel("Use 'Open sequence .txt…' to load an existing file.")
        self.lbl_import.setWordWrap(True)
        iv.addWidget(self.lbl_import)
        self.plot_tabs.addTab(iw, "Imported sequence")
        right.addWidget(self.plot_tabs)
        self.imported: core.ParsedSequence | None = None
        self.imported_file = ""
        self.sim: core.SimResult | None = None

        ow = QWidget(); ov = QVBoxLayout(ow)
        hb3 = QHBoxLayout()
        hb3.addWidget(QLabel("Output format:"))
        self.cb_fmt = QComboBox()
        self.cb_fmt.addItems(["SCPI upload commands", "Step list"])
        self.cb_fmt.currentIndexChanged.connect(self.refresh)
        hb3.addWidget(self.cb_fmt); hb3.addStretch()
        self.lbl_status = QLabel(); hb3.addWidget(self.lbl_status)
        ov.addLayout(hb3)
        self.tabs = QTabWidget()
        self.txt_out = QPlainTextEdit(); self.txt_out.setReadOnly(True)
        self.txt_out.setFont(QFont("Consolas", 10))
        self.txt_msg = QPlainTextEdit(); self.txt_msg.setReadOnly(True)
        self.tabs.addTab(self.txt_out, "Generated file")
        self.tabs.addTab(self.txt_msg, "Messages")
        self.txt_import = QPlainTextEdit(); self.txt_import.setReadOnly(True)
        self.txt_import.setFont(QFont("Consolas", 10))
        self.tabs.addTab(self.txt_import, "Imported file")
        ov.addWidget(self.tabs)
        right.addWidget(ow)
        right.setSizes([450, 350])

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left); split.addWidget(right); split.setSizes([400, 900])
        self.setCentralWidget(split)

    @staticmethod
    def _dspin(lo, hi, dec):
        s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(dec)
        s.setKeyboardTracking(False)
        return s

    @staticmethod
    def _row(*widgets):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        for x in widgets: h.addWidget(x)
        return w

    # ------------------------------------------------------- settings <-> UI
    def _load_settings_into_ui(self):
        self._loading = True
        c = self.cfg
        self.ed_name.setText(c.name)
        self.cb_channel.setCurrentIndex(list(CHANNELS.values()).index(c.channel))
        self.sp_vlim.setValue(c.limit_voltage); self.sp_clim.setValue(c.limit_current)
        self.sp_vmax.setValue(c.vmax); self.sp_cmax.setValue(c.cmax)
        self.sp_pmax.setValue(c.pmax)
        self.sp_repeat.setValue(c.repeat)
        self.chk_final.setChecked(c.final_value_enabled); self.sp_final.setValue(c.final_value)
        self.sp_dec.setValue(c.decimals); self.chk_merge.setChecked(c.merge_equal)
        self.chk_nv.setChecked(c.nonvolatile); self.chk_clear.setChecked(c.clear_before_upload)
        self.chk_run.setChecked(c.run_after_upload)
        self._loading = False
        self._rebuild_list(0)

    def settings_changed(self, *_):
        if self._loading:
            return
        c = self.cfg
        c.name = self.ed_name.text().strip()
        c.channel = CHANNELS[self.cb_channel.currentText()]
        c.limit_voltage = self.sp_vlim.value(); c.limit_current = self.sp_clim.value()
        c.vmax = self.sp_vmax.value(); c.cmax = self.sp_cmax.value()
        c.pmax = self.sp_pmax.value()
        c.repeat = self.sp_repeat.value()
        c.final_value_enabled = self.chk_final.isChecked()
        c.final_value = self.sp_final.value()
        c.decimals = self.sp_dec.value(); c.merge_equal = self.chk_merge.isChecked()
        c.nonvolatile = self.chk_nv.isChecked()
        c.clear_before_upload = self.chk_clear.isChecked()
        c.run_after_upload = self.chk_run.isChecked()
        self.sp_vlim.setEnabled(c.channel != "SV")
        self.sp_clim.setEnabled(c.channel != "SC")
        self.refresh()

    # ------------------------------------------------------------- segments
    def _rebuild_list(self, select=None):
        self.lst.blockSignals(True)
        self.lst.clear()
        for i, s in enumerate(self.cfg.segments, 1):
            self.lst.addItem(f"{i}. {core.describe_segment(s)}")
        self.lst.blockSignals(False)
        if select is not None and self.cfg.segments:
            self.lst.setCurrentRow(max(0, min(select, len(self.cfg.segments) - 1)))
        else:
            self.segment_selected(self.lst.currentRow())

    def add_segment(self):
        seg = core.default_segment(self.cb_type.currentText())
        # continue from the previous segment's last value
        if self.cfg.segments:
            try:
                pts = core.sample_segment(self.cfg.segments[-1])
            except (ValueError, ZeroDivisionError):
                pts = []
            last = pts[-1][0] if pts else 0.0
            for key in ("value", "start", "low", "offset"):
                if key in seg:
                    seg[key] = round(last, 3); break
        self.cfg.segments.append(seg)
        self._rebuild_list(len(self.cfg.segments) - 1)

    def dup_segment(self):
        r = self.lst.currentRow()
        if r < 0: return
        self.cfg.segments.insert(r + 1, copy.deepcopy(self.cfg.segments[r]))
        self._rebuild_list(r + 1)

    def del_segment(self):
        r = self.lst.currentRow()
        if r < 0: return
        del self.cfg.segments[r]
        self._rebuild_list(r)
        self.refresh()

    def combine_selected(self):
        rows = sorted({i.row() for i in self.lst.selectedIndexes()})
        if len(rows) != 2:
            QMessageBox.information(
                self, "Combine",
                "Select exactly two segments (Ctrl+click), then click Combine.\n\n"
                "Tip: you can also add a 'Combine' segment and edit A and B directly.")
            return
        op, ok = QInputDialog.getItem(self, "Combine", "Operation (A ∘ B):",
                                      list(core.COMBINE_OPS), 2, False)
        if not ok: return
        a, b = (copy.deepcopy(self.cfg.segments[r]) for r in rows)
        dts = [x["dt"] for x in (a, b) if "dt" in x]
        seg = {"type": "Combine", "op": op, "dt": min(dts) if dts else 0.05,
               "a": a, "b": b}
        self.cfg.segments[rows[0]] = seg
        del self.cfg.segments[rows[1]]
        self._rebuild_list(rows[0])

    def split_segment(self):
        r = self.lst.currentRow()
        if r < 0 or self.cfg.segments[r]["type"] != "Combine":
            QMessageBox.information(self, "Split", "Select a Combine segment first.")
            return
        seg = self.cfg.segments[r]
        self.cfg.segments[r:r + 1] = [seg["a"], seg["b"]]
        self._rebuild_list(r)

    def move_segment(self, d):
        r = self.lst.currentRow(); n = r + d
        if r < 0 or not 0 <= n < len(self.cfg.segments): return
        s = self.cfg.segments
        s[r], s[n] = s[n], s[r]
        self._rebuild_list(n)

    def segment_selected(self, row):
        while self.form_params.rowCount():
            self.form_params.removeRow(0)
        if row < 0 or row >= len(self.cfg.segments):
            self.grp_params.setTitle("Segment parameters")
            self.refresh(); return
        seg = self.cfg.segments[row]
        self.grp_params.setTitle(f"Segment {row + 1}: {seg['type']}")
        build_segment_form(self.form_params, seg,
                           lambda r=row: self._seg_edited(r), self)
        self.refresh()

    def _seg_edited(self, row):
        item = self.lst.item(row)
        if item:
            item.setText(f"{row + 1}. {core.describe_segment(self.cfg.segments[row])}")
        self.refresh()

    # --------------------------------------------------------------- output
    def _fmt_key(self):
        return "scpi" if self.cb_fmt.currentIndex() == 0 else "steps"

    def refresh(self):
        if self._loading or not hasattr(self, "canvas"):
            return
        comp = core.compile_sequence(self.cfg)
        self.comp = comp
        # segment time bounds for highlighting
        bounds, t = [], 0.0
        for s in self.cfg.segments:
            try:
                d = sum(dt for _, dt in core.sample_segment(s))
            except (ValueError, ZeroDivisionError, KeyError):
                d = 0
            bounds.append((t, t + d)); t += d
        self.canvas.plot(comp.points, self.cfg.channel, self.cfg.repeat,
                         bounds, self.lst.currentRow())
        self.txt_out.setPlainText(core.to_text(self.cfg, comp, self._fmt_key()))
        msgs = [f"ERROR: {e}" for e in comp.errors] + [f"Warning: {w}" for w in comp.warnings]
        self.txt_msg.setPlainText("\n".join(msgs) or "No problems.")
        state = "❌ errors" if comp.errors else ("⚠ warnings" if comp.warnings else "✔ OK")
        self.lbl_status.setText(
            f"{len(comp.steps)}/{core.MAX_STEPS} steps · "
            f"{comp.duration_one_pass:.3f} s per pass · {state}")
        self.tabs.setTabText(1, f"Messages ({len(msgs)})" if msgs else "Messages")

    # ---------------------------------------------------------- file actions
    def new_project(self):
        self.cfg = core.SequenceSettings(segments=[])
        self.current_file = None
        self._load_settings_into_ui(); self.settings_changed()

    def open_project(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open project", "",
                                            "Sequence project (*.json)")
        if not fn: return
        try:
            with open(fn, encoding="utf-8") as fh:
                self.cfg = core.SequenceSettings.from_json(fh.read())
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e)); return
        self.current_file = fn
        self._load_settings_into_ui(); self.settings_changed()

    def save_project(self):
        if not self.current_file:
            return self.save_project_as()
        with open(self.current_file, encoding="utf-8", mode="w") as fh:
            fh.write(self.cfg.to_json())
        self.statusBar().showMessage(f"Saved {self.current_file}", 4000)

    def save_project_as(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Save project",
                                            f"{self.cfg.name}.json",
                                            "Sequence project (*.json)")
        if fn:
            self.current_file = fn; self.save_project()

    # ------------------------------------------------------- import .txt
    def import_txt(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open sequence file", "",
                                            "Sequence text (*.txt *.seq);;All files (*)")
        if not fn: return
        try:
            with open(fn, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            QMessageBox.critical(self, "Open failed", str(e)); return
        self.imported = core.parse_sequence_text(text)
        self.imported_file = fn
        self.txt_import.setPlainText(text)
        self.plot_tabs.setCurrentIndex(1)
        self.run_import_sim()

    def import_samples(self):
        dlg = SampleImportDialog(self, self.cfg.channel)
        if dlg.exec_() != QDialog.Accepted or not dlg.points:
            return
        seg = {"type": "Table", "points": dlg.points}
        if dlg.cb_target.currentIndex() == 0:
            name = "".join(c for c in os.path.splitext(os.path.basename(dlg.path))[0]
                           if c.isalnum() or c == "_")[:16]
            if not name or not name[0].isalpha():
                name = "SAMPLES"
            self.cfg.segments = [seg]
            self.cfg.name = name
            self.current_file = None
        else:
            self.cfg.segments.append(seg)
        self.cfg.channel = dlg.channel()
        self.cfg.repeat = dlg.repeat()
        self._load_settings_into_ui()
        self.settings_changed()
        self.lst.setCurrentRow(len(self.cfg.segments) - 1)
        self.plot_tabs.setCurrentIndex(0)

    def _parse_inputs(self) -> dict:
        out = {}
        for part in self.ed_inputs.text().replace(";", ",").split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                try: out[k.strip().upper()] = int(float(v))
                except ValueError: pass
        return out

    def run_import_sim(self):
        if not self.imported:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.sim = core.simulate(self.imported, max_time=self.sp_simtime.value(),
                                     inputs=self._parse_inputs())
        finally:
            QApplication.restoreOverrideCursor()
        r, p = self.sim, self.imported
        name = self.imported_file.replace("\\", "/").split("/")[-1]
        self.imp_canvas.plot(r, f"{name}  –  sequence '{p.name}'")
        self.lbl_import.setText(
            f"<b>{len(p.steps)} steps</b>, labels: "
            f"{', '.join(f'{k}={v}' for k, v in p.labels.items()) or 'none'} · "
            f"simulated {r.end_time:.3f} s, {r.executed} steps executed · "
            f"{r.stop_reason}")
        msgs = [f"ERROR: {e}" for e in r.errors] + [f"Warning: {w}" for w in r.warnings]
        body = "\n".join(f"{n:>5}  {c}" for n, c in p.steps.items())
        self.txt_msg.setPlainText(
            ("\n".join(msgs) or "Imported file: no problems.")
            + "\n\n--- Parsed steps ---\n" + body)
        self.tabs.setCurrentIndex(1)

    def convert_import(self):
        if not self.sim:
            QMessageBox.information(self, "Convert", "Open a sequence file first."); return
        r, p = self.sim, self.imported
        analog = [c for c in ("SV", "SC", "SP") if c in r.traces]
        changes = {c: len(r.traces[c]) for c in analog}
        best = max(analog, key=changes.get)
        ch, ok = QInputDialog.getItem(self, "Convert to editable",
                                      "Channel to turn into the editable signal:",
                                      analog, analog.index(best), False)
        if not ok: return
        if not r.stop_reason.startswith("END"):
            if QMessageBox.question(
                    self, "Convert",
                    f"The simulation did not reach END:\n{r.stop_reason}\n\n"
                    f"Loops are unrolled up to the simulated time "
                    f"({r.end_time:.1f} s). Continue?") != QMessageBox.Yes:
                return
        pts = core.trace_to_points(r.traces[ch], r.end_time)
        if QMessageBox.question(self, "Convert",
                                f"Replace the current project with a table of "
                                f"{len(pts)} points ({ch})?") != QMessageBox.Yes:
            return
        name = "".join(c for c in p.name if c.isalnum() or c == "_")[:16]
        if not name or not name[0].isalpha():
            name = "IMPORTED"
        cfg = core.SequenceSettings(name=name, channel=ch, repeat=1,
                                    final_value_enabled=False,
                                    segments=[{"type": "Table", "points": pts}])
        if ch != "SV" and r.traces["SV"]:
            cfg.limit_voltage = max(v for _, v in r.traces["SV"])
        if ch != "SC" and r.traces["SC"]:
            cfg.limit_current = max(v for _, v in r.traces["SC"])
        cfg.vmax = max(self.cfg.vmax, cfg.limit_voltage)
        cfg.cmax = max(self.cfg.cmax, cfg.limit_current)
        self.cfg = cfg; self.current_file = None
        self._load_settings_into_ui(); self.settings_changed()
        self.plot_tabs.setCurrentIndex(0)
        if len(pts) * 2 > core.MAX_STEPS:
            QMessageBox.warning(self, "Convert",
                                "The unrolled signal needs more than 2000 steps. "
                                "Use the Repeat setting or shorten the table.")

    def _check_ok(self) -> bool:
        if self.comp.errors:
            QMessageBox.warning(self, "Sequence has errors",
                                "\n".join(self.comp.errors))
            return False
        return True

    def export_txt(self):
        if not self._check_ok(): return
        fn, _ = QFileDialog.getSaveFileName(self, "Export sequence",
                                            f"{self.cfg.name}.txt", "Text (*.txt)")
        if not fn: return
        with open(fn, "w", encoding="ascii", newline="\n") as fh:
            fh.write(core.to_text(self.cfg, self.comp, self._fmt_key()))
        self.statusBar().showMessage(f"Exported {fn}", 4000)

    def upload_psu(self):
        if not self._check_ok(): return
        host, ok = QInputDialog.getText(self, "Upload", "Power supply IP address:",
                                        text="192.168.0.100")
        if not ok or not host: return
        port, ok = QInputDialog.getInt(self, "Upload", "TCP port:", 8462, 1, 65535)
        if not ok: return
        log = []
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            core.upload(host.strip(), port, core.to_scpi_lines(self.cfg, self.comp),
                        log=log.append)
        except OSError as e:
            QMessageBox.critical(self, "Upload failed", str(e)); return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Upload", "Upload finished.\n" + "\n".join(log))


def _excepthook(exc_type, exc, tb):
    """Show unexpected errors in a dialog instead of letting PyQt abort the app."""
    import traceback
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    sys.__stderr__.write(text)
    if QApplication.instance():
        box = QMessageBox(QMessageBox.Critical, "Unexpected error", str(exc))
        box.setDetailedText(text)
        box.exec_()


def main():
    sys.excepthook = _excepthook
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow(); w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
