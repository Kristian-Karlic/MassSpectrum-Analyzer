import pandas as pd
import re

class HTMLFormatter:
    """Utility class for HTML formatting of mass spectrometry annotations"""
    
    # Unicode character maps for subscripts and superscripts
    SUBSCRIPT_MAP = {
        '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
        '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
        '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎'
    }
    
    SUPERSCRIPT_MAP = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
        'n': 'ⁿ'
    }
    
    @staticmethod
    def to_subscript(text):
        """Convert text to Unicode subscript characters"""
        return ''.join(HTMLFormatter.SUBSCRIPT_MAP.get(c, c) for c in str(text))
    
    @staticmethod
    def to_superscript(text):
        """Convert text to Unicode superscript characters"""
        return ''.join(HTMLFormatter.SUPERSCRIPT_MAP.get(c, c) for c in str(text))
    
    @staticmethod
    def clean_number(x):
        """
        Convert a numeric value (which might be a float like 1.0) into an integer string.
        If conversion fails, just return the original string.
        """
        try:
            val = float(x)
            if val.is_integer():
                return str(int(val))
            else:
                return str(val)
        except Exception:
            return str(x)
    @staticmethod
    def _format_annotation_with_formatter(row, fmt_sub, fmt_sup, fmt_loss):
        """
        Internal method to build annotation string with pluggable formatters.

        Args:
            row: Data row containing ion information
            fmt_sub: Function to format subscript (e.g., lambda x: f"<sub>{x}</sub>")
            fmt_sup: Function to format superscript (e.g., lambda x: f"<sup>{x}</sup>")
            fmt_loss: Function to format neutral loss (e.g., format_neutral_loss)
        """
        # Get the values (and strip any extra whitespace)
        ion_type = str(row["Ion Type"]).strip()
        base_type = str(row["Base Type"]).strip()
        ion_number = str(row["Ion Number"]).strip()
        charge = str(row["Charge"]).strip()
        neutral_loss = row.get("Neutral Loss", None)
        ion_series_type = row.get("Ion Series Type", "Standard-Ion-Series")

        if not pd.isna(neutral_loss) and str(neutral_loss).strip() == "Custom_Ion":
            annotation = ion_type
            return annotation

        # Handle MH custom ion series case
        if base_type == "MH" and not pd.isna(neutral_loss) and str(neutral_loss).strip() == "custom_ion_series":
            annotation = f"{ion_type}"
            if charge != "1":
                annotation += fmt_sup(f"+{charge}")
            return annotation

        if base_type == "MH":
            # Check if ion_type already contains neutral loss information (e.g., "MH*-NH3")
            mh_loss_match = re.match(r'^(.+)-(\d*)([A-Z0-9]+)$', ion_type)

            if mh_loss_match:
                # This is a custom MH ion with neutral loss already in the ion_type
                custom_mh_base = mh_loss_match.group(1)  # e.g., "MH*"
                loss_count = mh_loss_match.group(2)      # e.g., ""
                loss_type = mh_loss_match.group(3)       # e.g., "NH3"

                # Format the loss with count and subscripts
                if loss_count and loss_count != "1":
                    formatted_loss = f"{loss_count}{fmt_loss(loss_type)}"
                else:
                    formatted_loss = fmt_loss(loss_type)

                # Build annotation for custom MH with embedded loss
                if charge == "1":
                    annotation = f"[{custom_mh_base}+H-{formatted_loss}]"
                else:
                    annotation = f"[{custom_mh_base}+{charge}H-{formatted_loss}]" + fmt_sup(f"+{charge}")

            elif ion_type != "MH":
                # This is a custom MH ion without embedded loss (e.g., "MH*")
                if charge == "1":
                    annotation = f"[{ion_type}+H]"
                else:
                    annotation = f"[{ion_type}+{charge}H]" + fmt_sup(f"+{charge}")

                # Check for additional neutral loss only if not already embedded in ion_type
                # Skip for Mod-NL-Series where the tag is already in ion_type
                if ion_series_type != "Mod-NL-Series" and not (pd.isna(neutral_loss) or str(neutral_loss).strip() in ["", "None"]):
                    formatted_loss = fmt_loss(str(neutral_loss).strip())
                    if charge == "1":
                        annotation = f"[{ion_type}+H-{formatted_loss}]"
                    else:
                        annotation = f"[{ion_type}+{charge}H-{formatted_loss}]" + fmt_sup(f"+{charge}")
            else:
                # Standard MH formatting
                if charge == "1":
                    annotation = "[M+H]"
                else:
                    annotation = f"[M+{charge}H]" + fmt_sup(f"+{charge}")

                # Check for neutral loss only for standard MH
                if not (pd.isna(neutral_loss) or str(neutral_loss).strip() in ["", "None"]):
                    formatted_loss = fmt_loss(str(neutral_loss).strip())
                    if charge == "1":
                        annotation = f"[M+H-{formatted_loss}]"
                    else:
                        annotation = f"[M+{charge}H-{formatted_loss}]" + fmt_sup(f"+{charge}")

            return annotation

        # Handle non-MH cases
        neutral_loss = row.get("Neutral Loss", None)

        # CUSTOM ION SERIES HANDLING
        if ion_series_type == "Custom-Ion-Series":
            # For custom ions, the ion_type contains the custom name (e.g., "MyCustomIon-H2O")

            # Check if this is a custom ion with neutral loss
            custom_loss_match = re.match(r'^(.+)-(\d*)([A-Z0-9]+)$', ion_type)

            if custom_loss_match:
                # Extract: custom ion name, loss count, loss type
                custom_ion_name = custom_loss_match.group(1)
                loss_count = custom_loss_match.group(2)
                loss_type = custom_loss_match.group(3)

                # Format the loss with count and subscripts
                if loss_count and loss_count != "1":
                    formatted_loss = f"{loss_count}{fmt_loss(loss_type)}"
                else:
                    formatted_loss = fmt_loss(loss_type)

                # Build annotation for custom ion with loss
                annotation = f"[{custom_ion_name}-{formatted_loss}]" + fmt_sub(ion_number)

            else:
                # Custom ion without neutral loss
                annotation = ion_type + fmt_sub(ion_number)

            # Add charge state if not +1
            if charge != "1":
                annotation += fmt_sup(f"+{charge}")

            return annotation

        # MODIFICATION-SPECIFIC NEUTRAL LOSS HANDLING (*, **, ***, ~, ^)
        if ion_series_type == "Mod-NL-Series":
            # Check if ion_type has an embedded standard neutral loss (e.g. "y*-H2O", "b~-2NH3")
            mod_nl_loss_match = re.match(r'^(.+)-(\d*)([A-Z][A-Z0-9]*)$', ion_type)
            if mod_nl_loss_match:
                mod_base = mod_nl_loss_match.group(1)   # e.g. "y*", "b~", "y^"
                loss_count = mod_nl_loss_match.group(2)  # e.g. "" or "2"
                loss_type = mod_nl_loss_match.group(3)   # e.g. "H2O"
                formatted_mod_base = HTMLFormatter.format_ion_type_with_radicals(mod_base)
                if loss_count and loss_count != "1":
                    formatted_loss = f"{loss_count}{fmt_loss(loss_type)}"
                else:
                    formatted_loss = fmt_loss(loss_type)
                annotation = f"[{formatted_mod_base}-{formatted_loss}]" + fmt_sub(ion_number)
            else:
                formatted_ion_type = HTMLFormatter.format_ion_type_with_radicals(ion_type)
                annotation = formatted_ion_type + fmt_sub(ion_number)
            if charge != "1":
                annotation += fmt_sup(f"+{charge}")
            return annotation

        # STANDARD ION SERIES HANDLING
        # Check if ion_type contains multiple neutral losses (e.g., y-2H2O, b-3NH3)
        multiple_loss_match = re.match(r'^([abcxyzwvd]+)-(\d*)([A-Z0-9]+)$', ion_type)

        if multiple_loss_match:
            # Extract components: base ion, count, loss type
            base_ion = multiple_loss_match.group(1)
            loss_count = multiple_loss_match.group(2)
            loss_type = multiple_loss_match.group(3)

            # Format the loss with count and subscripts
            if loss_count and loss_count != "1":
                formatted_loss = f"{loss_count}{fmt_loss(loss_type)}"
            else:
                formatted_loss = fmt_loss(loss_type)

            # Format ion type with radicals if needed
            formatted_base_ion = HTMLFormatter.format_ion_type_with_radicals(base_ion)

            # Build annotation with proper loss formatting
            annotation = f"[{formatted_base_ion}-{formatted_loss}]" + fmt_sub(ion_number)

        elif pd.isna(neutral_loss) or str(neutral_loss).strip() in ["", "None"]:
            # No neutral loss - standard formatting
            formatted_ion_type = HTMLFormatter.format_ion_type_with_radicals(ion_type)
            annotation = formatted_ion_type + fmt_sub(ion_number)

        else:
            # Single neutral loss - legacy formatting
            formatted_loss = fmt_loss(str(neutral_loss).strip())
            formatted_base_type = HTMLFormatter.format_ion_type_with_radicals(base_type)
            annotation = f"[{formatted_base_type}-{formatted_loss}]" + fmt_sub(ion_number)

        # Handle custom_ion_series for non-MH cases (legacy)
        if not pd.isna(neutral_loss) and str(neutral_loss).strip() == "custom_ion_series":
            formatted_ion_type = HTMLFormatter.format_ion_type_with_radicals(ion_type)
            annotation = formatted_ion_type + fmt_sub(ion_number)

        # Add charge state if not +1
        if charge != "1":
            annotation += fmt_sup(f"+{charge}")

        return annotation

    @staticmethod
    def format_annotation(row):
        """
        Build the annotation string using HTML tags.
        - Base: Ion Type (e.g. "y")
        - For MH type: [M+H] for charge=1, [M+nH]<sup>+n</sup> for charge>1
        - For other types: ion_type<sub>number</sub> with optional charge
        - For z type: z• (radical symbol)
        - For multiple neutral losses: y-2H2O, b-3NH3, etc.
        - For custom ions: Use the custom ion name with neutral losses
        """
        return HTMLFormatter._format_annotation_with_formatter(
            row,
            fmt_sub=lambda x: f"<sub>{x}</sub>",
            fmt_sup=lambda x: f"<sup>{x}</sup>",
            fmt_loss=HTMLFormatter.format_neutral_loss
        )

    @staticmethod
    def format_annotation_unicode(row):
        """
        Build the annotation string using Unicode subscripts and superscripts.
        Same logic as format_annotation but with Unicode characters instead of HTML tags.
        """
        return HTMLFormatter._format_annotation_with_formatter(
            row,
            fmt_sub=HTMLFormatter.to_subscript,
            fmt_sup=HTMLFormatter.to_superscript,
            fmt_loss=HTMLFormatter.format_neutral_loss_unicode
        )

    @staticmethod
    def format_neutral_loss(loss):
        """
        Format neutral losses with proper subscripts.
        Examples: NH3 -> NH<sub>3</sub>, H2O -> H<sub>2</sub>O
        Now handles complex losses like H3PO4, SOCH4
        """
        common_losses = {
            'NH3': 'NH<sub>3</sub>',
            'H2O': 'H<sub>2</sub>O',
            'CH3SOH': 'CH<sub>3</sub>SOH',
            'H3PO4': 'H<sub>3</sub>PO<sub>4</sub>',
            'SOCH4': 'SOCH<sub>4</sub>'
        }
        
        # If it's a known loss, return the formatted version
        if loss in common_losses:
            return common_losses[loss]
        
        # For unknown losses, try to format numbers as subscripts
        # This handles cases like CO2 -> CO<sub>2</sub>
        formatted_loss = re.sub(r'(\d+)', r'<sub>\1</sub>', loss)
        return formatted_loss

    @staticmethod
    def _format_ion_type_with_radicals(ion_type, fmt_sub):
        """
        Internal method to format ion types with correct radical notation.

        Args:
            ion_type: The ion type string
            fmt_sub: Function to format subscript (e.g., lambda x: f"<sub>{x}</sub>")

        Examples:
        - z -> z• (z-type has radical)
        - z+1 -> z' (z+1 has no radical)
        - c-1 -> c (c-1 has no radical)
        - da -> formatted subscript, wb -> formatted subscript
        """
        # Handle z-type: base z should have radical
        if ion_type == 'z':
            return 'z•'
        # Handle z+1: should be just z (no radical)
        elif ion_type == 'z+1':
            return "z'"
        # Handle z+2, z+3, etc.: keep as is
        elif ion_type.startswith('z+'):
            return ion_type
        # Handle c-1: should be just c (no modification indicator)
        elif ion_type == 'c-1':
            return 'c'
        # Handle satellite ion variants: da->d<sub>a</sub> or dₐ, wb->w<sub>b</sub> or w_b
        elif ion_type in ('da', 'db', 'wa', 'wb'):
            return f'{ion_type[0]}{fmt_sub(ion_type[1])}'

        # Return unchanged for other ion types
        return ion_type

    @staticmethod
    def format_ion_type_with_radicals(ion_type):
        """
        Format ion types with correct radical notation using HTML tags.
        Examples:
        - z -> z• (z-type has radical)
        - z+1 -> z' (z+1 has no radical)
        - c-1 -> c (c-1 has no radical)
        - da -> d<sub>a</sub>, wb -> w<sub>b</sub>
        """
        return HTMLFormatter._format_ion_type_with_radicals(
            ion_type,
            fmt_sub=lambda x: f"<sub>{x}</sub>"
        )

    @staticmethod
    def format_ion_type_with_radicals_unicode(ion_type):
        """
        Format ion types with correct radical notation using Unicode characters.
        Examples:
        - z -> z• (z-type has radical)
        - z+1 -> z' (z+1 has no radical)
        - z+2 -> z+2 (keep as is)
        - c-1 -> c (c-1 has no modification indicator)
        - da -> dₐ, wb -> wᵦ (Unicode subscript a/b)
        """
        return HTMLFormatter._format_ion_type_with_radicals(
            ion_type,
            fmt_sub=HTMLFormatter.to_subscript
        )

    @staticmethod
    def format_neutral_loss_unicode(loss):
        """
        Format neutral losses with proper Unicode subscripts.
        Examples: NH3 -> NH₃, H2O -> H₂O
        """
        common_losses = {
            'NH3': f'NH{HTMLFormatter.to_subscript("3")}',
            'H2O': f'H{HTMLFormatter.to_subscript("2")}O',
            'CH3SOH': f'CH{HTMLFormatter.to_subscript("3")}SOH',
            'H3PO4': f'H{HTMLFormatter.to_subscript("3")}PO{HTMLFormatter.to_subscript("4")}',
            'SOCH4': f'SOCH{HTMLFormatter.to_subscript("4")}'
        }

        # If it's a known loss, return the formatted version
        if loss in common_losses:
            return common_losses[loss]

        # For unknown losses, convert numbers to subscripts
        formatted_loss = ''
        for char in loss:
            if char.isdigit():
                formatted_loss += HTMLFormatter.to_subscript(char)
            else:
                formatted_loss += char
        return formatted_loss

