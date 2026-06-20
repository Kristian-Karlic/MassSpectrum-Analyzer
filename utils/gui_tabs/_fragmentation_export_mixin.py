"""
_FragmentationExportMixin
--------------------------
All export methods for the fragmentation tab.
Covers: export_comparison_data, _get_export_filename,
_get_comparison_default_filename, _export_comparison_data_to_file,
_export_comparison_data_to_file_with_source_rows, _create_source_rows_data,
_create_comparison_summary_data, _create_peptide_info_data,
_create_comparison_metadata, export_fragmentation_analysis,
_export_fragmentation_to_excel, _get_fragmentation_export_default_filename.
"""

import os
import logging
import traceback
from datetime import datetime
import pandas as pd
from PyQt6.QtWidgets import (
    QMessageBox,
    QFileDialog,
    QProgressDialog,
)
from PyQt6.QtCore import Qt, QSettings

logger = logging.getLogger(__name__)


class _FragmentationExportMixin:

    def export_comparison_data(self, export_type="svg"):
        """Enhanced export method for integration"""

        # Validation for graph export
        if export_type in ["svg", "png"]:
            if (
                not hasattr(self, "comparison_figure")
                or not self.comparison_figure.get_axes()
            ):
                QMessageBox.warning(
                    self.main_app,
                    "No Graph",
                    "No comparison graph to export. Please create a comparison first.",
                )
                return

        # Get filename
        if export_type == "svg":
            default_filename = self._get_comparison_default_filename("svg")
            file_filter = "SVG files (*.svg);;All files (*.*)"
            title = "Export Comparison Graph as SVG"
        elif export_type == "png":
            default_filename = self._get_comparison_default_filename("png")
            file_filter = "PNG files (*.png);;All files (*.*)"
            title = "Export Comparison Graph as PNG"
        else:
            # Data export
            if (
                not hasattr(self, "last_comparison_data")
                or self.last_comparison_data is None
            ):
                QMessageBox.warning(
                    self.main_app,
                    "No Data",
                    "No comparison data to export. Please create a comparison first.",
                )
                return
            default_filename = self._get_comparison_default_filename("xlsx")
            file_filter = "Excel files (*.xlsx);;CSV files (*.csv);;All files (*.*)"
            title = "Export Comparison Raw Data"

        filename = self._get_export_filename(title, default_filename, file_filter)

        if not filename:
            return

        try:
            if export_type in ["svg", "png"]:
                # Graph export - only matplotlib
                self.comparison_figure.savefig(
                    filename, format=export_type, bbox_inches="tight", dpi=300
                )
                QMessageBox.information(
                    self.main_app,
                    "Success",
                    f"Graph exported successfully to:\n{filename}",
                )
            elif export_type == "xlsx":
                # Data export
                self._export_comparison_data_to_file(filename)
                QMessageBox.information(
                    self.main_app,
                    "Success",
                    f"Raw data exported successfully to:\n{filename}",
                )
        except Exception as e:
            QMessageBox.critical(
                self.main_app,
                "Error",
                f"Failed to export {export_type.upper()}:\n{str(e)}",
            )

    def _get_export_filename(self, title, default_filename, file_filter):
        """Get export filename with remembered directory"""
        # Use QSettings to remember last directory
        settings = QSettings("YourCompany", "MassSpecAnalyzer")
        last_dir = settings.value("last_export_directory", "")

        if last_dir and os.path.exists(last_dir):
            full_path = os.path.join(last_dir, default_filename)
        else:
            full_path = os.path.join(
                os.path.expanduser("~/Documents"), default_filename
            )

        filename, _ = QFileDialog.getSaveFileName(
            self.main_app, title, full_path, file_filter
        )

        if filename:
            # Save directory for next time
            directory = os.path.dirname(filename)
            settings.setValue("last_export_directory", directory)

        return filename

    def _get_comparison_default_filename(self, extension):
        """Generate default filename using group data - UPDATED for new plot types"""
        # Count active groups and use their custom names
        active_groups = []
        for original_key, group_info in self.comparison_groups.items():
            if group_info["widget"].count() > 0:
                custom_name = group_info["current_name"].replace(" ", "_")
                active_groups.append(custom_name)

        # Determine plot type based on current dropdown selection
        if hasattr(self, "plot_type_combo"):
            current_plot = self.plot_type_combo.currentText()
            if current_plot == "Isotope Ratio Plot":
                plot_type = "isotope_ratio"
            else:
                plot_type = "ion_count"
        else:
            plot_type = "ion_count"

        if active_groups:
            groups_str = "_vs_".join(active_groups)
            base_name = f"fragmentation_{plot_type}_{groups_str}"
        else:
            base_name = f"fragmentation_{plot_type}"

        if extension:
            return f"{base_name}.{extension}"
        else:
            return base_name

    def _export_comparison_data_to_file(self, filename):
        """Export comparison data to Excel or CSV file"""

        if filename.endswith(".xlsx"):
            # Use the method that includes source rows
            self._export_comparison_data_to_file_with_source_rows(filename)
        else:
            # Export main data as CSV
            summary_data = self._create_comparison_summary_data()
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_csv(filename, index=False)

    def _export_comparison_data_to_file_with_source_rows(self, filename):
        """Export comparison data to Excel file including source PSM rows"""

        if filename.endswith(".xlsx"):
            # Export to Excel with multiple sheets INCLUDING source rows
            with pd.ExcelWriter(filename, engine="openpyxl") as writer:

                # Export main data in long format
                summary_data = self._create_comparison_summary_data()
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(
                    writer, sheet_name="Fragmentation_Data", index=False
                )

                # Export source PSM rows with group information
                source_rows_df = self._create_source_rows_data()
                if not source_rows_df.empty:
                    source_rows_df.to_excel(
                        writer, sheet_name="Source_PSM_Rows", index=False
                    )

                # Export peptide information for each group
                for original_key, group_data in self.last_comparison_data.items():
                    if group_data["peptides"]:  # Only export if group has data
                        custom_name = self.comparison_groups[original_key][
                            "current_name"
                        ]
                        peptide_df = self._create_peptide_info_data(
                            custom_name, group_data
                        )
                        # Sanitize sheet name (Excel requirements)
                        sheet_name = f"{custom_name.replace(' ', '_')}_Peptides"[:31]
                        peptide_df.to_excel(writer, sheet_name=sheet_name, index=False)

                # Export metadata sheet
                metadata_df = self._create_comparison_metadata()
                metadata_df.to_excel(writer, sheet_name="Metadata", index=False)

    def _create_source_rows_data(self):
        """Create a dataframe with all source PSM rows used in the comparison"""

        source_rows = []

        if not hasattr(self, "last_comparison_data") or not self.last_comparison_data:
            return pd.DataFrame()

        # Get the active PSM summary widget
        current_tab = self.main_app.main_tab_widget.currentIndex()
        if current_tab == 0:  # Annotation tab
            psm_widget = self.main_app.psm_summary_widget
        else:  # Fragmentation analysis tab
            psm_widget = self.main_app.frag_psm_summary_widget

        # Check if we have access to the details dataframe
        if (
            not hasattr(psm_widget, "current_details_df")
            or psm_widget.current_details_df.empty
        ):
            logger.warning("No current_details_df available for source row export")
            return pd.DataFrame()

        details_df = psm_widget.current_details_df

        # Process each group to find matching rows
        for original_key, group_data in self.last_comparison_data.items():
            custom_name = self.comparison_groups[original_key]["current_name"]

            if "peptides" not in group_data or not group_data["peptides"]:
                continue

            # For each peptide in this group, find the matching row in details_df
            for peptide_info in group_data["peptides"]:
                try:
                    # Extract peptide information
                    if isinstance(peptide_info, dict):
                        peptide_seq = peptide_info.get("Peptide", "")
                        charge = peptide_info.get("Charge", "")
                        scan_number = str(peptide_info.get("index", ""))
                        spectrum_file = peptide_info.get("Spectrum file", "")

                        # If we have valid data, try to find the matching row
                        if (
                            peptide_seq
                            and peptide_seq != "Unknown"
                            and charge
                            and charge != "Unknown"
                        ):
                            # Create a mask to find matching rows
                            mask = (details_df["Peptide"] == peptide_seq) & (
                                details_df["Charge"] == charge
                            )

                            # Add scan number if available
                            if scan_number and scan_number != "Unknown":
                                mask = mask & (
                                    details_df["index"].astype(str) == scan_number
                                )

                            # Add spectrum file if available
                            if (
                                spectrum_file
                                and spectrum_file != "Unknown"
                                and "Spectrum file" in details_df.columns
                            ):
                                mask = mask & (
                                    details_df["Spectrum file"] == spectrum_file
                                )

                            # Find matching rows
                            matching_rows = details_df[mask]

                            if len(matching_rows) > 0:
                                # Take the first matching row
                                row_data = matching_rows.iloc[0].to_dict()

                                # Add group information
                                row_data["Comparison_Group"] = custom_name
                                row_data["Group_Original_Key"] = original_key
                                row_data["Export_Timestamp"] = (
                                    pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                                )

                                source_rows.append(row_data)

                except Exception as e:
                    logger.error(f"Error processing peptide info for source rows: {e}")
                    continue

        if source_rows:
            source_df = pd.DataFrame(source_rows)

            # Reorder columns to put group information first
            group_cols = ["Comparison_Group", "Group_Original_Key", "Export_Timestamp"]
            other_cols = [col for col in source_df.columns if col not in group_cols]
            source_df = source_df[group_cols + other_cols]

            return source_df
        else:
            return pd.DataFrame()

    def _create_comparison_summary_data(self):
        """Create summary data for export in long format - ENHANCED to handle charge grouping and isotope ratios"""
        summary_data = []

        if not self.last_comparison_data:
            return summary_data

        # Export regular data (existing logic)
        for original_key, group_data in self.last_comparison_data.items():
            custom_name = self.comparison_groups[original_key]["current_name"]

            if "ion_counts" in group_data:
                for ion_type, counts in group_data["ion_counts"].items():
                    # Add each individual replicate as a separate row
                    for count_value in counts:
                        summary_data.append(
                            {
                                "Ion_Type": ion_type,
                                "Ion_Count": count_value,
                                "Group": custom_name,
                            }
                        )

            # Handle isotope ratio data
            if "isotope_ratios" in group_data:
                for ion_type, position_data in group_data["isotope_ratios"].items():
                    # position_data is a dict: {position: [ratio1, ratio2, ...]}
                    for position, ratios in position_data.items():
                        # Handle position as tuple (position, charge) or scalar
                        if isinstance(position, tuple) and len(position) == 2:
                            pos, charge = position
                        else:
                            pos = position
                            charge = None

                        for ratio_value in ratios:
                            row_data = {
                                "Ion_Type": ion_type,
                                "Ion_Position": pos,
                                "Isotope_Ratio": ratio_value,
                                "Group": custom_name,
                            }
                            if charge is not None:
                                row_data["Charge"] = charge
                            summary_data.append(row_data)

            # Handle zero denominator positions (complete hydrogen transfer) if present
            if "zero_denom_positions" in group_data:
                for ion_type, zero_denom_list in group_data[
                    "zero_denom_positions"
                ].items():
                    for zd in zero_denom_list:
                        summary_data.append(
                            {
                                "Ion_Type": ion_type,
                                "Ion_Position": zd["position"],
                                "Charge": zd["charge"],
                                "Isotope_Ratio": 5.0,  # Complete transfer ratio
                                "Complete_Transfer": True,
                                "Numerator_Intensity": zd["numerator_intensity"],
                                "Group": custom_name,
                            }
                        )

        return summary_data

    def _create_peptide_info_data(self, group_name, group_data):
        """Create peptide information data for a specific group"""

        peptide_data = []

        if "peptides" in group_data:
            for i, peptide_info in enumerate(group_data["peptides"]):
                if isinstance(peptide_info, dict):
                    # Extract the actual values
                    peptide_seq = peptide_info.get("Peptide", "Unknown")
                    charge = peptide_info.get("Charge", "Unknown")
                    spectrum_file = peptide_info.get("Spectrum file", "Unknown")
                    scan = peptide_info.get("index", "Unknown")
                    modifications = peptide_info.get("Parsed Modifications", [])

                    # Convert modifications to readable string
                    if isinstance(modifications, list) and modifications:
                        mod_str = str(modifications)
                    else:
                        mod_str = "None"

                    peptide_data.append(
                        {
                            "Group": group_name,
                            "Replicate_Index": i + 1,
                            "Peptide": peptide_seq,
                            "Modifications": mod_str,
                            "Charge": charge,
                            "File": spectrum_file,
                            "Scan": scan,
                        }
                    )
                else:
                    # Fallback for non-dictionary items
                    peptide_data.append(
                        {
                            "Group": group_name,
                            "Replicate_Index": i + 1,
                            "Peptide": str(peptide_info) if peptide_info else "Unknown",
                            "Modifications": "Unknown",
                            "Charge": "Unknown",
                            "File": "Unknown",
                            "Scan": "Unknown",
                        }
                    )

        return pd.DataFrame(peptide_data)

    def _create_comparison_metadata(self):
        """Create metadata for the comparison export"""

        # Get current plot type from combo box
        current_plot_type = (
            self.plot_type_combo.currentText()
            if hasattr(self, "plot_type_combo")
            else "Unknown"
        )

        metadata = [
            {
                "Parameter": "Export_Date",
                "Value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            {"Parameter": "Plot_Type", "Value": current_plot_type},
            {
                "Parameter": "Selected_Ion_Types",
                "Value": (
                    ", ".join(self.last_selected_ions)
                    if self.last_selected_ions
                    else "None"
                ),
            },
            {
                "Parameter": "Number_of_Groups",
                "Value": len(
                    [
                        g
                        for g in self.comparison_groups.values()
                        if g["widget"].count() > 0
                    ]
                ),
            },
            {
                "Parameter": "PPM_Tolerance",
                "Value": self.main_app.ppm_tolerance_input.value(),
            },
            {
                "Parameter": "Max_Neutral_Losses",
                "Value": self.main_app.max_neutral_losses_input.value(),
            },
            {
                "Parameter": "Active_Tab",
                "Value": (
                    "Annotation"
                    if self.main_app.main_tab_widget.currentIndex() == 0
                    else "Fragmentation_Analysis"
                ),
            },
        ]

        # Add isotope ratio settings if applicable
        if current_plot_type == "Isotope Ratio Plot":
            if hasattr(self, "isotope_numerator_combo"):
                metadata.append(
                    {
                        "Parameter": "Isotope_Numerator",
                        "Value": self.isotope_numerator_combo.currentText(),
                    }
                )
            if hasattr(self, "isotope_denominator_combo"):
                metadata.append(
                    {
                        "Parameter": "Isotope_Denominator",
                        "Value": self.isotope_denominator_combo.currentText(),
                    }
                )
            if hasattr(self, "zero_denom_checkbox"):
                metadata.append(
                    {
                        "Parameter": "Handle_Zero_Denominator",
                        "Value": self.zero_denom_checkbox.isChecked(),
                    }
                )
            if hasattr(self, "charge_combo"):
                metadata.append(
                    {
                        "Parameter": "Charge_Filter",
                        "Value": self.charge_combo.currentText(),
                    }
                )

        # Add group information with custom names
        total_peptides = 0
        for original_key, group_info in self.comparison_groups.items():
            if group_info["widget"].count() > 0:
                custom_name = group_info["current_name"]
                peptide_count = group_info["widget"].count()
                total_peptides += peptide_count
                metadata.append(
                    {
                        "Parameter": f"{custom_name}_Replicate_Count",
                        "Value": peptide_count,
                    }
                )

        metadata.append({"Parameter": "Total_Peptides_Used", "Value": total_peptides})

        return pd.DataFrame(metadata)

    def export_fragmentation_analysis(self):
        """Export detailed fragmentation analysis for all peptides in all groups"""

        # Get selected ion types
        selected_ions = self.get_selected_ion_types_for_comparison()

        if not selected_ions:
            QMessageBox.warning(
                self.main_app,
                "No Ion Types Selected",
                "Please select at least one ion type in the left panel before exporting fragmentation analysis.",
            )
            return

        # Collect all peptides from all groups
        all_peptides = []
        peptide_group_mapping = []

        for group_id, group_info in self.comparison_groups.items():
            peptides = self.get_peptides_from_group(group_info["widget"])
            group_name = group_info["current_name"]

            for peptide_data in peptides:
                all_peptides.append(peptide_data)
                peptide_group_mapping.append(
                    {
                        "group_id": group_id,
                        "group_name": group_name,
                        "peptide": peptide_data.get("peptide", "Unknown"),
                        "charge": peptide_data.get("charge", "Unknown"),
                    }
                )

        if not all_peptides:
            QMessageBox.warning(
                self.main_app,
                "No Peptides Found",
                "No peptides found in any comparison groups. Please add peptides to analyze.",
            )
            return

        # Get export filename
        default_filename = self._get_fragmentation_export_default_filename()
        filename = self._get_export_filename(
            "Export Fragmentation Analysis",
            default_filename,
            "Excel files (*.xlsx);;CSV files (*.csv);;All files (*.*)",
        )

        if not filename:
            return

        # Create progress dialog
        progress = QProgressDialog(
            "Analyzing fragmentation patterns...",
            "Cancel",
            0,
            len(all_peptides),
            self.main_app,
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        try:
            # Process all peptides and collect matched data
            all_matched_data = []

            for i, (peptide_data, group_info) in enumerate(
                zip(all_peptides, peptide_group_mapping)
            ):

                # Update progress
                progress.setValue(i)
                progress.setLabelText(
                    f"Analyzing peptide {i+1}/{len(all_peptides)}: {group_info['peptide']}"
                )

                if progress.wasCanceled():
                    return

                # Run fragmentation analysis
                matched_df = self.run_fragmentation_analysis(
                    peptide_data, selected_ions
                )

                if not matched_df.empty:
                    # Add group and peptide information to each row
                    matched_df = matched_df.copy()
                    matched_df["Group_ID"] = group_info["group_id"]
                    matched_df["Group_Name"] = group_info["group_name"]
                    matched_df["Peptide_Sequence"] = group_info["peptide"]
                    matched_df["Peptide_Charge"] = group_info["charge"]
                    matched_df["Peptide_Index"] = i + 1

                    # Add additional peptide metadata if available
                    matched_df["Spectrum_File"] = peptide_data.get(
                        "Spectrum file", "Unknown"
                    )
                    matched_df["Scan_Number"] = peptide_data.get("index", "Unknown")
                    matched_df["Modifications"] = str(
                        peptide_data.get("parsed_modifications", [])
                    )

                    all_matched_data.append(matched_df)
                else:
                    logger.warning(
                        f"No matched data for peptide {group_info['peptide']} in group {group_info['group_name']}"
                    )

            progress.close()

            if not all_matched_data:
                QMessageBox.warning(
                    self.main_app,
                    "No Fragmentation Data",
                    "No fragmentation matches found for any peptides. Check your ion selections and peptide data.",
                )
                return

            # Combine all matched data
            combined_df = pd.concat(all_matched_data, ignore_index=True)

            # Reorder columns to put metadata first
            metadata_cols = [
                "Group_ID",
                "Group_Name",
                "Peptide_Index",
                "Peptide_Sequence",
                "Peptide_Charge",
                "Modifications",
                "Spectrum_File",
                "Scan_Number",
            ]
            other_cols = [
                col for col in combined_df.columns if col not in metadata_cols
            ]
            final_df = combined_df[metadata_cols + other_cols]

            # Export data
            if filename.endswith(".xlsx"):
                self._export_fragmentation_to_excel(
                    final_df, filename, selected_ions, peptide_group_mapping
                )
            else:
                # CSV export
                final_df.to_csv(filename, index=False)

            # Show success message
            QMessageBox.information(
                self.main_app,
                "Export Complete",
                f"Fragmentation analysis exported successfully!\n\n"
                f"File: {filename}\n"
                f"Peptides analyzed: {len(all_peptides)}\n"
                f"Total matches: {len(final_df)}\n"
                f"Ion types: {', '.join(selected_ions)}",
            )

        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self.main_app,
                "Export Error",
                f"Failed to export fragmentation analysis:\n{str(e)}",
            )
            logger.error(f"Fragmentation export error: {e}")

            traceback.print_exc()

    def _export_fragmentation_to_excel(
        self, combined_df, filename, selected_ions, peptide_group_mapping
    ):
        """Export fragmentation data to Excel with multiple sheets"""

        with pd.ExcelWriter(filename, engine="openpyxl") as writer:

            # Main fragmentation data sheet
            combined_df.to_excel(
                writer, sheet_name="Fragmentation_Analysis", index=False
            )

            # Summary sheet - ion counts per peptide
            summary_data = []
            for i, group_info in enumerate(peptide_group_mapping):
                peptide_df = combined_df[combined_df["Peptide_Index"] == i + 1]

                # Count matched ions (excluding "No Match")
                matched_df = peptide_df[
                    (peptide_df["Matched"].notna())
                    & (peptide_df["Matched"] != "No Match")
                ]
                matched_columns = list(matched_df.columns)
                matched_col_idx = {
                    col: pos for pos, col in enumerate(matched_columns, start=1)
                }
                idx_ion_type = matched_col_idx.get("Ion Type")

                # Count by ion type
                ion_counts = {}
                for ion_type in selected_ions:
                    count = 0
                    for row_tuple in matched_df.itertuples(index=False, name=None):
                        ion_type_full = (
                            str(row_tuple[idx_ion_type - 1])
                            if idx_ion_type is not None
                            else ""
                        )
                        if self._ion_type_matches_selected(ion_type_full, ion_type):
                            count += 1
                    ion_counts[ion_type] = count

                # Collect sequence coverage by base type (monoisotopic only)
                mono_df = matched_df
                if "Isotope" in mono_df.columns:
                    mono_df = mono_df[
                        pd.to_numeric(mono_df["Isotope"], errors="coerce") == 0
                    ]
                base_type_positions = {}
                mono_columns = list(mono_df.columns)
                mono_col_idx = {
                    col: pos for pos, col in enumerate(mono_columns, start=1)
                }
                mono_idx_base_type = mono_col_idx.get("Base Type")
                mono_idx_ion_number = mono_col_idx.get("Ion Number")
                for row_tuple in mono_df.itertuples(index=False, name=None):
                    base_type = (
                        str(row_tuple[mono_idx_base_type - 1]).strip()
                        if mono_idx_base_type is not None
                        else ""
                    )
                    if not base_type or base_type in ("None", "nan", ""):
                        continue
                    try:
                        ion_number = (
                            int(row_tuple[mono_idx_ion_number - 1])
                            if mono_idx_ion_number is not None
                            else 0
                        )
                        if base_type not in base_type_positions:
                            base_type_positions[base_type] = set()
                        base_type_positions[base_type].add(ion_number)
                    except (ValueError, TypeError):
                        pass
                base_type_coverage = {
                    bt: len(pos) for bt, pos in base_type_positions.items()
                }

                # Create summary row
                summary_row = {
                    "Group_Name": group_info["group_name"],
                    "Peptide_Sequence": group_info["peptide"],
                    "Peptide_Charge": group_info["charge"],
                    "Total_Theoretical": len(peptide_df),
                    "Total_Matched": len(matched_df),
                    "Match_Rate_%": (
                        (len(matched_df) / len(peptide_df) * 100)
                        if len(peptide_df) > 0
                        else 0
                    ),
                }

                # Add ion type counts
                for ion_type in selected_ions:
                    summary_row[f"{ion_type}_Count"] = ion_counts.get(ion_type, 0)

                # Add sequence coverage counts
                for base_type, cov_count in sorted(base_type_coverage.items()):
                    summary_row[f"sequence_coverage_count_{base_type}"] = cov_count

                summary_data.append(summary_row)

            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name="Summary", index=False)

    def _get_fragmentation_export_default_filename(self):
        """Generate default filename for fragmentation export"""

        # Count active groups
        active_groups = []
        for group_info in self.comparison_groups.values():
            if group_info["widget"].count() > 0:
                active_groups.append(group_info["current_name"].replace(" ", "_"))

        if active_groups:
            groups_str = "_".join(
                active_groups[:3]
            )  # Limit to first 3 groups for filename
            if len(active_groups) > 3:
                groups_str += f"_plus{len(active_groups)-3}more"
        else:
            groups_str = "no_groups"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"fragmentation_analysis_{groups_str}_{timestamp}.xlsx"
