"""Dialog for handling unlocalized ptm_result masses from pepXML files.

When open-search pepXML results contain ``<ptm_result>`` elements whose
``localization`` attribute is empty, the user must decide how to handle them:
either assign the PTM mass to the first occurrence of a chosen amino acid in
each peptide, or ignore those PSMs entirely.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from PyQt6.QtCore import Qt

from utils.style.style import EditorConstants, StyleSheet
from utils.tables.Custom_ion_series import AMINO_ACIDS


class PtmResultLocalizationDialog(QDialog):
    """Ask the user how to handle unlocalized open-search PTM masses.

    For each unique PTM mass that has no localization position, the user
    can either choose a target amino acid (the mass will be placed on the
    first occurrence in the peptide) or choose to ignore those PSMs.
    """

    def __init__(self, unlocalized_masses: dict[float, int], parent=None):
        """
        Parameters
        ----------
        unlocalized_masses : dict[float, int]
            Maps each unique ``ptm_mass`` to the number of affected PSMs.
        parent : QWidget, optional
        """
        super().__init__(parent)
        self._masses = sorted(unlocalized_masses.keys())
        self._counts = unlocalized_masses
        self._combos: list[QComboBox] = []
        self.result_prefs: dict[float, str | None] = {}

        self.setWindowTitle("Unlocalized PTM Results")
        self.setMinimumSize(560, 340)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            "The following PTM masses (from open-search ptm_result data) could "
            "not be localized to a specific residue.\n\n"
            "For each mass, select a target amino acid — the modification will "
            "be placed on the first occurrence of that residue in each peptide. "
            "If the chosen residue is not present, that PSM will be skipped.\n\n"
            'Or choose "Ignore" to discard PSMs with that unlocalized mass.'
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {EditorConstants.TEXT_COLOR()}; "
            f"{EditorConstants.get_font_string()}"
        )
        layout.addWidget(info)

        # Table ---------------------------------------------------------------
        self.table = QTableWidget(len(self._masses), 3)
        self.table.setHorizontalHeaderLabels(
            [
                "PTM Mass (Da)",
                "Affected PSMs",
                "Action",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Fixed,
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Fixed,
        )
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 160)
        StyleSheet.apply_table_styling(self.table)
        self.table.setAlternatingRowColors(False)

        for row, ptm_mass in enumerate(self._masses):
            mass_item = QTableWidgetItem(f"{ptm_mass:.5f}")
            mass_item.setFlags(mass_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, mass_item)

            count_item = QTableWidgetItem(str(self._counts[ptm_mass]))
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, 1, count_item)

            combo = QComboBox()
            combo.addItem("Ignore")
            for aa in AMINO_ACIDS:
                combo.addItem(aa)
            self.table.setCellWidget(row, 2, combo)
            self._combos.append(combo)

        layout.addWidget(self.table)

        # Buttons -------------------------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        ok_btn = QPushButton("Continue")
        ok_btn.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
        ok_btn.clicked.connect(self._on_continue)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _on_continue(self):
        self.result_prefs = {}
        for row, ptm_mass in enumerate(self._masses):
            text = self._combos[row].currentText()
            if text == "Ignore":
                self.result_prefs[ptm_mass] = None
            else:
                self.result_prefs[ptm_mass] = text
        self.accept()

    def get_preferences(self) -> dict[float, str | None]:
        """Return user choices.

        Returns
        -------
        dict[float, str | None]
            Maps each PTM mass to a single-letter amino acid code (place on
            first occurrence in the peptide), or ``None`` to ignore PSMs
            carrying that mass.
        """
        return self.result_prefs
