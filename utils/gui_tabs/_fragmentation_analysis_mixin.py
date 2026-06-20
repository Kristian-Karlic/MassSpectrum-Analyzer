"""
_FragmentationAnalysisMixin
---------------------------
Analysis engine and chart/plot rendering for the fragmentation tab.
Covers: create_multi_group_bar_chart_with_custom_names, show_comparison_message,
update_bar_chart_plot, calculate_group_analysis, run_fragmentation_analysis,
count_ions_by_type, _ion_type_matches_selected, create_isotope_ratio_plot,
get_raw_spectral_data, generate_comprehensive_ion_types,
calculate_isotope_ratios_by_position, create_isotope_ratio_scatter_plot.
"""

import re
import logging
import traceback
from collections import defaultdict
import numpy as np
import pandas as pd
from matplotlib.ticker import MultipleLocator
import matplotlib.colors as mcolors
from utils.style.style import EditorConstants
from utils.peak_matching.peptide_fragmentation import (
    calculate_fragment_ions,
    match_fragment_ions,
)
from utils.utilities import DataGatherer

logger = logging.getLogger(__name__)


class _FragmentationAnalysisMixin:

    def create_multi_group_bar_chart_with_custom_names(
        self, all_group_counts, selected_ions, group_colors, custom_names
    ):
        """Create a multi-group bar chart with custom group names - ENHANCED for single group support"""

        logger.debug(
            f"Creating bar chart for {len(custom_names)} group(s): {custom_names}"
        )

        # Validate that we have data
        if not all_group_counts or not custom_names or not group_colors:
            self.show_comparison_message("No groups with data found for analysis")
            return

        # Ensure all arrays have the same length
        n_groups = len(custom_names)
        if len(all_group_counts) != n_groups or len(group_colors) != n_groups:
            logger.error(
                f"Mismatch in group data lengths: counts={len(all_group_counts)}, names={len(custom_names)}, colors={len(group_colors)}"
            )
            self.show_comparison_message("Error: Inconsistent group data")
            return

        self.comparison_figure.clear()

        # Filter out ion types with zero counts in all groups
        active_ions = []
        for ion_type in selected_ions:
            has_data = False
            for group_counts in all_group_counts.values():
                if group_counts.get(ion_type) and np.mean(group_counts[ion_type]) > 0:
                    has_data = True
                    break
            if has_data:
                active_ions.append(ion_type)

        if not active_ions:
            self.show_comparison_message("No ion counts found for selected ion types")
            return

        ax = self.comparison_figure.add_subplot(111)

        # Apply theme-aware styling to axes
        self._apply_theme_to_axes(ax)

        # Use the actual groups that have data
        original_keys = list(all_group_counts.keys())
        n_ions = len(active_ions)

        logger.debug(f"Plotting {n_groups} group(s) with {n_ions} ion types")
        logger.debug(f"Groups: {original_keys}")
        logger.debug(f"Custom names: {custom_names}")

        # Calculate means for each group and ion type
        data_matrix = np.zeros((n_groups, n_ions))
        error_matrix = np.zeros((n_groups, n_ions))

        for i, original_key in enumerate(original_keys):
            if original_key not in all_group_counts:
                logger.error(f"Missing group data for {original_key}")
                continue

            for j, ion_type in enumerate(active_ions):
                values = all_group_counts[original_key].get(ion_type, [])
                if values:
                    data_matrix[i, j] = np.mean(values)
                    error_matrix[i, j] = (
                        np.std(values) / np.sqrt(len(values)) if len(values) > 1 else 0
                    )

        # Create grouped bar chart - ADAPTED for single or multiple groups
        x = np.arange(n_ions)  # Ion type positions

        if n_groups == 1:
            # Single group - wider bars, centered
            width = 0.6
            bars = ax.bar(
                x,
                data_matrix[0],
                width,
                label=custom_names[0],
                color=group_colors[0],
                alpha=0.8,
                yerr=error_matrix[0],
                capsize=3,
            )

            # Add value labels on bars
            for j, (bar, value) in enumerate(zip(bars, data_matrix[0])):
                if value > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + error_matrix[0, j] + 0.1,
                        f"{value:.1f}",
                        ha="center",
                        va="bottom",
                        fontsize=10,
                        fontweight="bold",
                    )
        else:
            # Multiple groups - grouped bars
            width = 0.8 / n_groups  # Width of bars

            # Plot bars for each group
            for i in range(n_groups):
                if i >= len(custom_names) or i >= len(group_colors):
                    logger.error(f"Index {i} out of range for names or colors")
                    continue

                custom_name = custom_names[i]
                color = group_colors[i]

                offset = (i - n_groups / 2 + 0.5) * width
                bars = ax.bar(
                    x + offset,
                    data_matrix[i],
                    width,
                    label=custom_name,
                    color=color,
                    alpha=0.8,
                    yerr=error_matrix[i],
                    capsize=3,
                )

                # Add value labels on bars
                for j, (bar, value) in enumerate(zip(bars, data_matrix[i])):
                    if value > 0:
                        ax.text(
                            bar.get_x() + bar.get_width() / 2,
                            bar.get_height() + error_matrix[i, j] + 0.1,
                            f"{value:.1f}",
                            ha="center",
                            va="bottom",
                            fontsize=9,
                            fontweight="bold",
                        )

        # Customize plot based on number of groups
        ax.set_xlabel("Ion Type", fontsize=12, fontweight="bold")
        ax.set_ylabel("Ion Count", fontsize=12, fontweight="bold")

        if n_groups == 1:
            ax.set_title(
                f"Fragmentation Pattern Analysis - {custom_names[0]}\n({n_ions} ion types with matches)",
                fontsize=14,
                fontweight="bold",
            )
        else:
            ax.set_title(
                f"Ion Count Comparison Across {n_groups} Groups\n({n_ions} ion types with matches)",
                fontsize=14,
                fontweight="bold",
            )

        ax.set_xticks(x)
        ax.set_xticklabels(active_ions, rotation=45 if n_ions > 6 else 0)

        # Only show legend if more than one group
        if n_groups > 1:
            ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left")

        ax.grid(True, alpha=0.3, axis="y")

        # Adjust layout to prevent legend cutoff
        self.comparison_figure.tight_layout()
        self.comparison_canvas.draw()

    def show_comparison_message(self, message):
        """Show a message in the comparison plot area"""
        if hasattr(self, "comparison_figure"):
            self.comparison_figure.clear()
            ax = self.comparison_figure.add_subplot(111)
            ax.text(
                0.5,
                0.5,
                message,
                horizontalalignment="center",
                verticalalignment="center",
                transform=ax.transAxes,
                fontsize=14,
                bbox=dict(
                    boxstyle="round,pad=0.5",
                    facecolor=EditorConstants.GRAY_200(),
                    alpha=0.8,
                ),
            )
            ax.set_xticks([])
            ax.set_yticks([])
            self.comparison_canvas.draw()

    def update_bar_chart_plot(self, selected_ions):
        """Update bar chart plot"""
        # Collect data from ALL groups that have peptides (including single group)
        group_data = {}
        group_colors = []
        custom_names = []
        groups_with_data = []

        # Identify groups with data
        for group_id, group_info in self.comparison_groups.items():
            peptides = self.get_peptides_from_group(group_info["widget"])
            if peptides:  # Only include groups with peptides
                group_data[group_id] = peptides
                groups_with_data.append(group_id)
                group_colors.append(group_info["color"])
                custom_names.append(group_info["current_name"])

        # CHANGED: Allow single group analysis
        if len(group_data) < 1:
            self.show_comparison_message(
                "Please add peptides to at least one group for analysis"
            )
            return

        # Use existing logic for regular bar chart
        all_group_counts = {}
        comparison_data = {}

        # Collect all discovered Ion Type keys across all groups
        all_discovered_ions = set()

        for group_id, peptides in group_data.items():
            ion_counts, _, coverage = self.calculate_group_analysis(
                peptides, selected_ions, "ion_count"
            )
            all_group_counts[group_id] = ion_counts
            all_discovered_ions.update(ion_counts.keys())

            # Store data for export
            comparison_data[group_id] = {
                "peptides": peptides,
                "ion_counts": ion_counts,
                "coverage": coverage,
            }

        # Store for export
        self.last_comparison_data = comparison_data
        # Use discovered Ion Types as the axis labels instead of selected base types
        discovered_ions_list = sorted(all_discovered_ions)
        self.last_selected_ions = discovered_ions_list

        # Create regular bar chart with actual Ion Type labels
        self.create_multi_group_bar_chart_with_custom_names(
            all_group_counts, discovered_ions_list, group_colors, custom_names
        )

    def calculate_group_analysis(
        self,
        peptides,
        selected_ions,
        analysis_type="ion_count",
        numerator_isotope=1,
        denominator_isotope=0,
        handle_zero_denom=False,
    ):
        """Unified method for group analysis calculations - ENHANCED to handle matched DataFrames"""
        if analysis_type == "ion_count":
            # Results keyed by actual Ion Type values discovered across all peptides
            results = {}
            coverage_results = {}  # base_type -> list of coverage counts per peptide
            peptide_idx = 0
            for peptide_data in peptides:
                matched_df = self.run_fragmentation_analysis(
                    peptide_data, selected_ions
                )
                peptide_results, base_type_coverage = self.count_ions_by_type(
                    matched_df, selected_ions
                )

                # Register any newly discovered Ion Types with zero back-fill
                for ion_type in peptide_results:
                    if ion_type not in results:
                        results[ion_type] = [0] * peptide_idx

                # Append this peptide's count for every known Ion Type
                for ion_type in results:
                    results[ion_type].append(peptide_results.get(ion_type, 0))

                peptide_idx += 1

                for base_type, cov_count in base_type_coverage.items():
                    if base_type not in coverage_results:
                        coverage_results[base_type] = []
                    coverage_results[base_type].append(cov_count)

            return (
                results,
                {},
                coverage_results,
            )  # Return empty zero_denom for consistency

        else:  # isotope_ratio
            results = {ion_type: {} for ion_type in selected_ions}
            all_zero_denom = {ion_type: [] for ion_type in selected_ions}

            for peptide_data in peptides:
                # Get matched DataFrame from fragmentation analysis
                matched_df = self.run_fragmentation_analysis(
                    peptide_data, selected_ions
                )

                # Process the matched DataFrame for isotope ratios
                peptide_results, zero_denom = self.calculate_isotope_ratios_by_position(
                    matched_df,
                    selected_ions,
                    numerator_isotope,
                    denominator_isotope,
                    handle_zero_denom,
                )

                for ion_type in selected_ions:
                    if ion_type in peptide_results:
                        for position, ratio in peptide_results[ion_type].items():
                            if position not in results[ion_type]:
                                results[ion_type][position] = []
                            results[ion_type][position].append(ratio)

                    # Accumulate zero denominator positions
                    if ion_type in zero_denom:
                        all_zero_denom[ion_type].extend(zero_denom[ion_type])

            return results, all_zero_denom, {}

    def run_fragmentation_analysis(self, peptide_data, selected_ions):
        """Run fragmentation analysis and return matched DataFrame"""

        # Extract common data
        peptide = peptide_data.get("peptide", "")
        modifications = peptide_data.get("parsed_modifications", [])
        charge = peptide_data.get("charge", 1)

        logger.debug(
            f"Running fragmentation analysis for peptide: {peptide}, charge: {charge}"
        )

        # Get spectral data
        mz_data, intensity_data = self.get_raw_spectral_data(peptide_data)
        if not mz_data:
            logger.debug("No spectral data found for peptide")
            return pd.DataFrame()  # Return empty DataFrame

        try:
            # grab ions selected
            ion_types = (
                self.main_app.generate_dynamic_ion_types()
                if self.main_app
                else self.generate_comprehensive_ion_types()
            )

            # Get custom ion series
            custom_ion_series_list = []
            if self.main_app and hasattr(self.main_app, "selected_custom_ions_data"):
                from utils.utilities import DataGatherer

                custom_ion_series_list = DataGatherer.gather_custom_ion_series(
                    self.main_app.selected_custom_ions_data
                )

            # Build modification-specific neutral losses from central DB
            mod_neutral_losses = None
            central_mod_db = getattr(self.main_app, "central_mod_db", None)
            if central_mod_db and modifications:
                from utils.utilities import DataGatherer

                enable_labile = getattr(self.main_app, "enable_labile_losses_cb", None)
                enable_labile = enable_labile.isChecked() if enable_labile else False
                enable_remainder = getattr(
                    self.main_app, "enable_remainder_ions_cb", None
                )
                enable_remainder = (
                    enable_remainder.isChecked() if enable_remainder else False
                )
                enable_mod_nl = getattr(self.main_app, "enable_mod_nl_cb", None)
                enable_mod_nl = enable_mod_nl.isChecked() if enable_mod_nl else False
                mod_neutral_losses = DataGatherer.build_mod_neutral_losses(
                    modifications,
                    central_mod_db,
                    enable_labile=enable_labile,
                    enable_remainder=enable_remainder,
                    enable_mod_nl=enable_mod_nl,
                )

            # Calculate theoretical fragments
            calculated_ions = calculate_fragment_ions(
                peptide_sequence=peptide,
                modifications=modifications,
                max_charge=charge,
                ion_types=ion_types,
                Internal=(
                    ["b", "a"]
                    if self.main_app
                    and any(
                        cb.isChecked()
                        for cb in self.main_app.internal_ion_checkboxes.values()
                    )
                    else []
                ),
                custom_ion_series=custom_ion_series_list,
                max_neutral_losses=(
                    self.main_app.max_neutral_losses_input.value()
                    if self.main_app
                    else 1
                ),
                mod_neutral_losses=mod_neutral_losses,
            )

            if calculated_ions.empty:
                logger.debug("No theoretical fragments calculated")
                return pd.DataFrame()  # Return empty DataFrame

            # Match fragments with experimental data
            user_mz_values = list(zip(mz_data, intensity_data))
            ppm_tolerance = (
                self.main_app.ppm_tolerance_input.value() if self.main_app else 10
            )
            matched_data = match_fragment_ions(
                calculated_ions.to_dict("records"),
                user_mz_values,
                ppm_tolerance=ppm_tolerance,
            )

            matched_df = pd.DataFrame(matched_data)
            return matched_df

        except Exception as e:
            logger.debug(f"Error in fragmentation analysis: {e}")
            traceback.print_exc()
            return pd.DataFrame()  # Return empty DataFrame

    def count_ions_by_type(self, matched_data, selected_ions):
        """Count matched ions by their actual Ion Type column value.

        Each selected ion (a base-type key like 'y' or 'b') is expanded
        into all distinct Ion Type values that share that Base Type in the
        data (e.g. 'y', 'y*', 'y-H2O').

        Returns:
            ion_counts:        dict {ion_type_str: count}
            base_type_coverage: dict {base_type_str: unique_positions}
        """
        if matched_data.empty:
            return {ion_type: 0 for ion_type in selected_ions}, {}

        logger.debug(f"Enhanced counting from {len(matched_data)} matched peaks")

        # Filter for matched, monoisotopic peaks
        matched_peaks = matched_data[
            (matched_data["Matched"].notna()) & (matched_data["Matched"] != "No Match")
        ].copy()

        if "Isotope" in matched_peaks.columns:
            matched_peaks = matched_peaks[
                pd.to_numeric(matched_peaks["Isotope"], errors="coerce") == 0
            ]

        logger.debug(f"After filtering: {len(matched_peaks)} peaks")

        # Build a set of selected base-type keys for fast lookup.
        # Handle special selected_ions like 'int-b', custom series, etc.
        selected_set = set(selected_ions)

        ion_counts = {}

        columns = list(matched_peaks.columns)
        col_idx = {col: pos for pos, col in enumerate(columns, start=1)}
        idx_ion_type = col_idx.get("Ion Type")
        idx_base_type = col_idx.get("Base Type")

        for row_tuple in matched_peaks.itertuples(index=False, name=None):
            ion_type_full = (
                str(row_tuple[idx_ion_type - 1]).strip()
                if idx_ion_type is not None
                else ""
            )
            base_type = (
                str(row_tuple[idx_base_type - 1]).strip()
                if idx_base_type is not None
                else ""
            )

            if not ion_type_full or not base_type:
                continue

            # Determine if this row belongs to any selected ion category.
            # Internal ions: selected as 'int-b', ion type starts with 'int-'
            is_selected = False
            if ion_type_full.startswith("int-"):
                # Internal ion — check if 'int-<base>' is in selected set
                int_key = f"int-{base_type}"
                if int_key in selected_set:
                    is_selected = True
            elif ion_type_full.startswith("custom_"):
                # Custom ion series
                for sel in selected_set:
                    if sel in ion_type_full:
                        is_selected = True
                        break
            else:
                # Standard ions: check if base_type is in selected set
                if base_type in selected_set:
                    is_selected = True
                # Also check for special selected keys like z+1, c-1
                elif "z+1" in selected_set and "z+1" in ion_type_full:
                    is_selected = True
                elif "c-1" in selected_set and "c-1" in ion_type_full:
                    is_selected = True
                # Neutral loss selected directly (e.g. 'y-H2O' in selected)
                elif ion_type_full in selected_set:
                    is_selected = True

            if is_selected:
                ion_counts[ion_type_full] = ion_counts.get(ion_type_full, 0) + 1

        # Sequence coverage by base type (unchanged)
        base_type_positions = {}
        idx_ion_number = col_idx.get("Ion Number")
        for row_tuple in matched_peaks.itertuples(index=False, name=None):
            base_type = (
                str(row_tuple[idx_base_type - 1]).strip()
                if idx_base_type is not None
                else ""
            )
            if not base_type or base_type in ("None", "nan", ""):
                continue
            try:
                ion_number = (
                    int(row_tuple[idx_ion_number - 1])
                    if idx_ion_number is not None
                    else 0
                )
                if base_type not in base_type_positions:
                    base_type_positions[base_type] = set()
                base_type_positions[base_type].add(ion_number)
            except (ValueError, TypeError):
                pass
        base_type_coverage = {
            bt: len(positions) for bt, positions in base_type_positions.items()
        }

        logger.debug(f"Ion counts: {ion_counts}")
        logger.debug(f"Sequence coverage by base type: {base_type_coverage}")
        return ion_counts, base_type_coverage

    def _ion_type_matches_selected(self, ion_type_full, selected_ion_type):
        """Unified ion type matching method"""
        # Handle z+1 as special case first
        if selected_ion_type == "z+1":
            return "z+1" in ion_type_full.lower() or (
                ion_type_full.startswith("z") and "+1" in ion_type_full
            )

        # Handle c-1 as special case
        if selected_ion_type == "c-1":
            return "c-1" in ion_type_full.lower() or (
                ion_type_full.startswith("c") and "-1" in ion_type_full
            )

        # Handle regular z ions (should NOT match z+1)
        if selected_ion_type == "z":
            if "z+1" in ion_type_full.lower():
                return False
            base_match = re.match(r"^z\d*", ion_type_full)
            return base_match is not None

        # Handle regular c ions (should NOT match c-1)
        if selected_ion_type == "c":
            if "c-1" in ion_type_full.lower():
                return False
            base_match = re.match(r"^c\d*", ion_type_full)
            return base_match is not None

        # Handle d (include da, db variants)
        if selected_ion_type == "d":
            return re.match(r"^d[ab]?\d*", ion_type_full) is not None

        # Handle w (include wa, wb variants)
        if selected_ion_type == "w":
            return re.match(r"^w[ab]?\d*", ion_type_full) is not None

        # Handle satellite neutral losses: d-H2O matches da-H2O, db-H2O etc.
        if selected_ion_type.startswith(("d-", "w-")):
            base_letter = selected_ion_type[0]  # 'd' or 'w'
            loss_part = selected_ion_type[1:]  # '-H2O', '-NH3'
            return (
                re.match(rf"^{base_letter}[ab]?{re.escape(loss_part)}$", ion_type_full)
                is not None
            )
        if selected_ion_type.startswith("v-"):
            return ion_type_full == selected_ion_type

        # Extract base type from the full ion type string
        base_type = ion_type_full.split("-")[0].split("+")[0]

        # Handle different ion type categories
        if selected_ion_type.startswith("int-"):
            if base_type.startswith("int-") and base_type[4:] == selected_ion_type[4:]:
                return True
        elif "-" in selected_ion_type and selected_ion_type not in ["z+1", "c-1"]:
            if (
                selected_ion_type in ion_type_full
                or base_type == selected_ion_type.split("-")[0]
            ):
                return True
        elif selected_ion_type in ["b", "y", "a", "x", "MH", "d", "v", "w"]:
            if base_type == selected_ion_type:
                return True
        else:
            # Custom ion series
            if selected_ion_type in ion_type_full:
                return True

        return False

    def create_isotope_ratio_plot(self, selected_ions):
        """Create isotope ratio plot with user-selected isotopes"""
        logger.debug(f"Creating isotope ratio plot for selected ions: {selected_ions}")

        # Get selected charge state
        selected_charge = None
        if hasattr(self, "charge_combo"):
            charge_text = self.charge_combo.currentText()
            if charge_text != "All":
                selected_charge = int(charge_text)
                logger.debug(f"Filtering for charge state: {selected_charge}")

        # Get selected isotope numerator and denominator
        numerator_isotope = 1  # Default
        denominator_isotope = 0  # Default
        handle_zero_denom = False  # Default

        if hasattr(self, "isotope_numerator_combo"):
            numerator_isotope = int(self.isotope_numerator_combo.currentText())
        if hasattr(self, "isotope_denominator_combo"):
            denominator_isotope = int(self.isotope_denominator_combo.currentText())
        if hasattr(self, "zero_denom_checkbox"):
            handle_zero_denom = self.zero_denom_checkbox.isChecked()

        logger.debug(
            f"Isotope ratio: isotope {numerator_isotope} / isotope {denominator_isotope}"
        )
        logger.debug(f"Handle zero denominator: {handle_zero_denom}")

        # Collect data ONLY from groups that have peptides
        group_data = {}
        group_colors = []
        custom_names = []

        # Identify groups with data
        for group_id, group_info in self.comparison_groups.items():
            peptides = self.get_peptides_from_group(group_info["widget"])
            if peptides:  # Only include groups with peptides
                group_data[group_id] = peptides
                group_colors.append(group_info["color"])
                custom_names.append(group_info["current_name"])

        if len(group_data) < 1:
            self.show_comparison_message(
                "Please add peptides to at least one group for isotope ratio analysis"
            )
            return

        # Calculate isotope ratios for each group
        all_group_ratios = {}
        all_group_zero_denom = {}
        comparison_data = {}

        for group_id, peptides in group_data.items():
            isotope_ratios, zero_denom, _ = self.calculate_group_analysis(
                peptides,
                selected_ions,
                "isotope_ratio",
                numerator_isotope,
                denominator_isotope,
                handle_zero_denom,
            )
            all_group_ratios[group_id] = isotope_ratios
            all_group_zero_denom[group_id] = zero_denom

            # Store data for export
            comparison_data[group_id] = {
                "peptides": peptides,
                "isotope_ratios": isotope_ratios,
                "zero_denom_positions": zero_denom,
            }

        # Store for export
        self.last_comparison_data = comparison_data
        self.last_selected_ions = selected_ions

        # Create the isotope ratio plot with charge filter
        self.create_isotope_ratio_scatter_plot(
            all_group_ratios,
            selected_ions,
            group_colors,
            custom_names,
            selected_charge,
            numerator_isotope,
            denominator_isotope,
            handle_zero_denom,
            all_group_zero_denom,
        )

    def get_raw_spectral_data(self, peptide_data):
        """Get raw spectral data (m/z and intensity) from cache - returns tuple (mz_values, intensity_values)"""
        try:
            # Get the row data which should contain the proper file path info
            row_data = peptide_data.get("row_data", {})

            if not row_data:
                logger.debug("No row data found in peptide_data")
                return [], []

            # Use the same approach as PSM summary widget
            raw_path_str = row_data.get("spectrum_file_path", "")
            index_str = str(row_data.get("index", ""))

            logger.debug(f"Raw path: {raw_path_str}")
            logger.debug(f"Index: {index_str}")

            if not raw_path_str or not index_str:
                logger.debug("Missing spectrum_file_path or index in row_data")
                logger.debug(f"Available row_data keys: {list(row_data.keys())}")
                return [], []

            # Clean scan number using the same method as PSM summary
            scan_str = DataGatherer._clean_scan_number(index_str)

            # Create cache key exactly like PSM summary does
            cache_key = f"{raw_path_str}_{scan_str}"

            logger.debug(f"Looking for cache key: {cache_key}")

            # Access main app's extracted spectral data directly
            if not hasattr(self.main_app, "extracted_spectral_data"):
                logger.debug("No extracted_spectral_data found on main app")
                return [], []

            extracted_data = self.main_app.extracted_spectral_data

            if cache_key not in extracted_data:
                logger.debug("Cache key not found in extracted_spectral_data")

                # Debug: Show what keys are actually available
                available_keys = list(extracted_data.keys())
                logger.debug(
                    f"Available cache keys ({len(available_keys)}): {available_keys[:5]}..."
                )

                # Try to find similar keys
                similar_keys = [key for key in available_keys if scan_str in key]
                if similar_keys:
                    logger.debug(
                        f"Keys containing scan '{scan_str}': {similar_keys[:3]}"
                    )

                return [], []

            # Get spectral data
            spectral_data = extracted_data[cache_key]
            mz_data = spectral_data.get("mz_values", [])
            intensity_data = spectral_data.get("intensity_values", [])

            logger.debug(f"Found cached spectral data: {len(mz_data)} peaks")

            return mz_data, intensity_data

        except Exception as e:
            logger.debug(f"Error getting raw spectral data: {e}")
            traceback.print_exc()
            return [], []

    def generate_comprehensive_ion_types(self):
        """Generate comprehensive ion types as fallback when main app is not available"""
        return [
            "b",
            "y",
            "a",
            "c",
            "z",
            "x",
            "MH",
            "y-H2O",
            "b-H2O",
            "a-H2O",
            "y-NH3",
            "b-NH3",
            "a-NH3",
            "y-H3PO4",
            "b-H3PO4",
            "a-H3PO4",
            "y-SOCH4",
            "b-SOCH4",
            "MH-H2O",
            "MH-NH3",
        ]

    def calculate_isotope_ratios_by_position(
        self,
        matched_df,
        selected_ions,
        numerator_isotope=1,
        denominator_isotope=0,
        handle_zero_denom=False,
    ):
        """Calculate isotope ratios by ion position with configurable isotopes"""
        isotope_ratios = {ion_type: {} for ion_type in selected_ions}
        zero_denom_positions = {
            ion_type: [] for ion_type in selected_ions
        }  # Track positions with zero denominator

        if matched_df.empty:
            return isotope_ratios, zero_denom_positions

        # Filter for matched peaks only
        matched_peaks = matched_df[
            (matched_df["Matched"].notna()) & (matched_df["Matched"] != "No Match")
        ].copy()

        if matched_peaks.empty:
            return isotope_ratios, zero_denom_positions

        logger.debug(
            f"Processing {len(matched_peaks)} matched peaks for isotope ratios (isotope {numerator_isotope} / isotope {denominator_isotope})"
        )

        columns = list(matched_peaks.columns)
        col_idx = {col: pos for pos, col in enumerate(columns, start=1)}
        idx_ion_type = col_idx.get("Ion Type")
        idx_charge = col_idx.get("Charge")
        idx_ion_number = col_idx.get("Ion Number")
        idx_isotope = col_idx.get("Isotope")
        idx_intensity = col_idx.get("intensity") or col_idx.get("Intensity")

        if idx_ion_type is None:
            return isotope_ratios, zero_denom_positions

        # Pre-group by exact ion type once, then match selected ion classes to unique ion types.
        ion_type_buckets = defaultdict(list)
        for row_tuple in matched_peaks.itertuples(index=False, name=None):
            ion_type_full = str(row_tuple[idx_ion_type - 1])
            ion_type_buckets[ion_type_full].append(row_tuple)

        selected_ion_rows = {ion_type: [] for ion_type in selected_ions}
        for ion_type_full, bucket_rows in ion_type_buckets.items():
            for selected_ion in selected_ions:
                if self._ion_type_matches_selected(ion_type_full, selected_ion):
                    selected_ion_rows[selected_ion].extend(bucket_rows)

        # Group by ion type, charge, and position
        for ion_type in selected_ions:
            type_filtered_peaks = selected_ion_rows.get(ion_type, [])

            if not type_filtered_peaks:
                continue

            # Group by charge and position to find isotope pairs
            charge_position_groups = defaultdict(
                lambda: defaultdict(lambda: [0.0, 0])
            )  # [sum, count]

            for row_tuple in type_filtered_peaks:
                ion_type_str = str(row_tuple[idx_ion_type - 1])

                # Extract charge - INLINED
                charge_val = (
                    row_tuple[idx_charge - 1] if idx_charge is not None else None
                )
                if pd.notna(charge_val):
                    try:
                        charge = int(charge_val)
                    except (ValueError, TypeError):
                        charge = 1
                else:
                    # Inline charge extraction
                    charge_match = re.search(r"\+(\d+)", ion_type_str)
                    if charge_match:
                        charge = int(charge_match.group(1))
                    else:
                        charge_match = re.search(r"\^(\d+)", ion_type_str)
                        charge = int(charge_match.group(1)) if charge_match else 1

                # Extract position - INLINED
                ion_number_val = (
                    row_tuple[idx_ion_number - 1]
                    if idx_ion_number is not None
                    else None
                )
                if pd.notna(ion_number_val):
                    try:
                        position = int(ion_number_val)
                    except (ValueError, TypeError):
                        position_match = re.search(r"^[a-zA-Z]+(\d+)", ion_type_str)
                        if position_match:
                            position = int(position_match.group(1))
                        elif ion_type_str.startswith("int-"):
                            internal_match = re.search(
                                r"int-[a-zA-Z]*(\d+)", ion_type_str
                            )
                            position = (
                                int(internal_match.group(1)) if internal_match else 0
                            )
                        else:
                            position = 0
                else:
                    # Same inline logic as above
                    position_match = re.search(r"^[a-zA-Z]+(\d+)", ion_type_str)
                    if position_match:
                        position = int(position_match.group(1))
                    elif ion_type_str.startswith("int-"):
                        internal_match = re.search(r"int-[a-zA-Z]*(\d+)", ion_type_str)
                        position = int(internal_match.group(1)) if internal_match else 0
                    else:
                        position = 0

                # Extract isotope number
                isotope_val = (
                    row_tuple[idx_isotope - 1] if idx_isotope is not None else None
                )
                if pd.notna(isotope_val):
                    try:
                        isotope = int(isotope_val)
                    except (ValueError, TypeError):
                        isotope = 0
                else:
                    isotope = 0

                # Group by charge and position
                # Store intensity
                intensity_val = (
                    row_tuple[idx_intensity - 1] if idx_intensity is not None else 0
                )
                try:
                    intensity = float(intensity_val)
                except (ValueError, TypeError):
                    intensity = 0.0
                agg = charge_position_groups[(charge, position)][isotope]
                agg[0] += intensity
                agg[1] += 1

            # Calculate ratios for each charge/position group
            for (charge, position), isotope_data in charge_position_groups.items():
                position_charge_key = (position, charge)

                if (
                    numerator_isotope in isotope_data
                    and denominator_isotope in isotope_data
                ):
                    # Both isotopes exist - calculate ratio normally
                    num_sum, num_count = isotope_data[numerator_isotope]
                    denom_sum, denom_count = isotope_data[denominator_isotope]
                    if num_count == 0 or denom_count == 0:
                        continue
                    intensity_num = num_sum / num_count
                    intensity_denom = denom_sum / denom_count

                    if intensity_denom > 0:
                        ratio = intensity_num / intensity_denom

                        # Store ratio with (position, charge) tuple as key
                        if position_charge_key not in isotope_ratios[ion_type]:
                            isotope_ratios[ion_type][position_charge_key] = []

                        isotope_ratios[ion_type][position_charge_key].append(ratio)

                        logger.debug(
                            f"{ion_type} position {position} charge {charge}: ratio = {ratio:.3f} (iso{numerator_isotope}={intensity_num:.0f}, iso{denominator_isotope}={intensity_denom:.0f})"
                        )
                    elif handle_zero_denom and intensity_num > 0:
                        # Denominator exists but intensity is 0 - complete transfer, add as ratio=5
                        complete_transfer_ratio = 5.0

                        if position_charge_key not in isotope_ratios[ion_type]:
                            isotope_ratios[ion_type][position_charge_key] = []

                        isotope_ratios[ion_type][position_charge_key].append(
                            complete_transfer_ratio
                        )
                        zero_denom_positions[ion_type].append(
                            {
                                "position": position,
                                "charge": charge,
                                "numerator_intensity": intensity_num,
                                "position_charge_key": position_charge_key,
                            }
                        )
                        logger.debug(
                            f"{ion_type} position {position} charge {charge}: zero denominator intensity - using ratio={complete_transfer_ratio} (iso{numerator_isotope}={intensity_num:.0f}, iso{denominator_isotope}=0)"
                        )

                elif (
                    handle_zero_denom
                    and numerator_isotope in isotope_data
                    and denominator_isotope not in isotope_data
                ):
                    # Numerator exists but denominator was never matched/detected - complete hydrogen transfer
                    num_sum, num_count = isotope_data[numerator_isotope]
                    if num_count == 0:
                        continue
                    intensity_num = num_sum / num_count
                    complete_transfer_ratio = 5.0

                    if intensity_num > 0:
                        # Add to regular ratios so it's plotted with the same group
                        if position_charge_key not in isotope_ratios[ion_type]:
                            isotope_ratios[ion_type][position_charge_key] = []

                        isotope_ratios[ion_type][position_charge_key].append(
                            complete_transfer_ratio
                        )
                        zero_denom_positions[ion_type].append(
                            {
                                "position": position,
                                "charge": charge,
                                "numerator_intensity": intensity_num,
                                "position_charge_key": position_charge_key,
                            }
                        )
                        logger.debug(
                            f"{ion_type} position {position} charge {charge}: COMPLETE TRANSFER - using ratio={complete_transfer_ratio} (iso{numerator_isotope}={intensity_num:.0f}, iso{denominator_isotope}=not found)"
                        )

        return isotope_ratios, zero_denom_positions

    def create_isotope_ratio_scatter_plot(
        self,
        all_group_ratios,
        selected_ions,
        group_colors,
        custom_names,
        selected_charge=None,
        numerator_isotope=1,
        denominator_isotope=0,
        handle_zero_denom=False,
        all_group_zero_denom=None,
    ):
        """Create scatter plot of isotope ratios vs ion position with charge filtering and averaging"""

        logger.debug(f"Creating isotope ratio scatter plot for groups: {custom_names}")
        if selected_charge:
            logger.debug(f"Filtering for charge state: {selected_charge}")

        if not all_group_ratios or not custom_names:
            self.show_comparison_message("No groups with isotope ratio data found")
            return

        self.comparison_figure.clear()
        ax = self.comparison_figure.add_subplot(111)

        # Apply theme-aware styling to axes
        self._apply_theme_to_axes(ax)

        # Filter data by charge state if specified
        filtered_ratios = {}
        for group_id, group_ratios in all_group_ratios.items():
            filtered_ratios[group_id] = {}
            for ion_type in selected_ions:
                if ion_type not in group_ratios:
                    continue
                filtered_ratios[group_id][ion_type] = {}

                for position_charge_key, ratio_values in group_ratios[ion_type].items():
                    # position_charge_key is tuple (position, charge)
                    if (
                        isinstance(position_charge_key, tuple)
                        and len(position_charge_key) == 2
                    ):
                        position, charge = position_charge_key
                        # Filter by charge if specified
                        if selected_charge is None or charge == selected_charge:
                            # Group by position only (combine all charges or filtered charge)
                            if position not in filtered_ratios[group_id][ion_type]:
                                filtered_ratios[group_id][ion_type][position] = []

                            # Add ratio values - flatten any nested lists
                            if isinstance(ratio_values, list):
                                # Flatten the list
                                for val in ratio_values:
                                    if isinstance(val, (int, float)):
                                        filtered_ratios[group_id][ion_type][
                                            position
                                        ].append(float(val))
                                    elif isinstance(val, list):
                                        # Nested list - flatten it
                                        filtered_ratios[group_id][ion_type][
                                            position
                                        ].extend([float(v) for v in val])
                            elif isinstance(ratio_values, (int, float)):
                                filtered_ratios[group_id][ion_type][position].append(
                                    float(ratio_values)
                                )

        # Find all positions and active ions
        all_positions = set()
        active_ions = []

        # Check regular ratio data
        for group_id, group_ratios in filtered_ratios.items():
            for ion_type in selected_ions:
                if ion_type in group_ratios and group_ratios[ion_type]:
                    if ion_type not in active_ions:
                        active_ions.append(ion_type)
                    for position in group_ratios[ion_type].keys():
                        all_positions.add(position)

        # Also check zero denominator (complete transfer) data for active ions
        if handle_zero_denom and all_group_zero_denom:
            for group_id, zero_denom_data in all_group_zero_denom.items():
                for ion_type in selected_ions:
                    if ion_type in zero_denom_data and zero_denom_data[ion_type]:
                        # Check if any match the charge filter
                        has_matching_charge = False
                        for zd in zero_denom_data[ion_type]:
                            if (
                                selected_charge is None
                                or zd["charge"] == selected_charge
                            ):
                                has_matching_charge = True
                                break
                        if has_matching_charge and ion_type not in active_ions:
                            active_ions.append(ion_type)

        if not active_ions:
            charge_msg = f" for charge {selected_charge}" if selected_charge else ""
            self.show_comparison_message(f"No isotope ratio data found{charge_msg}")
            return

        sorted_positions = sorted(all_positions)
        logger.debug(f"Found positions: {sorted_positions}")
        logger.debug(f"Active ions: {active_ions}")

        # Determine if we have single or multiple peptides per group
        peptides_per_group = {}
        for group_id in filtered_ratios.keys():
            group_info = self.comparison_groups[group_id]
            peptides_per_group[group_id] = group_info["widget"].count()

        # Plot data for each group and ion type
        for group_idx, (group_id, group_ratios) in enumerate(filtered_ratios.items()):
            custom_name = custom_names[group_idx]
            group_color = group_colors[group_idx]
            num_peptides = peptides_per_group[group_id]

            for ion_idx, ion_type in enumerate(active_ions):
                if ion_type not in group_ratios or not group_ratios[ion_type]:
                    continue

                positions = []
                mean_ratios = []
                std_ratios = []

                for position in sorted(group_ratios[ion_type].keys()):
                    ratio_values = group_ratios[ion_type][position]

                    if not ratio_values:
                        continue

                    # Ensure all values are scalars
                    clean_values = []
                    for val in ratio_values:
                        if isinstance(val, (int, float)):
                            clean_values.append(float(val))
                        elif isinstance(val, (list, tuple)) and len(val) > 0:
                            # Flatten nested structures
                            clean_values.extend(
                                [float(v) for v in val if isinstance(v, (int, float))]
                            )

                    if not clean_values:
                        continue

                    positions.append(position)

                    if len(clean_values) == 1 and num_peptides == 1:
                        # Single peptide, single point - no error bar
                        mean_ratios.append(float(clean_values[0]))
                        std_ratios.append(0.0)
                    else:
                        # Multiple values - show mean with error bar
                        mean_ratios.append(float(np.mean(clean_values)))
                        std_ratios.append(
                            float(
                                np.std(clean_values, ddof=1)
                                if len(clean_values) > 1
                                else 0.0
                            )
                        )

                if positions and mean_ratios:
                    # Ensure all arrays are numpy arrays of floats
                    positions = np.array(positions, dtype=float)
                    mean_ratios = np.array(mean_ratios, dtype=float)
                    std_ratios = np.array(std_ratios, dtype=float)

                    # Create marker style for this ion type
                    markers = ["o", "s", "^", "D", "v", "<", ">", "p", "*", "h"]
                    marker = markers[ion_idx % len(markers)]

                    # Adjust color for different ion types
                    base_color = mcolors.to_rgba(group_color)
                    alpha = 0.8 - (ion_idx * 0.1)
                    alpha = max(alpha, 0.3)

                    # Plot with error bars
                    ax.errorbar(
                        positions,
                        mean_ratios,
                        yerr=std_ratios,
                        fmt=marker,
                        color=base_color,
                        alpha=alpha,
                        markersize=8,
                        capsize=4,
                        capthick=1.5,
                        ecolor=base_color,
                        elinewidth=1.5,
                        label=f"{custom_name} - {ion_type}",
                        markeredgecolor="black",
                        markeredgewidth=0.5,
                    )

                    logger.debug(
                        f"Plotted {len(positions)} points for {custom_name} - {ion_type}"
                    )

        # Customize plot
        ax.set_xlabel("Ion Position", fontsize=12, fontweight="bold")
        ax.set_ylabel(
            f"Isotope Ratio (Isotope {numerator_isotope} / Isotope {denominator_isotope})",
            fontsize=12,
            fontweight="bold",
        )

        # Update title based on charge filter
        charge_text = f" (Charge {selected_charge})" if selected_charge else ""
        ax.set_title(
            f"Isotope Ratio Analysis{charge_text}\n({len(custom_names)} groups, {len(active_ions)} ion types)",
            fontsize=14,
            fontweight="bold",
        )

        # Use linear scale with breaks of 1, not log scale
        all_ratios = []
        for group_ratios in filtered_ratios.values():
            for ion_ratios in group_ratios.values():
                for ratio_values in ion_ratios.values():
                    if isinstance(ratio_values, list):
                        all_ratios.extend(ratio_values)
                    else:
                        all_ratios.append(ratio_values)

        # Handle zero denominator points (complete hydrogen transfer) if enabled
        zero_denom_count = 0
        complete_transfer_ratio = 5.0  # Fixed ratio for complete hydrogen transfer
        has_complete_transfer_points = False

        if handle_zero_denom and all_group_zero_denom:
            # Count complete transfer points (they're already plotted with regular data)
            for group_id, zero_denom_data in all_group_zero_denom.items():
                if not zero_denom_data:
                    continue

                for ion_type in active_ions:
                    if ion_type not in zero_denom_data:
                        continue

                    zero_denom_list = zero_denom_data[ion_type]
                    if not zero_denom_list:
                        continue

                    # Filter by charge if specified
                    for zd in zero_denom_list:
                        if selected_charge is None or zd["charge"] == selected_charge:
                            zero_denom_count += 1
                            has_complete_transfer_points = True

        # Set x-axis limits AFTER all points (including complete transfer) are added to all_positions
        if all_positions:
            x_min, x_max = min(all_positions), max(all_positions)
            ax.set_xlim(x_min - 0.5, x_max + 0.5)

        if all_ratios:
            y_min = max(0, min(all_ratios) - 1)
            y_max = max(all_ratios) + 1

            # Extend y_max if we have complete transfer points
            if has_complete_transfer_points:
                y_max = max(y_max, complete_transfer_ratio + 1)

            ax.set_ylim(y_min, y_max)

            # Set y-axis major ticks at intervals of 1
            ax.yaxis.set_major_locator(MultipleLocator(1.0))

        # Add horizontal line at ratio = 1 for reference
        ax.axhline(
            y=1.0,
            color=EditorConstants.GRID_COLOR(),
            linestyle="--",
            alpha=0.5,
            label="Ratio = 1.0 (reference)",
        )

        # Add complete transfer reference line at ratio = 5 if we have such points
        if has_complete_transfer_points:
            ax.axhline(
                y=complete_transfer_ratio,
                color="#E74C3C",
                linestyle=":",
                linewidth=2,
                alpha=0.7,
                label="Complete transfer (ratio = 5)",
            )

        # Create legend
        ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3, axis="both")

        # Add statistics text
        total_points = sum(
            len(ratios)
            for group_ratios in filtered_ratios.values()
            for ion_ratios in group_ratios.values()
            for ratios in ion_ratios.values()
        )

        stats_text = f"Total data points: {total_points}\n"
        if zero_denom_count > 0:
            stats_text += f"Complete transfer points: {zero_denom_count}\n"
        stats_text += f"Position range: {min(all_positions) if all_positions else 0}-{max(all_positions) if all_positions else 0}\n"
        if all_ratios:
            stats_text += f"Ratio range: {min(all_ratios):.3f}-{max(all_ratios):.3f}"

        ax.text(
            0.02,
            0.98,
            stats_text,
            transform=ax.transAxes,
            fontsize=9,
            verticalalignment="top",
            bbox=dict(
                boxstyle="round", facecolor=EditorConstants.ANNOTATION_BG(), alpha=0.8
            ),
        )

        # Adjust layout to prevent legend cutoff
        self.comparison_figure.tight_layout()
        self.comparison_canvas.draw()

        logger.debug("Isotope ratio scatter plot completed successfully")
