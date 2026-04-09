"""
PSMUtilsFormatDialog
====================
Fallback dialog shown when automatic format detection fails.

Presents the user with a list of psm_utils-supported formats and lets them
pick the correct one for each unrecognised file (or apply one choice to all).
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QDialogButtonBox, QFrame, QScrollArea,
    QWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from .psm_utils_normalizer import FORMAT_LABELS, available_formats


class PSMUtilsFormatDialog(QDialog):
    """Dialog for selecting the psm_utils format for one or more unrecognised files.

    Parameters
    ----------
    file_names : list[str]
        Base names of the files that could not be auto-detected.
    parent : QWidget, optional
    """

    def __init__(self, file_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Search File Format")
        self.setMinimumWidth(520)
        self.setModal(True)

        self._file_names = file_names
        self._format_combos: list[QComboBox] = []
        self._available = available_formats()

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Header
        header = QLabel(
            "The following file(s) could not be automatically identified.\n"
            "Please select the correct format for each:"
        )
        header.setWordWrap(True)
        root.addWidget(header)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        if not self._available:
            warn = QLabel(
                "No psm_utils readers are available.\n"
                "Please install psm_utils: pip install psm-utils"
            )
            warn.setStyleSheet("color: #cc4400;")
            root.addWidget(warn)
        else:
            # Scroll area in case there are many files
            scroll_widget = QWidget()
            scroll_layout = QVBoxLayout(scroll_widget)
            scroll_layout.setSpacing(8)

            for fname in self._file_names:
                row = self._make_file_row(fname)
                scroll_layout.addLayout(row)

            scroll_area = QScrollArea()
            scroll_area.setWidget(scroll_widget)
            scroll_area.setWidgetResizable(True)
            scroll_area.setMaximumHeight(260)
            root.addWidget(scroll_area)

            # "Apply same format to all" checkbox (only useful for multiple files)
            if len(self._file_names) > 1:
                self._apply_all_cb = QCheckBox("Apply same format to all files")
                self._apply_all_cb.stateChanged.connect(self._on_apply_all_toggled)
                root.addWidget(self._apply_all_cb)
            else:
                self._apply_all_cb = None

        # Separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line2)

        # Skip-unknown hint
        skip_hint = QLabel(
            "Files with no format selected will be skipped."
        )
        skip_hint.setStyleSheet("color: gray; font-style: italic;")
        root.addWidget(skip_hint)

        # Button box
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _make_file_row(self, fname: str) -> QHBoxLayout:
        row = QHBoxLayout()

        label = QLabel(fname)
        label.setMinimumWidth(200)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bold = QFont()
        bold.setBold(True)
        label.setFont(bold)
        row.addWidget(label)

        combo = QComboBox()
        combo.addItem("— skip this file —", userData=None)
        for key in self._available:
            combo.addItem(FORMAT_LABELS.get(key, key), userData=key)
        combo.setMinimumWidth(220)
        row.addWidget(combo)

        self._format_combos.append(combo)
        return row

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_apply_all_toggled(self, state: int):
        if state == Qt.CheckState.Checked.value and self._format_combos:
            first_index = self._format_combos[0].currentIndex()
            for combo in self._format_combos[1:]:
                combo.setCurrentIndex(first_index)
                combo.setEnabled(False)
            self._format_combos[0].currentIndexChanged.connect(
                self._sync_all_combos
            )
        else:
            for combo in self._format_combos[1:]:
                combo.setEnabled(True)
            try:
                self._format_combos[0].currentIndexChanged.disconnect(
                    self._sync_all_combos
                )
            except TypeError:
                pass

    def _sync_all_combos(self, index: int):
        for combo in self._format_combos[1:]:
            combo.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # Result accessor
    # ------------------------------------------------------------------

    def get_selections(self) -> dict[str, str | None]:
        """Return ``{filename: format_key_or_None}`` for every file shown."""
        result: dict[str, str | None] = {}
        for fname, combo in zip(self._file_names, self._format_combos):
            result[fname] = combo.currentData()  # None if "skip" selected
        return result
