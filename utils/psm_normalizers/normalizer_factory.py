from .base_normalizer import PSMNormalizer
from .msfragger_normalizer import MSFraggerNormalizer
from .msfragger_prevalidation_normalizer import MSFraggerPreValidationNormalizer
from .maxquant_normalizer import MaxQuantNormalizer
from .metamorpheus_normalizer import MetaMorpheusNormalizer
from .byonic_normalizer import ByonicNormalizer
from .psm_utils_normalizer import PSMUtilsNormalizer, READER_REGISTRY

# Format keys that route through PSMUtilsNormalizer
_PSM_UTILS_FORMATS = frozenset(READER_REGISTRY.keys())


class NormalizerFactory:
    """Factory for creating the appropriate PSM normalizer."""

    @staticmethod
    def create(file_type: str, mod_database=None, source_file_path: str = None) -> PSMNormalizer:
        """Return the normalizer for the given search-engine type.

        Args:
            file_type: One of ``"MSFragger"``, ``"MSFragger_PreValidation"``,
                       ``"MaxQuant"``, ``"MetaMorpheus"``, ``"Byonic"``,
                       or any psm_utils format key (``"PEAKS"``, ``"Sage"``,
                       ``"Percolator"``, ``"mzIdentML"``, ``"XTandem"``,
                       ``"IdXML"``).
            mod_database: :class:`ModificationMassDatabase` instance for
                          engines that need name→mass lookup.
            source_file_path: Path to the source file. Required for
                             MSFragger_PreValidation and all psm_utils formats.
        """
        if file_type == "MSFragger":
            return MSFraggerNormalizer()
        elif file_type == "MSFragger_PreValidation":
            return MSFraggerPreValidationNormalizer(source_file_path=source_file_path)
        elif file_type == "MaxQuant":
            return MaxQuantNormalizer(mod_database=mod_database)
        elif file_type == "MetaMorpheus":
            return MetaMorpheusNormalizer(mod_database=mod_database)
        elif file_type == "Byonic":
            return ByonicNormalizer(mod_database=mod_database)
        elif file_type in _PSM_UTILS_FORMATS:
            if not source_file_path:
                raise ValueError(
                    f"source_file_path is required for psm_utils format '{file_type}'"
                )
            return PSMUtilsNormalizer(format_key=file_type, source_file_path=source_file_path)
        else:
            raise ValueError(f"Unknown search-engine type: {file_type}")

    @staticmethod
    def is_psm_utils_format(file_type: str) -> bool:
        """Return True if the format is handled by PSMUtilsNormalizer."""
        return file_type in _PSM_UTILS_FORMATS
