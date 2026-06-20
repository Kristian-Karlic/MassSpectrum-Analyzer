from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QCheckBox,
    QLabel,
    QSpinBox,
    QDialogButtonBox,
)
from utils.style.style import EditorConstants, StyleSheet


class ScoringSettingsDialog(QDialog):
    """Dialog for configuring scoring methods and scoring parameters.

    Reads current values from the parent app on open, writes them back
    on accept, and triggers a settings save + recalculation.
    """

    def __init__(self, main_app, parent=None):
        super().__init__(parent or main_app)
        self.main_app = main_app
        self.setWindowTitle("Scoring Settings")
        self.setMinimumWidth(380)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # --- Scoring Methods group ---
        methods_group = QGroupBox("Scoring Methods")
        methods_group.setStyleSheet(EditorConstants.get_groupbox_style())
        methods_layout = QVBoxLayout()

        hs_label = QLabel("X!Tandem Hyperscore (always on)")
        hs_label.setEnabled(False)
        hs_label.setStyleSheet(StyleSheet.get_label_style())
        methods_layout.addWidget(hs_label)

        scoring = getattr(self.main_app, "scoring_methods", {})

        self.cb_consecutive = QCheckBox("Consecutive Ion Series")
        self.cb_consecutive.setChecked(scoring.get("consecutive_series", False))
        self.cb_consecutive.setStyleSheet(EditorConstants.get_checkbox_style())
        methods_layout.addWidget(self.cb_consecutive)

        self.cb_complementary = QCheckBox("Complementary Pairs")
        self.cb_complementary.setChecked(scoring.get("complementary_pairs", False))
        self.cb_complementary.setStyleSheet(EditorConstants.get_checkbox_style())
        methods_layout.addWidget(self.cb_complementary)

        methods_group.setLayout(methods_layout)
        layout.addWidget(methods_group)

        # --- Scoring Parameters group ---
        params_group = QGroupBox("Scoring Parameters")
        params_group.setStyleSheet(EditorConstants.get_groupbox_style())
        params_layout = QVBoxLayout()

        charge_row = QHBoxLayout()
        charge_label = QLabel("Max Charge for Scoring:")
        charge_label.setStyleSheet(StyleSheet.get_label_style())
        charge_row.addWidget(charge_label)

        self.max_charge_spin = QSpinBox()
        self.max_charge_spin.setRange(0, 10)
        self.max_charge_spin.setValue(getattr(self.main_app, "scoring_max_charge", 0))
        self.max_charge_spin.setStyleSheet(EditorConstants.get_spinbox_style())
        self.max_charge_spin.setToolTip(
            "Limit which charge states contribute to ion counts and scoring.\n"
            "0 = no limit (all charges used).\n"
            "E.g. 2 = only +1 and +2 ions are counted for\n"
            "X!Tandem"
        )
        charge_row.addWidget(self.max_charge_spin)
        params_layout.addLayout(charge_row)

        info = QLabel("0 = no limit. Applies to single annotation and bulk rescoring.")
        info.setStyleSheet(f"color: {EditorConstants.GRAY_500()}; font-style: italic;")
        info.setWordWrap(True)
        params_layout.addWidget(info)

        self.cb_nl_in_count = QCheckBox(
            "Count neutral loss species in ion position count"
        )
        self.cb_nl_in_count.setChecked(
            getattr(self.main_app, "scoring_nl_in_count", False)
        )
        self.cb_nl_in_count.setStyleSheet(EditorConstants.get_checkbox_style())
        self.cb_nl_in_count.setToolTip(
            "When checked, neutral loss ions (e.g. y7-H2O) count toward\n"
            "the unique ion position count (factorials) in X!Tandem scoring.\n"
            "When unchecked, their intensities still contribute but they\n"
            "do not count as a unique position.\n"
            "Does not affect modification neutral losses or remainder ions."
        )
        params_layout.addWidget(self.cb_nl_in_count)

        self.cb_calculate_isotopes = QCheckBox("Calculate and match isotope peaks")
        self.cb_calculate_isotopes.setChecked(
            getattr(self.main_app, "calculate_isotopes", False)
        )
        self.cb_calculate_isotopes.setStyleSheet(EditorConstants.get_checkbox_style())
        self.cb_calculate_isotopes.setToolTip(
            "When enabled, calculates isotope peaks M+1 through M+N for all ions.\n"
            "Matched isotope peaks contribute to annotated TIC but NOT to ion counts or scoring.\n"
            "Note: The M-1 isotope for z+1 and c ions (used for migration tracking) "
            "is always calculated regardless of this setting."
        )
        params_layout.addWidget(self.cb_calculate_isotopes)

        isotope_max_row = QHBoxLayout()
        isotope_max_label = QLabel("Max isotopes (M+N):")
        isotope_max_label.setStyleSheet(StyleSheet.get_label_style())
        isotope_max_row.addWidget(isotope_max_label)

        self.isotope_max_spin = QSpinBox()
        self.isotope_max_spin.setRange(1, 4)
        self.isotope_max_spin.setValue(getattr(self.main_app, "isotope_max", 4))
        self.isotope_max_spin.setStyleSheet(EditorConstants.get_spinbox_style())
        self.isotope_max_spin.setEnabled(self.cb_calculate_isotopes.isChecked())
        isotope_max_row.addWidget(self.isotope_max_spin)
        params_layout.addLayout(isotope_max_row)

        self.cb_calculate_isotopes.toggled.connect(self.isotope_max_spin.setEnabled)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

        # --- Post-Processing group ---
        postproc_group = QGroupBox("Post-Processing")
        postproc_group.setStyleSheet(EditorConstants.get_groupbox_style())
        postproc_layout = QVBoxLayout()

        self.cb_mokapot = QCheckBox("Mokapot FDR Control (q-values && PEP)")
        self.cb_mokapot.setChecked(scoring.get("mokapot_fdr", False))
        self.cb_mokapot.setStyleSheet(EditorConstants.get_checkbox_style())
        self.cb_mokapot.setToolTip(
            "Run mokapot (Percolator algorithm) after rescoring to compute\n"
            "calibrated q-values and posterior error probabilities (PEP)\n"
            "for FDR control. Requires decoy detection to be enabled."
        )
        postproc_layout.addWidget(self.cb_mokapot)

        mokapot_info = QLabel(
            "Requires decoy detection. Uses semi-supervised learning\n"
            "on all numeric rescoring features for FDR estimation."
        )
        mokapot_info.setStyleSheet(
            f"color: {EditorConstants.GRAY_500()}; font-style: italic;"
        )
        mokapot_info.setWordWrap(True)
        postproc_layout.addWidget(mokapot_info)

        postproc_group.setLayout(postproc_layout)
        layout.addWidget(postproc_group)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setStyleSheet(StyleSheet.get_dialog_style())

    def _on_accept(self):
        """Write values back to the main app, persist, and recalculate."""
        self.main_app.scoring_methods["consecutive_series"] = (
            self.cb_consecutive.isChecked()
        )
        self.main_app.scoring_methods["complementary_pairs"] = (
            self.cb_complementary.isChecked()
        )
        self.main_app.scoring_methods["mokapot_fdr"] = self.cb_mokapot.isChecked()
        self.main_app.scoring_max_charge = self.max_charge_spin.value()
        self.main_app.scoring_nl_in_count = self.cb_nl_in_count.isChecked()
        self.main_app.calculate_isotopes = self.cb_calculate_isotopes.isChecked()
        self.main_app.isotope_max = self.isotope_max_spin.value()

        # Persist and recalculate
        if hasattr(self.main_app, "_save_scoring_settings"):
            self.main_app._save_scoring_settings()
        if hasattr(self.main_app, "on_settings_changed"):
            self.main_app.on_settings_changed()

        self.accept()
