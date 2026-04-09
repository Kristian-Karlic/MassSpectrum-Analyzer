import logging
import pandas as pd
from typing import List, Tuple

logger = logging.getLogger(__name__)

class InputValidator:
    """Utility class for input validation"""

    @staticmethod
    def validate_fragmentation_inputs(peptide: str, max_charge: int,
                                    mz_values: List[Tuple[float, float]]) -> Tuple[bool, str]:
        """Validate inputs for fragmentation"""
        if not peptide:
            return False, "Please enter a peptide sequence."

        if max_charge < 1:
            return False, "Max charge must be at least 1."

        if not mz_values:
            return False, "Please provide at least one valid m/z and intensity pair."

        return True, ""

    @staticmethod
    def validate_scan_inputs(selected_file: str, scan_number: str) -> Tuple[bool, str]:
        """Validate inputs for scan extraction"""
        if not selected_file:
            return False, "Please select a raw file."

        if not scan_number:
            return False, "Please enter a scan number."

        return True, ""

    @staticmethod
    def validate_dataframe_for_rescoring(df: pd.DataFrame, required_columns: List[str]) -> Tuple[bool, str]:
        """Validate DataFrame has required columns for rescoring"""
        if df.empty:
            return False, "No data detected. Please load data before attempting to rescore."

        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return False, f"Missing required columns: {', '.join(missing_columns)}."

        return True, ""
