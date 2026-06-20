"""
Results Tab Manager

Provides a UI for viewing experiment-level results and statistics,
starting with MS2 identification rate per raw file.
"""

import os
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QLabel,
    QGroupBox,
    QFileDialog,
)
from PyQt6.QtCore import Qt
from utils.style.style import EditorConstants, StyleSheet


class ResultsTabManager:
    def __init__(self, main_app):
        self.main_app = main_app
        self.tab_widget = None
        self.results_table = None
        self.summary_label = None

    def setup_results_tab(self, parent_tab_widget=None, tab_name="Results"):
        """Create and add the identification-rate tab to a tab widget."""
        if self.tab_widget is not None:
            return self.tab_widget

        self.tab_widget = QWidget()
        main_layout = QVBoxLayout(self.tab_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # -- Header group --
        header_group = QGroupBox("Identification Summary")
        header_group.setStyleSheet(EditorConstants.get_groupbox_style())
        header_layout = QVBoxLayout(header_group)

        self.summary_label = QLabel(
            "Load raw files and search results, then click 'Prepare Data' "
            "to view identification statistics."
        )
        self.summary_label.setWordWrap(True)
        header_layout.addWidget(self.summary_label)
        main_layout.addWidget(header_group)

        # -- Results table --
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(
            [
                "Raw File",
                "Total MS1 Scans",
                "Total MS2 Scans",
                "PSMs Identified",
                "% ID Rate",
            ]
        )
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)

        header = self.results_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        StyleSheet.apply_table_styling(self.results_table)
        main_layout.addWidget(self.results_table, stretch=1)

        # -- Button row --
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        export_btn = QPushButton("Export to CSV")
        export_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        export_btn.clicked.connect(self._export_results)
        button_layout.addWidget(export_btn)

        main_layout.addLayout(button_layout)

        target_tab_widget = parent_tab_widget or self.main_app.main_tab_widget
        target_tab_widget.addTab(self.tab_widget, tab_name)
        return self.tab_widget

    # ----------------------------------------------------------------
    # Data update
    # ----------------------------------------------------------------
    def update_results_table(self):
        """Populate the table from scan_counts and merged_df."""
        scan_counts = self.main_app.experiment_data_manager.scan_counts
        merged_df = self.main_app.experiment_data_manager.merged_df

        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)

        if not scan_counts:
            self.summary_label.setText(
                "No scan count data available. Load files and run 'Prepare Data'."
            )
            return

        # PSMs per raw file path — normalize paths to avoid case/separator mismatches on Windows
        psm_counts = {}
        if (
            merged_df is not None
            and not merged_df.empty
            and "spectrum_file_path" in merged_df.columns
        ):
            normalized_paths = (
                merged_df["spectrum_file_path"]
                .dropna()
                .apply(lambda p: os.path.normcase(os.path.normpath(str(p))))
            )
            psm_counts = normalized_paths.groupby(normalized_paths).size().to_dict()

        total_ms2_all = 0
        total_psms_all = 0

        row_idx = 0
        for file_path, counts in scan_counts.items():
            ms1 = counts.get("ms1", 0)
            ms2 = counts.get("ms2", 0)
            psms = psm_counts.get(os.path.normcase(os.path.normpath(file_path)), 0)
            id_rate = (psms / ms2 * 100) if ms2 > 0 else 0.0

            total_ms2_all += ms2
            total_psms_all += psms

            self.results_table.insertRow(row_idx)

            # Raw file name (tooltip shows full path)
            name_item = QTableWidgetItem(os.path.basename(file_path))
            name_item.setToolTip(file_path)
            self.results_table.setItem(row_idx, 0, name_item)

            # Numeric columns — store as numeric data for correct sorting
            for col, value in enumerate([ms1, ms2, psms], start=1):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.DisplayRole, value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.results_table.setItem(row_idx, col, item)

            # % ID Rate
            rate_item = QTableWidgetItem()
            rate_item.setData(Qt.ItemDataRole.DisplayRole, round(id_rate, 2))
            rate_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results_table.setItem(row_idx, 4, rate_item)

            row_idx += 1

        self.results_table.setSortingEnabled(True)

        overall_rate = (
            (total_psms_all / total_ms2_all * 100) if total_ms2_all > 0 else 0.0
        )
        self.summary_label.setText(
            f"Showing {row_idx} file(s)  |  "
            f"Total MS2 scans: {total_ms2_all:,}  |  "
            f"Total PSMs: {total_psms_all:,}  |  "
            f"Overall ID rate: {overall_rate:.2f}%"
        )

    # ----------------------------------------------------------------
    # Export
    # ----------------------------------------------------------------
    def _export_results(self):
        """Export the results table as CSV."""
        if self.results_table.rowCount() == 0:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_app, "Export Results", "", "CSV Files (*.csv);;All Files (*.*)"
        )
        if not file_path:
            return

        headers = []
        for col in range(self.results_table.columnCount()):
            headers.append(self.results_table.horizontalHeaderItem(col).text())

        rows = []
        for row in range(self.results_table.rowCount()):
            row_data = []
            for col in range(self.results_table.columnCount()):
                item = self.results_table.item(row, col)
                row_data.append(item.text() if item else "")
            rows.append(",".join(row_data))

        with open(file_path, "w") as f:
            f.write(",".join(headers) + "\n")
            for line in rows:
                f.write(line + "\n")

    # ----------------------------------------------------------------
    # Theme
    # ----------------------------------------------------------------
    def update_theme(self, theme_name):
        """Update tab theme for dark/light mode support."""
        if self.results_table:
            StyleSheet.apply_table_styling(self.results_table)
