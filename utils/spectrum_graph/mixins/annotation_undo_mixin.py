import json
import logging

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QAction, QCursor, QColor
from PyQt6.QtWidgets import QMenu, QApplication

from ..config.constants import PlotConstants, matched_mask
from ..classes.interactivetext import InteractiveTextItem, EnhancedInteractiveTextItem
from utils.utility_classes.htmlformating import HTMLFormatter
from utils.style.style import EditorConstants

logger = logging.getLogger(__name__)


class AnnotationUndoMixin:
    """Annotation removal, undo, and swap functionality for MassSpecViewer."""

    def show_peak_context_menu(self, event):
        """Show peak context menu with improved peak detection"""
        # Hide any active tooltips when showing context menu
        if hasattr(self, 'persistent_tooltip'):
            self.persistent_tooltip.hide_tooltip()

        # Make sure we have valid peak data
        if not self.current_peak_data:
            print("[DEBUG] No current peak data for context menu")
            return

        menu_peak_data = self.current_peak_data.copy()  # Make a copy

        menu = QMenu(self)

        # Copy m/z action with stored data
        copy_action = QAction("Copy m/z value", self)
        copy_action.triggered.connect(lambda: self.copy_mz_to_clipboard_with_data(menu_peak_data))
        menu.addAction(copy_action)

        # Check if this peak is currently annotated by looking at the DataFrame
        target_mz = menu_peak_data['mz']
        tolerance = PlotConstants.MZ_TOLERANCE

        df_mask = abs(self.df['m/z'] - target_mz) < tolerance
        matching_rows = self.df[df_mask]

        is_matched = False
        if not matching_rows.empty:
            # Check if any matching row is actually matched (not "No Match")
            matched_status = matching_rows['Matched'].iloc[0]
            is_matched = (matched_status != 'No Match' and
                        pd.notna(matched_status) and
                        str(matched_status).strip() != '')

        if is_matched:
            menu.addSeparator()

            # Remove annotation action with stored data
            remove_annotation_action = QAction("Remove Annotation (Make Unmatched)", self)
            remove_annotation_action.triggered.connect(lambda: self.remove_peak_annotation_with_data(menu_peak_data))
            menu.addAction(remove_annotation_action)

            # Swap to Alternative submenu - only if alternatives exist
            alt_matches_raw = ''
            if not matching_rows.empty and 'Alternative Matches' in matching_rows.columns:
                alt_matches_raw = matching_rows.iloc[0].get('Alternative Matches', '')

            if alt_matches_raw:
                try:
                    alt_list = json.loads(alt_matches_raw) if isinstance(alt_matches_raw, str) else alt_matches_raw
                    if alt_list:
                        swap_menu = menu.addMenu("Swap Annotation To...")
                        for alt in alt_list:
                            alt_label = f"{alt['label']} ({alt['ppm']:.2f} ppm)"
                            alt_data = alt.copy()  # capture for lambda
                            swap_action = QAction(alt_label, self)
                            swap_action.triggered.connect(
                                lambda checked, ad=alt_data, mpd=menu_peak_data: self.swap_peak_to_alternative(mpd, ad)
                            )
                            swap_menu.addAction(swap_action)
                except (json.JSONDecodeError, TypeError):
                    pass

        # Show the menu at cursor position
        menu.exec(event.screenPos())


    def remove_peak_annotation_with_data(self, peak_data):
        """Remove annotation from the specified peak and store for undo.

        When removing a monoisotopic peak (Isotope == 0), also removes all
        associated isotope peaks (Isotope > 0) that share the same Ion Type,
        Ion Number, and Charge.
        """
        if not peak_data:
            print("[DEBUG] No peak data for annotation removal")
            return

        target_mz = peak_data['mz']
        tolerance = PlotConstants.MZ_TOLERANCE

        # Find matching rows in DataFrame
        df_mask = abs(self.df['m/z'] - target_mz) < tolerance
        matching_rows = self.df[df_mask]

        if matching_rows.empty:
            logger.debug(f"No matching rows found for m/z {target_mz}")
            return

        # Check if actually matched
        matched_status = matching_rows['Matched'].iloc[0]
        is_matched = (matched_status != 'No Match' and
                    pd.notna(matched_status) and
                    str(matched_status).strip() != '')

        if not is_matched:
            logger.debug(f"Peak at m/z {target_mz} is not matched")
            return

        # Mark manual changes if parent supports it
        if hasattr(self.parent(), 'mark_manual_changes'):
            self.parent().mark_manual_changes()

        # Determine if this is a monoisotopic peak - if so, find associated isotopes
        primary_row = matching_rows.iloc[0]
        primary_isotope = int(primary_row.get('Isotope', 0)) if pd.notna(primary_row.get('Isotope')) else 0
        primary_ion_type = primary_row.get('Ion Type', '')
        primary_ion_number = primary_row.get('Ion Number', '')
        primary_charge = primary_row.get('Charge', 1)

        # Collect all peaks to remove: primary + associated isotopes
        peaks_to_remove = []  # list of (df_mask, mz_value) tuples
        peaks_to_remove.append((df_mask, target_mz))

        # If monoisotopic, find all isotope peaks with same Ion Type, Ion Number, Charge
        isotope_masks = []
        if primary_isotope == 0 and primary_ion_type and primary_ion_number is not None:
            # Find all rows with same ion identity but Isotope > 0
            isotope_candidates = self.df[
                (self.df['Ion Type'] == primary_ion_type) &
                (self.df['Ion Number'].astype(str) == str(primary_ion_number)) &
                (pd.to_numeric(self.df['Charge'], errors='coerce') == int(primary_charge if pd.notna(primary_charge) else 1)) &
                (pd.to_numeric(self.df['Isotope'], errors='coerce') > 0) &
                matched_mask(self.df)
            ]

            for iso_idx in isotope_candidates.index:
                iso_mz = self.df.loc[iso_idx, 'm/z']
                iso_mask = self.df.index == iso_idx
                peaks_to_remove.append((iso_mask, iso_mz))
                isotope_masks.append((iso_mask, iso_mz, iso_idx))
                logger.debug(
                    "Also removing isotope peak at m/z %.4f (Isotope=%s)",
                    iso_mz, self.df.loc[iso_idx, 'Isotope']
                )

        # Store original data for undo (all peaks: primary + isotopes)
        original_data = {}
        undo_columns = [
            'Matched', 'Ion Number', 'Ion Type', 'Fragment Sequence',
            'Neutral Loss', 'Charge', 'Isotope', 'Color', 'Base Type',
            'error_ppm', 'text_annotation', 'Alternative Matches'
        ]
        # Primary peak
        for idx in matching_rows.index:
            original_data[idx] = {
                col: self.df.loc[idx, col] for col in undo_columns
                if col in self.df.columns
            }
        # Isotope peaks
        for _, _, iso_idx in isotope_masks:
            original_data[iso_idx] = {
                col: self.df.loc[iso_idx, col] for col in undo_columns
                if col in self.df.columns
            }

        # Store all removed m/z values for undo (so we can restore all of them)
        all_removed_mzs = [mz_val for _, mz_val in peaks_to_remove]

        # Store for undo
        self.annotation_removal_history.append({
            'mz': target_mz,
            'all_mzs': all_removed_mzs,
            'original_data': original_data,
            'timestamp': pd.Timestamp.now()
        })

        # Limit history
        if len(self.annotation_removal_history) > self.max_undo_history:
            self.annotation_removal_history.pop(0)

        # Get fragment sequence before removing
        fragment_sequence = matching_rows.iloc[0].get('Fragment Sequence', '')

        # Update DataFrame columns to unmatched state for ALL peaks
        reset_values = {
            'Matched': 'No Match',
            'Ion Number': None,
            'Ion Type': None,
            'Fragment Sequence': None,
            'Neutral Loss': 'None',
            'Charge': 1,
            'Isotope': 0,
            'Color': EditorConstants.UNMATCHED_PEAK_COLOR(),
            'Base Type': None,
            'error_ppm': None,
            'text_annotation': '',
            'Alternative Matches': ''
        }

        for peak_mask, peak_mz in peaks_to_remove:
            for column, value in reset_values.items():
                if column not in self.df.columns:
                    continue
                self.df.loc[peak_mask, column] = value

                # Also update matched_df if it exists
                if hasattr(self, 'matched_df') and not self.matched_df.empty:
                    matched_df_mask = abs(self.matched_df['m/z'] - peak_mz) < tolerance
                    if column in self.matched_df.columns:
                        self.matched_df.loc[matched_df_mask, column] = value

        # Update visuals for ALL peaks
        for _, peak_mz in peaks_to_remove:
            self.convert_peak_to_unmatched(peak_mz, fragment_sequence)

        # Update peptide fragment lines
        self._delayed_plot_data_fragments_only()

        self.update_undo_button_state()
        self.persistent_tooltip.hide_tooltip()
        self.reset_linked_highlighting()
        self.reset_peptide_highlighting()

        removed_count = len(peaks_to_remove)
        if removed_count > 1:
            logger.debug(f"Removed annotation for peak at m/z {target_mz} and {removed_count - 1} associated isotope(s)")
        else:
            logger.debug(f"Removed annotation for peak at m/z {target_mz}")

    def swap_peak_to_alternative(self, peak_data, alt_ion_data):
        """Swap a peak's annotation to an alternative ion match.

        Args:
            peak_data: dict with 'mz' and 'intensity' of the peak
            alt_ion_data: dict with full ion info from the alternative match
        """
        if not peak_data or not alt_ion_data:
            return

        target_mz = peak_data['mz']
        tolerance = PlotConstants.MZ_TOLERANCE

        # Find matching rows in DataFrame
        df_mask = abs(self.df['m/z'] - target_mz) < tolerance
        matching_rows = self.df[df_mask]

        if matching_rows.empty:
            logger.debug(f"No matching rows found for swap at m/z {target_mz}")
            return

        # Store original data for undo
        original_data = {}
        for idx in matching_rows.index:
            original_data[idx] = {
                col: self.df.loc[idx, col] for col in [
                    'Matched', 'Ion Number', 'Ion Type', 'Fragment Sequence',
                    'Neutral Loss', 'Charge', 'Isotope', 'Color', 'Base Type',
                    'error_ppm', 'text_annotation', 'Alternative Matches'
                ] if col in self.df.columns
            }

        # Store for undo
        self.annotation_removal_history.append({
            'mz': target_mz,
            'original_data': original_data,
            'timestamp': pd.Timestamp.now()
        })
        if len(self.annotation_removal_history) > self.max_undo_history:
            self.annotation_removal_history.pop(0)

        # Build the new alternative matches list:
        # The current (old) primary match becomes an alternative, and the selected alt is removed
        old_row = matching_rows.iloc[0]
        old_alt_raw = old_row.get('Alternative Matches', '')
        try:
            old_alt_list = json.loads(old_alt_raw) if isinstance(old_alt_raw, str) and old_alt_raw else []
        except (json.JSONDecodeError, TypeError):
            old_alt_list = []

        # Create entry for the old primary match (if it was a real match and monoisotopic)
        old_matched = old_row.get('Matched', 'No Match')
        new_alt_list = []
        old_isotope = int(old_row.get('Isotope', 0)) if pd.notna(old_row.get('Isotope')) else 0
        if old_matched != 'No Match' and pd.notna(old_matched) and old_isotope == 0:
            old_charge = int(old_row['Charge']) if pd.notna(old_row.get('Charge')) else 1
            charge_str = f"{old_charge}+" if old_charge > 1 else ""
            old_label = f"{old_row['Ion Type']}{old_row['Ion Number']}{charge_str}"
            old_ppm = float(old_row['error_ppm']) if pd.notna(old_row.get('error_ppm')) else 0.0
            new_alt_list.append({
                "label": old_label,
                "ppm": round(old_ppm, 4),
                "Theoretical Mass": float(old_matched),
                "Ion Number": old_row['Ion Number'],
                "Ion Type": old_row['Ion Type'],
                "Fragment Sequence": old_row.get('Fragment Sequence', ''),
                "Neutral Loss": old_row.get('Neutral Loss', 'None'),
                "Charge": old_charge,
                "Isotope": int(old_row.get('Isotope', 0)),
                "Color": old_row.get('Color', ''),
                "Base Type": old_row.get('Base Type', ''),
                "Ion Series Type": old_row.get('Ion Series Type', 'Standard-Ion-Series')
            })

        # Add remaining old alternatives (excluding the one being swapped in)
        for existing_alt in old_alt_list:
            if (existing_alt.get('Ion Type') == alt_ion_data.get('Ion Type') and
                existing_alt.get('Ion Number') == alt_ion_data.get('Ion Number') and
                existing_alt.get('Charge') == alt_ion_data.get('Charge')):
                continue  # skip the alt we're promoting to primary
            new_alt_list.append(existing_alt)

        # Sort by ppm
        new_alt_list.sort(key=lambda x: abs(x.get('ppm', 0)))
        new_alt_str = json.dumps(new_alt_list) if new_alt_list else ""

        # Calculate ppm error for the new primary match
        new_ppm_error = alt_ion_data.get('ppm', 0.0)

        # Get the fragment sequence before swap for peptide highlighting cleanup
        old_fragment_sequence = old_row.get('Fragment Sequence', '')

        # Build new annotation text using HTMLFormatter
        new_row_data = pd.Series({
            'Ion Type': alt_ion_data['Ion Type'],
            'Base Type': alt_ion_data['Base Type'],
            'Ion Number': alt_ion_data['Ion Number'],
            'Charge': alt_ion_data['Charge'],
            'Neutral Loss': alt_ion_data.get('Neutral Loss', 'None'),
            'Ion Series Type': alt_ion_data.get('Ion Series Type', 'Standard-Ion-Series')
        })
        new_annotation = HTMLFormatter.format_annotation_unicode(new_row_data)

        # Update DataFrame with new ion data
        new_values = {
            'Matched': alt_ion_data['Theoretical Mass'],
            'Ion Number': alt_ion_data['Ion Number'],
            'Ion Type': alt_ion_data['Ion Type'],
            'Fragment Sequence': alt_ion_data['Fragment Sequence'],
            'Neutral Loss': alt_ion_data.get('Neutral Loss', 'None'),
            'Charge': alt_ion_data['Charge'],
            'Isotope': alt_ion_data['Isotope'],
            'Color': alt_ion_data['Color'],
            'Base Type': alt_ion_data['Base Type'],
            'error_ppm': new_ppm_error,
            'text_annotation': new_annotation,
            'Alternative Matches': new_alt_str
        }

        for column, value in new_values.items():
            if column in self.df.columns:
                self.df.loc[df_mask, column] = value
            if hasattr(self, 'matched_df') and not self.matched_df.empty:
                matched_df_mask = abs(self.matched_df['m/z'] - target_mz) < tolerance
                if column in self.matched_df.columns:
                    self.matched_df.loc[matched_df_mask, column] = value

        # Mark manual changes
        if hasattr(self.parent(), 'mark_manual_changes'):
            self.parent().mark_manual_changes()

        # Visually update: remove old annotation, re-add with new data
        self.convert_peak_to_unmatched(target_mz, old_fragment_sequence)

        # Only restore visual annotation if this is a monoisotopic ion (Isotope == 0)
        alt_isotope = int(alt_ion_data.get('Isotope', 0))
        if alt_isotope == 0:
            self.restore_peak_annotation(target_mz, {
                0: {
                    'Color': alt_ion_data['Color'],
                    'text_annotation': new_annotation,
                    'Isotope': 0,
                    'Fragment Sequence': alt_ion_data['Fragment Sequence'],
                    'Base Type': alt_ion_data['Base Type'],
                    'Ion Number': alt_ion_data['Ion Number'],
                    'error_ppm': new_ppm_error
                }
            }, alt_ion_data['Fragment Sequence'])
        else:
            # For non-monoisotopic ions, just restore the peak color without text annotation
            for i, (line_item, data) in enumerate(self.peak_lines):
                if abs(data['mz'] - target_mz) < tolerance:
                    new_pen = pg.mkPen(alt_ion_data['Color'], width=PlotConstants.PEAK_LINE_WIDTH)
                    line_item.setPen(new_pen)
                    line_item.original_pen = new_pen
                    self.peak_lines[i] = (line_item, {
                        "mz": data['mz'],
                        "intensity": data['intensity'],
                        "annotation": "",
                        "is_matched": True,
                    })
                    break

        # Update fragment lines on the peptide display
        self._delayed_plot_data_fragments_only()

        self.update_undo_button_state()
        self.persistent_tooltip.hide_tooltip()
        self.reset_linked_highlighting()
        self.reset_peptide_highlighting()

        logger.debug(f"Swapped peak at m/z {target_mz:.4f} from {old_row.get('Ion Type', '?')}{old_row.get('Ion Number', '?')} to {alt_ion_data['Ion Type']}{alt_ion_data['Ion Number']}")

    def copy_mz_to_clipboard_with_data(self, peak_data):
        """Copy m/z value to clipboard with provided peak data"""
        if peak_data:
            try:
                clipboard = QApplication.clipboard()
                mz_text = f"{peak_data['mz']:.4f}"
                clipboard.setText(mz_text)
                logger.debug(f"Copied m/z {mz_text} to clipboard")
            except Exception as e:
                logger.error(f"Failed to copy to clipboard: {e}")
        else:
            print("[DEBUG] No peak data available for copying")

    def undo_annotation_removal(self):
        """Undo the last annotation removal or swap.

        Handles restoring multiple peaks when a monoisotopic + isotope removal is undone.
        """
        if not self.annotation_removal_history:
            return

        # Get the last removal/swap
        undo_data = self.annotation_removal_history.pop()
        target_mz = undo_data['mz']
        original_data = undo_data['original_data']
        all_mzs = undo_data.get('all_mzs', [target_mz])  # backwards compatible
        tolerance = PlotConstants.MZ_TOLERANCE

        # Helper to convert stored values to proper types
        def _convert_value(column, value):
            if column in ['Ion Number', 'Charge', 'Isotope'] and value is not None:
                try:
                    return int(value) if value != '' else 0
                except (ValueError, TypeError):
                    return 0
            elif column == 'error_ppm' and value is not None:
                try:
                    return float(value) if value != '' else None
                except (ValueError, TypeError):
                    return None
            return value

        # Clear current visual state for ALL affected peaks
        for mz_val in all_mzs:
            df_mask = abs(self.df['m/z'] - mz_val) < tolerance
            current_rows = self.df[df_mask]
            current_frag_seq = ''
            if not current_rows.empty:
                current_frag_seq = current_rows.iloc[0].get('Fragment Sequence', '') or ''
            self.convert_peak_to_unmatched(mz_val, current_frag_seq)

        # Restore original data to self.df for ALL peaks (primary + isotopes)
        for idx, data in original_data.items():
            for column, value in data.items():
                if column in self.df.columns:
                    self.df.loc[idx, column] = _convert_value(column, value)

        # Restore matched_df for ALL affected peaks
        if hasattr(self, 'matched_df') and not self.matched_df.empty:
            for idx, data in original_data.items():
                # Find by m/z of the original index
                if idx in self.df.index:
                    peak_mz = self.df.loc[idx, 'm/z']
                    matched_df_mask = abs(self.matched_df['m/z'] - peak_mz) < tolerance
                    if matched_df_mask.any():
                        for column, value in data.items():
                            if column in self.matched_df.columns:
                                self.matched_df.loc[matched_df_mask, column] = _convert_value(column, value)

        # Separate original_data into primary (monoisotopic) and isotope entries
        primary_data = {}
        for idx, data in original_data.items():
            isotope_val = data.get('Isotope', 0)
            try:
                isotope_num = int(isotope_val) if isotope_val is not None else 0
            except (ValueError, TypeError):
                isotope_num = 0

            if isotope_num == 0:
                primary_data[idx] = data

        # Restore visual annotation for the primary (monoisotopic) peak
        if primary_data:
            fragment_sequence = list(primary_data.values())[0].get('Fragment Sequence', '') or ''
            self.restore_peak_annotation(target_mz, primary_data, fragment_sequence)

        # Restore isotope peak colors (no text annotation, just color)
        for idx, data in original_data.items():
            isotope_val = data.get('Isotope', 0)
            try:
                isotope_num = int(isotope_val) if isotope_val is not None else 0
            except (ValueError, TypeError):
                isotope_num = 0

            if isotope_num > 0 and idx in self.df.index:
                iso_mz = self.df.loc[idx, 'm/z']
                iso_color = data.get('Color', EditorConstants.UNMATCHED_PEAK_COLOR())
                for i, (line_item, line_data) in enumerate(self.peak_lines):
                    if abs(line_data['mz'] - iso_mz) < tolerance:
                        new_pen = pg.mkPen(iso_color, width=PlotConstants.PEAK_LINE_WIDTH)
                        line_item.setPen(new_pen)
                        line_item.original_pen = new_pen
                        self.peak_lines[i] = (line_item, {
                            "mz": line_data['mz'],
                            "intensity": line_data['intensity'],
                            "annotation": "",
                            "is_matched": True,
                        })
                        break

        # Update peptide fragment lines from current DataFrame state
        self._delayed_plot_data_fragments_only()

        # Update undo button state
        self.update_undo_button_state()
        self.persistent_tooltip.hide_tooltip()
        self.reset_linked_highlighting()
        self.reset_peptide_highlighting()


    def convert_peak_to_unmatched(self, target_mz, fragment_sequence=None):
        """Convert an annotated peak to unmatched appearance while preserving the peak line"""
        tolerance = PlotConstants.MZ_TOLERANCE

        # Update peak line style with theme-aware color
        for i, (line_item, data) in enumerate(self.peak_lines):
            if abs(data['mz'] - target_mz) < tolerance:
                grey_color = pg.mkColor(EditorConstants.UNMATCHED_PEAK_COLOR())
                grey_color.setAlpha(PlotConstants.UNMATCHED_PEAK_ALPHA)
                new_pen = pg.mkPen(grey_color, width=PlotConstants.PEAK_LINE_WIDTH)
                line_item.setPen(new_pen)
                line_item.original_pen = new_pen

                self.peak_lines[i] = (line_item, {
                    "mz": data['mz'],
                    "intensity": data['intensity'],
                    "annotation": "",
                    "is_matched": False,
                })
                break


        items_to_remove = []
        for item in self.matched_items:
            should_remove = False

            # Check for EnhancedInteractiveTextItem (straight leader line system)
            if isinstance(item, EnhancedInteractiveTextItem):
                if hasattr(item, 'peak_coord'):
                    peak_mz = item.peak_coord[0]
                    if abs(peak_mz - target_mz) < tolerance:
                        should_remove = True
                        # Also remove associated leader line
                        if hasattr(item, 'leader_line') and item.leader_line:
                            items_to_remove.append(item.leader_line)

            # Check for old InteractiveTextItem (fallback)
            elif isinstance(item, InteractiveTextItem):
                if hasattr(item, 'peak_coord'):
                    peak_mz = item.peak_coord[0]
                    if abs(peak_mz - target_mz) < tolerance:
                        should_remove = True
                        # Also remove associated leader line
                        if hasattr(item, 'leader_line') and item.leader_line:
                            items_to_remove.append(item.leader_line)

            # Check for standalone leader line segments (PlotDataItem with dashed lines)
            elif hasattr(item, 'opts') and 'pen' in item.opts:
                try:
                    pen = item.opts['pen']
                    if hasattr(pen, 'style') and pen.style() == Qt.PenStyle.DashLine:
                        # Check if this leader line is associated with our target peak
                        data = item.getData()
                        if data and len(data) >= 2:
                            x_data, y_data = data
                            if len(x_data) >= 2:
                                # Check if any x coordinate matches our target (within tolerance)
                                for x_coord in x_data:
                                    if abs(float(x_coord) - target_mz) < tolerance:
                                        should_remove = True
                                        break
                except Exception:
                    continue

            if should_remove:
                items_to_remove.append(item)

        # Remove items from plot and matched_items list
        for item in items_to_remove:
            try:
                # Don't remove the peak line itself (it should stay as grey)
                if not any(item == line_item for line_item, _ in self.peak_lines):
                    self.spectrumplot.removeItem(item)
                    if item in self.matched_items:
                        self.matched_items.remove(item)
            except Exception:
                continue

        # Remove error plot points
        error_items_to_remove = []
        for i, error_data in enumerate(self.error_scatter_items):
            if abs(error_data['mz'] - target_mz) < tolerance:
                try:
                    self.errorbarplot.removeItem(error_data['scatter_item'])
                    error_items_to_remove.append(i)
                except Exception:
                    error_items_to_remove.append(i)

        # Remove from list in reverse order
        for i in reversed(error_items_to_remove):
            self.error_scatter_items.pop(i)

        # Remove fragment line
        if fragment_sequence and hasattr(self, 'mass_spec_viewer'):
            self.remove_fragment_line_from_peptide(fragment_sequence, target_mz)

    def restore_peak_annotation(self, target_mz, original_data, fragment_sequence=None):
        """Restore an unmatched peak to its original annotated state"""
        tolerance = PlotConstants.MZ_TOLERANCE

        first_data = list(original_data.values())[0]
        original_color = first_data.get('Color', EditorConstants.TEXT_COLOR())

        # Find the peak
        peak_intensity = None
        peak_data = None
        for i, (line_item, data) in enumerate(self.peak_lines):
            if abs(data['mz'] - target_mz) < tolerance:
                peak_intensity = data['intensity']
                peak_data = data

                # 1. Restore the line to matched style
                new_pen = pg.mkPen(original_color, width=PlotConstants.PEAK_LINE_WIDTH)
                line_item.setPen(new_pen)
                line_item.original_pen = new_pen

                self.peak_lines[i] = (line_item, {
                    "mz": data['mz'],
                    "intensity": data['intensity'],
                    "annotation": first_data.get('text_annotation', ''),
                    "is_matched": True,
                })
                break

        annotation_text = first_data.get('text_annotation', '')  # Unicode for plot display
        html_annotation_text = first_data.get('html_annotation', '')  # HTML for tooltips
        isotope_value = first_data.get('Isotope', 0)

        try:
            isotope_numeric = float(isotope_value) if isotope_value is not None else 0
        except (ValueError, TypeError):
            isotope_numeric = 0

        if (isotope_numeric == 0 and annotation_text and annotation_text.strip()):
            # Recreate annotation with improved leader line
            # Check if text will be rotated
            is_rotated = hasattr(self, 'text_rotation_angle') and abs(self.text_rotation_angle - 90) < 5

            # Increase vertical offset for rotated text to prevent clipping
            if is_rotated:
                vertical_offset = PlotConstants.PEAK_LABEL_OFFSET + 15  # Extra offset for rotated text
            else:
                vertical_offset = PlotConstants.PEAK_LABEL_OFFSET

            horizontal_offset = 15

            # Calculate label position
            if peak_intensity + vertical_offset <= PlotConstants.SPECTRUM_Y_LIMIT - 10:
                label_x = target_mz + horizontal_offset
                label_y = peak_intensity + vertical_offset
                anchor = (0, 0.5)
            else:
                label_x = target_mz + horizontal_offset + 10
                label_y = peak_intensity - 5
                anchor = (0, 0.5)

            # Create simple straight leader line with opacity
            leader_line = self._create_simple_leader_line(
                target_mz, peak_intensity, label_x, label_y, original_color, annotation_text, is_rotated=is_rotated
            )

            # Add leader line to plot
            self.spectrumplot.addItem(leader_line)
            self.matched_items.append(leader_line)

            # Prepare fragment data for hover highlighting
            fragment_data = {
                'fragment_sequence': first_data.get('Fragment Sequence', ''),
                'base_type': str(first_data.get('Base Type', '')).strip(),
                'ion_number': first_data.get('Ion Number', ''),
                'position': self._calculate_fragment_position(first_data)
            }

            # Create enhanced text item with proper HTML formatting
            text_item = EnhancedInteractiveTextItem(
                text=annotation_text,  # Unicode for display
                color=original_color,
                peak_coord=(target_mz, peak_intensity),
                leader_line=leader_line,
                viewer=self,
                fragment_data=fragment_data,
                anchor=anchor
            )

            # Apply font and rotation, then set HTML content
            text_item.setFont(QFont(PlotConstants.DEFAULT_FONT_FAMILY, self.annotation_font_size))
            if hasattr(self, 'text_rotation_angle') and self.text_rotation_angle != 0:
                text_item.setRotation(self.text_rotation_angle)

            # Set HTML content properly
            text_item.setHtml(annotation_text)  # Unicode displays fine with setHtml
            text_item._html_annotation = html_annotation_text  # Store HTML version for tooltips/export
            text_item.setPos(label_x, label_y)

            self.spectrumplot.addItem(text_item)
            self.matched_items.append(text_item)

        # Re-add error plot point
        error_ppm = first_data.get('error_ppm')

        if (error_ppm is not None and
            not (isinstance(error_ppm, str) and error_ppm.strip() == '') and
            not pd.isna(error_ppm) and
            isotope_numeric == 0):

            try:
                error_ppm_float = float(error_ppm)
                scatter_item = pg.ScatterPlotItem(
                    pos=[(target_mz, error_ppm_float)],
                    brush=original_color,
                    symbol='o',
                    size=PlotConstants.ERROR_SCATTER_SIZE,
                    pen=pg.mkPen(original_color, width=1)
                )

                scatter_data = {
                    'mz': target_mz,
                    'error': error_ppm_float,
                    'idx': list(original_data.keys())[0],
                    'ion_type': first_data.get('Ion Type', ''),
                    'original_brush': original_color,
                    'scatter_item': scatter_item,
                    'annotation': html_annotation_text or annotation_text,  # Use HTML for tooltips
                    'intensity': peak_intensity
                }

                self.error_scatter_items.append(scatter_data)
                self.errorbarplot.addItem(scatter_item)
            except (ValueError, TypeError) as e:
                logger.debug(f"Error converting error_ppm to float: {e}")
        else:
            logger.debug(f"Not restoring error point - conditions not met")

        # Redraw peptide fragment lines
        if hasattr(self, 'mass_spec_viewer'):
            self._delayed_plot_data_fragments_only()

        logger.debug(f"Restored peak annotation for m/z: {target_mz}")

    def update_undo_button_state(self):
        """Update the enabled state of the undo action"""
        if hasattr(self, 'undo_annotation_action'):
            has_history = len(self.annotation_removal_history) > 0
            self.undo_annotation_action.setEnabled(has_history)
            if has_history:
                last_entry = self.annotation_removal_history[-1]
                mz_str = f"m/z {last_entry['mz']:.4f}"
                # Check if this was a swap (has Alternative Matches in original) or a removal
                first_orig = list(last_entry['original_data'].values())[0]
                if 'Alternative Matches' in first_orig and first_orig.get('Alternative Matches'):
                    self.undo_annotation_action.setText(f"Undo change at {mz_str}")
                else:
                    self.undo_annotation_action.setText(f"Undo removal at {mz_str}")
            else:
                self.undo_annotation_action.setText("Undo Annotation Change")
            logger.debug(f"Undo button state updated: enabled={has_history}")
        else:
            print("[DEBUG] undo_annotation_action not found")
