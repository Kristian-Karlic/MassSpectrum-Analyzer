"""Dialog for customising per-ion-type text annotation visibility and colour."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QHBoxLayout, QColorDialog,
    QAbstractItemView, QStyledItemDelegate, QStyle,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from utils.style.style import StyleSheet

# ── Ion catalogue ──────────────────────────────────────────────────
# (settings_key, display_name, default_colour)
# default_colour=None means "inherits from base ion / varies"
ION_CATALOGUE = [
    # Normal ions — colours match PlotConstants.ION_FRAGMENT_OFFSETS
    ("y", "y", "red"),
    ("b", "b", "blue"),
    ("a", "a", "purple"),
    ("x", "x", "brown"),
    ("z", "z", "orange"),
    ("z+1", "z+1", "orange"),
    ("c", "c", "green"),
    ("c-1", "c-1", "green"),
    ("d", "d", "teal"),
    ("w", "w", "darkcyan"),
    ("v", "v", "magenta"),
    ("MH", "MH", "black"),
    # Neutral-loss variants
    ("y-H2O", "y–H₂O", "blue"),
    ("b-H2O", "b–H₂O", "blue"),
    ("a-H2O", "a–H₂O", "purple"),
    ("y-NH3", "y–NH₃", "red"),
    ("b-NH3", "b–NH₃", "blue"),
    ("a-NH3", "a–NH₃", "purple"),
    ("b-SOCH4", "b–SOCH₄", "blue"),
    ("y-SOCH4", "y–SOCH₄", "red"),
    ("b-H3PO4", "b–H₃PO₄", "blue"),
    ("y-H3PO4", "y–H₃PO₄", "red"),
    ("a-H3PO4", "a–H₃PO₄", "purple"),
    ("MH-H2O", "MH–H₂O", "black"),
    ("MH-NH3", "MH–NH₃", "black"),
    ("d-H2O", "d–H₂O", "teal"),
    ("d-NH3", "d–NH₃", "teal"),
    ("w-H2O", "w–H₂O", "darkcyan"),
    ("w-NH3", "w–NH₃", "darkcyan"),
    ("v-H2O", "v–H₂O", "magenta"),
    ("v-NH3", "v–NH₃", "magenta"),
    # Mod-NL / Remainder / Labile
    ("ModNL", "Mod NL (*)", None),
    ("LabileLoss", "Labile Loss (~)", None),
    ("ModRM", "Remainder (^)", None),
    # Others
    ("Internal", "Internal", None),
    ("Custom", "Custom", None),
    ("Diagnostic", "Diagnostic", None),
]

_COL_ION = 0
_COL_VIS = 1
_COL_CLR = 2


class _VisibilityDelegate(QStyledItemDelegate):
    """Paints green/red Yes/No background for the Visible column."""

    def paint(self, painter, option, index):
        painter.save()
        checked = index.data(Qt.ItemDataRole.UserRole)
        if checked is True:
            painter.fillRect(option.rect, QColor("#4CAF50"))
        else:
            painter.fillRect(option.rect, QColor("#F44336"))
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(255, 255, 255, 60))
        text = "Yes" if checked else "No"
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class _ColourDelegate(QStyledItemDelegate):
    """Paints the colour swatch for the Colour column."""

    def paint(self, painter, option, index):
        painter.save()
        colour = index.data(Qt.ItemDataRole.UserRole)
        if colour:
            painter.fillRect(option.rect, QColor(colour))
        else:
            # "inherits" — light grey with text
            painter.fillRect(option.rect, QColor("#3C3C3C"))
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(255, 255, 255, 60))
        text = colour if colour else "default"
        pen_col = QColor("#FFFFFF") if colour else QColor("#999999")
        painter.setPen(pen_col)
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class AnnotationSettingsDialog(QDialog):
    """Table-based dialog for tweaking per-ion-type annotation visibility
    and peak colour."""

    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        self.setWindowTitle("Annotation Display Settings")
        self.resize(440, 620)
        self._setup_ui()
        self._populate()

    # ── UI ──────────────────────────────────────────────────────
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget(len(ION_CATALOGUE), 3)
        self.table.setHorizontalHeaderLabels(["Ion Type", "Text Label", "Colour"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_ION, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_VIS, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(_COL_VIS, 90)
        header.setSectionResizeMode(_COL_CLR, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(_COL_CLR, 110)

        self._vis_delegate = _VisibilityDelegate(self.table)
        self.table.setItemDelegateForColumn(_COL_VIS, self._vis_delegate)
        self._clr_delegate = _ColourDelegate(self.table)
        self.table.setItemDelegateForColumn(_COL_CLR, self._clr_delegate)

        StyleSheet.apply_table_styling(self.table)
        self.table.setAlternatingRowColors(False)

        self.table.doubleClicked.connect(self._on_double_click)

        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()
        show_all_btn = QPushButton("Show All")
        show_all_btn.clicked.connect(self._show_all)
        hide_all_btn = QPushButton("Hide All")
        hide_all_btn.clicked.connect(self._hide_all)
        reset_btn = QPushButton("Reset Colours")
        reset_btn.clicked.connect(self._reset_colours)
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(show_all_btn)
        btn_layout.addWidget(hide_all_btn)
        btn_layout.addWidget(reset_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    # ── Populate rows from current settings ────────────────────
    def _populate(self):
        settings = self.viewer.annotation_display_settings
        for row, (key, display, default_clr) in enumerate(ION_CATALOGUE):
            cur = settings.get(key, {})

            # Ion name (read-only)
            name_item = QTableWidgetItem(display)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, _COL_ION, name_item)

            # Visible toggle
            vis = cur.get("visible", True)
            vis_item = QTableWidgetItem("Yes" if vis else "No")
            vis_item.setData(Qt.ItemDataRole.UserRole, vis)
            vis_item.setFlags(vis_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, _COL_VIS, vis_item)

            # Colour
            clr = cur.get("color") or default_clr
            clr_item = QTableWidgetItem(clr or "default")
            clr_item.setData(Qt.ItemDataRole.UserRole, clr)
            clr_item.setFlags(clr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, _COL_CLR, clr_item)

    # ── Interactions ───────────────────────────────────────────
    def _on_double_click(self, index):
        row, col = index.row(), index.column()
        if col == _COL_VIS:
            item = self.table.item(row, _COL_VIS)
            cur = item.data(Qt.ItemDataRole.UserRole) is True
            new_val = not cur
            item.setData(Qt.ItemDataRole.UserRole, new_val)
            item.setText("Yes" if new_val else "No")
        elif col == _COL_CLR:
            item = self.table.item(row, _COL_CLR)
            current = item.data(Qt.ItemDataRole.UserRole) or "#FFFFFF"
            colour = QColorDialog.getColor(QColor(current), self, "Pick Ion Colour")
            if colour.isValid():
                name = colour.name()
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setText(name)

    def _show_all(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, _COL_VIS)
            item.setData(Qt.ItemDataRole.UserRole, True)
            item.setText("Yes")

    def _hide_all(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, _COL_VIS)
            item.setData(Qt.ItemDataRole.UserRole, False)
            item.setText("No")

    def _reset_colours(self):
        for row, (key, display, default_clr) in enumerate(ION_CATALOGUE):
            item = self.table.item(row, _COL_CLR)
            item.setData(Qt.ItemDataRole.UserRole, default_clr)
            item.setText(default_clr or "default")

    # ── Accept ─────────────────────────────────────────────────
    def _on_accept(self):
        new_settings = {}
        for row, (key, _, default_clr) in enumerate(ION_CATALOGUE):
            vis_item = self.table.item(row, _COL_VIS)
            clr_item = self.table.item(row, _COL_CLR)
            visible = vis_item.data(Qt.ItemDataRole.UserRole) is True
            colour = clr_item.data(Qt.ItemDataRole.UserRole)
            # Only store overrides (non-default)
            entry = {}
            if not visible:
                entry["visible"] = False
            if colour and colour != default_clr:
                entry["color"] = colour
            if entry:
                new_settings[key] = entry
        self.viewer.annotation_display_settings = new_settings
        self.viewer.plot_spectrum()
        self.accept()
