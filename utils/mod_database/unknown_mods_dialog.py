from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)
from PyQt6.QtCore import Qt
from utils.style.style import EditorConstants, StyleSheet


class UnknownModificationsDialog(QDialog):
    """Dialog shown when unknown modification names are detected.

    Displays a table of modification names that have no mass in the
    database.  The user must provide a mass (Da) for each before the
    data-preparation pipeline can continue.
    """

    def __init__(self, unknown_mods: set, engine_name: str, parent=None):
        super().__init__(parent)
        self.unknown_mods = sorted(unknown_mods)
        self.engine_name = engine_name
        self.result_masses: dict[str, float] = {}

        self.setWindowTitle(f"Unknown Modifications - {engine_name}")
        self.setMinimumSize(500, 400)
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            f"The following {self.engine_name} modifications were not found "
            "in the database.\nPlease provide the monoisotopic mass (Da) for "
            "each modification.\nThese values will be saved for future use.\n\n"
            "If you do not know the mass, enter 0 to treat the modification "
            "as having no mass offset."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {EditorConstants.TEXT_COLOR()}; "
                           f"{EditorConstants.get_font_string()}")
        layout.addWidget(info)

        # Table -----------------------------------------------------------
        self.table = QTableWidget(len(self.unknown_mods), 2)
        self.table.setHorizontalHeaderLabels(["Modification Name", "Mass (Da)"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(1, 150)
        StyleSheet.apply_table_styling(self.table)
        self.table.setAlternatingRowColors(False)

        for row, mod_name in enumerate(self.unknown_mods):
            name_item = QTableWidgetItem(mod_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(""))

        layout.addWidget(self.table)

        # Buttons ---------------------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("Save and Continue")
        save_btn.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    def _on_save(self):
        self.result_masses = {}
        errors = []

        for row in range(self.table.rowCount()):
            mod_name = self.table.item(row, 0).text()
            mass_item = self.table.item(row, 1)
            mass_text = mass_item.text().strip() if mass_item else ""

            if not mass_text:
                errors.append(f"Missing mass for: {mod_name}")
                continue

            try:
                mass = float(mass_text)
                self.result_masses[mod_name] = mass
            except ValueError:
                errors.append(f"Invalid mass for {mod_name}: '{mass_text}'")

        if errors:
            QMessageBox.warning(
                self, "Validation Error",
                "Please fix the following:\n\n" + "\n".join(errors)
            )
            return

        self.accept()

    def get_masses(self) -> dict[str, float]:
        return self.result_masses
