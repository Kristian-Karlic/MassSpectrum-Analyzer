import logging
import re

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QHeaderView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QKeySequence, QShortcut

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from utils.style.style import StyleSheet, EditorConstants
from utils.peak_matching.peptide_fragmentation import fragment_and_match_peaks_cached
from utils.spectrum_graph.config.constants import matched_mask
from utils.utilities import (
    DataGatherer,
    IonTypeGenerator,
    IonCollectionUtils,
    TableUtils,
)

logger = logging.getLogger(__name__)

# (key_in_scores_dict, combo_label)
_PLOT_METRICS = [
    ("xtandem",     "X!Tandem"),
    ("consecutive", "Consecutive"),
    ("comp_pairs",  "Complementary"),
    ("theor_pct",   "Theor frag (%)"),
    ("peaks_pct",   "Peaks (%)"),
    ("tic_pct",     "TIC (%)"),
    ("cov_pct",     "Cov (%)"),
    ("intact_pct",  "Intact (%)"),
    ("partial_pct", "Partial cov (%)"),
]

_C_TERMINAL = frozenset(("y", "z", "x"))
_N_TERMINAL = frozenset(("b", "c", "a"))


def _get_labile_settings(app):
    def _cb(attr):
        cb = getattr(app, attr, None)
        return cb.isChecked() if cb is not None else False

    return (
        _cb("enable_labile_losses_cb"),
        _cb("enable_remainder_ions_cb"),
        _cb("enable_mod_nl_cb"),
    )


def _backbone_coverage(matched_data, peptide, exclude_chars=None):
    """Return (matched_bonds, potential_bonds) for backbone coverage.

    exclude_chars: set of single chars whose presence in Ion Type disqualifies a row.
    """
    potential = max(0, (len(peptide) * 2) - 2)
    if matched_data is None or matched_data.empty:
        return 0, potential

    mask = matched_mask(matched_data)
    df = matched_data[mask].copy()
    if df.empty:
        return 0, potential

    if exclude_chars and "Ion Type" in df.columns:
        pattern = "|".join(map(re.escape, exclude_chars))
        df = df[~df["Ion Type"].astype(str).str.contains(pattern, regex=True, na=False)]

    if "Base Type" not in df.columns or "Ion Number" not in df.columns:
        return 0, potential

    bonds = set()
    for row in df[["Base Type", "Ion Number"]].itertuples(index=False, name=None):
        bt = str(row[0]).strip()
        try:
            num = int(row[1])
        except (ValueError, TypeError):
            continue
        if bt in _C_TERMINAL:
            bonds.add(("yzx", num))
        elif bt in _N_TERMINAL:
            bonds.add(("bca", num))

    return len(bonds), potential


# ------------------------------------------------------------------
# Popup dialog for results
# ------------------------------------------------------------------
class RelocalisationResultsDialog(QDialog):
    """Resizable, non-modal popup showing relocalisation results."""

    _COLUMNS = ["Position", "AA", "X!Tandem", "Consecutive", "Complementary"]

    def __init__(self, rows, peptide, mod_label, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Relocalisation Results  —  {mod_label}  on  {peptide}")
        self.setMinimumSize(620, 300)
        self.resize(700, max(300, 60 + 28 * len(rows)))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self._setup_ui(rows)

    def _setup_ui(self, rows):
        layout = QVBoxLayout(self)

        self.table = QTableWidget(len(rows), len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setAlternatingRowColors(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        StyleSheet.apply_table_styling(self.table)

        best_idx = 0
        best_hs = -1.0
        for r, (pos, aa, scores, is_original) in enumerate(rows):
            pos_label = str(pos)
            if is_original:
                pos_label += " (original)"
            self.table.setItem(r, 0, QTableWidgetItem(pos_label))
            self.table.setItem(r, 1, QTableWidgetItem(aa))
            self.table.setItem(r, 2, QTableWidgetItem(f"{scores['xtandem']:.2f}"))
            self.table.setItem(r, 3, QTableWidgetItem(str(scores["consecutive"])))
            self.table.setItem(r, 4, QTableWidgetItem(str(scores["complementary"])))

            if scores["xtandem"] > best_hs:
                best_hs = scores["xtandem"]
                best_idx = r

        highlight = QColor("#d4edda")
        for c in range(self.table.columnCount()):
            item = self.table.item(best_idx, c)
            if item:
                item.setBackground(highlight)

        layout.addWidget(self.table)

        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        copy_sc.activated.connect(self._copy_selection)

        copy_hint = QLabel("Tip: select rows and press Ctrl+C to copy as spreadsheet")
        copy_hint.setStyleSheet(
            f"color: {EditorConstants.GRAY_500()}; font-size: 8pt;"
        )
        layout.addWidget(copy_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        self.setStyleSheet(StyleSheet.get_dialog_style())

    def _copy_selection(self):
        selected_rows = sorted(
            {idx.row() for idx in self.table.selectedIndexes()}
        )
        if not selected_rows:
            selected_rows = list(range(self.table.rowCount()))

        header = "\t".join(self._COLUMNS)
        lines = [header]
        for r in selected_rows:
            cells = [
                (self.table.item(r, c).text() if self.table.item(r, c) else "")
                for c in range(self.table.columnCount())
            ]
            lines.append("\t".join(cells))

        QApplication.clipboard().setText("\n".join(lines))


# ------------------------------------------------------------------
# In-panel controls
# ------------------------------------------------------------------
class RelocalisationWidget(QWidget):
    """Test every valid position for a selected modification and rank by score."""

    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self._mod_entries = []   # [(mass, position), ...] parallel to combo index
        self._last_rows = []     # cached result rows
        self._results_dialog = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # --- Modification selector ---
        mod_row = QHBoxLayout()
        mod_label = QLabel("Modification:")
        mod_label.setStyleSheet(StyleSheet.get_label_style())
        mod_row.addWidget(mod_label)

        self.mod_combo = QComboBox()
        self.mod_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.mod_combo.setMinimumWidth(140)
        mod_row.addWidget(self.mod_combo, 1)
        layout.addLayout(mod_row)

        # --- Allowed amino acids ---
        aa_row = QHBoxLayout()
        aa_label = QLabel("Allowed AA:")
        aa_label.setStyleSheet(StyleSheet.get_label_style())
        aa_row.addWidget(aa_label)

        self.aa_input = QLineEdit()
        self.aa_input.setPlaceholderText("e.g. S,T  or leave blank for all residues")
        self.aa_input.setStyleSheet(EditorConstants.get_lineedit_style())
        self.aa_input.setToolTip(
            "Comma-separated amino acid letters where the modification is\n"
            "allowed to be placed.  Leave blank to try all residues."
        )
        aa_row.addWidget(self.aa_input, 1)
        layout.addLayout(aa_row)

        # --- Buttons row ---
        btn_row = QHBoxLayout()

        self.run_btn = QPushButton("Run Relocalisation")
        self.run_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        self.run_btn.clicked.connect(self.run_relocalisation)
        btn_row.addWidget(self.run_btn, 1)

        self.show_btn = QPushButton("Show Last Results")
        self.show_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.show_btn.clicked.connect(self._show_last_results)
        self.show_btn.setEnabled(False)
        btn_row.addWidget(self.show_btn, 1)

        layout.addLayout(btn_row)

        # --- Inline score plot ---
        self._plot_figure = Figure(
            figsize=(3, 2),
            facecolor=EditorConstants.PLOT_BACKGROUND(),
        )
        self._plot_canvas = FigureCanvas(self._plot_figure)
        self._plot_canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._plot_canvas.setMinimumHeight(120)
        self._plot_canvas.setVisible(False)
        layout.addWidget(self._plot_canvas, 1)

        # --- Y-axis metric selector ---
        metric_row = QHBoxLayout()
        metric_label = QLabel("Y-axis:")
        metric_label.setStyleSheet(StyleSheet.get_label_style())
        metric_row.addWidget(metric_label)

        self._metric_combo = QComboBox()
        self._metric_combo.setStyleSheet(EditorConstants.get_combobox_style())
        for _, label in _PLOT_METRICS:
            self._metric_combo.addItem(label)
        self._metric_combo.currentIndexChanged.connect(self._on_metric_changed)
        self._metric_combo.setVisible(False)
        metric_row.addWidget(self._metric_combo, 1)
        layout.addLayout(metric_row)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Refresh combo from current peptide mods
    # ------------------------------------------------------------------
    def refresh_modifications(self):
        self.mod_combo.clear()
        self._mod_entries.clear()

        mods = getattr(self.main_app, "current_interactive_mods", None) or []
        peptide = (
            self.main_app.peptide_input.text().strip()
            if hasattr(self.main_app, "peptide_input")
            else ""
        )
        central_db = getattr(self.main_app, "central_mod_db", None)

        for mass, pos in mods:
            aa = peptide[pos - 1] if 0 < pos <= len(peptide) else "?"
            name = central_db.find_by_mass(mass) if central_db else None
            label = name if name else f"{mass:.4f}"
            self.mod_combo.addItem(f"{label} @ {aa}{pos}")
            self._mod_entries.append((mass, pos))

    # ------------------------------------------------------------------
    # Show last results
    # ------------------------------------------------------------------
    def _show_last_results(self):
        if not self._last_rows:
            return
        # Bring existing dialog to front, or open a fresh one
        if self._results_dialog is not None and self._results_dialog.isVisible():
            self._results_dialog.raise_()
            self._results_dialog.activateWindow()
            return
        self._open_results_dialog()

    def _open_results_dialog(self):
        peptide = self.main_app.peptide_input.text().strip()
        sel_idx = self.mod_combo.currentIndex()
        if sel_idx < 0 or not self._last_rows:
            return

        sel_mass = self._mod_entries[sel_idx][0]
        central_db = getattr(self.main_app, "central_mod_db", None)
        mod_name = central_db.find_by_mass(sel_mass) if central_db else None
        mod_label = mod_name if mod_name else f"{sel_mass:.4f}"

        dlg = RelocalisationResultsDialog(
            self._last_rows, peptide, mod_label, parent=self
        )
        self._results_dialog = dlg
        dlg.show()

    # ------------------------------------------------------------------
    # Core relocalisation
    # ------------------------------------------------------------------
    def run_relocalisation(self):
        if self.mod_combo.currentIndex() < 0:
            return

        peptide = self.main_app.peptide_input.text().strip()
        if not peptide:
            return

        sel_idx = self.mod_combo.currentIndex()
        sel_mass, sel_pos = self._mod_entries[sel_idx]

        raw_aa = self.aa_input.text().strip()
        allowed = (
            {c.strip().upper() for c in raw_aa.split(",") if c.strip()}
            if raw_aa
            else None  # None = all residues
        )

        all_mods = getattr(self.main_app, "current_interactive_mods", []) or []
        base_mods = [m for i, m in enumerate(all_mods) if i != sel_idx]

        candidates = [
            (i + 1, aa.upper())
            for i, aa in enumerate(peptide)
            if allowed is None or aa.upper() in allowed
        ]
        if not candidates:
            return

        params = self._gather_fragmentation_params(peptide)
        if params is None:
            return

        ion_types = params["ion_types"]
        scoring_flags = getattr(self.main_app, "scoring_methods", {})

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = []
            for cand_pos, cand_aa in candidates:
                test_mods = base_mods + [(sel_mass, cand_pos)]
                enable_labile, enable_remainder, enable_mod_nl = _get_labile_settings(
                    self.main_app
                )
                mod_nl = DataGatherer.build_mod_neutral_losses(
                    test_mods,
                    getattr(self.main_app, "central_mod_db", None),
                    enable_labile=enable_labile,
                    enable_remainder=enable_remainder,
                    enable_mod_nl=enable_mod_nl,
                )

                matched_data, theoretical_data = fragment_and_match_peaks_cached(
                    peptide=peptide,
                    modifications=test_mods,
                    max_charge=params["max_charge"],
                    ppm_tolerance=params["ppm_tolerance"],
                    selected_ions=params["selected_ions"],
                    selected_internal_ions=params["selected_internal_ions"],
                    user_mz_values=params["user_mz_values"],
                    diagnostic_ions=params["diagnostic_ions"],
                    custom_ion_series_list=params["custom_ion_series_list"],
                    max_neutral_losses=params["max_neutral_losses"],
                    mod_neutral_losses=mod_nl,
                )

                scores = self._compute_scores(
                    matched_data,
                    theoretical_data,
                    ion_types,
                    peptide,
                    scoring_flags,
                )
                is_original = cand_pos == sel_pos
                rows.append((cand_pos, cand_aa, scores, is_original))
        finally:
            QApplication.restoreOverrideCursor()

        if rows:
            self._last_rows = rows
            self.show_btn.setEnabled(True)
            self._update_inline_plot(rows)
            self._open_results_dialog()

    # ------------------------------------------------------------------
    # Inline plot
    # ------------------------------------------------------------------
    def _on_metric_changed(self):
        if self._last_rows:
            self._update_inline_plot(self._last_rows)

    def _update_inline_plot(self, rows):
        metric_idx = self._metric_combo.currentIndex()
        metric_key, metric_label = _PLOT_METRICS[metric_idx]

        positions = [r[0] for r in rows]
        values = [r[2].get(metric_key, 0.0) for r in rows]
        is_original = [r[3] for r in rows]

        bg = EditorConstants.PLOT_BACKGROUND()
        fg = EditorConstants.PLOT_FOREGROUND()
        grid_color = EditorConstants.GRID_COLOR()

        self._plot_figure.clear()
        ax = self._plot_figure.add_subplot(111)
        ax.set_facecolor(bg)
        self._plot_figure.set_facecolor(bg)

        ax.plot(positions, values, color="#4a90d9", linewidth=1.5, zorder=2)
        ax.scatter(positions, values, color="#4a90d9", s=30, zorder=3)

        best_val = max(values) if values else 0
        for pos, val, orig in zip(positions, values, is_original):
            if val == best_val and best_val > 0:
                ax.scatter([pos], [val], color="#28a745", s=60, zorder=4)
            if orig:
                ax.scatter([pos], [val], color="#dc3545", s=60, marker="D", zorder=5)

        ax.set_xlabel("Position", color=fg, fontsize=7)
        ax.set_ylabel(metric_label, color=fg, fontsize=7)
        ax.tick_params(colors=fg, labelsize=6)
        ax.set_xticks(positions)
        for spine in ax.spines.values():
            spine.set_edgecolor(fg)
        ax.grid(True, color=grid_color, linewidth=0.5, alpha=0.5)

        self._plot_figure.tight_layout(pad=0.4)
        self._plot_canvas.setVisible(True)
        self._metric_combo.setVisible(True)
        self._plot_canvas.draw()

    # ------------------------------------------------------------------
    # Parameter gathering
    # ------------------------------------------------------------------
    def _gather_fragmentation_params(self, peptide):
        app = self.main_app
        try:
            max_charge = app.max_charge_input.value()
            ppm_tolerance = app.ppm_tolerance_input.value()
            max_neutral_losses = app.max_neutral_losses_input.value()
            user_mz_values = TableUtils.extract_mz_intensity_from_table(app.mz_table)
            if not user_mz_values:
                return None

            selected_ions = IonTypeGenerator.generate_dynamic_ion_types(
                app.normal_ion_checkboxes,
                app.neutral_ion_checkboxes,
                max_neutral_losses,
            )
            selected_internal_ions = IonCollectionUtils.collect_selected_internal_ions(
                app.internal_ion_checkboxes
            )
            diagnostic_ions = DataGatherer.gather_diagnostic_ions(
                app.selected_diagnostic_ions_data
            )
            custom_ion_series_list = DataGatherer.gather_custom_ion_series(
                app.selected_custom_ions_data
            )
            ion_types = app.annotation_tab_manager.get_selected_annotation_ion_types()

            return {
                "max_charge": max_charge,
                "ppm_tolerance": ppm_tolerance,
                "max_neutral_losses": max_neutral_losses,
                "user_mz_values": user_mz_values,
                "selected_ions": selected_ions,
                "selected_internal_ions": selected_internal_ions,
                "diagnostic_ions": diagnostic_ions,
                "custom_ion_series_list": custom_ion_series_list,
                "ion_types": ion_types,
            }
        except Exception as e:
            logger.debug(f"[RELOCALISE] Failed to gather parameters: {e}")
            return None

    # ------------------------------------------------------------------
    # Score computation
    # ------------------------------------------------------------------
    def _compute_scores(self, matched_data, theoretical_data, ion_types, peptide, scoring_flags):
        scores = {
            "xtandem":    0.0,
            "consecutive": 0,
            "complementary": "0/0",
            "comp_pairs": 0,
            "theor_pct":  0.0,
            "peaks_pct":  0.0,
            "tic_pct":    0.0,
            "cov_pct":    0.0,
            "intact_pct": 0.0,
            "partial_pct": 0.0,
        }
        pep_len = len(peptide)

        # ── Spectrum-level metrics (whole matched_data) ──────────────
        if matched_data is not None and not matched_data.empty:
            mask = matched_mask(matched_data)
            total_peaks = len(matched_data)
            matched_peaks = int(mask.sum())
            scores["peaks_pct"] = (matched_peaks / total_peaks * 100) if total_peaks else 0.0

            if "intensity" in matched_data.columns:
                total_int = matched_data["intensity"].sum()
                matched_int = matched_data[mask]["intensity"].sum()
                scores["tic_pct"] = (float(matched_int / total_int * 100) if total_int else 0.0)

            # Theor frag %
            if theoretical_data is not None and not theoretical_data.empty:
                theor_total = len(theoretical_data)
                mono = matched_data[mask].copy()
                if "Isotope" in mono.columns:
                    mono = mono[pd.to_numeric(mono["Isotope"], errors="coerce") == 0]
                if "Ion Type" in mono.columns and "Ion Number" in mono.columns:
                    theor_matched = mono.drop_duplicates(
                        subset=["Ion Type", "Ion Number"]
                    ).shape[0]
                else:
                    theor_matched = len(mono)
                scores["theor_pct"] = (theor_matched / theor_total * 100) if theor_total else 0.0

            # Coverage metrics
            cov_n, cov_d = _backbone_coverage(matched_data, peptide)
            scores["cov_pct"] = (cov_n / cov_d * 100) if cov_d else 0.0

            intact_n, intact_d = _backbone_coverage(matched_data, peptide, {"*", "^", "~"})
            scores["intact_pct"] = (intact_n / intact_d * 100) if intact_d else 0.0

            partial_n, partial_d = _backbone_coverage(matched_data, peptide, {"~"})
            scores["partial_pct"] = (partial_n / partial_d * 100) if partial_d else 0.0

        # ── Ion-type-filtered metrics ────────────────────────────────
        if matched_data is None or matched_data.empty:
            return scores

        atm = self.main_app.annotation_tab_manager
        filtered = atm.filter_data_for_scoring(
            matched_data, ion_types, include_neutral=True
        )
        if filtered.empty:
            return scores

        hs_result = atm.calculate_single_xtandem(filtered, ion_types)
        scores["xtandem"] = hs_result.get("xtandem", 0.0)

        if scoring_flags.get("consecutive_series"):
            consec = atm.calculate_consecutive_ion_series(filtered)
            scores["consecutive"] = consec.get("longest", 0) if consec else 0

        if scoring_flags.get("complementary_pairs"):
            comp = atm.calculate_complementary_pairs(filtered, pep_len)
            if comp:
                pairs = comp.get("pairs", 0)
                possible = comp.get("possible_pairs", 0)
                scores["complementary"] = f"{pairs}/{possible}"
                scores["comp_pairs"] = pairs

        return scores
