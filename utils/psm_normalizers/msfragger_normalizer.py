import re
import pandas as pd
from collections import defaultdict
from .base_normalizer import PSMNormalizer


class MSFraggerNormalizer(PSMNormalizer):
    """Normalizer for MSFragger psm.tsv output."""

    def get_engine_name(self) -> str:
        return "MSFragger"

    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()

        # Split "Spectrum" column → Spectrum file + index
        if "Spectrum" in result.columns:
            parts = result["Spectrum"].str.split(".", expand=True)
            result["Spectrum file"] = parts[0]
            result["index"] = parts[1]

        # Parse modifications
        result["Parsed Modifications"] = result.apply(
            lambda row: self._parse_modifications(
                row.get("Assigned Modifications"),
                row.get("Peptide Length", 0),
            ),
            axis=1,
        )

        # Select only the internal columns (keep extras that already match)
        return self._select_internal_columns(result)

    # ------------------------------------------------------------------
    def _select_internal_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        # Keep ALL original columns, plus ensure internal columns exist
        out = df.copy()

        # Fill any missing internal columns
        for c in self.INTERNAL_COLUMNS:
            if c not in out.columns:
                out[c] = ""
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_modifications(mod_str, peptide_length):
        """Parse MSFragger modification string to (mass, position) tuples.

        Input format examples:
            "17S(988.3491), 2M(15.9949), 9M(15.9949)"
            "N-term(42.0106)"
            None / NaN

        Returns:
            list[(float, int)] or None
        """
        if pd.isna(mod_str):
            return None

        mod_str = mod_str.replace(" ", "")
        if not mod_str:
            return None

        modifications = []
        for mod in mod_str.split(","):
            try:
                if mod.startswith("N-term"):
                    position = 1
                    mass = float(re.search(r"\((.*?)\)", mod).group(1))
                elif mod.startswith("C-term"):
                    position = int(peptide_length)
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
        """Extract unique spectrum file names from the Spectrum column.

        The Spectrum column format is: 'filename.scannum.scannum.charge'
        Example: '20230928_KT-7289_TioX_AB_ATCC19606_A.04009.04009.3'
        """
        if "Spectrum" not in df.columns:
            return set()
        parts = df["Spectrum"].str.split(".", expand=True)
        return set(parts[0].dropna().unique())
