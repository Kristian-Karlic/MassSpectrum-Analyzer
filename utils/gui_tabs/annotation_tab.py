
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QSizePolicy
)
import re
import pandas as pd
import math
from math import factorial

from PyQt6.QtCore import Qt
from utils.style.style import EditorConstants
from utils.spectrum_graph.mass_spec_viewer_widget import MassSpecViewer
from utils.spectrum_graph.peptide_info_widget import PeptideInfoWidget
from utils.tables.spectrum_tracking import SpectrumTrackerWidget
from utils.tables.psm_summary_widget import PSMSummaryWidget
from utils.style.style import StyleSheet
import traceback
class AnnotationTabManager:
    def __init__(self, main_app):
        self.main_app = main_app
        
        # Initialize annotation-specific attributes
        self.mass_spec_viewer = None
        self.peptide_info_widget = None
        self.spectrum_tracker = None
        self.psm_summary_widget = None
        
        # Containers
        self.tracker_container = None
        self.info_container = None
        self.graph_container = None
        self.right_panel_container = None
        
        #  Current data reference for rescore calculation
        self.current_matched_data = None
    
    def setup_annotation_tab(self):
        """Setup the annotation tab with mass spec viewer functionality and original PSM Summary"""
        annotation_tab = QWidget()
        annotation_layout = QVBoxLayout(annotation_tab)
        annotation_layout.setContentsMargins(0, 0, 0, 0)
        annotation_layout.setSpacing(0)
        
        ################################################################
        # TOP SECTION - Mass Spec Viewer and Analysis Tools
        ################################################################
        
        top_section = QWidget()
        top_layout = QHBoxLayout(top_section)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        
        # Create mass spec viewer container
        self._create_mass_spec_viewer_container()
        
        # Create right panel with analysis tools
        self._create_analysis_tools_panel()
        
        # Add to top section layout
        top_layout.addWidget(self.graph_container, 3)  # Mass spec viewer gets 3/4 of space
        top_layout.addWidget(self.right_panel_container, 1)  # Analysis tools get 1/4 of space
        
        ################################################################
        # BOTTOM SECTION - Original PSM Summary Widget
        ################################################################
        
        # Create original PSM summary widget (non-draggable, for selecting spectra)
        self.psm_summary_widget = PSMSummaryWidget()  # Original version
        self.psm_summary_widget.setMinimumHeight(50)
        self.psm_summary_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        # Add sections to annotation tab
        annotation_layout.addWidget(top_section, 2)  # Top gets more space
        annotation_layout.addWidget(self.psm_summary_widget, 1)  # Bottom gets less space
        
        # Add tab to main tab widget
        self.main_app.main_tab_widget.addTab(annotation_tab, "Annotation")
        
        # Connect signals
        self._connect_annotation_signals()
        
        print("[DEBUG] Annotation tab setup completed")
        
        return annotation_tab
    
    def _create_mass_spec_viewer_container(self):
        """Create the mass spec viewer container"""
        self.graph_container = QWidget()
        graph_layout = QVBoxLayout(self.graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(0)
        
        self.mass_spec_viewer = MassSpecViewer()
        self.mass_spec_viewer.setWindowFlags(Qt.WindowType.Widget)
        self.mass_spec_viewer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        
        graph_layout.addWidget(self.mass_spec_viewer)
        
        self.graph_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
    
    def _create_analysis_tools_panel(self):
        """Create the right panel with analysis tools"""
        from utils.style.GUI_dimensions import LayoutConstants

        self.right_panel_container = QWidget()
        self.right_panel_container.setMinimumWidth(LayoutConstants.RIGHT_PANEL_MIN_WIDTH)
        self.right_panel_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )

        right_main_layout = QVBoxLayout(self.right_panel_container)
        right_main_layout.setContentsMargins(0, 0, 0, 0)
        right_main_layout.setSpacing(0)


        right_content_widget = QWidget()
        right_content_layout = QVBoxLayout(right_content_widget)
        right_content_layout.setContentsMargins(0, 0, 0, 0)
        right_content_layout.setSpacing(6)

        # Create peptide info widget (will be inserted into tracker tabs)
        self._create_peptide_info_widget()

        # Create spectrum tracker widget (takes full right panel space)
        self._create_spectrum_tracker_widget(right_content_layout)

        # Insert the peptide info scroll area as the first tab in the spectrum tracker
        self.spectrum_tracker.set_peptide_info_widget(self.peptide_info_scroll)

        right_main_layout.addWidget(right_content_widget)

    def _create_spectrum_tracker_widget(self, parent_layout):
        """Create the spectrum tracker widget """
        self.tracker_container = self._create_panel(
            widget_type="spectrum_tracker"
        )

        self.spectrum_tracker = SpectrumTrackerWidget(main_app=self.main_app)
        self.spectrum_tracker.setMinimumHeight(50)
        self.spectrum_tracker.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )

        self.tracker_container.content_widget.layout().addWidget(self.spectrum_tracker)
        parent_layout.addWidget(self.tracker_container, 1)

    def _create_peptide_info_widget(self):
        """Create the peptide info widget (to be inserted into spectrum tracker tabs)"""
        self.peptide_info_scroll = QScrollArea()
        self.peptide_info_scroll.setWidgetResizable(True)
        self.peptide_info_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.peptide_info_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.peptide_info_scroll.setMinimumHeight(50)
        self.peptide_info_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )

        # Create the peptide info widget
        self.peptide_info_widget = PeptideInfoWidget()
        self.peptide_info_scroll.setWidget(self.peptide_info_widget)
    
    def _create_panel(self, widget_type: str) -> QWidget:
        """Create a simple panel"""
        # Main container
        container = QWidget()
        
        # Main layout
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        
        # Content widget
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(2, 2, 2, 2)
        
        # Add to main layout
        main_layout.addWidget(content_widget)
        
        # Store minimal references (for compatibility)
        container.content_widget = content_widget
        container.widget_type = widget_type
        
        return container

    
    def _connect_annotation_signals(self):
        """Connect signals for the annotation tab"""
        # Connect mass spec viewer modification changes
        if self.mass_spec_viewer:
            self.mass_spec_viewer.modificationsChanged.connect(
                self.main_app.event_handlers.on_interactive_modifications_changed
            )
            
            # Connect to notify analysis tab when data changes
            if hasattr(self.mass_spec_viewer, 'dataChanged'):
                self.mass_spec_viewer.dataChanged.connect(self._on_mass_spec_data_changed)
            
            # Set available modifications
            if hasattr(self.main_app, 'available_mods'):
                try:
                    self.mass_spec_viewer.set_available_modifications(self.main_app.available_mods)
                except Exception as e:
                    print(f"Error setting available modifications: {e}")
        
        # Connect PSM summary widget signals 
        if self.psm_summary_widget:
            self.psm_summary_widget.peptideSelected.connect(
                self.main_app.event_handlers.on_peptide_selected
            )
            self.psm_summary_widget.rawDataExtracted.connect(
                self.main_app.event_handlers.on_raw_data_extracted
            )
            
            # Connect table view change signal for synchronization
            if hasattr(self.psm_summary_widget, 'stacked_widget'):
                self.psm_summary_widget.stacked_widget.currentChanged.connect(
                    self._on_annotation_table_view_changed
                )
        
        # Connect spectrum tracker signals 
        if self.spectrum_tracker:
            self.spectrum_tracker.spectrumAccepted.connect(
                self.main_app.event_handlers.on_spectrum_accepted
            )
            self.spectrum_tracker.spectrumDeclined.connect(
                self.main_app.event_handlers.on_spectrum_declined
            )
        
        # Connect peptide info widget signals
        if self.peptide_info_widget:
            self.peptide_info_widget.analysisRequested.connect(
                self.main_app.event_handlers.on_analysis_requested
            )
    
    def _on_mass_spec_data_changed(self):
        """Handle when mass spec viewer data changes"""
        try:
            # Notify analysis tab that annotation data has changed
            if (hasattr(self.main_app, 'analysis_tab_manager') and 
                hasattr(self.main_app.analysis_tab_manager, 'on_annotation_data_changed')):
                self.main_app.analysis_tab_manager.on_annotation_data_changed()
                print("[DEBUG] Notified analysis tab of annotation data change")
                
        except Exception as e:
            print(f"[ERROR] Error notifying analysis tab of data change: {e}")

    def _on_annotation_table_view_changed(self, index):
        """Handle when annotation tab PSM table view changes"""
        try:
            # Sync the view change to analysis tab if it exists
            if (hasattr(self.main_app, 'analysis_tab_manager') and 
                hasattr(self.main_app.analysis_tab_manager, 'analysis_psm_summary') and
                self.main_app.analysis_tab_manager.analysis_psm_summary):
                
                analysis_psm = self.main_app.analysis_tab_manager.analysis_psm_summary
                
                if hasattr(analysis_psm, 'stacked_widget'):
                    try:
                        analysis_psm.stacked_widget.currentChanged.disconnect(
                            self.main_app.analysis_tab_manager._on_analysis_table_view_changed
                        )
                    except TypeError:
                        pass
                    
                    analysis_psm.stacked_widget.setCurrentIndex(index)
                    
                    # Reconnect the specific signal
                    analysis_psm.stacked_widget.currentChanged.connect(
                        self.main_app.analysis_tab_manager._on_analysis_table_view_changed
                    )
                
                # Also sync filter visibility
                if index == 0:  # Summary view
                    if hasattr(analysis_psm, 'summary_filter_widget'):
                        analysis_psm.summary_filter_widget.setVisible(True)
                    if hasattr(analysis_psm, 'details_filter_widget'):
                        analysis_psm.details_filter_widget.setVisible(False)
                else:  # Details view
                    if hasattr(analysis_psm, 'summary_filter_widget'):
                        analysis_psm.summary_filter_widget.setVisible(False)
                    if hasattr(analysis_psm, 'details_filter_widget'):
                        analysis_psm.details_filter_widget.setVisible(True)
                    
                    # Sync details data
                    if (hasattr(self.psm_summary_widget, 'original_details_df') and 
                        not self.psm_summary_widget.original_details_df.empty):
                        
                        analysis_psm.original_details_df = self.psm_summary_widget.original_details_df.copy()
                        analysis_psm.current_details_df = self.psm_summary_widget.current_details_df.copy()
                        analysis_psm._show_details_table()
                
                print(f"[DEBUG] Synced annotation table view change to analysis tab: index {index}")
                
        except Exception as e:
            print(f"[ERROR] Error syncing annotation table view change: {e}")

    def set_data(self, merged_df):
        """Set data for the PSM summary widget"""
        if self.psm_summary_widget and not merged_df.empty:
            self.psm_summary_widget.setData(merged_df)
    
    def update_peptide_info(self, peptide, fragmented_bonds, annotated_tic, matched_data, theoretical_data=None):
        """Update peptide information widget"""
        if self.peptide_info_widget:
            # Calculate rescore using local methods
            rescore = None
            try:
                # Store the matched data for rescore calculation
                self.current_matched_data = matched_data
                rescore = self.calculate_rescore_for_peptide_info()
                # Refresh relocalisation combo with current modifications
                if hasattr(self, 'spectrum_tracker') and hasattr(self.spectrum_tracker, 'relocalise_tab'):
                    self.spectrum_tracker.relocalise_tab.refresh_modifications()
            except Exception as e:
                print(f"[ERROR] Error calculating rescore: {e}")
                rescore = None

            self.peptide_info_widget.update_peptide_info(
                peptide=peptide,
                fragmented_bonds=fragmented_bonds,
                annotated_tic=annotated_tic,
                matched_data=matched_data,
                rescore=rescore,
                theoretical_data=theoretical_data
            )

    # A X!Tandem score calculation methods
    def calculate_rescore_for_peptide_info(self):
        """Calculate all scores for display in peptide info widget.

        Returns a dict with keys:
            xtandem, consecutive_series, complementary_pairs
        or None on failure.  Optional scores are only computed when the user
        has enabled them via File → Rescore Settings.
        """
        try:
            if self.current_matched_data is None or self.current_matched_data.empty:
                return None
            
            # Get selected ion types from annotation settings
            selected_ions = self.get_selected_annotation_ion_types()
            
            if not selected_ions:
                return None
            
            # Read which optional scoring methods are enabled
            scoring_flags = {}
            if hasattr(self, 'main_app') and hasattr(self.main_app, 'scoring_methods'):
                scoring_flags = self.main_app.scoring_methods
            
            # Filter data including neutral losses by default
            filtered_data = self.filter_data_for_scoring(
                self.current_matched_data, 
                selected_ions, 
                include_neutral=True
            )
            
            # Always calculate X!Tandem score
            result = self.calculate_single_xtandem(filtered_data, selected_ions)
            xtandem = result.get('xtandem', 0.0)

            scores = {
                'xtandem': xtandem,
                'consecutive_series': None,
                'complementary_pairs': None,
                'morpheus_score': None
            }

            # Only compute optional scores if the user enabled them
            needs_peptide_length = (
                scoring_flags.get('complementary_pairs')
            )
            
            peptide_length = 0
            if needs_peptide_length:
                if hasattr(self, 'main_app') and hasattr(self.main_app, 'peptide_input'):
                    try:
                        peptide_length = len(self.main_app.peptide_input.text().strip())
                    except Exception:
                        pass
                if peptide_length == 0:
                    try:
                        nums = pd.to_numeric(filtered_data['Ion Number'], errors='coerce').dropna()
                        if not nums.empty:
                            peptide_length = int(nums.max()) + 1
                    except Exception:
                        peptide_length = 0
            

            if scoring_flags.get('consecutive_series'):
                scores['consecutive_series'] = self.calculate_consecutive_ion_series(
                    filtered_data
                )
            
            if scoring_flags.get('complementary_pairs'):
                scores['complementary_pairs'] = self.calculate_complementary_pairs(
                    filtered_data, peptide_length
                )

            if scoring_flags.get('morpheus_score'):
                # Morpheus = matched_fragment_count + annotated_tic_fraction
                # e.g. 45 matched + 60% TIC = 45.60
                matched_peaks = filtered_data[
                    (filtered_data['Matched'].notna()) &
                    (filtered_data['Matched'] != 'No Match')
                ]
                isotope_col = 'Isotope' if 'Isotope' in matched_peaks.columns else None
                if isotope_col:
                    mono = matched_peaks[
                        pd.to_numeric(matched_peaks[isotope_col], errors='coerce') == 0
                    ]
                else:
                    mono = matched_peaks
                n_matched = len(mono)

                intensity_col = 'intensity' if 'intensity' in self.current_matched_data.columns else 'Intensity'
                total_int = pd.to_numeric(
                    self.current_matched_data[intensity_col], errors='coerce'
                ).fillna(0).sum()
                matched_int = pd.to_numeric(
                    matched_peaks[intensity_col], errors='coerce'
                ).fillna(0).sum()
                tic_pct = (matched_int / total_int * 100.0) if total_int > 0 else 0.0
                scores['morpheus_score'] = round(n_matched + tic_pct / 100.0, 4)

            return scores
            
        except Exception as e:
            print(f"[ERROR] Error calculating rescore for peptide info: {e}")
            return None

    def get_selected_annotation_ion_types(self):
        """Get the currently selected ion types from the annotation settings"""
        try:
            selected_ion_types = []
            
            # Get selected normal ion types
            if hasattr(self.main_app, 'normal_ion_checkboxes'):
                for ion_type, checkbox in self.main_app.normal_ion_checkboxes.items():
                    if checkbox.isChecked():
                        selected_ion_types.append(ion_type)

            # Get selected neutral loss ion types
            if hasattr(self.main_app, 'neutral_ion_checkboxes'):
                for ion_type, checkbox in self.main_app.neutral_ion_checkboxes.items():
                    if checkbox.isChecked():
                        # Convert neutral loss format to base type for scoring
                        base_type = ion_type.split('-')[0]
                        if base_type not in selected_ion_types:
                            selected_ion_types.append(base_type)

            # Get selected internal ion types
            if hasattr(self.main_app, 'internal_ion_checkboxes'):
                for ion_type, checkbox in self.main_app.internal_ion_checkboxes.items():
                    if checkbox.isChecked():
                        if ion_type not in selected_ion_types:
                            selected_ion_types.append(ion_type)
            
            # Always include custom and diagnostic ions if they're selected
            if hasattr(self.main_app, 'selected_custom_ions_data') and self.main_app.selected_custom_ions_data:
                for custom_ion in self.main_app.selected_custom_ions_data:
                    base_ion = custom_ion.get('Base Ion', '')
                    if base_ion and base_ion not in selected_ion_types:
                        selected_ion_types.append(base_ion)
            
            if hasattr(self.main_app, 'selected_diagnostic_ions_data') and self.main_app.selected_diagnostic_ions_data:
                # Diagnostic ions are typically treated as special cases
                selected_ion_types.append('diagnostic')
            
            return selected_ion_types
            
        except Exception as e:
            print(f"[ERROR] Error getting selected annotation ion types: {e}")
            return ['b', 'y']  # Fallback to common ion types

    def filter_data_for_scoring(self, data, ion_types, include_neutral=True):
        """Filter data based on scoring criteria - ENHANCED to handle z+1 and c-1 separately"""
        if data is None or data.empty:
            return pd.DataFrame()
            
        # Start with matched peaks only
        filtered_data = data[
            (data['Matched'].notna()) & 
            (data['Matched'] != 'No Match')
        ].copy()
        
        if filtered_data.empty:
            return filtered_data
        
        print(f"[DEBUG] Starting with {len(filtered_data)} matched peaks")
        print(f"[DEBUG] Ion types to include: {ion_types}")
        
        # Filter by selected ion types
        ion_type_mask = pd.Series([False] * len(filtered_data), index=filtered_data.index)
        
        if 'Ion Type' in filtered_data.columns:
            for _, row in filtered_data.iterrows():
                ion_type_str = str(row.get('Ion Type', '')).strip()
                
                # Check against each selected ion type
                for selected_ion_type in ion_types:
                    if self._ion_type_matches_selected_for_scoring(ion_type_str, selected_ion_type):
                        ion_type_mask.loc[row.name] = True
                        break  # Found a match, no need to check other types
        
        elif 'Base Type' in filtered_data.columns:
            # If Base Type column exists, use it directly (but still handle z+1 and c-1)
            for _, row in filtered_data.iterrows():
                base_type = str(row.get('Base Type', '')).strip()
                ion_type_full = str(row.get('Ion Type', '')).strip()
                
                for selected_ion_type in ion_types:
                    if selected_ion_type == 'z+1':
                        if 'z+1' in ion_type_full.lower():
                            ion_type_mask.loc[row.name] = True
                            break
                    elif selected_ion_type == 'c-1':
                        if 'c-1' in ion_type_full.lower():
                            ion_type_mask.loc[row.name] = True
                            break
                    elif selected_ion_type == 'z':
                        if base_type == 'z' and 'z+1' not in ion_type_full.lower():
                            ion_type_mask.loc[row.name] = True
                            break
                    elif selected_ion_type == 'c':
                        if base_type == 'c' and 'c-1' not in ion_type_full.lower():
                            ion_type_mask.loc[row.name] = True
                            break
                    else:
                        if base_type == selected_ion_type:
                            ion_type_mask.loc[row.name] = True
                            break
        
        filtered_data = filtered_data[ion_type_mask]
        
        if not include_neutral:
            # Exclude neutral losses 
            if 'Neutral Loss' in filtered_data.columns:
                neutral_mask = (filtered_data['Neutral Loss'] == 'None') | (filtered_data['Neutral Loss'].isna())
                filtered_data = filtered_data[neutral_mask]
            elif 'Ion Type' in filtered_data.columns:
                # Check for neutral loss indicators in Ion Type
                neutral_mask = ~filtered_data['Ion Type'].str.contains('-', na=False)
                filtered_data = filtered_data[neutral_mask]
            print(f"[DEBUG] After neutral loss filtering: {len(filtered_data)} peaks")

        # Charge state filter for scoring
        scoring_max_charge = getattr(self.main_app, 'scoring_max_charge', 0)
        if scoring_max_charge > 0 and 'Charge' in filtered_data.columns and not filtered_data.empty:
            filtered_data = filtered_data[
                pd.to_numeric(filtered_data['Charge'], errors='coerce').fillna(1).astype(int)
                <= scoring_max_charge
            ]

        return filtered_data

    def _ion_type_matches_selected_for_scoring(self, ion_type_str, selected_ion_type):
        """Check if ion type matches selected type for scoring - handles z+1 and c-1 separately"""

        
        # Handle z+1 as special case
        if selected_ion_type == 'z+1':
            return 'z+1' in ion_type_str.lower()
        
        # Handle c-1 as special case
        if selected_ion_type == 'c-1':
            return 'c-1' in ion_type_str.lower()
        
        # Handle regular z (exclude z+1)
        if selected_ion_type == 'z':
            if 'z+1' in ion_type_str.lower():
                return False
            base_match = re.match(r'^z\d*', ion_type_str)
            return base_match is not None
        
        # Handle regular c (exclude c-1)
        if selected_ion_type == 'c':
            if 'c-1' in ion_type_str.lower():
                return False
            base_match = re.match(r'^c\d*', ion_type_str)
            return base_match is not None

        # Handle d (include da, db variants)
        if selected_ion_type == 'd':
            return re.match(r'^d[ab]?\d*', ion_type_str) is not None

        # Handle w (include wa, wb variants)
        if selected_ion_type == 'w':
            return re.match(r'^w[ab]?\d*', ion_type_str) is not None

        # Handle satellite neutral losses: d-H2O matches da-H2O, db-H2O etc.
        if selected_ion_type.startswith(('d-', 'w-')):
            base_letter = selected_ion_type[0]  # 'd' or 'w'
            loss_part = selected_ion_type[1:]    # '-H2O', '-NH3'
            return re.match(rf'^{base_letter}[ab]?{re.escape(loss_part)}$', ion_type_str) is not None
        if selected_ion_type.startswith('v-'):
            return ion_type_str == selected_ion_type

        # For other ion types, use standard logic
        base_match = re.match(r'^([a-zA-Z]+)', ion_type_str)
        if base_match:
            base_type = base_match.group(1)
            return base_type == selected_ion_type
        
        return False

    def calculate_single_xtandem(self, data, ion_types):
        """Calculate X!Tandem score using formula: HS = log10((∑Ii) * Nb! * Ny!)
        - Ion counts: UNIQUE Ion Number positions per base type (isotope=0 only)
        - Intensities: SUM of ALL matched peaks (all isotopes)"""
        if data.empty:
            return {
                'xtandem': 0.0,
                'total_ion_count': {ion: 0 for ion in ion_types},
                'total_ion_intensities': {ion: 0 for ion in ion_types},
                'total_intensity': 0.0,
                'factorial_product': 1,
                'matched_peaks': 0,
                'error': None
            }
        
        try:
            
            # Initialize counters
            unique_ion_positions = {ion_type: set() for ion_type in ion_types}  # Track unique positions
            total_ion_intensities = {ion_type: 0 for ion_type in ion_types}      # All isotopes
            total_intensity = 0.0
            
            # Determine which columns to use
            base_type_col = 'Base Type'
            ion_number_col = 'Ion Number'
            isotope_col = 'Isotope' if 'Isotope' in data.columns else None
            intensity_col = 'intensity' if 'intensity' in data.columns else 'Intensity'
            
            # Validate required columns
            if base_type_col not in data.columns:
                print(f"[ERROR] Required column '{base_type_col}' not found")
                return self._get_empty_result(ion_types)
            
            if ion_number_col not in data.columns:
                print(f"[ERROR] Required column '{ion_number_col}' not found")
                return self._get_empty_result(ion_types)

            
            # Process each fragment
            for _, row in data.iterrows():
                # Extract base type
                base_type = str(row.get(base_type_col, '')).strip()
                
                # Check if this base type is in our selected ion types
                if base_type not in ion_types:
                    continue
                
                # Get ion number
                try:
                    ion_number = int(row.get(ion_number_col, 0))
                except (ValueError, TypeError):
                    print(f"[WARNING] Invalid ion number: {row.get(ion_number_col)}")
                    continue
                
                # Get isotope info
                if isotope_col and isotope_col in data.columns:
                    isotope = row.get(isotope_col, 0)
                    try:
                        isotope = int(float(isotope)) if pd.notna(isotope) else 0
                    except (ValueError, TypeError):
                        isotope = 0
                else:
                    isotope = 0
                
                # Get intensity
                try:
                    observed_intensity = float(row.get(intensity_col, 0))
                except (ValueError, TypeError):
                    observed_intensity = 0.0
                
                # ALWAYS add intensity to the total (all isotopes)
                total_ion_intensities[base_type] += observed_intensity
                total_intensity += observed_intensity
                
                # ONLY count UNIQUE positions with isotope=0 for factorial calculation
                if isotope == 0:
                    unique_ion_positions[base_type].add(ion_number)
            
            # Convert unique positions to counts
            total_ion_count = {ion_type: len(positions) for ion_type, positions in unique_ion_positions.items()}
            
            # Debug output
            for ion_type in ion_types:
                if total_ion_count[ion_type] > 0:
                    print(f"[DEBUG] {ion_type}: {total_ion_count[ion_type]} unique positions, "
                        f"total intensity: {total_ion_intensities[ion_type]:.2f}")
            
            # Calculate factorial product using ONLY unique monoisotopic position counts
            factorial_product = 1
            
            for ion_type in ion_types:
                unique_count = total_ion_count[ion_type]
                if unique_count > 0:
                    factorial_val = factorial(unique_count)
                    factorial_product *= factorial_val
                    print(f"[DEBUG] {ion_type}! = {unique_count}! = {factorial_val}")
            
            print(f"[DEBUG] Total factorial product: {factorial_product}")
            print(f"[DEBUG] Total intensity: {total_intensity:.2f}")
            
            # Calculate final X!Tandem score: HS = log10((∑Ii) * Nb! * Ny!)
            if total_intensity > 0 and factorial_product > 0:
                xtandem_raw = total_intensity * factorial_product
                xtandem = math.log1p(xtandem_raw)
                print(f"[DEBUG] X!Tandem: log10({total_intensity:.2f} * {factorial_product}) = {xtandem:.4f}")
            else:
                xtandem = 0.0

            return {
                'xtandem': xtandem,
                'total_ion_count': total_ion_count,
                'total_ion_intensities': total_ion_intensities,
                'total_intensity': total_intensity,
                'factorial_product': factorial_product,
                'matched_peaks': len(data),
                'error': None
            }

        except Exception as e:
            print(f"[ERROR] Error calculating X!Tandem score: {e}")
            
            traceback.print_exc()
            return self._get_empty_result(ion_types)

    def _get_empty_result(self, ion_types):
        """Helper to return empty result dictionary"""
        return {
            'xtandem': 0.0,
            'total_ion_count': {ion: 0 for ion in ion_types},
            'total_ion_intensities': {ion: 0 for ion in ion_types},
            'total_intensity': 0.0,
            'factorial_product': 1,
            'matched_peaks': 0,
            'error': None
        }

    # ------------------------------------------------------------------
    # Additional scoring methods
    # ------------------------------------------------------------------

    def calculate_consecutive_ion_series(self, matched_data):
        """
        Find the longest run of consecutively numbered monoisotopic
        fragment ions for each base ion type, and return the overall
        longest run and per-type results.

        Returns
        -------
        dict  {'longest': int, 'per_type': {base_type: int, ...}}
        """
        result = {'longest': 0, 'per_type': {}}
        try:
            if matched_data is None or matched_data.empty:
                return result

            matched_peaks = matched_data[
                (matched_data['Matched'].notna()) &
                (matched_data['Matched'] != 'No Match')
            ]
            if matched_peaks.empty:
                return result

            isotope_col = 'Isotope' if 'Isotope' in matched_peaks.columns else None
            if isotope_col:
                mono = matched_peaks[
                    pd.to_numeric(matched_peaks[isotope_col], errors='coerce') == 0
                ]
            else:
                mono = matched_peaks

            if mono.empty or 'Base Type' not in mono.columns or 'Ion Number' not in mono.columns:
                return result

            # Group by base type
            overall_longest = 0
            for base_type, group in mono.groupby('Base Type'):
                try:
                    positions = sorted(set(
                        int(x) for x in group['Ion Number']
                        if pd.notna(x) and str(x).strip() != ''
                    ))
                except (ValueError, TypeError):
                    continue

                if not positions:
                    continue

                max_run = current_run = 1
                for i in range(1, len(positions)):
                    if positions[i] == positions[i - 1] + 1:
                        current_run += 1
                        max_run = max(max_run, current_run)
                    else:
                        current_run = 1

                result['per_type'][str(base_type)] = max_run
                overall_longest = max(overall_longest, max_run)

            result['longest'] = overall_longest
            return result

        except Exception as e:
            print(f"[ERROR] Consecutive ion series calculation error: {e}")
            return result

    def calculate_complementary_pairs(self, matched_data, peptide_length):
        """
        Count backbone positions where both an N-terminal (b/a/c) and
        the complementary C-terminal (y/x/z) fragment are observed
        (monoisotopic only).

        A position i (1-based) has a complementary pair when:
            b_i  and  y_(n-i)   are both present   (n = peptide_length)

        Returns
        -------
        dict  {'pairs': int, 'positions': list[int], 'possible': int}
        """
        empty = {'pairs': 0, 'positions': [], 'possible': max(peptide_length - 1, 0)}
        try:
            if matched_data is None or matched_data.empty or peptide_length < 2:
                return empty

            matched_peaks = matched_data[
                (matched_data['Matched'].notna()) &
                (matched_data['Matched'] != 'No Match')
            ]
            if matched_peaks.empty:
                return empty

            isotope_col = 'Isotope' if 'Isotope' in matched_peaks.columns else None
            if isotope_col:
                mono = matched_peaks[
                    pd.to_numeric(matched_peaks[isotope_col], errors='coerce') == 0
                ]
            else:
                mono = matched_peaks

            if mono.empty or 'Base Type' not in mono.columns or 'Ion Number' not in mono.columns:
                return empty

            n_term_types = {'b', 'a', 'c', 'c-1', 'd', 'da', 'db'}
            c_term_types = {'y', 'x', 'z', 'z+1', 'w', 'wa', 'wb', 'v'}

            # Collect ion numbers per terminus group
            n_positions = set()
            c_positions = set()

            for _, row in mono.iterrows():
                base_type = str(row.get('Base Type', '')).strip()
                try:
                    ion_num = int(row['Ion Number'])
                except (ValueError, TypeError):
                    continue

                # Check full Ion Type for z+1 / c-1 variants
                ion_type_full = str(row.get('Ion Type', '')).lower()
                if 'z+1' in ion_type_full:
                    effective_type = 'z+1'
                elif 'c-1' in ion_type_full:
                    effective_type = 'c-1'
                else:
                    effective_type = base_type

                if effective_type in n_term_types:
                    n_positions.add(ion_num)
                elif effective_type in c_term_types:
                    c_positions.add(ion_num)

            # Check complementary pairs
            paired_positions = []
            n = peptide_length
            for pos in sorted(n_positions):
                complement = n - pos
                if complement in c_positions:
                    paired_positions.append(pos)

            return {
                'pairs': len(paired_positions),
                'positions': paired_positions,
                'possible': n - 1
            }

        except Exception as e:
            print(f"[ERROR] Complementary pairs calculation error: {e}")
            return empty
            
    def set_current_spectrum(self, row_data, settings_data):
        """Update spectrum tracker with current spectrum"""
        if self.spectrum_tracker:
            self.spectrum_tracker.set_current_spectrum(row_data, settings_data)
    
    def set_mass_spec_data(self, matched_data, peptide, mod_positions, row_data, theoretical_data=None):
        """Set data for mass spec viewer"""
        if self.mass_spec_viewer:
            self.mass_spec_viewer.set_data(
                matched_data=matched_data,
                peptide=peptide,
                mod_positions=mod_positions,
                row_data=row_data,
                theoretical_data=theoretical_data
            )
    
    def set_peptide_sequence(self, peptide_sequence):
        """Set peptide sequence in mass spec viewer"""
        if self.mass_spec_viewer:
            self.mass_spec_viewer.set_peptide_sequence(peptide_sequence)
    
    def set_modifications(self, modifications):
        """Set modifications in mass spec viewer"""
        if self.mass_spec_viewer:
            self.mass_spec_viewer.set_modifications(modifications)
    
    def set_available_modifications(self, available_mods):
        """Set available modifications for mass spec viewer"""
        if self.mass_spec_viewer:
            self.mass_spec_viewer.set_available_modifications(available_mods)
    
    def update_y_axis_limits(self):
        """Update y-axis limits in mass spec viewer"""
        if self.mass_spec_viewer:
            # Get the current ppm tolerance from the main app
            ppm_tolerance = self.main_app.ppm_tolerance_input.value()
            self.mass_spec_viewer.update_y_axis_limits(ppm_tolerance)
    
    def update_text_annotation_threshold(self):
        """Update text annotation threshold in mass spec viewer"""
        if self.mass_spec_viewer:
            # Get the current threshold from the main app
            threshold = self.main_app.text_annotation_threshold.value()
            self.mass_spec_viewer.update_text_annotation_threshold(threshold)
    
    def show_loading_indicator(self):
        """Show loading indicator in mass spec viewer"""
        if self.mass_spec_viewer:
            if hasattr(self.mass_spec_viewer, 'loading_indicator'):
                self.mass_spec_viewer.loading_indicator.show()
            elif hasattr(self.mass_spec_viewer, 'show_loading_indicator'):
                self.mass_spec_viewer.show_loading_indicator()
    
    def hide_loading_indicator(self):
        """Hide loading indicator in mass spec viewer"""
        if self.mass_spec_viewer:
            if hasattr(self.mass_spec_viewer, 'loading_indicator'):
                self.mass_spec_viewer.loading_indicator.hide()
            elif hasattr(self.mass_spec_viewer, 'hide_loading_indicator'):
                self.mass_spec_viewer.hide_loading_indicator()
            elif hasattr(self.mass_spec_viewer, 'hide_loading'):
                self.mass_spec_viewer.hide_loading()
    
    def update_theme(self, theme_name):
        """Update theme for annotation tab components"""
        # Update mass spectrum viewer theme
        if self.mass_spec_viewer:
            self._update_mass_spectrum_viewer_theme(theme_name)
        
        # Update PSM summary widget theme
        if self.psm_summary_widget:
            self._update_psm_summary_theme()
        
        # Update spectrum tracker theme
        if self.spectrum_tracker:
            self._update_spectrum_tracker_theme()
        
        # Update peptide info widget theme
        if self.peptide_info_widget:
            self.peptide_info_widget.update_theme()
    
    def _update_mass_spectrum_viewer_theme(self, theme_name):
        """Update mass spectrum viewer for dark/light theme"""
        if not self.mass_spec_viewer:
            return
        
        # Use theme-aware colors
        plot_bg_color = EditorConstants.PLOT_BACKGROUND()
        unmatched_peak_color = EditorConstants.UNMATCHED_PEAK_COLOR()
        
        # Update plot backgrounds
        try:
            # Update spectrum plot background
            if hasattr(self.mass_spec_viewer, 'spectrumplot'):
                self.mass_spec_viewer.spectrumplot.getViewBox().setBackgroundColor(plot_bg_color)
            
            # Update error plot background  
            if hasattr(self.mass_spec_viewer, 'errorbarplot'):
                self.mass_spec_viewer.errorbarplot.getViewBox().setBackgroundColor(plot_bg_color)
            
            # Update graphics layout widget background
            if hasattr(self.mass_spec_viewer, 'glw'):
                self.mass_spec_viewer.glw.setBackground(plot_bg_color)
            
            # Store unmatched peak color for future use
            self.mass_spec_viewer.unmatched_peak_color = unmatched_peak_color
            
            # Reconfigure axes with new theme colors
            if hasattr(self.mass_spec_viewer, 'spectrumplot'):
                self.mass_spec_viewer._configure_plot_axis(
                    self.mass_spec_viewer.spectrumplot,
                    'Relative Intensity (%)', 'm/z',
                    (0, 100), (True, True)
                )
            if hasattr(self.mass_spec_viewer, 'errorbarplot'):
                self.mass_spec_viewer._configure_plot_axis(
                    self.mass_spec_viewer.errorbarplot,
                    'Error (ppm)', 'm/z',
                    (-11, 11), (True, False)
                )
            
            # Re-plot if there's data to apply new colors
            if hasattr(self.mass_spec_viewer, 'df') and not self.mass_spec_viewer.df.empty:
                self.mass_spec_viewer.plot_spectrum()
                self.mass_spec_viewer.plot_error_ppm()
            
            # Redraw peptide sequence with new theme colors
            if hasattr(self.mass_spec_viewer, 'peptide_sequence') and self.mass_spec_viewer.peptide_sequence:
                self.mass_spec_viewer._draw_peptide_sequence()
                # Restore modification display if any
                if hasattr(self.mass_spec_viewer, 'current_modifications') and self.mass_spec_viewer.current_modifications:
                    self.mass_spec_viewer.update_modification_display()
                
        except Exception as e:
            print(f"[DEBUG] Error updating mass spectrum viewer theme: {e}")
    
    def _update_psm_summary_theme(self):
        """Update PSM summary widget theme"""

        # Update filter widgets
        filter_widget_style = f"""
            QWidget {{
                background-color: {EditorConstants.GRAY_50()};
                {EditorConstants.get_border_string(EditorConstants.GRAY_200(), radius=EditorConstants.BORDER_RADIUS_LARGE())}
            }}
            QLabel {{
                color: {EditorConstants.HEADER_TEXT_COLOR()};
                {EditorConstants.get_font_string("bold")}
                border: none;
                background: transparent;
            }}
            {EditorConstants.get_scrollbar_style()}
        """
        
        if hasattr(self.psm_summary_widget, 'summary_filter_widget'):
            self.psm_summary_widget.summary_filter_widget.setStyleSheet(filter_widget_style)
        if hasattr(self.psm_summary_widget, 'details_filter_widget'):
            self.psm_summary_widget.details_filter_widget.setStyleSheet(filter_widget_style)
        
        # Update all filter input boxes (QLineEdit widgets)
        for line_edit in [
            getattr(self.psm_summary_widget, 'peptide_filter_input', None),
            getattr(self.psm_summary_widget, 'protein_filter_input', None),
            getattr(self.psm_summary_widget, 'mods_filter_input', None),
            getattr(self.psm_summary_widget, 'details_charge_filter', None),
            getattr(self.psm_summary_widget, 'details_mods_filter', None),
            getattr(self.psm_summary_widget, 'details_score_filter', None),
        ]:
            if line_edit:
                line_edit.setStyleSheet(EditorConstants.get_lineedit_style())
        
        # Update tables
        if hasattr(self.psm_summary_widget, 'summary_table'):
            StyleSheet.apply_table_styling(self.psm_summary_widget.summary_table)
        if hasattr(self.psm_summary_widget, 'details_table'):
            StyleSheet.apply_table_styling(self.psm_summary_widget.details_table)
    
    def _update_spectrum_tracker_theme(self):
        """Update spectrum tracker theme"""
        if hasattr(self.spectrum_tracker, 'export_table'):
            StyleSheet.apply_table_styling(self.spectrum_tracker.export_table)