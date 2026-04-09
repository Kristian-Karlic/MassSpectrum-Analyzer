from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QAbstractItemView, QApplication, QLineEdit,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence


class ExcelLikeTableWidget(QTableWidget):
    """QTableWidget with Excel-like copy/paste, fill-down, and multi-cell selection.

    Supports:
      - Ctrl+C: copy selected cells (tab-separated, newline per row)
      - Ctrl+V: paste from clipboard into selected region (multi-row/col)
      - Ctrl+D: fill down (copy top selected row's values into all rows below)
      - Delete/Backspace: clear selected editable cells
      - Multi-cell selection with click+drag or Shift+click
    """

    def __init__(self, *args, **kwargs):
        # Track which columns are read-only (like file path)
        self._readonly_columns = set()
        super().__init__(*args, **kwargs)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def set_readonly_columns(self, columns):
        """Mark columns as read-only (0-indexed)"""
        self._readonly_columns = set(columns)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection()
        elif event.matches(QKeySequence.StandardKey.Paste):
            self._paste_clipboard()
        elif event.key() == Qt.Key.Key_D and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self._fill_down()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._clear_selection()
        else:
            super().keyPressEvent(event)

    def _get_selected_range(self):
        """Get the bounding rectangle of selected cells as (min_row, max_row, min_col, max_col)"""
        selected = self.selectedIndexes()
        if not selected:
            return None
        rows = [idx.row() for idx in selected]
        cols = [idx.column() for idx in selected]
        return min(rows), max(rows), min(cols), max(cols)

    def _copy_selection(self):
        """Copy selected cells to clipboard as tab-separated text"""
        sel_range = self._get_selected_range()
        if not sel_range:
            return
        min_row, max_row, min_col, max_col = sel_range

        lines = []
        for row in range(min_row, max_row + 1):
            row_data = []
            for col in range(min_col, max_col + 1):
                item = self.item(row, col)
                row_data.append(item.text() if item else '')
            lines.append('\t'.join(row_data))

        clipboard = QApplication.clipboard()
        clipboard.setText('\n'.join(lines))

    def _paste_clipboard(self):
        """Paste clipboard text into table starting at the top-left selected cell.

        Handles multi-row, multi-col paste. If pasting a single value onto a
        multi-cell selection, fills all selected cells with that value.
        """
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if not text:
            return

        # Parse clipboard rows/cols
        paste_rows = text.rstrip('\n').split('\n')
        paste_data = [row.split('\t') for row in paste_rows]

        sel_range = self._get_selected_range()
        if not sel_range:
            return
        start_row, end_row, start_col, end_col = sel_range

        # Single value pasted onto multi-cell selection: fill all selected
        if len(paste_data) == 1 and len(paste_data[0]) == 1:
            value = paste_data[0][0]
            for idx in self.selectedIndexes():
                if idx.column() not in self._readonly_columns:
                    item = self.item(idx.row(), idx.column())
                    if item:
                        item.setText(value)
                    else:
                        self.setItem(idx.row(), idx.column(), QTableWidgetItem(value))
            return

        # Multi-value paste starting at top-left of selection
        for r_offset, row_data in enumerate(paste_data):
            target_row = start_row + r_offset
            if target_row >= self.rowCount():
                break
            for c_offset, value in enumerate(row_data):
                target_col = start_col + c_offset
                if target_col >= self.columnCount():
                    break
                if target_col in self._readonly_columns:
                    continue
                item = self.item(target_row, target_col)
                if item:
                    item.setText(value)
                else:
                    self.setItem(target_row, target_col, QTableWidgetItem(value))

    def _fill_down(self):
        """Fill down: copy the first selected row's values into all rows below in the selection"""
        sel_range = self._get_selected_range()
        if not sel_range:
            return
        min_row, max_row, min_col, max_col = sel_range

        if min_row == max_row:
            return  # Nothing to fill

        # Get source values from first row
        source_values = {}
        for col in range(min_col, max_col + 1):
            if col in self._readonly_columns:
                continue
            item = self.item(min_row, col)
            source_values[col] = item.text() if item else ''

        # Fill into remaining rows
        for row in range(min_row + 1, max_row + 1):
            for col, value in source_values.items():
                item = self.item(row, col)
                if item:
                    item.setText(value)
                else:
                    self.setItem(row, col, QTableWidgetItem(value))

    def _clear_selection(self):
        """Clear editable selected cells"""
        for idx in self.selectedIndexes():
            if idx.column() not in self._readonly_columns:
                item = self.item(idx.row(), idx.column())
                if item:
                    item.setText('')


def create_search_bar(table, parent=None, placeholder="Search..."):
    """Create a QLineEdit that filters table rows by case-insensitive substring match.

    Returns the QLineEdit widget. Caller should add it to their layout.
    The returned widget has a ``_filter_func`` attribute that can be called
    manually after adding/removing rows: ``search_bar._filter_func(search_bar.text())``
    """
    search_input = QLineEdit(parent)
    search_input.setPlaceholderText(placeholder)
    search_input.setClearButtonEnabled(True)

    def filter_rows(text):
        text = text.lower()
        for row in range(table.rowCount()):
            if not text:
                table.setRowHidden(row, False)
                continue
            match = False
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item and text in item.text().lower():
                    match = True
                    break
            table.setRowHidden(row, not match)

    search_input.textChanged.connect(filter_rows)
    search_input._filter_func = filter_rows
    return search_input
