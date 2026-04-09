from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QTabWidget, QWidget,
    QAbstractItemView, QStyledItemDelegate, QStyle
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from utils.style.style import EditorConstants, StyleSheet
from .modification_mass_database import ModificationMassDatabase
from .central_mod_database import CentralModificationDatabase
from utils.tables.excel_table import ExcelLikeTableWidget, create_search_bar


# ------------------------------------------------------------------
#  Shared helpers
# ------------------------------------------------------------------

def _make_filter_func(table):
    """Create a row-filter closure for a search input bound to *table*."""
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
    """Disconnect the default signal and re-connect with a row filter."""
    search_input.textChanged.disconnect()
    filter_func = _make_filter_func(table)
    search_input.textChanged.connect(filter_func)
    search_input._filter_func = filter_func


def _create_button_bar(add_cb, delete_cb, save_cb, close_cb):
    """Create the standard Add / Delete / Save / Close button bar."""
    btn_layout = QHBoxLayout()

    add_btn = QPushButton("Add Entry")
    add_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
    add_btn.clicked.connect(add_cb)
    btn_layout.addWidget(add_btn)

    del_btn = QPushButton("Delete Selected")
    del_btn.setStyleSheet(EditorConstants.get_pushbutton_style("danger"))
    del_btn.clicked.connect(delete_cb)
    btn_layout.addWidget(del_btn)

    btn_layout.addStretch()

    save_btn = QPushButton("Save Changes")
    save_btn.setStyleSheet(EditorConstants.get_pushbutton_style("success"))
    save_btn.clicked.connect(save_cb)
    btn_layout.addWidget(save_btn)

    close_btn = QPushButton("Close")
    close_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
    close_btn.clicked.connect(close_cb)
    btn_layout.addWidget(close_btn)

    return btn_layout


def _delete_selected_rows(table):
    """Remove all selected rows from *table*."""
    selected = table.selectionModel().selectedRows()
    if not selected:
        return
    for idx in sorted(selected, key=lambda i: i.row(), reverse=True):
        table.removeRow(idx.row())


class ModDatabaseEditorDialog(QDialog):
    """Dialog for viewing and editing modification mass databases.

    Shows a tabbed interface with one tab per engine (MaxQuant,
    MetaMorpheus).  Each tab displays an editable two-column table of
    modification names and masses.
    """

    def __init__(self, maxquant_db: ModificationMassDatabase,
                 metamorpheus_db: ModificationMassDatabase, parent=None):
        super().__init__(parent)
        self.maxquant_db = maxquant_db
        self.metamorpheus_db = metamorpheus_db

        self.setWindowTitle("Search Tool Databases")
        self.resize(600, 500)
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.tab_widget = QTabWidget()

        mq_widget, self.mq_table = self._create_db_tab(self.maxquant_db)
        self.tab_widget.addTab(mq_widget, "MaxQuant Modifications")

        mm_widget, self.mm_table = self._create_db_tab(self.metamorpheus_db)
        self.tab_widget.addTab(mm_widget, "MetaMorpheus Modifications")

        layout.addWidget(self.tab_widget)

        layout.addLayout(_create_button_bar(
            self._add_entry, self._delete_entry,
            self._save_changes, self.accept,
        ))

    # ------------------------------------------------------------------
    def _create_db_tab(self, db: ModificationMassDatabase):
        widget = QWidget()
        tab_layout = QVBoxLayout(widget)

        search_input = create_search_bar(None, widget, "Search modifications...")
        tab_layout.addWidget(search_input)

        table = ExcelLikeTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Modification Name", "Mass (Da)"])
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        table.setColumnWidth(1, 150)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        StyleSheet.apply_table_styling(table)
        table.setAlternatingRowColors(False)

        _wire_search(search_input, table)

        self._populate_table(table, db)
        tab_layout.addWidget(table)
        widget.search_input = search_input
        return widget, table

    @staticmethod
    def _populate_table(table: QTableWidget, db: ModificationMassDatabase):
        mods = db.get_all_mods()
        table.setRowCount(len(mods))
        for row, (name, mass) in enumerate(sorted(mods.items())):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(f"{mass}"))

    # ------------------------------------------------------------------
    def _current_table_and_db(self):
        idx = self.tab_widget.currentIndex()
        if idx == 0:
            return self.mq_table, self.maxquant_db
        else:
            return self.mm_table, self.metamorpheus_db

    def _add_entry(self):
        table, _ = self._current_table_and_db()
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(""))
        table.setItem(row, 1, QTableWidgetItem("0.0"))
        table.scrollToItem(table.item(row, 0))
        table.editItem(table.item(row, 0))

    def _delete_entry(self):
        table, _ = self._current_table_and_db()
        _delete_selected_rows(table)

    def _save_changes(self):
        """Read every row from the active tab and overwrite the database."""
        for table, db in [(self.mq_table, self.maxquant_db),
                          (self.mm_table, self.metamorpheus_db)]:
            new_mods: dict[str, float] = {}
            errors = []
            for row in range(table.rowCount()):
                name_item = table.item(row, 0)
                mass_item = table.item(row, 1)
                name = name_item.text().strip() if name_item else ""
                mass_text = mass_item.text().strip() if mass_item else ""
                if not name:
                    continue
                try:
                    mass = float(mass_text)
                    new_mods[name] = mass
                except ValueError:
                    errors.append(f"Row {row + 1}: invalid mass '{mass_text}' "
                                  f"for '{name}'")

            if errors:
                QMessageBox.warning(
                    self, "Validation Error",
                    "Fix these issues before saving:\n\n" + "\n".join(errors)
                )
                return

            db.mods = new_mods
            db._save()

        QMessageBox.information(self, "Saved",
                                "Modification databases saved successfully.")


class _LabileCellDelegate(QStyledItemDelegate):
    """Delegate that paints green/red background for the Labile column.

    Qt stylesheets override QTableWidgetItem.setBackground(), so we
    must paint the colour ourselves in a delegate.
    """

    def paint(self, painter, option, index):
        painter.save()
        checked = index.data(Qt.ItemDataRole.UserRole)
        if checked is True:
            painter.fillRect(option.rect, QColor("#4CAF50"))
        else:
            painter.fillRect(option.rect, QColor("#F44336"))

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(255, 255, 255, 60))

        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, str(text))
        painter.restore()


class CentralModEditorDialog(QDialog):
    """Editor for the central modification database with neutral-loss columns.

    Columns: Name | Mass | Neutral Losses | Remainder Ions | Labile
    """

    _COL_NAME = 0
    _COL_MASS = 1
    _COL_NL = 2
    _COL_RM = 3
    _COL_LABILE = 4
    _HEADERS = ["Name", "Mass (Da)", "Neutral Losses", "Remainder Ions", "Labile"]

    def __init__(self, central_db: CentralModificationDatabase, parent=None):
        super().__init__(parent)
        self.central_db = central_db
        self.setWindowTitle("Central Modification Database")
        self.resize(800, 550)
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Search bar
        self.search_input = create_search_bar(None, self, "Search modifications...")
        layout.addWidget(self.search_input)

        self.table = ExcelLikeTableWidget()
        self.table.set_readonly_columns([self._COL_LABILE])
        self.table.setColumnCount(len(self._HEADERS))
        self.table.setHorizontalHeaderLabels(self._HEADERS)

        # Column stretch / width
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self._COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self._COL_MASS, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self._COL_MASS, 110)
        for col in (self._COL_NL, self._COL_RM):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, 170)
        header.setSectionResizeMode(self._COL_LABILE, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self._COL_LABILE, 70)

        self._labile_delegate = _LabileCellDelegate(self.table)
        self.table.setItemDelegateForColumn(self._COL_LABILE, self._labile_delegate)

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        StyleSheet.apply_table_styling(self.table)
        self.table.setAlternatingRowColors(False)

        _wire_search(self.search_input, self.table)

        self._populate_table()
        layout.addWidget(self.table)

        layout.addLayout(_create_button_bar(
            self._add_entry, self._delete_entry,
            self._save_changes, self.accept,
        ))

    # ------------------------------------------------------------------
    def _populate_table(self):
        entries = self.central_db.get_all_entries()
        self.table.setRowCount(len(entries))
        for row, (name, entry) in enumerate(sorted(entries.items())):
            self.table.setItem(row, self._COL_NAME, QTableWidgetItem(name))
            self.table.setItem(row, self._COL_MASS,
                               QTableWidgetItem(f"{entry['mass']}"))
            self.table.setItem(row, self._COL_NL,
                               QTableWidgetItem(entry.get("neutral_losses", "")))
            self.table.setItem(row, self._COL_RM,
                               QTableWidgetItem(entry.get("remainder_ions", "")))
            self._set_labile_cell(row, entry.get("labile_loss", False))

    def _set_labile_cell(self, row: int, checked: bool):
        item = QTableWidgetItem("Yes" if checked else "No")
        item.setData(Qt.ItemDataRole.UserRole, checked)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, self._COL_LABILE, item)

    def _toggle_labile(self, item):
        """Toggle labile value on double-click."""
        if item.column() == self._COL_LABILE:
            current = item.data(Qt.ItemDataRole.UserRole) is True
            self._set_labile_cell(item.row(), not current)

    def _refilter(self):
        """Re-apply the current search filter after row changes."""
        self.search_input._filter_func(self.search_input.text())

    # ------------------------------------------------------------------
    def _add_entry(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, self._COL_NAME, QTableWidgetItem(""))
        self.table.setItem(row, self._COL_MASS, QTableWidgetItem("0.0"))
        self.table.setItem(row, self._COL_NL, QTableWidgetItem(""))
        self.table.setItem(row, self._COL_RM, QTableWidgetItem(""))
        self._set_labile_cell(row, False)
        self.table.scrollToItem(self.table.item(row, 0))
        self.table.editItem(self.table.item(row, 0))
        self._refilter()

    def _delete_entry(self):
        _delete_selected_rows(self.table)
        self._refilter()

    # ------------------------------------------------------------------
    def _save_changes(self):
        """Read every row and overwrite the central database."""
        new_mods: dict[str, dict] = {}
        errors = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, self._COL_NAME)
            name = name_item.text().strip() if name_item else ""
            if not name:
                continue

            try:
                mass = self._read_float(row, self._COL_MASS, "Mass")
                nl_text = self._read_csv_floats(row, self._COL_NL, "Neutral Losses")
                rm_text = self._read_csv_floats(row, self._COL_RM, "Remainder Ions")
            except ValueError as exc:
                errors.append(f"Row {row + 1} ({name}): {exc}")
                continue

            labile_item = self.table.item(row, self._COL_LABILE)
            labile = labile_item.data(Qt.ItemDataRole.UserRole) is True if labile_item else False

            new_mods[name] = {
                "mass": mass,
                "neutral_losses": nl_text,
                "remainder_ions": rm_text,
                "labile_loss": labile,
            }

        if errors:
            QMessageBox.warning(
                self, "Validation Error",
                "Fix these issues before saving:\n\n" + "\n".join(errors),
            )
            return

        self.central_db.mods = new_mods
        self.central_db._save()
        QMessageBox.information(self, "Saved",
                                "Central modification database saved successfully.")

    def _read_float(self, row: int, col: int, label: str) -> float:
        item = self.table.item(row, col)
        text = item.text().strip() if item else ""
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"invalid {label} value '{text}'")

    def _read_csv_floats(self, row: int, col: int, label: str) -> str:
        """Read and validate a comma-separated float string from a table cell."""
        item = self.table.item(row, col)
        text = item.text().strip() if item else ""
        if not text:
            return ""
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                float(part)
            except ValueError:
                raise ValueError(f"invalid {label} value '{part}'")
        return text

    def showEvent(self, event):
        super().showEvent(event)
        # Connect double-click for labile toggle after table is visible
        try:
            self.table.itemDoubleClicked.disconnect(self._toggle_labile)
        except TypeError:
            pass
        self.table.itemDoubleClicked.connect(self._toggle_labile)
