import os
import re
import pandas as pd
from collections import defaultdict
from .base_normalizer import PSMNormalizer


class MSFraggerPreValidationNormalizer(PSMNormalizer):
    """Normalizer for MSFragger pre-validation TSV output.

    This format is produced by MSFragger before Philosopher/PeptideProphet validation.
    Key differences from psm.tsv:
    - Raw file name is embedded in the filename itself (not in a column)
    - Uses 'scannum' instead of 'Spectrum'
    - Uses 'modification_info' instead of 'Assigned Modifications'
    - Column names are lowercase with underscores
    """

    def __init__(self, source_file_path: str = None):
        """Initialize with source file path to extract raw file name from filename.

        Args:
            source_file_path: Full path to the TSV file. The filename (without extension)
                            is used as the spectrum/raw file name.
        """
        self.source_file_path = source_file_path

    def get_engine_name(self) -> str:
        return "MSFragger (pre-validation)"

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        # Start with ALL original columns
        result = df.copy()

        # Extract raw file name from the TSV filename itself
        spectrum_file = self._extract_spectrum_file_from_path()

        # Map columns from pre-validation format to internal format
        result["Peptide"] = df["peptide"]
        result["Modified Peptide"] = df["peptide"]  # Same as peptide for now
        result["Charge"] = df["charge"].astype(int)
        result["Observed M/Z"] = self._calculate_mz(df)
        result["Assigned Modifications"] = df["modification_info"].fillna("")

        # Parse modifications using peptide length
        result["Parsed Modifications"] = df.apply(
            lambda row: self._parse_modifications(
                row.get("modification_info"),
                len(row["peptide"]) if pd.notna(row["peptide"]) else 0,
            ),
            axis=1,
        )

        result["Hyperscore"] = df["hyperscore"] if "hyperscore" in df.columns else 0.0
        result["Protein"] = df["proteins"].fillna("")
        result["Peptide Length"] = df["peptide"].str.len()
        result["Prev AA"] = df["peptide_prev_aa"].fillna("")
        result["Next AA"] = df["peptide_next_aa"].fillna("")
        result["Protein Start"] = ""  # Not available in pre-validation format
        result["Protein End"] = ""    # Not available in pre-validation format
        result["Spectrum file"] = spectrum_file  # Same value for all rows
        result["index"] = df["scannum"].astype(str)

        return result

    def _extract_spectrum_file_from_path(self) -> str:
        """Extract raw file name from the TSV filename.

        For example: "20250128_KT-10169_D12_A1.tsv" -> "20250128_KT-10169_D12_A1"
        """
        if not self.source_file_path:
            return ""
        filename = os.path.basename(self.source_file_path)
        return os.path.splitext(filename)[0]

    def _calculate_mz(self, df: pd.DataFrame) -> pd.Series:
        """Calculate observed M/Z from precursor neutral mass and charge.

        Formula: M/Z = (precursor_neutral_mass + charge * proton_mass) / charge
        where proton_mass = 1.007276 Da
        """
        proton_mass = 1.007276
        return (df["precursor_neutral_mass"] + df["charge"] * proton_mass) / df["charge"]

    @staticmethod
    def _parse_modifications(mod_str, peptide_length):
        """Parse MSFragger modification string to (mass, position) tuples.

        Input format examples:
            "5K(28.0313)"
            "12D(84.1054), 25D(84.1054)"
            "N-term(42.0106)"
            None / NaN

        Returns:
            list[(float, int)] or None
        """
        if pd.isna(mod_str):
            return None

        mod_str = str(mod_str).replace(" ", "")
        if not mod_str:
            return None

        modifications = []
        for mod in mod_str.split(","):
            try:
                if mod.startswith("N-term"):
                    position = 1
                    mass = float(re.search(r"\((.*?)\)", mod).group(1))
                elif mod.startswith("C-term"):
                    position = int(peptide_length) if peptide_length else 1
                    mass = float(re.search(r"\((.*?)\)", mod).group(1))
                else:
                    position = int(re.search(r"(\d+)", mod).group(1))
                    mass = float(re.search(r"\((.*?)\)", mod).group(1))
                modifications.append((mass, position))
            except (AttributeError, ValueError):
                continue

        if not modifications:
            return None

        # Combine duplicate positions (e.g. two mods on same residue)
        pos_map: dict[int, float] = defaultdict(float)
        for mass_val, pos_val in modifications:
            pos_map[pos_val] += mass_val
        modifications = [(mass_sum, pos) for pos, mass_sum in sorted(pos_map.items())]

        return modifications

    def extract_spectrum_files(self, df: pd.DataFrame) -> set[str]:
        """Extract unique spectrum file names.

        For pre-validation format, the spectrum file is derived from the filename.
        """
        return {self._extract_spectrum_file_from_path()}
