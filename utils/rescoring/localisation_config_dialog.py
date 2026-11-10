import ast
from collections import Counter

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QCheckBox,
    QLineEdit,
    QWidget,
    QHeaderView,
)
from PyQt6.QtCore import Qt
from utils.style.style import StyleSheet, EditorConstants

_FIXED = "Fixed"
_RELOCALISE = "Relocalise"

# Suggested residues when a modification is first switched to Relocalise
_DEFAULT_AA_BY_NAME = {
    "phospho": "S,T,Y",
    "oxidation": "M",
    "acetylation": "K",
    "acetyl": "K",
    "methylation": "K,R",
    "dimethylation": "K,R",
    "trimethylation": "K",
    "deamidation": "N,Q",
    "hexnac": "S,T",
    "sulfo": "Y",
}


def collect_modification_masses(merged_df):
    """Count PSMs per unique modification mass (rounded to 4 dp)."""
    counts = Counter()
    if merged_df is None or "Parsed Modifications" not in merged_df.columns:
        return counts
    for mods in merged_df["Parsed Modifications"]:
        if isinstance(mods, str):
            try:
                mods = ast.literal_eval(mods) if mods else None
            except Exception:
                continue
        if not mods or isinstance(mods, float):
            continue
        for mass in {round(float(m[0]), 4) for m in mods}:
            counts[mass] += 1
    return counts


class LocalisationConfigDialog(QDialog):
    """Choose which modifications are fixed and which may be relocalised."""

    _COLUMNS = ["Modification", "Mass", "PSMs", "Mode", "Allowed AA", "Stack"]

    def __init__(self, mass_counts, central_mod_db=None, current_rules=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Site Localisation - Modifications")
        self.setMinimumSize(620, 360)
        self._central_mod_db = central_mod_db
        self._current_rules = current_rules or {}
        self._masses = sorted(mass_counts, key=lambda m: -mass_counts[m])
        self._init_ui(mass_counts)

    def _init_ui(self, mass_counts):
        layout = QVBoxLayout(self)

        info = QLabel(
            "Fixed modifications stay where the search engine placed them. "
            "Relocalised modifications are tried on every allowed residue "
            "(comma-separated, blank = any residue) and the best-scoring site "
            "by Rescore is kept. Stack lets several copies of a modification share "
            "one residue (e.g. two glycans that are really one larger glycan). "
            "N-terminal modifications appear at position 1 and should normally "
            "stay Fixed."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {EditorConstants.GRAY_500()}; font-style: italic;")
        layout.addWidget(info)

        self.table = QTableWidget(len(self._masses), len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        StyleSheet.apply_table_styling(self.table)

        self._mode_combos = []
        self._aa_edits = []
        self._stack_checks = []
        for row, mass in enumerate(self._masses):
            name = self._mod_name(mass)
            for col, text in enumerate((name, f"{mass:.4f}", str(mass_counts[mass]))):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)

            combo = QComboBox()
            combo.addItems([_FIXED, _RELOCALISE])
            combo.setStyleSheet(EditorConstants.get_combobox_style())
            aa_edit = QLineEdit()
            aa_edit.setPlaceholderText("any residue")
            aa_edit.setStyleSheet(EditorConstants.get_lineedit_style())

            stack_check = QCheckBox()
            stack_check.setStyleSheet(EditorConstants.get_checkbox_style())
            stack_check.setToolTip("Allow several copies of this modification on one residue")

            if mass in self._current_rules:
                combo.setCurrentText(_RELOCALISE)
                aa_edit.setText(self._current_rules[mass]["aa"])
                stack_check.setChecked(self._current_rules[mass]["stack"])
            else:
                aa_edit.setEnabled(False)
                stack_check.setEnabled(False)
                stack_check.setChecked(self._is_glycan(name))

            combo.currentTextChanged.connect(
                lambda text, e=aa_edit, s=stack_check, n=name: self._on_mode_changed(
                    text, e, s, n
                )
            )
            self.table.setCellWidget(row, 3, combo)
            self.table.setCellWidget(row, 4, aa_edit)
            self.table.setCellWidget(row, 5, self._centered(stack_check))
            self._mode_combos.append(combo)
            self._aa_edits.append(aa_edit)
            self._stack_checks.append(stack_check)

        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        ok_button = QPushButton("OK")
        ok_button.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        ok_button.clicked.connect(self.accept)
        button_layout.addWidget(ok_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        self.setStyleSheet(StyleSheet.get_dialog_style())

    def _mod_name(self, mass):
        name = self._central_mod_db.find_by_mass(mass) if self._central_mod_db else None
        return name if name else f"{mass:+.4f}"

    def _is_glycan(self, name):
        # Glycans in user databases are often only flagged labile, not is_glycan
        entry = self._central_mod_db.get_entry(name) if self._central_mod_db else None
        return bool(entry and (entry.get("is_glycan") or entry.get("labile_loss")))

    @staticmethod
    def _centered(widget):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(widget)
        return container

    @staticmethod
    def _on_mode_changed(text, aa_edit, stack_check, name):
        relocalise = text == _RELOCALISE
        aa_edit.setEnabled(relocalise)
        stack_check.setEnabled(relocalise)
        if relocalise and not aa_edit.text():
            aa_edit.setText(_DEFAULT_AA_BY_NAME.get(name.lower(), ""))

    def rules(self):
        """{rounded_mass: {"aa": str, "stack": bool}} for mods set to Relocalise."""
        rules = {}
        for mass, combo, aa_edit, stack_check in zip(
            self._masses, self._mode_combos, self._aa_edits, self._stack_checks
        ):
            if combo.currentText() == _RELOCALISE:
                aa = ",".join(
                    c.strip().upper() for c in aa_edit.text().split(",") if c.strip()
                )
                rules[mass] = {"aa": aa, "stack": stack_check.isChecked()}
        return rules
