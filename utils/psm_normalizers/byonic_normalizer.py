import re
import csv
import io
import pandas as pd
from .base_normalizer import PSMNormalizer


class ByonicNormalizer(PSMNormalizer):
    """Normalizer for Byonic CSV output.

    Byonic exports sequence in format: PreviousAA.ModifiedPeptide.NextAA
    Modifications are provided in columns "Mods (variable)" and "Mods (fixed)"
    with format: AA#(ModName / Mass); AA#(ModName / Mass)...
    """

    # Pre-compiled regex patterns for performance
    _SCAN_NUMBER_PATTERN = re.compile(r'scan\s*=\s*(\d+)')
    _SEQUENCE_FORMAT_PATTERN = re.compile(r'^([A-Z-])\.(.+)\.([A-Z-])$')
    _BRACKET_PATTERN = re.compile(r'\[[^\]]+\]')
    _FILE_PATTERN = re.compile(r'File:"([^"]+)"')
    _FALLBACK_FILENAME_PATTERN = re.compile(r'([^\.]+)')
    _MOD_PATTERN = re.compile(r'([A-Z])(\d+)\(([^/]+)\s*/\s*([\d.]+)\)')
    _SIMPLE_SCAN_NUMBER_PATTERN = re.compile(r'^\d+$')

    def __init__(self, mod_database=None):
        self.mod_database = mod_database

    def get_engine_name(self) -> str:
        return "Byonic"

    # ------------------------------------------------------------------
    #  Column name normalization
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names by removing/replacing newlines and collapsing whitespace."""
        df.columns = [re.sub(r'\s+', ' ', (col or '').replace('\n', ' ').replace('\r', ' ')).strip() for col in df.columns]
        return df

    @staticmethod
    def read_byonic_csv(file_path: str) -> pd.DataFrame:
        """Read a Byonic CSV file using Python's csv module which correctly handles
        quoted fields containing embedded newlines (\\r\\n).

        Returns:
            pd.DataFrame with normalized column names
        """
        with open(file_path, 'r', encoding='utf-8', newline='') as f:
            # Use csv.DictReader which properly handles quoted fields with newlines
            reader = csv.DictReader(f)
            rows = list(reader)

        # Convert to DataFrame
        df = pd.DataFrame(rows)

        # Normalize column names
        return ByonicNormalizer._normalize_column_names(df)

    # ------------------------------------------------------------------
    #  Main normalization
    # ------------------------------------------------------------------
    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        # Normalize column names in case they have embedded newlines
        df = self._normalize_column_names(df)
        # Start with ALL original columns
        result = df.copy()

        # Parse sequence format: K.TVVTEAGNLLKDN[+1054.37004]ATQEEILHYLEK.T
        parsed_sequences = df["Sequence (unformatted)"].apply(self._parse_sequence_format)

        result["Peptide"] = parsed_sequences.apply(lambda x: x['unmodified'])
        result["Modified Peptide"] = parsed_sequences.apply(lambda x: x['modified'])
        result["Prev AA"] = parsed_sequences.apply(lambda x: x['prev_aa'])
        result["Next AA"] = parsed_sequences.apply(lambda x: x['next_aa'])

        result["Charge"] = pd.to_numeric(df["z"], errors="coerce").fillna(0).astype(int)
        result["Observed M/Z"] = pd.to_numeric(df["Obs. m/z"], errors="coerce").fillna(0.0)
        result["Hyperscore"] = pd.to_numeric(df["Score"], errors="coerce").fillna(0.0)
        result["Protein"] = df["Protein Name"].fillna("")
        result["Peptide Length"] = pd.to_numeric(df["Pos."], errors="coerce").fillna(0).astype(int)
        result["Spectrum file"] = df["Comment"].apply(self._extract_raw_filename)
        result["index"] = df["Scan #"].apply(self._extract_scan_number)

        # Protein Start/End not directly available
        result["Protein Start"] = ""
        result["Protein End"] = ""

        # Combine variable and fixed modifications
        result["Assigned Modifications"] = df.apply(
            lambda row: self._combine_modifications(
                row.get("Mods (variable)", ""),
                row.get("Mods (fixed)", "")
            ),
            axis=1
        )

        # Parse modifications - pass the combined string directly
        result["Parsed Modifications"] = result["Assigned Modifications"].apply(
            self._parse_modifications
        )

        return result

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_sequence_format(seq_str):
        """Parse Byonic sequence format: K.TVVTEAGNLLKDN[+1054.37004]ATQEEILHYLEK.T

        Returns dict with:
            - prev_aa: amino acid before the period
            - modified: the modified peptide sequence with mass annotations
            - unmodified: peptide without in-bracket modifications
            - next_aa: amino acid after the final period
        """
        if pd.isna(seq_str):
            return {
                'prev_aa': '',
                'modified': '',
                'unmodified': '',
                'next_aa': ''
            }

        seq = str(seq_str).strip()

        # Match pattern: SingleLetter.Sequence.SingleLetter (or dash for start/end of protein)
        # Use regex to handle brackets containing periods and dashes for protein boundaries
        match = ByonicNormalizer._SEQUENCE_FORMAT_PATTERN.match(seq)
        if match:
            prev_aa = match.group(1)
            peptide_with_mods = match.group(2)
            next_aa = match.group(3)

            # Convert dash to empty string (dash indicates start/end of protein)
            prev_aa = '' if prev_aa == '-' else prev_aa
            next_aa = '' if next_aa == '-' else next_aa

            # Remove in-bracket modifications for unmodified sequence
            unmodified = ByonicNormalizer._BRACKET_PATTERN.sub('', peptide_with_mods)

            return {
                'prev_aa': prev_aa,
                'modified': peptide_with_mods,
                'unmodified': unmodified,
                'next_aa': next_aa
            }

        # Fallback for sequences without flanking AAs
        return {
            'prev_aa': '',
            'modified': seq,
            'unmodified': ByonicNormalizer._BRACKET_PATTERN.sub('', seq),
            'next_aa': ''
        }

    @staticmethod
    def _combine_modifications(var_mods, fixed_mods):
        """Combine variable and fixed modifications into single string."""
        mods = []
        if pd.notna(var_mods):
            mod_str = str(var_mods).strip()
            if mod_str:
                mods.append(mod_str)
        if pd.notna(fixed_mods):
            mod_str = str(fixed_mods).strip()
            if mod_str:
                mods.append(mod_str)
        return "; ".join(mods) if mods else ""

    @staticmethod
    def _extract_raw_filename(comment_str):
        """Extract raw file name from comment field.

        Format example: "2017_01_19_MB1-4_Glyco_rep1_Frac1.14651.14651.4 File:"2017_01_19_MB1-4_Glyco_rep1_Frac1.raw", NativeID:"controllerType=0 controllerNumber=1 scan=14651""

        Returns just the filename without path or extension details.
        """
        if pd.isna(comment_str):
            return ""

        comment = str(comment_str)

        # Extract from File: pattern
        match = ByonicNormalizer._FILE_PATTERN.search(comment)
        if match:
            file_path = match.group(1)
            # Get the basename
            return file_path.split('/')[-1].split('\\')[-1]

        # Fallback: try to extract from the beginning before scan details
        match = ByonicNormalizer._FALLBACK_FILENAME_PATTERN.match(comment)
        if match:
            return match.group(1)

        return ""

    @staticmethod
    def _extract_scan_number(scan_value):
        """Extract scan number from Scan # column.

        Handles two formats:
        1. Simple format: '15000'
        2. Key-value format: 'controllerType=0 controllerNumber=1 scan=15000'

        Args:
            scan_value: The value from the Scan # column

        Returns:
            Scan number as string, or empty string if invalid/unable to extract
        """
        if pd.isna(scan_value):
            return ""

        scan_str = str(scan_value).strip()

        # Check if it contains the key-value format
        if '=' in scan_str:
            # Extract scan number from key-value format
            match = ByonicNormalizer._SCAN_NUMBER_PATTERN.search(scan_str)
            if match:
                return match.group(1)
            # Malformed key-value format - return empty instead of invalid string
            return ""

        # Simple format - validate it's numeric
        if ByonicNormalizer._SIMPLE_SCAN_NUMBER_PATTERN.match(scan_str):
            return scan_str

        # Invalid format - return empty string
        return ""

    def _parse_modifications(self, mod_string):
        """Parse modifications from format: N13(NGlycan / 1054.37); M1(Oxidation / 15.9949)

        Returns list of (mass, position) tuples where position is 1-indexed.
        """
        if pd.isna(mod_string):
            return None

        mod_str = str(mod_string).strip()
        if not mod_str:
            return None

        modifications = []

        for match in self._MOD_PATTERN.finditer(mod_str):
            aa = match.group(1)
            position = int(match.group(2))
            mod_name = match.group(3).strip()
            mass_str = match.group(4).strip()

            try:
                mass = float(mass_str)
                modifications.append((mass, position))
            except ValueError:
                pass

        return modifications if modifications else None

    # ------------------------------------------------------------------
    #  Pre-scan for unknown modifications
    # ------------------------------------------------------------------
    def get_unknown_modifications(self, df: pd.DataFrame) -> set:
        """Scan for modification names that aren't in the database."""
        unknown: set[str] = set()

        for col in ["Mods (variable)", "Mods (fixed)"]:
            mod_col = df.get(col)
            if mod_col is None:
                continue

            for mod_str in mod_col.dropna().unique():
                mod_str = str(mod_str)
                for match in self._MOD_PATTERN.finditer(mod_str):
                    mod_name = match.group(3).strip()
                    if self.mod_database and not self.mod_database.has_mod(mod_name):
                        unknown.add(mod_name)

        return unknown

    # ------------------------------------------------------------------
    #  Spectrum file extraction for auto-matching
    # ------------------------------------------------------------------
    def extract_spectrum_files(self, df: pd.DataFrame) -> set[str]:
        """Extract unique spectrum file names from Byonic data.

        Extracts the raw file names from the Comment field or the normalized
        Spectrum file column, returning base names for matching with raw files.

        Args:
            df: DataFrame from Byonic CSV (before or after normalization).

        Returns:
            Set of unique raw file base names (without extensions).
        """
        spectrum_files = set()

        # Try the normalized column first
        if "Spectrum file" in df.columns:
            for filename in df["Spectrum file"].dropna().unique():
                if filename and str(filename).strip():
                    # Add both with and without .raw extension for matching
                    base = str(filename).strip()
                    spec_lower = base.lower()
                    spectrum_files.add(spec_lower)
                    # Also add without extension
                    if spec_lower.endswith('.raw'):
                        spectrum_files.add(spec_lower[:-4])

        # Also try extracting from Comment if Spectrum file wasn't available
        elif "Comment" in df.columns:
            for comment in df["Comment"].dropna().unique():
                filename = self._extract_raw_filename(comment)
                if filename and str(filename).strip():
                    spec_lower = str(filename).lower().strip()
                    spectrum_files.add(spec_lower)
                    if spec_lower.endswith('.raw'):
                        spectrum_files.add(spec_lower[:-4])

        return spectrum_files
