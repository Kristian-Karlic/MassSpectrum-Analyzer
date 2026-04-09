import logging
import pandas as pd
from typing import List, Tuple

logger = logging.getLogger(__name__)

class DataProcessingUtils:
    """Utility class for data processing and filtering operations"""

    @staticmethod
    def filter_dataframe(merged_df, topN=999999, unique_pep=False, unique_mod=False, groupby_column=None):
        """
        Filter dataframe based on user options with support for hierarchical grouping.

        Parameters:
        -----------
        merged_df : pd.DataFrame
            Input dataframe to filter
        topN : int
            Number of top scoring peptides to keep (default: 999999 = no limit)
        unique_pep : bool
            Whether to filter by unique peptides
        unique_mod : bool
            Whether to filter by unique modified peptides
        groupby_column : str, list, or None
            Column name(s) to group by:
            - str: Single column ('Group' or 'Replicate')
            - list: Multiple columns for hierarchical grouping (['Group', 'Replicate'])
            - None: No grouping

        Returns:
        --------
        pd.DataFrame
            Filtered dataframe
        """

        # Ensure we have Hyperscore column for sorting
        if 'Hyperscore' not in merged_df.columns:
            logger.warning("No Hyperscore column found - returning unfiltered data")
            return merged_df

        logger.debug(f"[Filter] Starting with {len(merged_df)} PSMs")
        logger.debug(f"[Filter] Settings: topN={topN}, unique_pep={unique_pep}, unique_mod={unique_mod}, groupby_column={groupby_column}")

        # If no filtering requested, return original
        if not unique_pep and not unique_mod:
            logger.debug("[Filter] No filtering requested - returning original data")
            return merged_df

        def filter_group(group_df):
            """Filter a single group of data"""
            if unique_mod and 'Modified Peptide' in group_df.columns:
                # Group by modified peptide and take top N for each
                result = (group_df.groupby('Modified Peptide', group_keys=False)
                         .apply(lambda x: x.nlargest(min(topN, len(x)), 'Hyperscore', keep='first'))
                         .reset_index(drop=True))
                return result

            elif unique_pep and 'Peptide' in group_df.columns:
                # Group by peptide sequence and take top N for each
                result = (group_df.groupby('Peptide', group_keys=False)
                         .apply(lambda x: x.nlargest(min(topN, len(x)), 'Hyperscore', keep='first'))
                         .reset_index(drop=True))
                return result
            else:
                # No valid filtering - return as-is
                return group_df

        try:
            if groupby_column:
                # Handle both single column and list of columns
                if isinstance(groupby_column, list):
                    # Hierarchical grouping (e.g., ['Group', 'Replicate'])
                    # Verify all columns exist
                    missing_cols = [col for col in groupby_column if col not in merged_df.columns]
                    if missing_cols:
                        logger.warning(f"Missing columns for grouping: {missing_cols} - applying filters without grouping")
                        result_df = filter_group(merged_df)
                    else:
                        logger.debug(f"[Filter] Applying filters grouped by: {' -> '.join(groupby_column)}")
                        filtered_dfs = []
                        for group_values, group in merged_df.groupby(groupby_column):
                            group_desc = ' -> '.join([f"{col}={val}" for col, val in zip(groupby_column, group_values)])
                            logger.debug(f"[Filter] Processing {group_desc} ({len(group)} PSMs)")
                            filtered_group = filter_group(group)
                            logger.info(f"  → After filtering: {len(filtered_group)} PSMs")
                            filtered_dfs.append(filtered_group)
                        result_df = pd.concat(filtered_dfs, ignore_index=True)

                elif groupby_column in merged_df.columns:
                    # Single column grouping
                    logger.debug(f"[Filter] Applying filters grouped by: {groupby_column}")
                    filtered_dfs = []
                    for group_value, group in merged_df.groupby(groupby_column):
                        logger.debug(f"[Filter] Processing {groupby_column}='{group_value}' ({len(group)} PSMs)")
                        filtered_group = filter_group(group)
                        logger.info(f"  → After filtering: {len(filtered_group)} PSMs")
                        filtered_dfs.append(filtered_group)
                    result_df = pd.concat(filtered_dfs, ignore_index=True)
                else:
                    logger.warning(f"Column '{groupby_column}' not found - applying filters without grouping")
                    result_df = filter_group(merged_df)
            else:
                # Process entire dataframe as one group
                logger.debug("[Filter] Applying filters to entire dataset")
                result_df = filter_group(merged_df)
                logger.info(f"  → After filtering: {len(result_df)} PSMs")

            logger.debug(f"[Filter] Final result: Filtered from {len(merged_df)} to {len(result_df)} rows")
            if len(merged_df) > 0:
                logger.debug(f"[Filter] Reduction: {((len(merged_df) - len(result_df)) / len(merged_df) * 100):.1f}% removed")

            return result_df

        except Exception as e:
            logger.error(f"Error filtering dataframe: {str(e)}", exc_info=True)
            logger.warning("Returning unfiltered dataframe due to error")
            return merged_df


class IonTypeGenerator:
    """Utility class for generating ion types"""

    @staticmethod
    def generate_dynamic_ion_types(normal_checkboxes: dict, neutral_checkboxes: dict, max_losses: int) -> List[str]:
        """Generate ion types list based on selections and max neutral losses"""
        # Get base ion types
        base_ions = [ion for ion, cb in normal_checkboxes.items() if cb.isChecked()]

        # Get single neutral loss types
        single_loss_ions = [ion for ion, cb in neutral_checkboxes.items() if cb.isChecked()]

        all_ion_types = base_ions + single_loss_ions

        # Generate multiple loss variants if max_losses > 1
        if max_losses > 1:
            loss_capable_ions = ["a", "b", "y", "x", "z", "d", "w", "v"]
            loss_types = ["H2O", "NH3", "H3PO4", "SOCH4"]

            for single_loss in single_loss_ions:
                if "-" in single_loss:
                    base_ion, loss_type = single_loss.split("-", 1)

                    if base_ion in loss_capable_ions and loss_type in loss_types:
                        for count in range(2, max_losses + 1):
                            multiple_loss_ion = f"{base_ion}-{count}{loss_type}"
                            if multiple_loss_ion not in all_ion_types:
                                all_ion_types.append(multiple_loss_ion)

        return all_ion_types


class IonCollectionUtils:
    """Utility class for collecting ion series selections"""

    @staticmethod
    def collect_selected_ions(*checkbox_dicts) -> List[str]:
        """Collect selected ions from multiple checkbox dictionaries"""
        selected_ions = []
        for checkbox_dict in checkbox_dicts:
            for ion, cb in checkbox_dict.items():
                if cb.isChecked():
                    selected_ions.append(ion)
        return selected_ions

    @staticmethod
    def collect_selected_internal_ions(internal_ion_checkboxes: dict) -> List[str]:
        """Collect selected internal ions"""
        return [ion for ion, cb in internal_ion_checkboxes.items() if cb.isChecked()]
