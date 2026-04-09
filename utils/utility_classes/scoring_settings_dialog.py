from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox,
    QLabel, QSpinBox, QDialogButtonBox,
)
from PyQt6.QtCore import Qt
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

        scoring = getattr(self.main_app, 'scoring_methods', {})

        self.cb_consecutive = QCheckBox("Consecutive Ion Series")
        self.cb_consecutive.setChecked(scoring.get('consecutive_series', False))
        self.cb_consecutive.setStyleSheet(EditorConstants.get_checkbox_style())
        methods_layout.addWidget(self.cb_consecutive)

        self.cb_complementary = QCheckBox("Complementary Pairs")
        self.cb_complementary.setChecked(scoring.get('complementary_pairs', False))
        self.cb_complementary.setStyleSheet(EditorConstants.get_checkbox_style())
        methods_layout.addWidget(self.cb_complementary)

        self.cb_morpheus = QCheckBox("Morpheus Score")
        self.cb_morpheus.setChecked(scoring.get('morpheus_score', False))
        self.cb_morpheus.setStyleSheet(EditorConstants.get_checkbox_style())
        methods_layout.addWidget(self.cb_morpheus)

        self.cb_length_dep = QCheckBox("Length-Dependent Normalized Score")
        self.cb_length_dep.setChecked(scoring.get('length_dependent_normalized_score', False))
        self.cb_length_dep.setStyleSheet(EditorConstants.get_checkbox_style())
        methods_layout.addWidget(self.cb_length_dep)

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
        self.max_charge_spin.setValue(getattr(self.main_app, 'scoring_max_charge', 0))
        self.max_charge_spin.setStyleSheet(EditorConstants.get_spinbox_style())
        self.max_charge_spin.setToolTip(
            "Limit which charge states contribute to ion counts and scoring.\n"
            "0 = no limit (all charges used).\n"
            "E.g. 2 = only +1 and +2 ions are counted for\n"
            "X!Tandem, Morpheus, etc."
        )
        charge_row.addWidget(self.max_charge_spin)
        params_layout.addLayout(charge_row)

        info = QLabel("0 = no limit. Applies to single annotation and bulk rescoring.")
        info.setStyleSheet(f"color: {EditorConstants.GRAY_500()}; font-style: italic;")
        info.setWordWrap(True)
        params_layout.addWidget(info)

        params_group.setLayout(params_layout)
        layout.addWidget(params_group)

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
        self.main_app.scoring_methods['consecutive_series'] = self.cb_consecutive.isChecked()
        self.main_app.scoring_methods['complementary_pairs'] = self.cb_complementary.isChecked()
        self.main_app.scoring_methods['morpheus_score'] = self.cb_morpheus.isChecked()
        self.main_app.scoring_methods['length_dependent_normalized_score'] = self.cb_length_dep.isChecked()
        self.main_app.scoring_max_charge = self.max_charge_spin.value()

        # Persist and recalculate
        if hasattr(self.main_app, '_save_scoring_settings'):
            self.main_app._save_scoring_settings()
        if hasattr(self.main_app, 'on_settings_changed'):
            self.main_app.on_settings_changed()

        self.accept()
