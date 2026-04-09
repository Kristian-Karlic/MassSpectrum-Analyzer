import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTabWidget,
    QLabel, QGroupBox, QScrollArea, QComboBox, QCheckBox, QFileDialog
)

from utils.utilities import UIHelpers
from utils.style.style import StyleSheet, EditorConstants
from utils.rescoring.interactive_plot_widget import InteractivePlotWidget
from utils.rescoring.export_options_dialog import ExportOptionsDialog, build_fragment_columns



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
        self.export_data_button.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
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
        
        self.histogram_tab = QWidget()
        self.tab_widget.addTab(self.histogram_tab, "Score Histograms")

        self.interactive_tab = QWidget()
        self.tab_widget.addTab(self.interactive_tab, "Interactive Plots")
        
    def load_results_dataframe(self, df):
        """Load results from a dataframe (called by RescoringTabManager)"""
        try:
            self.original_df = df
            self.results_df = self.original_df.copy()
            self.filtered_df = self.results_df.copy()  # Keep for potential future use
            required_cols = ['Rescore', 'Annotated_TIC_%']
            missing_cols = []
            for col in required_cols:
                if col not in self.results_df.columns:
                    missing_cols.append(col)
                
            if missing_cols:
                UIHelpers.show_validation_error(
                    self,
                    "Invalid Data",
                    f"Missing required columns: {', '.join(missing_cols)}"
                )
                return
            
            # Update info label
            info_text = f"Showing {len(self.results_df)} results"
            if 'PSM_Type' in self.results_df.columns:
                decoy_count = (self.results_df['PSM_Type'] == 'Decoy').sum()
                target_count = (self.results_df['PSM_Type'] == 'Target').sum()
                info_text += f" ({target_count} Targets, {decoy_count} Decoys)"
            self.info_label.setText(info_text)
            
            # Enable export button
            self.export_data_button.setEnabled(True)
            
            # Populate analysis tabs only
            self.populate_summary_stats()
            self.populate_score_comparison()
            self.populate_histograms()
            self.populate_interactive_plots()
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"[ERROR] Error loading results: {error_details}")
            UIHelpers.show_validation_error(
                self,
                "Processing Error",
                f"Error processing loaded data: {str(e)}"
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
            QWidget().setLayout(self.stats_tab.layout())
        
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
        
        # Basic counts
        basic_stats = {
            "Total PSMs": len(self.results_df),
            "Unique Peptides": self.results_df['Peptide'].nunique() if 'Peptide' in self.results_df.columns else "N/A",
            "Unique Proteins": self.results_df['Protein'].nunique() if 'Protein' in self.results_df.columns else "N/A"
        }
        
        # Add decoy statistics if available
        if 'PSM_Type' in self.results_df.columns:
            decoy_count = (self.results_df['PSM_Type'] == 'Decoy').sum()
            target_count = (self.results_df['PSM_Type'] == 'Target').sum()
            basic_stats.update({
                "Target PSMs": f"{target_count} ({target_count/len(self.results_df)*100:.1f}%)",
                "Decoy PSMs": f"{decoy_count} ({decoy_count/len(self.results_df)*100:.1f}%)"
            })
        
        stats["Dataset Overview"] = basic_stats
                
        if 'Hyperscore' in self.results_df.columns and 'Rescore' in self.results_df.columns and 'Annotated_TIC_%' in self.results_df.columns:
            valid_data = self.results_df.dropna(subset=['Hyperscore', 'Rescore', 'Annotated_TIC_%'])
            
            improvement_stats = {
                "Mean Original Hyperscore": f"{valid_data['Hyperscore'].mean():.3f}",
                "Mean Rescore": f"{valid_data['Rescore'].mean():.3f}",
                "Mean Annotated TIC": f"{valid_data['Annotated_TIC_%'].mean():.2f}%",
                "Median Original Hyperscore": f"{valid_data['Hyperscore'].median():.3f}",
                "Median Rescore": f"{valid_data['Rescore'].median():.3f}",
                "Median Annotated TIC": f"{valid_data['Annotated_TIC_%'].median():.2f}%"
            }
            
            if 'PSM_Type' in self.results_df.columns:
                target_data = valid_data[valid_data['PSM_Type'] == 'Target']
                decoy_data = valid_data[valid_data['PSM_Type'] == 'Decoy']
                
                if len(target_data) > 0:
                    improvement_stats["Target Mean Rescore"] = f"{target_data['Rescore'].mean():.3f}"
                    improvement_stats["Target Mean Annotated TIC"] = f"{target_data['Annotated_TIC_%'].mean():.2f}%"
                
                if len(decoy_data) > 0:
                    improvement_stats["Decoy Mean Rescore"] = f"{decoy_data['Rescore'].mean():.3f}"
                    improvement_stats["Decoy Mean Annotated TIC"] = f"{decoy_data['Annotated_TIC_%'].mean():.2f}%"
            
            stats["Scoring Metrics"] = improvement_stats
                
        # Score distributions
        if 'Hyperscore' in self.results_df.columns:
            hyperscore_valid = self.results_df['Hyperscore'].dropna()
            stats["Hyperscore Statistics"] = {
                "Mean": f"{hyperscore_valid.mean():.3f}",
                "Median": f"{hyperscore_valid.median():.3f}",
                "Std Dev": f"{hyperscore_valid.std():.3f}",
                "Min": f"{hyperscore_valid.min():.3f}",
                "Max": f"{hyperscore_valid.max():.3f}"
            }
        
        if 'Rescore' in self.results_df.columns:
            rescore_valid = self.results_df['Rescore'].dropna()
            stats["Rescore Statistics"] = {
                "Mean": f"{rescore_valid.mean():.3f}",
                "Median": f"{rescore_valid.median():.3f}",
                "Std Dev": f"{rescore_valid.std():.3f}",
                "Min": f"{rescore_valid.min():.3f}",
                "Max": f"{rescore_valid.max():.3f}"
            }
            
        # Intensity statistics if available
        if 'Max_Intensity' in self.results_df.columns and 'Total_Intensity' in self.results_df.columns:
            max_int_valid = self.results_df['Max_Intensity'].dropna()
            total_int_valid = self.results_df['Total_Intensity'].dropna()
            stats["Intensity Statistics"] = {
                "Mean Max Intensity": f"{max_int_valid.mean():.1f}",
                "Median Max Intensity": f"{max_int_valid.median():.1f}",
                "Mean Total Intensity": f"{total_int_valid.mean():.1f}",
                "Median Total Intensity": f"{total_int_valid.median():.1f}",
            }

        # Group-based statistics if available
        if 'Group' in self.results_df.columns:
            group_counts = self.results_df['Group'].value_counts()
            stats["Group Distribution"] = {
                f"Group '{group}'": f"{count} PSMs" 
                for group, count in group_counts.items()
            }
        
        return stats
    
    def populate_score_comparison(self):
        """Create scatter plot comparing Hyperscore vs Rescore"""
        # Clear existing layout
        if self.comparison_tab.layout():
            QWidget().setLayout(self.comparison_tab.layout())
        
        layout = QVBoxLayout(self.comparison_tab)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        # Group coloring option
        if 'Group' in self.results_df.columns:
            self.color_by_group_cb = QCheckBox("Color by Group")
            self.color_by_group_cb.setStyleSheet(EditorConstants.get_checkbox_style())
            self.color_by_group_cb.stateChanged.connect(self.update_comparison_plot)
            controls_layout.addWidget(self.color_by_group_cb)
        
        # PSM Type coloring option
        if 'PSM_Type' in self.results_df.columns:
            self.color_by_psm_type_cb = QCheckBox("Color by PSM Type (Target/Decoy)")
            self.color_by_psm_type_cb.setStyleSheet(EditorConstants.get_checkbox_style())
            self.color_by_psm_type_cb.stateChanged.connect(self.update_comparison_plot)
            controls_layout.addWidget(self.color_by_psm_type_cb)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Create matplotlib figure
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
        
        if 'Hyperscore' not in self.results_df.columns or 'Rescore' not in self.results_df.columns:
            ax.text(0.5, 0.5, 'Missing required score columns\n(Hyperscore and/or Rescore)', 
                transform=ax.transAxes, ha='center', va='center', color=EditorConstants.TEXT_COLOR())
            self.comparison_canvas.draw()
            return
        
        # Get valid data
        plot_data = self.results_df.dropna(subset=['Hyperscore', 'Rescore'])
        if len(plot_data) == 0:
            ax.text(0.5, 0.5, 'No valid score data to plot', 
                transform=ax.transAxes, ha='center', va='center', color=EditorConstants.TEXT_COLOR())
            self.comparison_canvas.draw()
            return
        
        # Convert to numeric
        try:
            plot_data['Hyperscore'] = pd.to_numeric(plot_data['Hyperscore'], errors='coerce')
            plot_data['Rescore'] = pd.to_numeric(plot_data['Rescore'], errors='coerce')
            plot_data = plot_data.dropna(subset=['Hyperscore', 'Rescore'])
        except Exception as e:
            print(f"[ERROR] Error converting scores to numeric: {e}")
            ax.text(0.5, 0.5, 'Error processing score data', 
                transform=ax.transAxes, ha='center', va='center', color=EditorConstants.TEXT_COLOR())
            self.comparison_canvas.draw()
            return
        
        if len(plot_data) == 0:
            ax.text(0.5, 0.5, 'No valid numeric score data to plot', 
                transform=ax.transAxes, ha='center', va='center', color=EditorConstants.TEXT_COLOR())
            self.comparison_canvas.draw()
            return
        
        # Determine coloring strategy
        color_by_group = (hasattr(self, 'color_by_group_cb') and 
                        self.color_by_group_cb.isChecked() and 
                        'Group' in self.results_df.columns)
        
        color_by_psm_type = (hasattr(self, 'color_by_psm_type_cb') and 
                            self.color_by_psm_type_cb.isChecked() and 
                            'PSM_Type' in self.results_df.columns)
        
        if color_by_psm_type:
            target_data = plot_data[plot_data['PSM_Type'] == 'Target']
            decoy_data = plot_data[plot_data['PSM_Type'] == 'Decoy']
            
            if len(target_data) > 0:
                ax.scatter(target_data['Hyperscore'], target_data['Rescore'], 
                        label='Target', alpha=0.6, color='blue', s=30)
            if len(decoy_data) > 0:
                ax.scatter(decoy_data['Hyperscore'], decoy_data['Rescore'], 
                        label='Decoy', alpha=0.6, color='red', s=30)
            ax.legend()
            
        elif color_by_group:
            groups = plot_data['Group'].unique()
            colors = plt.cm.Set1(np.linspace(0, 1, len(groups)))
            
            for group, color in zip(groups, colors):
                group_data = plot_data[plot_data['Group'] == group]
                ax.scatter(group_data['Hyperscore'], group_data['Rescore'], 
                        label=group, alpha=0.6, color=color, s=30)
            ax.legend()
        else:
            ax.scatter(plot_data['Hyperscore'], plot_data['Rescore'], 
                    alpha=0.6, color='steelblue', s=30)
        
        ax.set_xlabel('Original Hyperscore', fontsize=12, color=EditorConstants.TEXT_COLOR())
        ax.set_ylabel('Rescore', fontsize=12, color=EditorConstants.TEXT_COLOR())
        ax.set_title('Score Comparison: Original Hyperscore vs Rescore', fontsize=14, fontweight='bold', color=EditorConstants.TEXT_COLOR())
        ax.grid(True, alpha=0.3, color=EditorConstants.GRID_COLOR())
        
        # Apply theme to all axes elements
        ax.tick_params(colors=EditorConstants.TEXT_COLOR(), which='both')
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
    
    def populate_histograms(self):
        """Create histograms comparing score distributions"""
        # Clear existing layout
        if self.histogram_tab.layout():
            QWidget().setLayout(self.histogram_tab.layout())
        
        layout = QVBoxLayout(self.histogram_tab)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        # Group selection
        if 'Group' in self.results_df.columns:
            group_label = QLabel("Show Group:")
            group_label.setStyleSheet(StyleSheet.get_label_style())
            controls_layout.addWidget(group_label)
            
            self.group_combo = QComboBox()
            self.group_combo.setStyleSheet(EditorConstants.get_combobox_style())
            self.group_combo.addItem("All Groups")
            self.group_combo.addItems(sorted(self.results_df['Group'].unique()))
            self.group_combo.currentTextChanged.connect(self.update_histograms)
            controls_layout.addWidget(self.group_combo)
        
        # PSM Type selection
        if 'PSM_Type' in self.results_df.columns:
            psm_type_label = QLabel("Show PSM Type:")
            psm_type_label.setStyleSheet(StyleSheet.get_label_style())
            controls_layout.addWidget(psm_type_label)
            
            self.psm_type_combo = QComboBox()
            self.psm_type_combo.setStyleSheet(EditorConstants.get_combobox_style())
            self.psm_type_combo.addItem("All PSMs")
            self.psm_type_combo.addItem("Target Only")
            self.psm_type_combo.addItem("Decoy Only")
            self.psm_type_combo.addItem("Separate Target/Decoy")
            self.psm_type_combo.currentTextChanged.connect(self.update_histograms)
            controls_layout.addWidget(self.psm_type_combo)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Create matplotlib figure
        self.histogram_figure = Figure(figsize=(12, 8))
        self.histogram_canvas = FigureCanvas(self.histogram_figure)
        layout.addWidget(self.histogram_canvas)
        
        # Initial plot
        self.update_histograms()
    
    def update_histograms(self):
        """Update histogram plots"""
        self.histogram_figure.clear()
        
        # Apply theme colors to figure
        self.histogram_figure.set_facecolor(EditorConstants.PLOT_BACKGROUND())
        self.histogram_figure.set_edgecolor(EditorConstants.PLOT_FOREGROUND())
        
        if 'Hyperscore' not in self.results_df.columns or 'Rescore' not in self.results_df.columns:
            ax = self.histogram_figure.add_subplot(111)
            ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            ax.text(0.5, 0.5, 'Missing required score columns\n(Hyperscore and/or Rescore)', 
                transform=ax.transAxes, ha='center', va='center', color=EditorConstants.TEXT_COLOR())
            self.histogram_canvas.draw()
            return
        
        # Filter data by selected group
        plot_data = self.results_df.copy()
        title_suffix = ""
        
        if (hasattr(self, 'group_combo') and 
            self.group_combo.currentText() != "All Groups"):
            selected_group = self.group_combo.currentText()
            plot_data = plot_data[plot_data['Group'] == selected_group]
            title_suffix += f" - Group: {selected_group}"
        
        # Filter by PSM type if available
        psm_type_filter = None
        if hasattr(self, 'psm_type_combo'):
            psm_type_selection = self.psm_type_combo.currentText()
            if psm_type_selection == "Target Only":
                plot_data = plot_data[plot_data['PSM_Type'] == 'Target']
                title_suffix += " - Target PSMs"
            elif psm_type_selection == "Decoy Only":
                plot_data = plot_data[plot_data['PSM_Type'] == 'Decoy']
                title_suffix += " - Decoy PSMs"
            elif psm_type_selection == "Separate Target/Decoy":
                psm_type_filter = "separate"
                title_suffix += " - Target vs Decoy"
        
        # Get valid data and convert to numeric
        valid_data = plot_data.dropna(subset=['Hyperscore', 'Rescore'])
        
        try:
            valid_data['Hyperscore'] = pd.to_numeric(valid_data['Hyperscore'], errors='coerce')
            valid_data['Rescore'] = pd.to_numeric(valid_data['Rescore'], errors='coerce')
            valid_data = valid_data.dropna(subset=['Hyperscore', 'Rescore'])
        except Exception as e:
            print(f"[ERROR] Error converting scores to numeric: {e}")
            ax = self.histogram_figure.add_subplot(111)
            ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            ax.text(0.5, 0.5, 'Error processing score data', 
                transform=ax.transAxes, ha='center', va='center', color=EditorConstants.TEXT_COLOR())
            self.histogram_canvas.draw()
            return
        
        if len(valid_data) == 0:
            ax = self.histogram_figure.add_subplot(111)
            ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            ax.text(0.5, 0.5, 'No valid data to plot', 
                transform=ax.transAxes, ha='center', va='center', color=EditorConstants.TEXT_COLOR())
            self.histogram_canvas.draw()
            return
        
        # Create subplots based on whether we're separating target/decoy
        if psm_type_filter == "separate" and 'PSM_Type' in valid_data.columns:
            target_data = valid_data[valid_data['PSM_Type'] == 'Target']
            decoy_data = valid_data[valid_data['PSM_Type'] == 'Decoy']
            
            if len(target_data) == 0 and len(decoy_data) == 0:
                ax = self.histogram_figure.add_subplot(111)
                ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
                ax.text(0.5, 0.5, 'No target or decoy data to plot', 
                    transform=ax.transAxes, ha='center', va='center', color=EditorConstants.TEXT_COLOR())
                self.histogram_canvas.draw()
                return
            
            # Create 2x2 subplot layout
            ax1 = self.histogram_figure.add_subplot(2, 2, 1)
            ax2 = self.histogram_figure.add_subplot(2, 2, 2)
            ax3 = self.histogram_figure.add_subplot(2, 2, 3)
            ax4 = self.histogram_figure.add_subplot(2, 2, 4)
            
            # Hyperscore comparison
            if len(target_data) > 0:
                ax1.hist(target_data['Hyperscore'], bins=30, alpha=0.6, 
                        label='Target', color='blue', edgecolor=EditorConstants.EDGE_COLOR())
            if len(decoy_data) > 0:
                ax1.hist(decoy_data['Hyperscore'], bins=30, alpha=0.6, 
                        label='Decoy', color='red', edgecolor=EditorConstants.EDGE_COLOR())
            ax1.set_xlabel('Hyperscore')
            ax1.set_ylabel('Frequency')
            ax1.set_title('Hyperscore: Target vs Decoy')
            ax1.legend()
            
            # Rescore comparison
            if len(target_data) > 0:
                ax2.hist(target_data['Rescore'], bins=30, alpha=0.6, 
                        label='Target', color='blue', edgecolor=EditorConstants.EDGE_COLOR())
            if len(decoy_data) > 0:
                ax2.hist(decoy_data['Rescore'], bins=30, alpha=0.6, 
                        label='Decoy', color='red', edgecolor=EditorConstants.EDGE_COLOR())
            ax2.set_xlabel('Rescore')
            ax2.set_ylabel('Frequency')
            ax2.set_title('Rescore: Target vs Decoy')
            ax2.legend()
            
            # Target comparison
            if len(target_data) > 0:
                ax3.hist(target_data['Hyperscore'], bins=30, alpha=0.6, 
                        label='Hyperscore', color='lightblue', edgecolor=EditorConstants.EDGE_COLOR())
                ax3.hist(target_data['Rescore'], bins=30, alpha=0.6, 
                        label='Rescore', color='darkblue', edgecolor=EditorConstants.EDGE_COLOR())
                ax3.set_xlabel('Score')
                ax3.set_ylabel('Frequency')
                ax3.set_title('Target PSMs: Score Comparison')
                ax3.legend()
            
            # Decoy comparison
            if len(decoy_data) > 0:
                ax4.hist(decoy_data['Hyperscore'], bins=30, alpha=0.6, 
                        label='Hyperscore', color='lightcoral', edgecolor=EditorConstants.EDGE_COLOR())
                ax4.hist(decoy_data['Rescore'], bins=30, alpha=0.6, 
                        label='Rescore', color='darkred', edgecolor=EditorConstants.EDGE_COLOR())
                ax4.set_xlabel('Score')
                ax4.set_ylabel('Frequency')
                ax4.set_title('Decoy PSMs: Score Comparison')
                ax4.legend()
            
            # Apply theme to all axes
            self._apply_theme_to_axes([ax1, ax2, ax3, ax4])
            
        else:
            ax1 = self.histogram_figure.add_subplot(2, 2, 1)
            ax2 = self.histogram_figure.add_subplot(2, 2, 2)
            ax3 = self.histogram_figure.add_subplot(2, 1, 2)
            
            # Hyperscore histogram
            ax1.hist(valid_data['Hyperscore'], bins=30, alpha=0.7, color='blue', edgecolor=EditorConstants.EDGE_COLOR())
            ax1.set_xlabel('Original Hyperscore')
            ax1.set_ylabel('Frequency')
            ax1.set_title('Original Hyperscore Distribution')
            
            # Rescore histogram
            ax2.hist(valid_data['Rescore'], bins=30, alpha=0.7, color='red', edgecolor=EditorConstants.EDGE_COLOR())
            ax2.set_xlabel('Rescore')
            ax2.set_ylabel('Frequency')
            ax2.set_title('Rescore Distribution')
            
            # Overlaid histograms
            ax3.hist(valid_data['Hyperscore'], bins=30, alpha=0.6, label='Original Hyperscore', color='blue', edgecolor=EditorConstants.EDGE_COLOR())
            ax3.hist(valid_data['Rescore'], bins=30, alpha=0.6, label='Rescore', color='red', edgecolor=EditorConstants.EDGE_COLOR())
            ax3.set_xlabel('Score')
            ax3.set_ylabel('Frequency')
            ax3.set_title('Score Distribution Comparison')
            ax3.legend()
            
            # Apply theme to all axes
            self._apply_theme_to_axes([ax1, ax2, ax3])
        
        # Set overall title
        main_title = 'Score Distributions'
        if title_suffix:
            main_title += title_suffix
        else:
            main_title += ' - All Data'
            
        self.histogram_figure.suptitle(main_title, fontsize=14, fontweight='bold', color=EditorConstants.TEXT_COLOR())
        self.histogram_figure.tight_layout()
        self.histogram_canvas.draw()
    
    def _apply_theme_to_axes(self, axes_list):
        """Apply theme colors to a list of matplotlib axes"""
        for ax in axes_list:
            ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            ax.tick_params(colors=EditorConstants.TEXT_COLOR(), which='both')
            
            # Update spines
            for spine in ax.spines.values():
                spine.set_color(EditorConstants.TEXT_COLOR())
            
            # Update labels
            ax.xaxis.label.set_color(EditorConstants.TEXT_COLOR())
            ax.yaxis.label.set_color(EditorConstants.TEXT_COLOR())
            ax.title.set_color(EditorConstants.TEXT_COLOR())
            
            # Update tick labels
            for label in ax.get_xticklabels() + ax.get_yticklabels():
                label.set_color(EditorConstants.TEXT_COLOR())
            
            # Update legend if it exists
            legend = ax.get_legend()
            if legend:
                legend.get_frame().set_facecolor(EditorConstants.LEGEND_BG())
                legend.get_frame().set_edgecolor(EditorConstants.LEGEND_BORDER())
                for text in legend.get_texts():
                    text.set_color(EditorConstants.TEXT_COLOR())
            
            # Update grid color
            ax.grid(True, alpha=0.3, color=EditorConstants.GRID_COLOR())
    
    def set_fragment_export_data(self, debug_df, ion_config):
        """Store fragment data for optional export."""
        self.debug_df = debug_df
        self.ion_config = ion_config

    def export_data(self):
        """Export results with optional matched fragment detail columns."""
        if self.results_df is None:
            UIHelpers.show_validation_error(
                self,
                "No Data",
                "No results data available to export."
            )
            return

        has_fragment_data = (self.debug_df is not None and self.ion_config is not None
                            and 'matched_fragments' in self.debug_df.columns)

        dialog = ExportOptionsDialog(
            ion_config=self.ion_config if has_fragment_data else None,
            parent=self
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Rescoring Results",
            "rescoring_results.csv",
            "CSV Files (*.csv);;All Files (*.*)"
        )
        if not file_path:
            return

        try:
            export_df = self.results_df.copy()
            selected_groups = dialog.get_selected_groups()
            if has_fragment_data and selected_groups:
                fragment_df = build_fragment_columns(self.debug_df, selected_groups)
                export_df = export_df.join(fragment_df, how='left')
            export_df.to_csv(file_path, index=False)
            UIHelpers.show_success_message(
                self,
                f"Results exported successfully!\n\n{len(export_df)} rows exported to:\n{file_path}"
            )
        except Exception as e:
            UIHelpers.show_validation_error(
                self,
                "Export Error",
                f"Failed to export results: {str(e)}"
            )
    
    def update_theme(self, theme_name):
        """Update matplotlib figures with theme colors"""
        print(f"[DEBUG] Updating results viewer theme to {theme_name}")
        
        # Update comparison figure if it exists
        if hasattr(self, 'comparison_figure'):
            self.comparison_figure.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            self.comparison_figure.set_edgecolor(EditorConstants.PLOT_FOREGROUND())
            
            # Update all axes in the comparison figure
            for ax in self.comparison_figure.get_axes():
                ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
                ax.tick_params(colors=EditorConstants.TEXT_COLOR(), which='both')
                ax.spines['bottom'].set_color(EditorConstants.TEXT_COLOR())
                ax.spines['top'].set_color(EditorConstants.TEXT_COLOR())
                ax.spines['right'].set_color(EditorConstants.TEXT_COLOR())
                ax.spines['left'].set_color(EditorConstants.TEXT_COLOR())
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
            if hasattr(self, 'comparison_canvas'):
                self.comparison_canvas.draw()
        
        # Update histogram figure if it exists
        if hasattr(self, 'histogram_figure'):
            self.histogram_figure.set_facecolor(EditorConstants.PLOT_BACKGROUND())
            self.histogram_figure.set_edgecolor(EditorConstants.PLOT_FOREGROUND())
            
            # Update all axes in the histogram figure
            for ax in self.histogram_figure.get_axes():
                ax.set_facecolor(EditorConstants.PLOT_BACKGROUND())
                ax.tick_params(colors=EditorConstants.TEXT_COLOR(), which='both')
                ax.spines['bottom'].set_color(EditorConstants.TEXT_COLOR())
                ax.spines['top'].set_color(EditorConstants.TEXT_COLOR())
                ax.spines['right'].set_color(EditorConstants.TEXT_COLOR())
                ax.spines['left'].set_color(EditorConstants.TEXT_COLOR())
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
            
            # Update suptitle if it exists
            if self.histogram_figure._suptitle:
                self.histogram_figure._suptitle.set_color(EditorConstants.TEXT_COLOR())
            
            # Redraw canvas
            if hasattr(self, 'histogram_canvas'):
                self.histogram_canvas.draw()

        # Update interactive plot widget if it exists
        if hasattr(self, 'interactive_plot_widget'):
            self.interactive_plot_widget.update_theme()
        