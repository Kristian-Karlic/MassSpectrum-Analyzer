import pandas as pd
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QApplication, QDialog, QDialogButtonBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from utils.style.style import StyleSheet, EditorConstants
from utils.peak_matching.peptide_fragmentation import fragment_and_match_peaks_cached
from utils.utilities import (
    DataGatherer, IonTypeGenerator, IonCollectionUtils, TableUtils,
)

logger = logging.getLogger(__name__)


def _get_labile_settings(app):
    """Read the labile/remainder/mod-NL checkbox states from *app*. Returns (bool, bool, bool)."""
    def _cb(attr):
        cb = getattr(app, attr, None)
        return cb.isChecked() if cb is not None else False
    return _cb('enable_labile_losses_cb'), _cb('enable_remainder_ions_cb'), _cb('enable_mod_nl_cb')


# ------------------------------------------------------------------
# Popup dialog for results
# ------------------------------------------------------------------
class RelocalisationResultsDialog(QDialog):
    """Resizable popup showing relocalisation results."""

    _COLUMNS = [
        "Position", "AA", "X!Tandem",
        "Consecutive", "Complementary", "Morpheus",
    ]

    def __init__(self, rows, peptide, mod_label, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Relocalisation Results  —  {mod_label}  on  {peptide}")
        self.setMinimumSize(620, 300)
        self.resize(700, max(300, 60 + 28 * len(rows)))
        self._setup_ui(rows)

    def _setup_ui(self, rows):
        layout = QVBoxLayout(self)

        self.table = QTableWidget(len(rows), len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
            self.table.setItem(r, 3, QTableWidgetItem(str(scores['consecutive'])))
            self.table.setItem(r, 4, QTableWidgetItem(str(scores['complementary'])))
            self.table.setItem(r, 5, QTableWidgetItem(f"{scores['morpheus']:.2f}"))

            if scores["xtandem"] > best_hs:
                best_hs = scores["hyperscore"]
                best_idx = r

        # Highlight best row
        highlight = QColor("#d4edda")
        for c in range(self.table.columnCount()):
            item = self.table.item(best_idx, c)
            if item:
                item.setBackground(highlight)

        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        self.setStyleSheet(StyleSheet.get_dialog_style())


# ------------------------------------------------------------------
# In-panel controls
# ------------------------------------------------------------------
class RelocalisationWidget(QWidget):
    """Test every valid position for a selected modification and rank by score."""

    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self._mod_entries = []  # [(mass, position), ...] parallel to combo index
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
        self.aa_input.setPlaceholderText("e.g. S,T  or  S,T,N")
        self.aa_input.setStyleSheet(EditorConstants.get_lineedit_style())
        self.aa_input.setToolTip(
            "Comma-separated amino acid letters where the\n"
            "modification is allowed to be placed."
        )
        aa_row.addWidget(self.aa_input, 1)
        layout.addLayout(aa_row)

        # --- Run button ---
        self.run_btn = QPushButton("Run Relocalisation")
        self.run_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        self.run_btn.clicked.connect(self.run_relocalisation)
        layout.addWidget(self.run_btn)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Refresh combo from current peptide mods
    # ------------------------------------------------------------------
    def refresh_modifications(self):
        """Populate the combo box from the current peptide's modifications."""
        self.mod_combo.clear()
        self._mod_entries.clear()

        mods = getattr(self.main_app, 'current_interactive_mods', None) or []
        peptide = self.main_app.peptide_input.text().strip() if hasattr(self.main_app, 'peptide_input') else ""
        central_db = getattr(self.main_app, 'central_mod_db', None)

        for mass, pos in mods:
            aa = peptide[pos - 1] if 0 < pos <= len(peptide) else "?"
            name = central_db.find_by_mass(mass) if central_db else None
            label = name if name else f"{mass:.4f}"
            self.mod_combo.addItem(f"{label} @ {aa}{pos}")
            self._mod_entries.append((mass, pos))

    # ------------------------------------------------------------------
    # Core relocalisation
    # ------------------------------------------------------------------
    def run_relocalisation(self):
        """Fragment the peptide with the mod at every allowed position and score."""
        if self.mod_combo.currentIndex() < 0:
            return

        peptide = self.main_app.peptide_input.text().strip()
        if not peptide:
            return

        sel_idx = self.mod_combo.currentIndex()
        sel_mass, sel_pos = self._mod_entries[sel_idx]

        # Parse allowed amino acids
        allowed = {c.strip().upper() for c in self.aa_input.text().split(",") if c.strip()}
        if not allowed:
            return

        # Base mods = everything except the selected one
        all_mods = getattr(self.main_app, 'current_interactive_mods', []) or []
        base_mods = [m for i, m in enumerate(all_mods) if i != sel_idx]

        # Find candidate positions (1-based)
        candidates = []
        for i, aa in enumerate(peptide):
            if aa.upper() in allowed:
                candidates.append((i + 1, aa.upper()))

        if not candidates:
            return

        # Gather fragmentation parameters once
        params = self._gather_fragmentation_params(peptide)
        if params is None:
            return

        ion_types = params["ion_types"]
        pep_len = len(peptide)
        scoring_flags = getattr(self.main_app, 'scoring_methods', {})

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = []
            for cand_pos, cand_aa in candidates:
                test_mods = base_mods + [(sel_mass, cand_pos)]
                enable_labile, enable_remainder, enable_mod_nl = _get_labile_settings(self.main_app)
                mod_nl = DataGatherer.build_mod_neutral_losses(
                    test_mods,
                    getattr(self.main_app, 'central_mod_db', None),
                    enable_labile=enable_labile,
                    enable_remainder=enable_remainder,
                    enable_mod_nl=enable_mod_nl,
                )

                matched_data, _ = fragment_and_match_peaks_cached(
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

                scores = self._compute_scores(matched_data, ion_types, pep_len, scoring_flags)
                is_original = (cand_pos == sel_pos)
                rows.append((cand_pos, cand_aa, scores, is_original))
        finally:
            QApplication.restoreOverrideCursor()

        if rows:
            central_db = getattr(self.main_app, 'central_mod_db', None)
            mod_name = central_db.find_by_mass(sel_mass) if central_db else None
            mod_label = mod_name if mod_name else f"{sel_mass:.4f}"
            dlg = RelocalisationResultsDialog(rows, peptide, mod_label, parent=self)
            dlg.exec()

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
    def _compute_scores(self, matched_data, ion_types, pep_len, scoring_flags):
        """Run all enabled scoring methods on *matched_data*."""
        scores = {
            "xtandem": 0.0,
            "consecutive": 0,
            "complementary": "0/0",
            "morpheus": 0.0,
        }
        if matched_data is None or matched_data.empty:
            return scores

        atm = self.main_app.annotation_tab_manager

        filtered = atm.filter_data_for_scoring(matched_data, ion_types, include_neutral=True)
        if filtered.empty:
            return scores

        # X!Tandem (always)
        hs_result = atm.calculate_single_xtandem(filtered, ion_types)
        scores["xtandem"] = hs_result.get("xtandem", 0.0)

        # Consecutive
        if scoring_flags.get("consecutive_series"):
            consec = atm.calculate_consecutive_ion_series(filtered)
            scores["consecutive"] = consec.get("longest", 0) if consec else 0

        # Complementary
        if scoring_flags.get("complementary_pairs"):
            comp = atm.calculate_complementary_pairs(filtered, pep_len)
            if comp:
                scores["complementary"] = f"{comp.get('pairs', 0)}/{comp.get('possible_pairs', 0)}"

        # Morpheus
        if scoring_flags.get("morpheus_score"):
            try:
                matched_mask = (
                    (matched_data["Matched"].notna())
                    & (matched_data["Matched"] != "No Match")
                )
                iso_col = "Isotope" if "Isotope" in matched_data.columns else None
                if iso_col:
                    mono_mask = matched_mask & (
                        pd.to_numeric(matched_data[iso_col], errors="coerce").fillna(0).astype(int) == 0
                    )
                else:
                    mono_mask = matched_mask
                n_mono = int(mono_mask.sum())
                int_col = "intensity" if "intensity" in matched_data.columns else "Intensity"
                total_int = matched_data[int_col].sum()
                matched_int = matched_data.loc[matched_mask, int_col].sum()
                frac = (matched_int / total_int) if total_int > 0 else 0.0
                scores["morpheus"] = n_mono + frac
            except Exception:
                pass

        return scores
