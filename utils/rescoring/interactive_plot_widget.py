from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QPushButton, QGroupBox, QGridLayout, QSpinBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
import pandas as pd
import numpy as np
import plotly.express as px
from utils.style.style import EditorConstants


class InteractivePlotWidget(QWidget):
    """Interactive Plotly scatter/histogram widget for rescoring results exploration."""

    # Columns always offered when present in the DataFrame
    ALLOWED_FIXED_COLUMNS = [
        'Charge', 'Observed M/Z', 'Hyperscore', 'Annotated_TIC_%', 'Rescore',
        'Consecutive_Series_Longest', 'Complementary_Pairs',
        'Morpheus_Score',
        'Length_Dependent_Normalized_Score',
    ]

    # Columns derived at load time
    DERIVED_COLUMNS = [
        'Peptide_Length', 'Consecutive_Series_Pct', 'Complementary_Pairs_Pct',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plot_df = None  # Working copy with derived columns
        self.init_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        # --- Controls group ---
        controls_group = QGroupBox("Plot Controls")
        controls_group.setStyleSheet(EditorConstants.get_groupbox_style())
        grid = QGridLayout(controls_group)
        grid.setSpacing(6)

        # Row 0: plot type, axis selectors, bins
        type_label = QLabel("Plot Type:")
        type_label.setStyleSheet(self._label_style())
        self.plot_type_combo = QComboBox()
        self.plot_type_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.plot_type_combo.addItems(["Scatter", "Histogram"])
        self.plot_type_combo.currentTextChanged.connect(self._on_plot_type_changed)

        x_label = QLabel("X Axis:")
        x_label.setStyleSheet(self._label_style())
        self.x_combo = QComboBox()
        self.x_combo.setStyleSheet(EditorConstants.get_combobox_style())

        self.y_label = QLabel("Y Axis:")
        self.y_label.setStyleSheet(self._label_style())
        self.y_combo = QComboBox()
        self.y_combo.setStyleSheet(EditorConstants.get_combobox_style())

        self.bins_label = QLabel("Bins:")
        self.bins_label.setStyleSheet(self._label_style())
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(5, 500)
        self.bins_spin.setValue(50)
        self.bins_spin.setStyleSheet(EditorConstants.get_lineedit_style())
        self.bins_label.setVisible(False)
        self.bins_spin.setVisible(False)

        grid.addWidget(type_label, 0, 0)
        grid.addWidget(self.plot_type_combo, 0, 1)
        grid.addWidget(x_label, 0, 2)
        grid.addWidget(self.x_combo, 0, 3)
        grid.addWidget(self.y_label, 0, 4)
        grid.addWidget(self.y_combo, 0, 5)
        grid.addWidget(self.bins_label, 0, 6)
        grid.addWidget(self.bins_spin, 0, 7)

        # Row 1: text filters
        pep_label = QLabel("Peptide filter:")
        pep_label.setStyleSheet(self._label_style())
        self.peptide_filter = QLineEdit()
        self.peptide_filter.setPlaceholderText("Substring search...")
        self.peptide_filter.setStyleSheet(EditorConstants.get_lineedit_style())

        prot_label = QLabel("Protein filter:")
        prot_label.setStyleSheet(self._label_style())
        self.protein_filter = QLineEdit()
        self.protein_filter.setPlaceholderText("Substring search...")
        self.protein_filter.setStyleSheet(EditorConstants.get_lineedit_style())

        grid.addWidget(pep_label, 1, 0)
        grid.addWidget(self.peptide_filter, 1, 1, 1, 3)
        grid.addWidget(prot_label, 1, 4)
        grid.addWidget(self.protein_filter, 1, 5, 1, 3)

        # Row 2: categorical filters (populated dynamically)
        group_label = QLabel("Group:")
        group_label.setStyleSheet(self._label_style())
        self.group_combo = QComboBox()
        self.group_combo.setStyleSheet(EditorConstants.get_combobox_style())

        rep_label = QLabel("Replicate:")
        rep_label.setStyleSheet(self._label_style())
        self.replicate_combo = QComboBox()
        self.replicate_combo.setStyleSheet(EditorConstants.get_combobox_style())

        psm_label = QLabel("PSM Type:")
        psm_label.setStyleSheet(self._label_style())
        self.psm_type_combo = QComboBox()
        self.psm_type_combo.setStyleSheet(EditorConstants.get_combobox_style())

        grid.addWidget(group_label, 2, 0)
        grid.addWidget(self.group_combo, 2, 1)
        grid.addWidget(rep_label, 2, 2)
        grid.addWidget(self.replicate_combo, 2, 3)
        grid.addWidget(psm_label, 2, 4)
        grid.addWidget(self.psm_type_combo, 2, 5)

        # Store label refs for dynamic show/hide
        self.group_label = group_label
        self.rep_label = rep_label
        self.psm_label = psm_label

        # Row 3: color-by selector + update button
        color_label = QLabel("Color By:")
        color_label.setStyleSheet(self._label_style())
        self.color_by_combo = QComboBox()
        self.color_by_combo.setStyleSheet(EditorConstants.get_combobox_style())
        self.color_by_combo.addItems(["Group", "PSM Type", "None"])
        self.color_label = color_label

        self.update_btn = QPushButton("Update Plot")
        self.update_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        self.update_btn.clicked.connect(self.update_plot)

        # Sample size selector (for scatter plots with large datasets)
        sample_label = QLabel("Sample Size:")
        sample_label.setStyleSheet(self._label_style())
        self.sample_size_spin = QSpinBox()
        self.sample_size_spin.setRange(100, 50000)
        self.sample_size_spin.setValue(2000)
        self.sample_size_spin.setSingleStep(500)
        self.sample_size_spin.setStyleSheet(EditorConstants.get_lineedit_style())
        self.sample_label = sample_label

        self.randomize_btn = QPushButton("Randomize")
        self.randomize_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))
        self.randomize_btn.clicked.connect(self.update_plot)

        grid.addWidget(color_label, 3, 0)
        grid.addWidget(self.color_by_combo, 3, 1)
        grid.addWidget(sample_label, 3, 2)
        grid.addWidget(self.sample_size_spin, 3, 3)
        grid.addWidget(self.randomize_btn, 3, 4)
        grid.addWidget(self.update_btn, 3, 5, 1, 2)

        layout.addWidget(controls_group)

        # --- Web view for Plotly ---
        self.web_view = QWebEngineView()
        self.web_view.setMinimumHeight(400)
        layout.addWidget(self.web_view, stretch=1)

        # Start with placeholder
        self.web_view.setHtml(self._placeholder_html(
            "Load rescoring results to enable interactive plots."))

    def _on_plot_type_changed(self, text):
        """Toggle Y-axis / bins visibility based on plot type."""
        is_histogram = text == "Histogram"
        self.y_label.setVisible(not is_histogram)
        self.y_combo.setVisible(not is_histogram)
        self.bins_label.setVisible(is_histogram)
        self.bins_spin.setVisible(is_histogram)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def load_data(self, df):
        """Accept a results DataFrame, compute derived columns, populate controls."""
        if df is None or df.empty:
            return

        self.plot_df = df.copy()
        self._compute_derived_columns()

        columns = self._detect_plottable_columns()
        self._populate_axis_combos(columns)
        self._populate_filter_combos()

        # Auto-plot with sensible defaults
        self.update_plot()

    def _compute_derived_columns(self):
        df = self.plot_df

        # Peptide length
        if 'Peptide' in df.columns:
            df['Peptide_Length'] = df['Peptide'].str.len()

        backbone = (df['Peptide_Length'] - 1).replace(0, np.nan) if 'Peptide_Length' in df.columns else None

        # Consecutive series as percentage
        if 'Consecutive_Series_Longest' in df.columns and backbone is not None:
            consec = pd.to_numeric(df['Consecutive_Series_Longest'], errors='coerce')
            df['Consecutive_Series_Pct'] = (consec / backbone * 100.0).round(2)

        # Complementary pairs as percentage — parse "5/12" string
        if 'Complementary_Pairs' in df.columns:
            parts = df['Complementary_Pairs'].astype(str).str.split('/', expand=True)
            if parts.shape[1] >= 2:
                pairs = pd.to_numeric(parts[0], errors='coerce')
                possible = pd.to_numeric(parts[1], errors='coerce').replace(0, np.nan)
                df['Complementary_Pairs_Pct'] = (pairs / possible * 100.0).round(2)

        # Sequence coverage count → percentage columns
        if backbone is not None:
            for col in list(df.columns):
                if col.startswith('sequence_coverage_count_'):
                    ion_type = col.replace('sequence_coverage_count_', '')
                    pct_col = f'sequence_coverage_pct_{ion_type}'
                    raw = pd.to_numeric(df[col], errors='coerce')
                    df[pct_col] = (raw / backbone * 100.0).round(2)

    def _detect_plottable_columns(self):
        df = self.plot_df
        columns = []
        for col in self.ALLOWED_FIXED_COLUMNS:
            if col in df.columns:
                columns.append(col)
        for col in self.DERIVED_COLUMNS:
            if col in df.columns:
                columns.append(col)
        for col in df.columns:
            if col in columns:
                continue
            if col.endswith('_count') or col.endswith('_unique_count'):
                columns.append(col)
            elif col.startswith('sequence_coverage_count_'):
                columns.append(col)
            elif col.startswith('sequence_coverage_pct_'):
                columns.append(col)
        return columns

    def _populate_axis_combos(self, columns):
        self.x_combo.blockSignals(True)
        self.y_combo.blockSignals(True)
        self.x_combo.clear()
        self.y_combo.clear()
        self.x_combo.addItems(columns)
        self.y_combo.addItems(columns)

        # Set sensible defaults
        if 'Hyperscore' in columns:
            self.x_combo.setCurrentText('Hyperscore')
        if 'Rescore' in columns:
            self.y_combo.setCurrentText('Rescore')

        self.x_combo.blockSignals(False)
        self.y_combo.blockSignals(False)

    def _populate_filter_combos(self):
        df = self.plot_df

        # Group filter
        if 'Group' in df.columns:
            self.group_combo.clear()
            self.group_combo.addItem("All Groups")
            for g in sorted(df['Group'].dropna().unique()):
                self.group_combo.addItem(str(g))
            self.group_combo.setVisible(True)
            self.group_label.setVisible(True)
        else:
            self.group_combo.setVisible(False)
            self.group_label.setVisible(False)

        # Replicate filter
        if 'Replicate' in df.columns:
            self.replicate_combo.clear()
            self.replicate_combo.addItem("All Replicates")
            for r in sorted(df['Replicate'].dropna().unique(), key=str):
                self.replicate_combo.addItem(str(r))
            self.replicate_combo.setVisible(True)
            self.rep_label.setVisible(True)
        else:
            self.replicate_combo.setVisible(False)
            self.rep_label.setVisible(False)

        # PSM Type filter
        if 'PSM_Type' in df.columns:
            self.psm_type_combo.clear()
            self.psm_type_combo.addItems(["All PSMs", "Target Only", "Decoy Only"])
            self.psm_type_combo.setVisible(True)
            self.psm_label.setVisible(True)
        else:
            self.psm_type_combo.setVisible(False)
            self.psm_label.setVisible(False)

        # Color-by options: dynamically populate based on available columns
        self.color_by_combo.blockSignals(True)
        self.color_by_combo.clear()
        color_options = ["None"]
        if 'Group' in df.columns:
            color_options.insert(0, "Group")
        if 'PSM_Type' in df.columns:
            color_options.insert(len(color_options) - 1, "PSM Type")
        self.color_by_combo.addItems(color_options)
        # Default to Group if available
        if 'Group' in df.columns:
            self.color_by_combo.setCurrentText("Group")
        self.color_by_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def _apply_filters(self):
        df = self.plot_df
        if df is None or df.empty:
            return pd.DataFrame()

        mask = pd.Series(True, index=df.index)

        # Peptide substring
        pep_text = self.peptide_filter.text().strip()
        if pep_text and 'Peptide' in df.columns:
            mask &= df['Peptide'].str.contains(pep_text, case=False, na=False)

        # Protein substring
        prot_text = self.protein_filter.text().strip()
        if prot_text and 'Protein' in df.columns:
            mask &= df['Protein'].astype(str).str.contains(prot_text, case=False, na=False)

        # Group dropdown
        if self.group_combo.isVisible() and self.group_combo.currentText() != "All Groups":
            mask &= df['Group'].astype(str) == self.group_combo.currentText()

        # Replicate dropdown
        if self.replicate_combo.isVisible() and self.replicate_combo.currentText() != "All Replicates":
            mask &= df['Replicate'].astype(str) == self.replicate_combo.currentText()

        # PSM Type dropdown
        if self.psm_type_combo.isVisible():
            sel = self.psm_type_combo.currentText()
            if sel == "Target Only":
                mask &= df['PSM_Type'] == 'Target'
            elif sel == "Decoy Only":
                mask &= df['PSM_Type'] == 'Decoy'

        return df[mask]

    # ------------------------------------------------------------------
    # Plot generation
    # ------------------------------------------------------------------
    def update_plot(self):
        if self.plot_df is None or self.plot_df.empty:
            self.web_view.setHtml(self._placeholder_html("No data loaded."))
            return

        if self.x_combo.count() == 0:
            self.web_view.setHtml(self._placeholder_html(
                "No plottable columns detected in dataset."))
            return

        filtered = self._apply_filters()
        if filtered.empty:
            self.web_view.setHtml(self._placeholder_html(
                "No data matches the current filters."))
            return

        is_histogram = self.plot_type_combo.currentText() == "Histogram"

        if is_histogram:
            self._render_histogram(filtered)
        else:
            self._render_scatter(filtered)

    def _render_scatter(self, filtered):
        x_col = self.x_combo.currentText()
        y_col = self.y_combo.currentText()

        plot_df = filtered.copy()
        plot_df[x_col] = pd.to_numeric(plot_df[x_col], errors='coerce')
        plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors='coerce')
        plot_df = plot_df.dropna(subset=[x_col, y_col])

        if plot_df.empty:
            self.web_view.setHtml(self._placeholder_html(
                f"No numeric data for {x_col} / {y_col} after filtering."))
            return

        # Determine color and symbol encoding
        color_col, symbol_col = self._resolve_color_symbol(plot_df)

        # Hover info
        hover_cols = [c for c in ['Peptide', 'Protein', 'Charge']
                      if c in plot_df.columns]

        try:
            len_data = len(plot_df)
            sample_msg = ""

            # Sample data if larger than selected sample size
            sample_size = self.sample_size_spin.value()
            if len_data > sample_size:
                plot_df = plot_df.sample(n=sample_size, random_state=None)
                sample_msg = f" (showing {sample_size:,} / {len_data:,} random points)"

            # Use scattergl for large datasets (>10k points) for better performance
            use_scattergl = len(plot_df) > 10000

            if use_scattergl:
                # scattergl doesn't support symbol parameter, so only use color
                fig = px.scatter(
                    plot_df,
                    x=x_col,
                    y=y_col,
                    color=color_col,
                    hover_data=hover_cols,
                    title=f"{y_col}  vs  {x_col}{sample_msg}",
                )
                # Change to scattergl type for GPU acceleration
                fig.update_traces(type='scattergl', marker=dict(size=6, opacity=0.7))
            else:
                fig = px.scatter(
                    plot_df,
                    x=x_col,
                    y=y_col,
                    color=color_col,
                    symbol=symbol_col,
                    hover_data=hover_cols,
                    title=f"{y_col}  vs  {x_col}{sample_msg}",
                )
                fig.update_traces(marker=dict(size=6, opacity=0.7))

            self._apply_theme_and_render(fig)
        except Exception as e:
            self.web_view.setHtml(self._placeholder_html(f"Plot error: {e}"))

    def _render_histogram(self, filtered):
        x_col = self.x_combo.currentText()

        plot_df = filtered.copy()
        plot_df[x_col] = pd.to_numeric(plot_df[x_col], errors='coerce')
        plot_df = plot_df.dropna(subset=[x_col])

        if plot_df.empty:
            self.web_view.setHtml(self._placeholder_html(
                f"No numeric data for {x_col} after filtering."))
            return

        nbins = self.bins_spin.value()
        color_col, _ = self._resolve_color_symbol(plot_df)

        try:
            fig = px.histogram(
                plot_df,
                x=x_col,
                color=color_col,
                nbins=nbins,
                barmode='overlay',
                title=f"Distribution of {x_col}",
                labels={x_col: x_col, 'count': 'Count'},
            )
            fig.update_traces(opacity=0.75)
            self._apply_theme_and_render(fig)
        except Exception as e:
            self.web_view.setHtml(self._placeholder_html(f"Plot error: {e}"))

    def _resolve_color_symbol(self, plot_df):
        """Determine color and symbol columns based on user selections."""
        color_sel = self.color_by_combo.currentText()
        color_col = None
        if color_sel == "Group" and 'Group' in plot_df.columns:
            color_col = 'Group'
        elif color_sel == "PSM Type" and 'PSM_Type' in plot_df.columns:
            color_col = 'PSM_Type'

        # Symbol by Replicate (scatter only, but harmless if unused)
        symbol_col = 'Replicate' if 'Replicate' in plot_df.columns else None

        return color_col, symbol_col

    def _apply_theme_and_render(self, fig):
        """Apply theme colours and render to web view."""
        bg_color = EditorConstants.PLOT_BACKGROUND()
        text_color = EditorConstants.TEXT_COLOR()
        grid_color = EditorConstants.GRID_COLOR()

        fig.update_layout(
            paper_bgcolor=bg_color,
            plot_bgcolor=bg_color,
            font_color=text_color,
            title_font_color=text_color,
            legend_font_color=text_color,
            xaxis=dict(
                gridcolor=grid_color,
                zerolinecolor=grid_color,
                title_font_color=text_color,
                tickfont_color=text_color,
            ),
            yaxis=dict(
                gridcolor=grid_color,
                zerolinecolor=grid_color,
                title_font_color=text_color,
                tickfont_color=text_color,
            ),
            margin=dict(l=60, r=30, t=50, b=50),
        )

        html = fig.to_html(include_plotlyjs='cdn', full_html=True)
        self.web_view.setHtml(html)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def update_theme(self):
        """Re-apply styles and re-render the current plot."""
        for combo in [self.x_combo, self.y_combo, self.group_combo,
                      self.replicate_combo, self.psm_type_combo,
                      self.plot_type_combo, self.color_by_combo]:
            combo.setStyleSheet(EditorConstants.get_combobox_style())

        for le in [self.peptide_filter, self.protein_filter]:
            le.setStyleSheet(EditorConstants.get_lineedit_style())

        self.bins_spin.setStyleSheet(EditorConstants.get_lineedit_style())
        self.sample_size_spin.setStyleSheet(EditorConstants.get_lineedit_style())
        self.update_btn.setStyleSheet(EditorConstants.get_pushbutton_style("primary"))
        self.randomize_btn.setStyleSheet(EditorConstants.get_pushbutton_style("secondary"))

        for lbl in [self.group_label, self.rep_label, self.psm_label,
                    self.color_label, self.y_label, self.bins_label, self.sample_label]:
            lbl.setStyleSheet(self._label_style())

        for child in self.findChildren(QGroupBox):
            child.setStyleSheet(EditorConstants.get_groupbox_style())

        # Re-render plot with new colours
        self.update_plot()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _label_style():
        return f"""
            QLabel {{
                color: {EditorConstants.TEXT_COLOR()};
                font-size: 12px;
                padding: 2px;
            }}
        """

    @staticmethod
    def _placeholder_html(message):
        bg = EditorConstants.PLOT_BACKGROUND()
        fg = EditorConstants.TEXT_COLOR()
        return f"""
        <html>
        <body style="background-color:{bg}; color:{fg};
                     display:flex; align-items:center; justify-content:center;
                     height:100vh; margin:0; font-family:sans-serif;">
            <h3 style="text-align:center;">{message}</h3>
        </body>
        </html>
        """
