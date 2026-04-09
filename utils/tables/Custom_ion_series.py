from PyQt6.QtWidgets import (
    QStyledItemDelegate, QComboBox, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QCheckBox, QGridLayout, QGroupBox,
    QScrollArea, QWidget, QFrame
)
from PyQt6.QtCore import Qt
from utils.style.style import DelegateStyles, EditorConstants


# All 20 standard amino acids
AMINO_ACIDS = [
    'A', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'K', 'L',
    'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'V', 'W', 'Y'
]


class RestrictionDialog(QDialog):
    """Dialog for configuring amino acid restrictions for custom ion series."""

    def __init__(self, current_restriction="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Restriction")
        self.resize(380, 460)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
            }}
            QGroupBox {{
                color: {EditorConstants.TEXT_COLOR()};
                border: 1px solid {EditorConstants.BORDER_COLOR()};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 12px;
                {EditorConstants.get_font_string()}
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
            QCheckBox {{
                color: {EditorConstants.TEXT_COLOR()};
                spacing: 4px;
                {EditorConstants.get_font_string()}
            }}
            QLabel {{
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
            }}
        """)

        self._build_ui()
        self._parse_restriction(current_restriction)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Termini group ---
        termini_group = QGroupBox("Terminus Options")
        termini_layout = QVBoxLayout(termini_group)

        info_label = QLabel(
            "Selecting a terminus means the restriction applies\n"
            "to the full peptide sequence rather than each fragment."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(f"color: {EditorConstants.DISABLED_COLOR()}; font-size: 11px;")
        termini_layout.addWidget(info_label)

        self.c_term_cb = QCheckBox("C-terminus (full peptide for y/x/z ions)")
        self.n_term_cb = QCheckBox("N-terminus (full peptide for b/a/c ions)")
        termini_layout.addWidget(self.c_term_cb)
        termini_layout.addWidget(self.n_term_cb)
        layout.addWidget(termini_group)

        # --- Amino acid restriction group ---
        aa_group = QGroupBox("Amino Acid Requirements")
        aa_layout = QVBoxLayout(aa_group)

        aa_info = QLabel("Select amino acids that must be present in the fragment sequence (any one is sufficient):")
        aa_info.setWordWrap(True)
        aa_info.setStyleSheet(f"color: {EditorConstants.DISABLED_COLOR()}; font-size: 11px;")
        aa_layout.addWidget(aa_info)

        # Scrollable grid of amino acids
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background-color: {EditorConstants.BACKGROUND_COLOR()};")

        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(4)

        self.aa_checkboxes = {}

        for i, aa in enumerate(AMINO_ACIDS):
            row, col = divmod(i, 5)

            cb = QCheckBox(aa)

            self.aa_checkboxes[aa] = cb

            grid_layout.addWidget(cb, row, col)

        scroll.setWidget(grid_widget)
        aa_layout.addWidget(scroll)
        layout.addWidget(aa_group)

        # --- Clear / OK / Cancel ---
        btn_layout = QHBoxLayout()

        clear_btn = QPushButton("Clear All")
        clear_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        clear_btn.clicked.connect(self._clear_all)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------ #
    #  Serialization helpers – compact string format
    #   Examples:  ""  |  "E"  |  "E,D"  |  "C-term"  |  "N-term,E,D"
    # ------------------------------------------------------------------ #
    def _parse_restriction(self, text: str):
        """Populate the UI from a restriction string."""
        if not text or not isinstance(text, str):
            return
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if part == "C-term":
                self.c_term_cb.setChecked(True)
            elif part == "N-term":
                self.n_term_cb.setChecked(True)
            else:
                # New format: single letter like "E" or "D"
                aa = part.upper()
                if aa in self.aa_checkboxes:
                    self.aa_checkboxes[aa].setChecked(True)
                else:
                    # Backwards compatibility: old format like "2E"
                    try:
                        aa = part[-1].upper()
                        if aa in self.aa_checkboxes:
                            self.aa_checkboxes[aa].setChecked(True)
                    except IndexError:
                        pass

    def get_restriction_string(self) -> str:
        """Build the compact restriction string from the current UI state."""
        parts = []
        if self.c_term_cb.isChecked():
            parts.append("C-term")
        if self.n_term_cb.isChecked():
            parts.append("N-term")
        for aa in AMINO_ACIDS:
            if self.aa_checkboxes[aa].isChecked():
                parts.append(aa)
        return ",".join(parts)

    def _clear_all(self):
        """Reset every control."""
        self.c_term_cb.setChecked(False)
        self.n_term_cb.setChecked(False)
        for aa in AMINO_ACIDS:
            self.aa_checkboxes[aa].setChecked(False)


class RestrictionDelegate(QStyledItemDelegate):
    """Table delegate that opens a RestrictionDialog on edit."""

    def createEditor(self, parent, option, index):
        # We don't create an inline editor; we launch a dialog instead.
        return None

    def editorEvent(self, event, model, option, index):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonDblClick:
            current_value = model.data(index, Qt.ItemDataRole.EditRole) or ""
            dlg = RestrictionDialog(current_value, option.widget)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                model.setData(index, dlg.get_restriction_string(), Qt.ItemDataRole.EditRole)
            return True
        return False


class BaseIonComboDelegate(QStyledItemDelegate):
    def __init__(self, base_ions, parent=None):
        super().__init__(parent)
        self.base_ions = base_ions  # e.g. ["b","y","a","c","x","z"]
    
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems(self.base_ions)
        DelegateStyles.apply_combobox_style(combo)
        return combo
    
    def setEditorData(self, editor, index):
        current_text = index.model().data(index, Qt.ItemDataRole.EditRole)
        idx = editor.findText(current_text)
        if idx >= 0:
            editor.setCurrentIndex(idx)
    
    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
    
    def updateEditorGeometry(self, editor, option, index):
        """Keep editor within cell bounds"""
        editor.setGeometry(option.rect)