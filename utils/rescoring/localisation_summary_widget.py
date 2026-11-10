import logging

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSizePolicy,
)
from PyQt6.QtCore import Qt

from utils.style.style import StyleSheet, EditorConstants

logger = logging.getLogger(__name__)

# Display order for Loc_Status values (unknown values are appended after these)
_STATUS_ORDER = [
    "relocalised",
    "same_localisation",
    "ambiguous",
    "single_site",
    "no_alternatives",
    "over_cap",
    "error",
    "no_movable",
]

# Display labels; Loc_Status values in the data/export are unchanged
_STATUS_LABELS = {
    "relocalised": "Relocalised",
    "same_localisation": "Localisation unchanged",
    "ambiguous": "Ambiguous",
    "single_site": "Only single localisation site",
    "no_alternatives": "No alternative placement",
    "over_cap": "Over isoform cap",
    "error": "Error",
    "no_movable": "Non-modified PSMs",
}

# Statuses shown in the Loc_Delta distribution plot
_PLOT_STATUSES = ["relocalised", "same_localisation"]


def _label(status):
    return _STATUS_LABELS.get(status, status)


class LocalisationSummaryWidget(QWidget):
    """Summary of bulk site localisation: status counts and Loc_Delta distribution."""

    _COLUMNS = ["Status", "PSMs", "%", "Median Δ"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.df = None
        self._layout = QVBoxLayout(self)

        self.message_label = QLabel(
            "No site localisation data.\n"
            "Enable Site Localisation in the Configuration tab and re-run rescoring."
        )
        self.message_label.setStyleSheet(StyleSheet.get_label_style())
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.message_label)

        self.content = QWidget()
        content_layout = QHBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)
        StyleSheet.apply_table_styling(self.table)
        content_layout.addWidget(self.table)

        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        content_layout.addWidget(self.canvas, 1)

        self._layout.addWidget(self.content)
        self.content.setVisible(False)

    def load_data(self, df):
        self.df = df
        has_data = df is not None and "Loc_Status" in df.columns
        self.message_label.setVisible(not has_data)
        self.content.setVisible(has_data)
        if not has_data:
            return
        self._populate_table()
        self.update_plot()

    def _populate_table(self):
        statuses = self.df["Loc_Status"].fillna("NA").astype(str)
        counts = statuses.value_counts()
        order = [s for s in _STATUS_ORDER if s in counts.index]
        order += sorted(s for s in counts.index if s not in order)
        total = int(counts.sum())
        deltas = pd.to_numeric(self.df["Loc_Delta"], errors="coerce")

        self.table.setRowCount(len(order) + 1)
        for row, status in enumerate(order):
            status_deltas = deltas[statuses == status].dropna()
            median = status_deltas.median() if len(status_deltas) else np.nan
            values = [
                _label(status),
                str(int(counts[status])),
                f"{counts[status] / total * 100:.1f}" if total else "0.0",
                f"{median:.2f}" if pd.notna(median) else "",
            ]
            self._set_row(row, values)
        self._set_row(len(order), ["Total", str(total), "100.0", ""], bold=True)

        # Fit the table to its columns so it never scrolls sideways; the table
        # stylesheet pads headers beyond Qt's size hint, hence the extra margin
        header = self.table.horizontalHeader()
        for c in range(self.table.columnCount()):
            self.table.setColumnWidth(
                c,
                max(self.table.sizeHintForColumn(c), header.sectionSizeHint(c)) + 24,
            )
        width = sum(self.table.columnWidth(c) for c in range(self.table.columnCount()))
        scrollbar = self.table.verticalScrollBar().sizeHint().width()
        self.table.setFixedWidth(width + 2 * self.table.frameWidth() + scrollbar)

    def _set_row(self, row, values, bold=False):
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            if col > 0:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            if bold:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.table.setItem(row, col, item)

    def update_plot(self):
        """Violin + box + jitter of Loc_Delta for relocalised / same-site PSMs."""
        if self.df is None or "Loc_Status" not in self.df.columns:
            return

        bg = EditorConstants.PLOT_BACKGROUND()
        fg = EditorConstants.TEXT_COLOR()
        colors = {
            "relocalised": EditorConstants.SUCCESS_COLOR(),
            "same_localisation": EditorConstants.PRIMARY_BLUE(),
        }

        self.figure.clear()
        self.figure.set_facecolor(bg)
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(bg)

        deltas = pd.to_numeric(self.df["Loc_Delta"], errors="coerce")
        groups = []
        for status in _PLOT_STATUSES:
            values = deltas[(self.df["Loc_Status"] == status) & deltas.notna()].values
            if len(values):
                groups.append((status, values))

        if not groups:
            ax.text(
                0.5, 0.5, "No relocalised or same-site PSMs to plot",
                ha="center", va="center", color=fg, transform=ax.transAxes,
            )
            ax.set_axis_off()
            self.canvas.draw()
            return

        rng = np.random.default_rng(0)
        for pos, (status, values) in enumerate(groups, start=1):
            color = colors.get(status, EditorConstants.GRAY_500())

            # Violin needs spread for its density estimate
            if len(values) > 1 and np.ptp(values) > 0:
                parts = ax.violinplot(
                    values, positions=[pos], widths=0.8, showextrema=False
                )
                for body in parts["bodies"]:
                    body.set_facecolor(color)
                    body.set_edgecolor("none")
                    body.set_alpha(0.4)

            ax.boxplot(
                values,
                positions=[pos],
                widths=0.15,
                showfliers=False,
                patch_artist=True,
                boxprops={"facecolor": bg, "edgecolor": fg},
                medianprops={"color": fg},
                whiskerprops={"color": fg},
                capprops={"color": fg},
                zorder=3,
            )

            jitter = pos + rng.uniform(-0.1, 0.1, size=len(values))
            ax.scatter(jitter, values, s=6, alpha=0.4, color=color, zorder=4, linewidths=0)

        ax.set_xticks(range(1, len(groups) + 1))
        ax.set_xticklabels([f"{_label(s)}\n(n={len(v)})" for s, v in groups])
        ax.set_xlim(0.4, len(groups) + 0.6)
        ax.set_xlabel("Localisation status")
        ax.set_ylabel("Loc_Delta (best − second Rescore)")
        ax.set_title("Localisation confidence")
        ax.grid(True, axis="y", color=EditorConstants.GRID_COLOR(), linewidth=0.5, alpha=0.5)

        ax.tick_params(colors=fg)
        for spine in ax.spines.values():
            spine.set_color(fg)
        ax.xaxis.label.set_color(fg)
        ax.yaxis.label.set_color(fg)
        ax.title.set_color(fg)

        self.figure.tight_layout()
        self.canvas.draw()
