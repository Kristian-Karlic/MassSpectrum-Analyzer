import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QLabel,
    QGroupBox,
    QScrollArea,
    QCheckBox,
    QFileDialog,
)
from PyQt6.QtCore import Qt

from utils.utilities import UIHelpers
from utils.style.style import StyleSheet, EditorConstants
from utils.rescoring.interactive_plot_widget import InteractivePlotWidget
from utils.rescoring.export_options_dialog import (
    ExportOptionsDialog,
    build_fragment_long_format,
    companion_fragment_path,
)

# Columns to drop from the rescoring results CSV on export.
# Add any column name here that users don't need in the output file.
_EXPORT_DROP_COLUMNS = [
    "Raw data directory path",
    "Raw data file name",
    "Raw file type",
    "Search data directory path",
    "Search data file name",
    "Search file type",
    "spectrum_file_path",
]

logger = logging.getLogger(__name__)


class RescoreResultsViewerWidget(QWidget):
    """Embeddable results viewer widget for rescoring results"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.results_df = None
        self.original_df = None
        self.filtered_df = None
        self.debug_df = None
        self.ion_config = None

        self.init_ui()

    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)

        # Info label
        self.info_label = QLabel("No results loaded. Run rescoring to see results.")
        self.info_label.setStyleSheet(StyleSheet.get_label_style())
        layout.addWidget(self.info_label)

        # REMOVED: Export button moved to info section
        export_layout = QHBoxLayout()
        export_layout.addWidget(self.info_label)
        export_layout.addStretch()

        self.export_data_button = QPushButton("Export Data")
        self.export_data_button.setStyleSheet(
            EditorConstants.get_pushbutton_style("primary")
        )
        self.export_data_button.clicked.connect(self.export_data)
        self.export_data_button.setEnabled(False)
        export_layout.addWidget(self.export_data_button)

        layout.addLayout(export_layout)

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(EditorConstants.get_tab_style())
        layout.addWidget(self.tab_widget)

        self.stats_tab = QWidget()
        self.tab_widget.addTab(self.stats_tab, "Summary Statistics")

        self.comparison_tab = QWidget()
        self.tab_widget.addTab(self.comparison_tab, "Score Comparison")

        self.interactive_tab = QWidget()
        self.tab_widget.addTab(self.interactive_tab, "Interactive Plots")

        self.fdr_tab = QWidget()
        self.tab_widget.addTab(self.fdr_tab, "FDR Analysis")

    def load_results_dataframe(self, df):
        """Load results from a dataframe (called by RescoringTabManager)"""
        try:
            self.original_df = df
            self.results_df = df
            self.filtered_df = None
            required_cols = ["Rescore", "Annotated_TIC_%"]
            missing_cols = []
            for col in required_cols:
                if col not in self.results_df.columns:
                    missing_cols.append(col)

            if missing_cols:
                UIHelpers.show_validation_error(
                    self,
                    "Invalid Data",
                    f"Missing required columns: {', '.join(missing_cols)}",
                )
                return

            # Update info label
            info_text = f"Showing {len(self.results_df)} results"
            if "PSM_Type" in self.results_df.columns:
                decoy_count = (self.results_df["PSM_Type"] == "Decoy").sum()
                target_count = (self.results_df["PSM_Type"] == "Target").sum()
                info_text += f" ({target_count} Targets, {decoy_count} Decoys)"
            if "mokapot_qvalue" in self.results_df.columns:
                fdr_01_count = (self.results_df["mokapot_qvalue"] <= 0.01).sum()
                info_text += f" | {fdr_01_count} PSMs at 1% FDR"
            self.info_label.setText(info_text)

            # Enable export button
            self.export_data_button.setEnabled(True)

            # Populate analysis tabs only
            self.populate_summary_stats()
            self.populate_score_comparison()
            self.populate_interactive_plots()
            self.populate_fdr_analysis()

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            logger.error(f"Error loading results: {error_details}")
            UIHelpers.show_validation_error(
                self, "Processing Error", f"Error processing loaded data: {str(e)}"
            )

    def populate_interactive_plots(self):
        """Create the interactive Plotly plot tab."""
        # Clear any existing layout
        existing = self.interactive_tab.layout()
        if existing:
            while existing.count():
                child = existing.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
        else:
            existing = QVBoxLayout(self.interactive_tab)
            existing.setContentsMargins(0, 0, 0, 0)

        self.interactive_plot_widget = InteractivePlotWidget(self)
        existing.addWidget(self.interactive_plot_widget)
        self.interactive_plot_widget.load_data(self.results_df)

    def populate_summary_stats(self):
        """Populate summary statistics tab"""
        # Clear existing layout
        if self.stats_tab.layout():
            temp = QWidget(self)
            temp.setLayout(self.stats_tab.layout())
            temp.deleteLater()

        layout = QVBoxLayout(self.stats_tab)

        # Create scroll area for stats
        scroll = QScrollArea()
        scroll.setStyleSheet(StyleSheet.get_scrollarea_style())
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Calculate statistics
        stats = self.calculate_summary_stats()

        # Display stats in groups with styling
        for group_name, group_stats in stats.items():
            group_box = QGroupBox(group_name)
            group_box.setStyleSheet(EditorConstants.get_groupbox_style())
            group_layout = QVBoxLayout(group_box)

            for stat_name, value in group_stats.items():
                label = QLabel(f"{stat_name}: {value}")
                label.setStyleSheet(StyleSheet.get_label_style())
                group_layout.addWidget(label)

            scroll_layout.addWidget(group_box)

        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def calculate_summary_stats(self):
        """Calculate comprehensive summary statistics"""
        stats = {}

        if "Rescore" in self.results_df.columns:
            rescore_valid = self.results_df["Rescore"].dropna()
            stats["Rescore Statistics"] = {
                "Mean": f"{rescore_valid.mean():.3f}",
                "Median": f"{rescore_valid.median():.3f}",
                "Std Dev": f"{rescore_valid.std():.3f}",
                "Min": f"{rescore_valid.min():.3f}",
                "Max": f"{rescore_valid.max():.3f}",
            }

        # Group-based statistics if available
        if "Group" in self.results_df.columns:
            group_counts = self.results_df["Group"].value_counts()
            stats["Group Distribution"] = {
                f"Group '{group}'": f"{count} PSMs"
                for group, count in group_counts.items()
            }

        # Mokapot FDR statistics if available
        if "mokapot_qvalue" in self.results_df.columns:
            total = len(self.results_df)
            fdr_stats = {}

            for threshold in [0.01, 0.05, 0.10]:
                passing = (self.results_df["mokapot_qvalue"] <= threshold).sum()
                pct = (passing / total * 100) if total > 0 else 0
                fdr_stats[f"PSMs at {threshold*100:.0f}% FDR"] = (
                    f"{passing} ({pct:.1f}%)"
                )

            if "PSM_Type" in self.results_df.columns:
                targets = self.results_df[self.results_df["PSM_Type"] == "Target"]
                for threshold in [0.01, 0.05]:
                    passing = (targets["mokapot_qvalue"] <= threshold).sum()
                    fdr_stats[f"Target PSMs at {threshold*100:.0f}% FDR"] = str(passing)

            pep_valid = self.results_df["mokapot_PEP"].dropna()
            if len(pep_valid) > 0:
                fdr_stats["Mean PEP"] = f"{pep_valid.mean():.4f}"
                fdr_stats["Median PEP"] = f"{pep_valid.median():.4f}"

            stats["Mokapot FDR Control"] = fdr_stats

        return stats

    def populate_fdr_analysis(self):
        """Create FDR analysis plots: q-value curve and score distribution with FDR cutoffs."""
        if self.fdr_tab.layout():
            temp = QWidget(self)
            temp.setLayout(self.fdr_tab.layout())
            temp.deleteLater()

        layout = QVBoxLayout(self.fdr_tab)

        if "mokapot_qvalue" not in self.results_df.columns:
            no_data_label = QLabel(
                "No Mokapot FDR data available.\n"
                "Enable Mokapot FDR Control in Scoring Settings and re-run rescoring."
            )
            no_data_label.setStyleSheet(StyleSheet.get_label_style())
            no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_data_label)
            return

        if hasattr(self, "fdr_figure"):
            plt.close(self.fdr_figure)
        self.fdr_figure = Figure(figsize=(8, 6))
        self.fdr_canvas = FigureCanvas(self.fdr_figure)
        layout.addWidget(self.fdr_canvas)

        self._update_fdr_plots()

    def _update_fdr_plots(self):
        """Draw the FDR analysis plots."""
        self.fdr_figure.clear()
        self.fdr_figure.set_facecolor(EditorConstants.PLOT_BACKGROUND())

        df = self.results_df
        qvalues = df["mokapot_qvalue"].dropna().values

        # --- Cumulative discoveries vs q-value ---
        ax1 = self.fdr_figure.add_subplot(1, 1, 1)
        ax1.set_facecolor(EditorConstants.PLOT_BACKGROUND())

        try:
            import mokapot

            mokapot.plot_qvalues(
                qvalues, threshold=0.10, ax=ax1, color=EditorConstants.PRIMARY_BLUE()
            )
        except Exception:
            # Fallback: manual cumulative plot
            sorted_q = np.sort(qvalues)
            thresholded = sorted_q[sorted_q <= 0.10]
            counts = np.arange(1, len(thresholded) + 1)
            ax1.plot(thresholded, counts, color=EditorConstants.PRIMARY_BLUE())
            ax1.set_xlabel("q-value")
            ax1.set_ylabel("Discoveries")

        # Add FDR threshold lines
        for fdr_thresh, ls in [(0.01, "--"), (0.05, ":")]:
            n_pass = (qvalues <= fdr_thresh).sum()
            ax1.axvline(
                x=fdr_thresh,
                linestyle=ls,
                linewidth=1,
                color=EditorConstants.DANGER_COLOR(),
                alpha=0.8,
            )
            ax1.text(
                fdr_thresh + 0.002,
                ax1.get_ylim()[1] * 0.9,
                f"{fdr_thresh*100:.0f}% FDR\n({n_pass})",
                color=EditorConstants.DANGER_COLOR(),
                fontsize=8,
                va="top",
            )

        ax1.set_title("Cumulative Discoveries vs q-value")
        self._style_fdr_axis(ax1)

        self.fdr_figure.tight_layout()
        self.fdr_canvas.draw()

    def _style_fdr_axis(self, ax):
        """Apply theme colors to an FDR plot axis."""
        ax.tick_params(colors=EditorConstants.TEXT_COLOR())
        for spine in ax.spines.values():
            spine.set_color(EditorConstants.TEXT_COLOR())
        ax.xaxis.label.set_color(EditorConstants.TEXT_COLOR())
        ax.yaxis.label.set_color(EditorConstants.TEXT_COLOR())
        ax.title.set_color(EditorConstants.TEXT_COLOR())

    def populate_score_comparison(self):
        """Create scatter plot comparing Hyperscore vs Rescore"""
        # Clear existing layout
        if self.comparison_tab.layout():
            temp = QWidget(self)
            temp.setLayout(self.comparison_tab.layout())
            temp.deleteLater()

        layout = QVBoxLayout(self.comparison_tab)

        # Controls
        controls_layout = QHBoxLayout()

        # Group coloring option
        if "Group" in self.results_df.columns:
            self.color_by_group_cb = QCheckBox("Color by Group")
            self.color_by_group_cb.setStyleSheet(EditorConstants.get_checkbox_style())
            self.color_by_group_cb.stateChanged.connect(self.update_comparison_plot)
            controls_layout.addWidget(self.color_by_group_cb)

        # PSM Type coloring option
        if "PSM_Type" in self.results_df.columns:
            self.color_by_psm_type_cb = QCheckBox("Color by PSM Type (Target/Decoy)")
            self.color_by_psm_type_cb.setStyleSheet(
                EditorConstants.get_checkbox_style()
            )
            self.color_by_psm_type_cb.stateChanged.connect(self.update_comparison_plot)
            controls_layout.addWidget(self.color_by_psm_type_cb)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Create matplotlib figure
        if hasattr(self, "comparison_figure"):
            plt.close(self.comparison_figure)
        self.comparison_figure = Figure(figsize=(10, 8))
        self.comparison_canvas = FigureCanvas(self.comparison_figure)
        layout.addWidget(self.comparison_canvas)

        # Initial plot
        self.update_comparison_plot()

    def update_comparison_plot(self):
        """Update the score comparison plot"""
        self.comparison_figure.clear()

        # Apply theme colors to figure
        self.comparison_figure.set_facecolor(EditorConstants.PLOT_BACKGROUND())
        self.comparison_figure.set_edgecolor(EditorConstants.PLOT_FOREGROUND())

        ax = self.comparison_figure.add_subplot(111)
        ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())

        if (
            "Hyperscore" not in self.results_df.columns
            or "Rescore" not in self.results_df.columns
        ):
            ax.text(
                0.5,
                0.5,
                "Missing required score columns\n(Hyperscore and/or Rescore)",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color=EditorConstants.TEXT_COLOR(),
            )
            self.comparison_canvas.draw()
            return

        # Get valid data
        plot_data = self.results_df.dropna(subset=["Hyperscore", "Rescore"])
        if len(plot_data) == 0:
            ax.text(
                0.5,
                0.5,
                "No valid score data to plot",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color=EditorConstants.TEXT_COLOR(),
            )
            self.comparison_canvas.draw()
            return

        # Convert to numeric
        try:
            plot_data["Hyperscore"] = pd.to_numeric(
                plot_data["Hyperscore"], errors="coerce"
            )
            plot_data["Rescore"] = pd.to_numeric(plot_data["Rescore"], errors="coerce")
            plot_data = plot_data.dropna(subset=["Hyperscore", "Rescore"])
        except Exception as e:
            logger.error(f"Error converting scores to numeric: {e}")
            ax.text(
                0.5,
                0.5,
                "Error processing score data",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color=EditorConstants.TEXT_COLOR(),
            )
            self.comparison_canvas.draw()
            return

        if len(plot_data) == 0:
            ax.text(
                0.5,
                0.5,
                "No valid numeric score data to plot",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color=EditorConstants.TEXT_COLOR(),
            )
            self.comparison_canvas.draw()
            return

        # Determine coloring strategy
        color_by_group = (
            hasattr(self, "color_by_group_cb")
            and self.color_by_group_cb.isChecked()
            and "Group" in self.results_df.columns
        )

        color_by_psm_type = (
            hasattr(self, "color_by_psm_type_cb")
            and self.color_by_psm_type_cb.isChecked()
            and "PSM_Type" in self.results_df.columns
        )

        if color_by_psm_type:
            target_data = plot_data[plot_data["PSM_Type"] == "Target"]
            decoy_data = plot_data[plot_data["PSM_Type"] == "Decoy"]

            if len(target_data) > 0:
                ax.scatter(
                    target_data["Hyperscore"],
                    target_data["Rescore"],
                    label="Target",
                    alpha=0.6,
                    color="blue",
                    s=30,
                )
            if len(decoy_data) > 0:
                ax.scatter(
                    decoy_data["Hyperscore"],
                    decoy_data["Rescore"],
                    label="Decoy",
                    alpha=0.6,
                    color="red",
                    s=30,
                )
            ax.legend()

        elif color_by_group:
            groups = plot_data["Group"].unique()
            colors = plt.cm.Set1(np.linspace(0, 1, len(groups)))

            for group, color in zip(groups, colors):
                group_data = plot_data[plot_data["Group"] == group]
                ax.scatter(
                    group_data["Hyperscore"],
                    group_data["Rescore"],
                    label=group,
                    alpha=0.6,
                    color=color,
                    s=30,
                )
            ax.legend()
        else:
            ax.scatter(
                plot_data["Hyperscore"],
                plot_data["Rescore"],
                alpha=0.6,
                color="steelblue",
                s=30,
            )

        ax.set_xlabel(
            "Original Hyperscore", fontsize=12, color=EditorConstants.TEXT_COLOR()
        )
        ax.set_ylabel("Rescore", fontsize=12, color=EditorConstants.TEXT_COLOR())
        ax.set_title(
            "Score Comparison: Original Hyperscore vs Rescore",
            fontsize=14,
            fontweight="bold",
            color=EditorConstants.TEXT_COLOR(),
        )
        ax.grid(True, alpha=0.3, color=EditorConstants.GRID_COLOR())

        # Apply theme to all axes elements
        ax.tick_params(colors=EditorConstants.TEXT_COLOR(), which="both")
        for spine in ax.spines.values():
            spine.set_color(EditorConstants.TEXT_COLOR())
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_color(EditorConstants.TEXT_COLOR())

        # Update legend if it exists
        legend = ax.get_legend()
        if legend:
            legend.get_frame().set_facecolor(EditorConstants.LEGEND_BG())
            legend.get_frame().set_edgecolor(EditorConstants.LEGEND_BORDER())
            for text in legend.get_texts():
                text.set_color(EditorConstants.TEXT_COLOR())

        self.comparison_figure.tight_layout()
        self.comparison_canvas.draw()

    def set_fragment_export_data(self, debug_df, ion_config):
        """Store fragment data for optional export."""
        self.debug_df = debug_df
        self.ion_config = ion_config

    def export_data(self):
        """Export results CSV and, optionally, a companion long-format fragment CSV."""
        if self.results_df is None:
            UIHelpers.show_validation_error(
                self, "No Data", "No results data available to export."
            )
            return

        has_fragment_data = (
            self.debug_df is not None
            and self.ion_config is not None
            and "matched_fragments" in self.debug_df.columns
        )

        dialog = ExportOptionsDialog(
            ion_config=self.ion_config if has_fragment_data else None, parent=self
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Rescoring Results",
            "rescoring_results.csv",
            "CSV Files (*.csv);;All Files (*.*)",
        )
        if not file_path:
            return

        try:
            export_df = self.results_df.drop(
                columns=_EXPORT_DROP_COLUMNS, errors="ignore"
            )
            export_df.to_csv(file_path, index=False, encoding="utf-8-sig")
            msg = f"Results exported successfully!\n\n{len(export_df)} rows exported to:\n{file_path}"

            if has_fragment_data and dialog.include_fragments():
                frag_path = companion_fragment_path(file_path)
                frag_df = build_fragment_long_format(self.debug_df)
                frag_df.to_csv(frag_path, index=False, encoding="utf-8-sig")
                msg += (
                    f"\n\nFragment companion file ({len(frag_df)} ions):\n{frag_path}"
                )

            UIHelpers.show_success_message(self, msg)
        except Exception as e:
            UIHelpers.show_validation_error(
                self, "Export Error", f"Failed to export results: {str(e)}"
            )

    def update_theme(self, theme_name):
        """Update matplotlib figures with theme colors"""
        logger.debug(f"Updating results viewer theme to {theme_name}")

        # Update comparison figure if it exists
        if hasattr(self, "comparison_figure"):
            self.comparison_figure.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            self.comparison_figure.set_edgecolor(EditorConstants.PLOT_FOREGROUND())

            # Update all axes in the comparison figure
            for ax in self.comparison_figure.get_axes():
                ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
                ax.tick_params(colors=EditorConstants.TEXT_COLOR(), which="both")
                ax.spines["bottom"].set_color(EditorConstants.TEXT_COLOR())
                ax.spines["top"].set_color(EditorConstants.TEXT_COLOR())
                ax.spines["right"].set_color(EditorConstants.TEXT_COLOR())
                ax.spines["left"].set_color(EditorConstants.TEXT_COLOR())
                ax.xaxis.label.set_color(EditorConstants.TEXT_COLOR())
                ax.yaxis.label.set_color(EditorConstants.TEXT_COLOR())
                ax.title.set_color(EditorConstants.TEXT_COLOR())

                # Update tick label colors
                for label in ax.get_xticklabels() + ax.get_yticklabels():
                    label.set_color(EditorConstants.TEXT_COLOR())

                # Update legend if it exists
                legend = ax.get_legend()
                if legend:
                    legend.get_frame().set_facecolor(EditorConstants.LEGEND_BG())
                    legend.get_frame().set_edgecolor(EditorConstants.LEGEND_BORDER())
                    for text in legend.get_texts():
                        text.set_color(EditorConstants.TEXT_COLOR())

            # Redraw canvas
            if hasattr(self, "comparison_canvas"):
                self.comparison_canvas.draw()

        # Update interactive plot widget if it exists
        if hasattr(self, "interactive_plot_widget"):
            self.interactive_plot_widget.update_theme()

        # Update FDR analysis figure if it exists
        if hasattr(self, "fdr_figure"):
            self._update_fdr_plots()
