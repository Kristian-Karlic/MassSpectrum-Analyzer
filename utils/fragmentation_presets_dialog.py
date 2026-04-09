"""
Fragmentation Preset Manager

Handles loading, saving, and management of user-defined fragmentation method presets.
Custom presets are persisted as JSON at data/custom_presets.json.
"""

import json
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QSplitter, QTextEdit, QInputDialog, QMessageBox,
    QFileDialog, QWidget, QFrame, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from utils.style.style import EditorConstants
from utils.resource_path import get_data_file_path

import logging

logger = logging.getLogger(__name__)

CUSTOM_PRESETS_FILE = "custom_presets.json"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_custom_presets() -> dict:
    """Load user-defined presets from JSON file. Returns {} if file missing or corrupt."""
    path = get_data_file_path(CUSTOM_PRESETS_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.warning(f"[PRESETS] Failed to load custom presets: {e}")
    return {}


def save_custom_presets(presets: dict) -> bool:
    """Save user-defined presets dict to JSON file. Returns True on success."""
    path = get_data_file_path(CUSTOM_PRESETS_FILE)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning(f"[PRESETS] Failed to save custom presets: {e}")
        return False


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def format_preset_for_export(name: str, preset: dict) -> str:
    """Build a human-readable ion list string suitable for referencing in publications."""
    lines = [
        f"Fragmentation Method: {name}",
        "=" * (22 + len(name)),
        "",
    ]

    normal = sorted(preset.get("normal", []))
    neutral = sorted(preset.get("neutral", []))
    custom_ions = preset.get("custom_ions", [])
    diagnostic_ions = preset.get("diagnostic_ions", [])

    lines.append(f"Normal Ion Types: {', '.join(normal) if normal else '(none)'}")
    lines.append(f"Neutral Loss Ion Types: {', '.join(neutral) if neutral else '(none)'}")

    lines.append("")
    lines.append("Custom Ion Series:")
    if custom_ions:
        for ion in custom_ions:
            base = ion.get("Base Ion", "?")
            name_s = ion.get("Series Name", "?")
            offset = ion.get("Mass Offset", "0")
            restriction = ion.get("Restriction", "")
            restr_str = f", restricted to: {restriction}" if restriction else ""
            lines.append(f"  - {name_s} ({base} ion + {offset} Da{restr_str})")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Diagnostic Ions:")
    if diagnostic_ions:
        for ion in diagnostic_ions:
            ion_name = ion.get("Name", "?")
            mass = ion.get("Mass", "?")
            lines.append(f"  - {ion_name} (m/z {mass})")
    else:
        lines.append("  (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Preset Manager Dialog
# ---------------------------------------------------------------------------

class PresetManagerDialog(QDialog):
    """Non-modal dialog for managing fragmentation method presets.

    Emits ``presets_changed`` whenever custom presets are modified so the
    caller can refresh the preset combo box.
    """

    presets_changed = pyqtSignal()

    def __init__(self, builtin_presets: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fragmentation Preset Manager")
        self.resize(780, 520)
        # Keep as independent window so the main GUI stays interactive
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinMaxButtonsHint
        )

        self.builtin_presets = builtin_presets  # hardcoded, read-only
        self.custom_presets = load_custom_presets()

        self._apply_style()
        self._build_ui()
        self._populate_list()

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def _apply_style(self):
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {EditorConstants.BACKGROUND_COLOR()};
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
            }}
            QLabel {{
                color: {EditorConstants.TEXT_COLOR()};
                {EditorConstants.get_font_string()}
            }}
            QListWidget {{
                background-color: {EditorConstants.GRAY_50()};
                color: {EditorConstants.TEXT_COLOR()};
                border: 1px solid {EditorConstants.BORDER_COLOR()};
                border-radius: 4px;
                {EditorConstants.get_font_string()}
            }}
            QListWidget::item:selected {{
                background-color: {EditorConstants.GRAY_200()};
                color: {EditorConstants.TEXT_COLOR()};
            }}
            QTextEdit {{
                background-color: {EditorConstants.GRAY_50()};
                color: {EditorConstants.TEXT_COLOR()};
                border: 1px solid {EditorConstants.BORDER_COLOR()};
                border-radius: 4px;
                {EditorConstants.get_font_string()}
            }}
        """)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # Title
        title = QLabel("Manage Fragmentation Presets")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        sub = QLabel(
            "Built-in presets are read-only. Custom presets can be renamed, deleted, or exported."
        )
        sub.setStyleSheet(f"color: {EditorConstants.DISABLED_COLOR()}; font-size: 11px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # -- Left: preset list --
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        list_label = QLabel("Presets")
        list_label.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(list_label)

        self.preset_list = QListWidget()
        self.preset_list.currentItemChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.preset_list)

        # Action buttons under list
        action_row = QHBoxLayout()
        self.rename_btn = QPushButton("Rename")
        self.rename_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.rename_btn.setEnabled(False)
        self.rename_btn.clicked.connect(self._rename_preset)
        action_row.addWidget(self.rename_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_preset)
        action_row.addWidget(self.delete_btn)
        left_layout.addLayout(action_row)

        splitter.addWidget(left_widget)

        # -- Right: detail panel --
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        detail_label = QLabel("Ion List")
        detail_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(detail_label)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("Select a preset to view its ion list.")
        right_layout.addWidget(self.detail_text)

        export_row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        export_row.addWidget(self.copy_btn)

        self.export_btn = QPushButton("Export to File...")
        self.export_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_to_file)
        export_row.addWidget(self.export_btn)
        export_row.addStretch()
        right_layout.addLayout(export_row)

        splitter.addWidget(right_widget)
        splitter.setSizes([260, 500])
        root.addWidget(splitter, stretch=1)

        # Bottom close button
        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    # ------------------------------------------------------------------
    # List population
    # ------------------------------------------------------------------

    def _make_section_header(self, text: str) -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)  # not selectable
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        item.setFont(font)
        item.setForeground(QColor(EditorConstants.DISABLED_COLOR()))
        item.setData(Qt.ItemDataRole.UserRole, {"_section": True})
        return item

    def _make_builtin_item(self, name: str) -> QListWidgetItem:
        item = QListWidgetItem(f"  {name}")
        item.setForeground(QColor(EditorConstants.DISABLED_COLOR()))
        item.setData(Qt.ItemDataRole.UserRole, {"_type": "builtin", "_name": name})
        return item

    def _make_custom_item(self, name: str) -> QListWidgetItem:
        item = QListWidgetItem(f"  {name}")
        item.setForeground(QColor(EditorConstants.TEXT_COLOR()))
        item.setData(Qt.ItemDataRole.UserRole, {"_type": "custom", "_name": name})
        return item

    def _populate_list(self, select_name: str = None):
        self.preset_list.blockSignals(True)
        self.preset_list.clear()

        self.preset_list.addItem(self._make_section_header("Built-in Presets"))
        for name in self.builtin_presets:
            self.preset_list.addItem(self._make_builtin_item(name))

        self.preset_list.addItem(self._make_section_header("Custom Presets"))
        if self.custom_presets:
            for name in self.custom_presets:
                self.preset_list.addItem(self._make_custom_item(name))
        else:
            placeholder = QListWidgetItem("  (no custom presets yet)")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            placeholder.setForeground(QColor(EditorConstants.DISABLED_COLOR()))
            self.preset_list.addItem(placeholder)

        self.preset_list.blockSignals(False)

        # Re-select previously selected item if possible
        if select_name:
            for i in range(self.preset_list.count()):
                item = self.preset_list.item(i)
                data = item.data(Qt.ItemDataRole.UserRole) or {}
                if data.get("_name") == select_name:
                    self.preset_list.setCurrentItem(item)
                    return
        self._on_selection_changed(None, None)

    # ------------------------------------------------------------------
    # Selection handler
    # ------------------------------------------------------------------

    def _on_selection_changed(self, current, _previous):
        if current is None:
            self._clear_detail()
            return
        data = current.data(Qt.ItemDataRole.UserRole) or {}
        if data.get("_section"):
            self._clear_detail()
            return

        ptype = data.get("_type")
        name = data.get("_name", "")

        is_custom = ptype == "custom"
        self.rename_btn.setEnabled(is_custom)
        self.delete_btn.setEnabled(is_custom)

        # Get preset dict
        if ptype == "builtin":
            raw = self.builtin_presets.get(name, {})
            # Normalise – builtin presets store sets, convert to sorted lists for display
            preset = {
                "normal": sorted(raw.get("normal", [])),
                "neutral": sorted(raw.get("neutral", [])),
                "custom_ions": [],
                "diagnostic_ions": [],
            }
        else:
            preset = self.custom_presets.get(name, {})

        text = format_preset_for_export(name, preset)
        self.detail_text.setPlainText(text)
        self.copy_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

    def _clear_detail(self):
        self.rename_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.detail_text.clear()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _current_custom_name(self) -> str | None:
        item = self.preset_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        if data.get("_type") == "custom":
            return data.get("_name")
        return None

    def _rename_preset(self):
        old_name = self._current_custom_name()
        if old_name is None:
            return

        new_name, ok = QInputDialog.getText(
            self, "Rename Preset",
            "New preset name:", text=old_name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Preset name cannot be empty.")
            return
        if new_name == old_name:
            return
        if new_name in self.builtin_presets or new_name in self.custom_presets:
            QMessageBox.warning(self, "Duplicate Name",
                                f"A preset named '{new_name}' already exists.")
            return

        self.custom_presets[new_name] = self.custom_presets.pop(old_name)
        if save_custom_presets(self.custom_presets):
            self._populate_list(select_name=new_name)
            self.presets_changed.emit()
        else:
            QMessageBox.critical(self, "Error", "Failed to save presets to disk.")

    def _delete_preset(self):
        name = self._current_custom_name()
        if name is None:
            return

        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Are you sure you want to delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del self.custom_presets[name]
        if save_custom_presets(self.custom_presets):
            self._populate_list()
            self.presets_changed.emit()
        else:
            QMessageBox.critical(self, "Error", "Failed to save presets to disk.")

    def _copy_to_clipboard(self):
        text = self.detail_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def _export_to_file(self):
        text = self.detail_text.toPlainText()
        if not text:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Ion List",
            os.path.expanduser("~/Documents/fragmentation_method.txt"),
            "Text files (*.txt);;All files (*.*)"
        )
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(text)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")

    # ------------------------------------------------------------------
    # Called by the main app after adding a new custom preset externally
    # ------------------------------------------------------------------

    def refresh(self):
        """Reload custom presets from disk and repopulate the list."""
        self.custom_presets = load_custom_presets()
        self._populate_list()
