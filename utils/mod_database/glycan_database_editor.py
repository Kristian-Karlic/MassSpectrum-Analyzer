"""Dialog for managing glycan composition presets and custom monosaccharide definitions."""

import csv
import os
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QTabWidget,
    QWidget,
    QAbstractItemView,
    QLabel,
    QComboBox,
    QStyledItemDelegate,
    QSpinBox,
    QDialogButtonBox,
    QGridLayout,
    QScrollArea,
)

from utils.style.style import EditorConstants, StyleSheet
from utils.tables.excel_table import ExcelLikeTableWidget, create_search_bar
from utils.peak_matching.constants import (
    MONOSACCHARIDE_MASSES,
    MONOSACCHARIDE_SHORT,
    MONOSACCHARIDE_SHAPE,
    SNFG_CLASSES,
)

# Map Unicode shape → class name (for display)
_SHAPE_TO_NAME = {shape: name for shape, name in SNFG_CLASSES}
PROTECTED_MONOSACCHARIDES = frozenset(MONOSACCHARIDE_MASSES.keys())


class ShapeDelegate(QStyledItemDelegate):
    """Dropdown delegate for the Shape column — shows all 12 SNFG classes as options."""

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItem("", "")
        for shape, name in SNFG_CLASSES:
            combo.addItem(f"{shape}  {name}", shape)
        return combo

    def setEditorData(self, editor, index):
        current = index.data(Qt.ItemDataRole.DisplayRole) or ""
        for i in range(editor.count()):
            if editor.itemData(i) == current:
                editor.setCurrentIndex(i)
                return
        editor.setCurrentIndex(0)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData() or "", Qt.ItemDataRole.DisplayRole)

    def displayText(self, value, locale):
        if value in _SHAPE_TO_NAME:
            return f"{value}  {_SHAPE_TO_NAME[value]}"
        return value or ""


class CompositionBuilderDialog(QDialog):
    """Visual builder for a glycan composition string.

    Shows each known monosaccharide with a spinbox; generates e.g. Hex(5)HexNAc(2).
    """

    def __init__(self, mono_names, existing="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Build Glycan Composition")
        self.setMinimumWidth(320)
        self._spins = {}

        # Parse any existing composition: Name(count)...
        existing_counts = {
            m: int(n) for m, n in re.findall(r"(\w+)\((\d+)\)", existing)
        }

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Scrollable grid of monosaccharide rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setColumnStretch(0, 1)
        grid.setContentsMargins(0, 0, 0, 0)

        for i, name in enumerate(mono_names):
            spin = QSpinBox()
            spin.setRange(0, 30)
            spin.setValue(existing_counts.get(name, 0))
            spin.setFixedWidth(64)
            spin.valueChanged.connect(self._update_preview)
            grid.addWidget(QLabel(name), i, 0)
            grid.addWidget(spin, i, 1)
            self._spins[name] = spin

        scroll.setWidget(container)
        layout.addWidget(scroll)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet("font-style: italic; color: grey; font-size: 10px;")
        layout.addWidget(self._preview)
        self._update_preview()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_preview(self):
        comp = self.get_composition()
        self._preview.setText(comp if comp else "(empty — no monosaccharides selected)")

    def get_composition(self):
        return "".join(
            f"{name}({spin.value()})"
            for name, spin in self._spins.items()
            if spin.value() > 0
        )


class CompositionDelegate(QStyledItemDelegate):
    """Item delegate for the Composition column — opens the visual builder dialog on edit."""

    def __init__(self, get_mono_names, parent=None):
        super().__init__(parent)
        self._get_mono_names = get_mono_names

    def createEditor(self, parent, option, index):
        current = index.data(Qt.ItemDataRole.DisplayRole) or ""
        dialog = CompositionBuilderDialog(self._get_mono_names(), current, parent)
        if dialog.exec():
            index.model().setData(
                index, dialog.get_composition(), Qt.ItemDataRole.EditRole
            )
        return None  # We've already committed the data; no native editor needed


try:
    from utils.resource_path import get_data_file_path as _get_data_file_path
except Exception:

    def _get_data_file_path(filename):
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data", filename)
        )


def _glycan_csv_path():
    return _get_data_file_path("glycan_compositions.csv")


def _custom_mono_csv_path():
    return _get_data_file_path("custom_monosaccharides.csv")


def _calculate_glycan_mass(composition_str, lookup):
    """Return total residue mass for a composition string, or None if any name is unknown."""
    parts = re.findall(r"(\w+)\((\d+)\)", composition_str)
    if not parts:
        return None
    total = 0.0
    for name, count in parts:
        if name not in lookup:
            return None
        total += lookup[name] * int(count)
    return total


def _make_mass_item(text=""):
    """Create a non-editable QTableWidgetItem for the auto-calculated mass column."""
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    return item


def _make_filter_func(table):
    def filter_rows(text):
        text = text.lower()
        for row in range(table.rowCount()):
            if not text:
                table.setRowHidden(row, False)
                continue
            match = any(
                (item := table.item(row, col)) and text in item.text().lower()
                for col in range(table.columnCount())
            )
            table.setRowHidden(row, not match)

    return filter_rows


def _wire_search(search_input, table):
    search_input.textChanged.disconnect()
    filter_func = _make_filter_func(table)
    search_input.textChanged.connect(filter_func)


def _create_button_bar(add_cb, delete_cb, save_cb, close_cb):
    layout = QHBoxLayout()
    add_btn = QPushButton("Add Entry")
    add_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
    add_btn.clicked.connect(add_cb)
    layout.addWidget(add_btn)

    del_btn = QPushButton("Delete Selected")
    del_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
    del_btn.clicked.connect(delete_cb)
    layout.addWidget(del_btn)

    layout.addStretch()

    save_btn = QPushButton("Save Changes")
    save_btn.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
    save_btn.clicked.connect(save_cb)
    layout.addWidget(save_btn)

    close_btn = QPushButton("Close")
    close_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
    close_btn.clicked.connect(close_cb)
    layout.addWidget(close_btn)

    return layout


def _delete_selected_rows(table):
    selected = table.selectionModel().selectedRows()
    if not selected:
        return
    for idx in sorted(selected, key=lambda i: i.row(), reverse=True):
        table.removeRow(idx.row())


class GlycanDatabaseEditor(QDialog):
    """Two-tab dialog for managing glycan structures and monosaccharide definitions.

    Tab 1 — Glycan Structures: Name + Composition rows from glycan_compositions.csv.
    Tab 2 — Monosaccharides:   Single editable table showing all monosaccharides
                               (built-ins pre-loaded, saved to custom_monosaccharides.csv).

    Emits data_changed() after any successful save so callers can refresh.
    """

    data_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Glycan Database")
        self.resize(640, 520)
        self._setup_ui()
        self._load_monosaccharides()  # load first so mass lookup is ready
        self._load_glycan_structures()

    # ── UI setup ──────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._setup_structures_tab()
        self._setup_monosaccharides_tab()

    def _setup_structures_tab(self):
        widget = QWidget()
        tab_layout = QVBoxLayout(widget)
        tab_layout.setContentsMargins(6, 6, 6, 6)

        search = create_search_bar(None, widget, "Search structures…")
        tab_layout.addWidget(search)

        self.struct_table = ExcelLikeTableWidget()
        self.struct_table.setColumnCount(3)
        self.struct_table.setHorizontalHeaderLabels(
            ["Name", "Composition", "Mass (Da)"]
        )
        self.struct_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.struct_table.setColumnWidth(0, 160)
        self.struct_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.struct_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.struct_table.setColumnWidth(2, 110)
        self.struct_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        StyleSheet.apply_table_styling(self.struct_table)
        self.struct_table.setAlternatingRowColors(False)

        self.struct_table.setItemDelegateForColumn(
            1,
            CompositionDelegate(
                lambda: [
                    self.mono_table.item(i, 0).text()
                    for i in range(self.mono_table.rowCount())
                    if self.mono_table.item(i, 0) and self.mono_table.item(i, 0).text()
                ]
            ),
        )
        self.struct_table.itemChanged.connect(self._on_struct_item_changed)
        _wire_search(search, self.struct_table)
        tab_layout.addWidget(self.struct_table)

        hint = QLabel(
            "Click a Composition cell to open the visual builder. Mass is auto-calculated."
        )
        hint.setStyleSheet("color: grey; font-size: 10px;")
        tab_layout.addWidget(hint)

        tab_layout.addLayout(
            _create_button_bar(
                self._add_structure,
                self._delete_structure,
                self._save_structures,
                self.accept,
            )
        )

        self.tabs.addTab(widget, "Glycan Structures")

    def _setup_monosaccharides_tab(self):
        widget = QWidget()
        tab_layout = QVBoxLayout(widget)
        tab_layout.setContentsMargins(6, 6, 6, 6)

        search = create_search_bar(None, widget, "Search monosaccharides…")
        tab_layout.addWidget(search)

        self.mono_table = ExcelLikeTableWidget()
        self.mono_table.setColumnCount(4)
        self.mono_table.setHorizontalHeaderLabels(
            ["Name", "Short code", "Mass (Da)", "Shape"]
        )
        self.mono_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.mono_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self.mono_table.setColumnWidth(1, 90)
        self.mono_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.mono_table.setColumnWidth(2, 130)
        self.mono_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.mono_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        StyleSheet.apply_table_styling(self.mono_table)
        self.mono_table.setAlternatingRowColors(False)

        self.mono_table.setItemDelegateForColumn(3, ShapeDelegate(self.mono_table))
        _wire_search(search, self.mono_table)
        tab_layout.addWidget(self.mono_table)

        hint = QLabel(
            "Short code: shorthand used in Y-ion labels (e.g. 'N' for HexNAc).\n"
            "Mass: residue mass in Da (monoisotopic, after glycosidic bond condensation).\n"
            "Shape: click to select an SNFG class from the dropdown."
        )
        hint.setStyleSheet("color: grey; font-size: 10px;")
        tab_layout.addWidget(hint)

        tab_layout.addLayout(
            _create_button_bar(
                self._add_mono_entry,
                self._delete_mono_entry,
                self._save_monosaccharides,
                self.accept,
            )
        )

        self.tabs.addTab(widget, "Monosaccharides")

    # ── Data loading ───────────────────────────────────────────────────────

    def _load_glycan_structures(self):
        rows = []
        try:
            with open(_glycan_csv_path(), newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 2:
                        name = row[0].strip()
                        # Skip header row
                        if name.lower() in ("name", "glycan name"):
                            continue
                        rows.append((name, row[1].strip()))
        except FileNotFoundError:
            pass

        lookup = self._get_mass_lookup()
        self.struct_table.blockSignals(True)
        self.struct_table.setRowCount(len(rows))
        for i, (name, comp) in enumerate(rows):
            self.struct_table.setItem(i, 0, QTableWidgetItem(name))
            self.struct_table.setItem(i, 1, QTableWidgetItem(comp))
            mass = _calculate_glycan_mass(comp, lookup)
            self.struct_table.setItem(
                i, 2, _make_mass_item(f"{mass:.4f}" if mass is not None else "—")
            )
        self.struct_table.blockSignals(False)

    def _load_monosaccharides(self):
        # Start with built-in entries (name → (short, mass, shape)), then override from CSV
        merged = {
            name: (
                MONOSACCHARIDE_SHORT.get(name, ""),
                f"{mass:.5f}",
                MONOSACCHARIDE_SHAPE.get(name, ""),
            )
            for name, mass in MONOSACCHARIDE_MASSES.items()
        }

        try:
            with open(_custom_mono_csv_path(), newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("Name", "").strip()
                    short = row.get("Short", "").strip()
                    mass = row.get("Mass", "").strip()
                    shape = row.get("Shape", "").strip()
                    if name:
                        if name in PROTECTED_MONOSACCHARIDES:
                            # Keep built-in definitions canonical and non-overridable.
                            continue
                        merged[name] = (short, mass, shape)
        except FileNotFoundError:
            pass

        rows = sorted(merged.items())
        self.mono_table.setRowCount(len(rows))
        for i, (name, (short, mass, shape)) in enumerate(rows):
            self.mono_table.setItem(i, 0, QTableWidgetItem(name))
            self.mono_table.setItem(i, 1, QTableWidgetItem(short))
            self.mono_table.setItem(i, 2, QTableWidgetItem(mass))
            self.mono_table.setItem(i, 3, QTableWidgetItem(shape))
            self._set_mono_row_editable(i, name not in PROTECTED_MONOSACCHARIDES)

    def _set_mono_row_editable(self, row: int, editable: bool):
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if editable:
            flags |= Qt.ItemFlag.ItemIsEditable

        for col in range(self.mono_table.columnCount()):
            item = self.mono_table.item(row, col)
            if item is not None:
                item.setFlags(flags)

    # ── Mass helpers ───────────────────────────────────────────────────────

    def _get_mass_lookup(self):
        """Build a {name: mass} dict from the current mono_table contents."""
        lookup = {}
        if not hasattr(self, "mono_table"):
            return lookup
        for i in range(self.mono_table.rowCount()):
            name_item = self.mono_table.item(i, 0)
            mass_item = self.mono_table.item(i, 2)
            if name_item and mass_item:
                try:
                    lookup[name_item.text().strip()] = float(mass_item.text().strip())
                except ValueError:
                    pass
        return lookup

    def _on_struct_item_changed(self, item):
        """Recalculate the mass cell when the Composition column changes."""
        if item.column() != 1:
            return
        row = item.row()
        mass = _calculate_glycan_mass(item.text(), self._get_mass_lookup())
        mass_text = f"{mass:.4f}" if mass is not None else "—"
        self.struct_table.blockSignals(True)
        mass_item = self.struct_table.item(row, 2)
        if mass_item is None:
            self.struct_table.setItem(row, 2, _make_mass_item(mass_text))
        else:
            mass_item.setText(mass_text)
        self.struct_table.blockSignals(False)

    # ── Glycan structures actions ──────────────────────────────────────────

    def _add_structure(self):
        row = self.struct_table.rowCount()
        self.struct_table.insertRow(row)
        self.struct_table.setItem(row, 0, QTableWidgetItem(""))
        self.struct_table.setItem(row, 1, QTableWidgetItem(""))
        self.struct_table.setItem(row, 2, _make_mass_item("—"))
        self.struct_table.scrollToItem(self.struct_table.item(row, 0))
        self.struct_table.editItem(self.struct_table.item(row, 0))

    def _delete_structure(self):
        _delete_selected_rows(self.struct_table)

    def _save_structures(self):
        rows = []
        errors = []
        for i in range(self.struct_table.rowCount()):
            name_item = self.struct_table.item(i, 0)
            comp_item = self.struct_table.item(i, 1)
            name = name_item.text().strip() if name_item else ""
            comp = comp_item.text().strip() if comp_item else ""
            if not name and not comp:
                continue
            if not name:
                errors.append(f"Row {i + 1}: missing name.")
                continue
            if not comp:
                errors.append(f"Row {i + 1}: missing composition for '{name}'.")
                continue
            rows.append((name, comp))

        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return

        try:
            with open(_glycan_csv_path(), "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Name", "Composition"])
                for name, comp in rows:
                    writer.writerow([name, comp])
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not write to file:\n{e}")
            return

        QMessageBox.information(self, "Saved", f"Saved {len(rows)} glycan structures.")
        self.data_changed.emit()

    # ── Monosaccharide actions ─────────────────────────────────────────────

    def _add_mono_entry(self):
        row = self.mono_table.rowCount()
        self.mono_table.insertRow(row)
        self.mono_table.setItem(row, 0, QTableWidgetItem(""))
        self.mono_table.setItem(row, 1, QTableWidgetItem(""))
        self.mono_table.setItem(row, 2, QTableWidgetItem("0.0"))
        self.mono_table.setItem(row, 3, QTableWidgetItem(""))
        self._set_mono_row_editable(row, editable=True)
        self.mono_table.scrollToItem(self.mono_table.item(row, 0))
        self.mono_table.editItem(self.mono_table.item(row, 0))

    def _delete_mono_entry(self):
        selected = self.mono_table.selectionModel().selectedRows()
        if not selected:
            return

        protected_selected = []
        for idx in selected:
            name_item = self.mono_table.item(idx.row(), 0)
            name = name_item.text().strip() if name_item else ""
            if name in PROTECTED_MONOSACCHARIDES:
                protected_selected.append(name)

        if protected_selected:
            QMessageBox.warning(
                self,
                "Protected Monosaccharides",
                "The following built-in monosaccharides cannot be deleted:\n"
                + "\n".join(sorted(set(protected_selected))),
            )

        deletable = [
            idx for idx in selected
            if (self.mono_table.item(idx.row(), 0) and self.mono_table.item(idx.row(), 0).text().strip() not in PROTECTED_MONOSACCHARIDES)
            or not self.mono_table.item(idx.row(), 0)
        ]
        for idx in sorted(deletable, key=lambda i: i.row(), reverse=True):
            self.mono_table.removeRow(idx.row())

    def _save_monosaccharides(self):
        rows = []
        errors = []

        for i in range(self.mono_table.rowCount()):
            name_item = self.mono_table.item(i, 0)
            short_item = self.mono_table.item(i, 1)
            mass_item = self.mono_table.item(i, 2)
            shape_item = self.mono_table.item(i, 3)
            name = name_item.text().strip() if name_item else ""
            short = short_item.text().strip() if short_item else ""
            mass_str = mass_item.text().strip() if mass_item else ""
            shape = shape_item.text().strip() if shape_item else ""
            if not name and not short and not mass_str:
                continue
            if not name:
                errors.append(f"Row {i + 1}: missing name.")
                continue
            if not short:
                errors.append(f"Row {i + 1}: missing short code for '{name}'.")
                continue
            if len(short) > 3:
                errors.append(
                    f"Row {i + 1}: short code '{short}' should be 1-3 characters."
                )
                continue
            try:
                mass = float(mass_str)
            except ValueError:
                errors.append(f"Row {i + 1}: invalid mass '{mass_str}' for '{name}'.")
                continue
            if name in PROTECTED_MONOSACCHARIDES:
                # Built-ins are canonical in constants and should not be persisted as overrides.
                continue
            rows.append(
                {"Name": name, "Short": short, "Mass": f"{mass:.5f}", "Shape": shape}
            )

        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return

        try:
            with open(_custom_mono_csv_path(), "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["Name", "Short", "Mass", "Shape"]
                )
                writer.writeheader()
                writer.writerows(rows)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not write to file:\n{e}")
            return

        QMessageBox.information(self, "Saved", f"Saved {len(rows)} monosaccharides.")
        self.data_changed.emit()
