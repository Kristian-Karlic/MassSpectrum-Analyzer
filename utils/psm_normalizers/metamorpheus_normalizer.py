import re
import pandas as pd
from .base_normalizer import PSMNormalizer


class MetaMorpheusNormalizer(PSMNormalizer):
    """Normalizer for MetaMorpheus AllPSMs.psmtsv / AllPeptides.psmtsv output."""

    def __init__(self, mod_database=None):
        self.mod_database = mod_database

    def get_engine_name(self) -> str:
        return "MetaMorpheus"

    # ------------------------------------------------------------------
    #  Main normalization
    # ------------------------------------------------------------------
    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        # Start with ALL original columns
        result = df.copy()

        result["Peptide"] = df["Base Sequence"]
        result["Modified Peptide"] = df["Full Sequence"].fillna("")
        result["Charge"] = pd.to_numeric(
            df["Precursor Charge"], errors="coerce"
        ).fillna(0).astype(int)
        result["Observed M/Z"] = pd.to_numeric(
            df["Precursor MZ"], errors="coerce"
        ).fillna(0.0)
        result["Hyperscore"] = pd.to_numeric(
            df["Score"], errors="coerce"
        ).fillna(0.0)
        result["Protein"] = df["Accession"].fillna("")
        result["Peptide Length"] = df["Base Sequence"].str.len()
        result["Spectrum file"] = df["File Name"].fillna("")
        result["index"] = (
            pd.to_numeric(df["Scan Number"], errors="coerce")
            .fillna(0)
            .astype(int)
            .astype(str)
        )

        result["Prev AA"] = df.get("Previous Residue", pd.Series("", index=df.index)).fillna("")
        result["Next AA"] = df.get("Next Residue", pd.Series("", index=df.index)).fillna("")

        # Parse "[3 to 38]" → Protein Start / Protein End
        residue_range = df.get(
            "Start and End Residues In Full Sequence",
            pd.Series("", index=df.index),
        ).apply(self._parse_residue_range)
        result["Protein Start"] = residue_range.apply(lambda x: x[0])
        result["Protein End"] = residue_range.apply(lambda x: x[1])

        result["Assigned Modifications"] = df["Mods"].fillna("")

        result["Parsed Modifications"] = df.apply(
            lambda row: self._parse_modifications(
                row.get("Full Sequence", ""),
                row.get("Base Sequence", ""),
            ),
            axis=1,
        )

        return result

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_residue_range(range_str):
        """Parse MetaMorpheus residue range string.

        ``[3 to 38]`` → ``(3, 38)``
        """
        if pd.isna(range_str) or not range_str:
            return ("", "")
        match = re.search(r"\[(\d+)\s+to\s+(\d+)\]", str(range_str))
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return ("", "")

    @staticmethod
    def _extract_mod_name(descriptor: str) -> str:
        """Extract canonical modification name from a MetaMorpheus descriptor.

        ``"Common Fixed:Carbamidomethyl on C"`` → ``"Carbamidomethyl"``
        ``"Common Biological:Oxidation on M"``  → ``"Oxidation"``
        ``"Glycan:BAL062_glycan on S"``          → ``"BAL062_glycan"``
        """
        # Strip category prefix  (everything before the first ':')
        if ":" in descriptor:
            descriptor = descriptor.split(":", 1)[1].strip()
        # Strip " on X" suffix
        match = re.match(r"(.+?)\s+on\s+[A-Z]$", descriptor)
        if match:
            return match.group(1).strip()
        return descriptor.strip()

    def _parse_modifications(self, full_seq, base_seq):
        """Walk the Full Sequence and extract (mass, position) tuples.

        Modification annotations look like:
            ``C[Common Fixed:Carbamidomethyl on C]``
            ``S[Glycan:BAL062_glycan on S]``
        """
        if pd.isna(full_seq) or not full_seq:
            return None

        full_seq = str(full_seq)
        modifications = []
        aa_position = 0
        i = 0

        while i < len(full_seq):
            char = full_seq[i]

            if char == "[":
                close = full_seq.index("]", i)
                descriptor = full_seq[i + 1 : close]
                mod_name = self._extract_mod_name(descriptor)
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
        full_seq_col = df.get("Full Sequence")
        if full_seq_col is None:
            return unknown

        for full_seq in full_seq_col.dropna().unique():
            for match in re.finditer(r"\[([^\]]+)\]", str(full_seq)):
                descriptor = match.group(1)
                mod_name = self._extract_mod_name(descriptor)
                if self.mod_database and not self.mod_database.has_mod(mod_name):
                    unknown.add(mod_name)
        return unknown
