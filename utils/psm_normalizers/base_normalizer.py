from abc import ABC, abstractmethod
import pandas as pd


class PSMNormalizer(ABC):
    """Abstract base class for PSM data normalizers.

    Each concrete subclass transforms a particular search-engine's
    output DataFrame into the application's internal column schema.
    """

    INTERNAL_COLUMNS = [
        "Peptide", "Modified Peptide", "Charge", "Observed M/Z",
        "Assigned Modifications", "Parsed Modifications", "Hyperscore",
        "Protein", "Peptide Length", "Prev AA", "Next AA",
        "Protein Start", "Protein End", "Spectrum file", "index",
    ]

    @abstractmethod
    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform a raw search-engine DataFrame into internal format.

        The returned DataFrame must contain every column listed in
        ``INTERNAL_COLUMNS``.
        """

    @abstractmethod
    def get_engine_name(self) -> str:
        """Return the human-readable engine name (e.g. 'MSFragger')."""

    def validate_output(self, df: pd.DataFrame) -> bool:
        missing = set(self.INTERNAL_COLUMNS) - set(df.columns)
        if missing:
            print(f"[WARNING] {self.get_engine_name()} normalizer output "
                  f"missing columns: {missing}")
            return False
        return True

    def extract_spectrum_files(self, df: pd.DataFrame) -> set[str]:
        """Extract unique spectrum file names from raw search data.

        Override in subclasses for format-specific extraction.
        Used for automatic matching between search files and raw files.

        Args:
            df: Raw DataFrame from search engine output.

        Returns:
            Set of unique spectrum/raw file base names.
        """
        return set()
