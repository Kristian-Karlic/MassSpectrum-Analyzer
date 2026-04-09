import re
import pandas as pd
from .base_normalizer import PSMNormalizer


class MaxQuantNormalizer(PSMNormalizer):
    """Normalizer for MaxQuant msms.txt output."""

    def __init__(self, mod_database=None):
        self.mod_database = mod_database

    def get_engine_name(self) -> str:
        return "MaxQuant"

    # ------------------------------------------------------------------
    #  Main normalization
    # ------------------------------------------------------------------
    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        # Start with ALL original columns
        result = df.copy()

        # Map/rename columns to internal names
        result["Peptide"] = df["Sequence"]
        result["Modified Peptide"] = df["Modified sequence"].apply(
            self._clean_modified_sequence
        )
        result["Charge"] = pd.to_numeric(df["Charge"], errors="coerce").fillna(0).astype(int)
        result["Observed M/Z"] = pd.to_numeric(df["m/z"], errors="coerce").fillna(0.0)
        result["Hyperscore"] = pd.to_numeric(df["Score"], errors="coerce").fillna(0.0)
        result["Protein"] = df["Proteins"].fillna("")
        result["Peptide Length"] = pd.to_numeric(df["Length"], errors="coerce").fillna(0).astype(int)
        result["Spectrum file"] = df["Raw file"].fillna("")
        result["index"] = df["Scan number"].astype(str)

        # Columns unavailable in MaxQuant
        result["Prev AA"] = ""
        result["Next AA"] = ""
        result["Protein Start"] = ""
        result["Protein End"] = ""

        result["Assigned Modifications"] = df["Modifications"].fillna("")

        result["Parsed Modifications"] = df.apply(
            lambda row: self._parse_modifications(
                row.get("Modified sequence", ""),
                row.get("Sequence", ""),
            ),
            axis=1,
        )

        return result

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_modified_sequence(mod_seq) -> str:
        if pd.isna(mod_seq):
            return ""
        return str(mod_seq).strip("_")

    def _parse_modifications(self, modified_seq, base_seq):
        """Walk the MaxQuant modified sequence to extract (mass, position).

        MaxQuant format: ``_ATSNE(AETMA)IKE(AETMA)SPLHGTQ_``
        Parenthesised tokens are modification names that follow the
        amino acid they modify.
        """
        if pd.isna(modified_seq):
            return None

        clean = str(modified_seq).strip("_")
        if not clean:
            return None

        modifications = []
        aa_position = 0
        i = 0

        while i < len(clean):
            char = clean[i]

            if char == "(":
                # Extract modification name until closing paren
                close = clean.index(")", i)
                mod_name = clean[i + 1 : close]
                mass = self._lookup_mod_mass(mod_name)
                if mass is not None:
                    modifications.append((mass, aa_position))
                i = close + 1
            elif char.isupper():
                aa_position += 1
                i += 1
            else:
                i += 1

        return modifications if modifications else None

    def _lookup_mod_mass(self, mod_name: str):
        if self.mod_database:
            return self.mod_database.get_mass(mod_name)
        return None

    # ------------------------------------------------------------------
    #  Pre-scan for unknown modifications
    # ------------------------------------------------------------------
    def get_unknown_modifications(self, df: pd.DataFrame) -> set:
        unknown: set[str] = set()
        mod_seq_col = df.get("Modified sequence")
        if mod_seq_col is None:
            return unknown

        for mod_seq in mod_seq_col.dropna().unique():
            clean = str(mod_seq).strip("_")
            for match in re.finditer(r"\(([^)]+)\)", clean):
                mod_name = match.group(1)
                if self.mod_database and not self.mod_database.has_mod(mod_name):
                    unknown.add(mod_name)
        return unknown
