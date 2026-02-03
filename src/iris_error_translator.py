"""
IRS IRIS XML Error Translator

Converts cryptic XML schema validation errors into user-friendly messages
with specific field references and actionable fixes.
"""

import re
from typing import Dict, Optional, Tuple


class IRISErrorTranslator:
    """Translates IRS XML validation errors to user-friendly messages."""

    # Map XML element names to user-friendly field names
    FIELD_NAMES = {
        # Person names
        "PersonFirstNm": "First Name",
        "PersonMiddleNm": "Middle Name",
        "PersonLastNm": "Last Name",
        "SuffixNm": "Name Suffix",
        "PersonNameControlTxt": "Name Control",

        # Business names
        "BusinessNameLine1Txt": "Business Name (Line 1)",
        "BusinessNameLine2Txt": "Business Name (Line 2)",
        "BusinessNameControlTxt": "Business Name Control",

        # Address fields
        "AddressLine1Txt": "Street Address (Line 1)",
        "AddressLine2Txt": "Street Address (Line 2)",
        "CityNm": "City",
        "StateAbbreviationCd": "State",
        "ZIPCd": "ZIP Code",

        # TIN fields
        "SSN": "Social Security Number",
        "EIN": "Employer Identification Number",
        "TIN": "Taxpayer Identification Number",

        # Form amounts
        "NonemployeeCompensationAmt": "Box 1 - Nonemployee Compensation",
        "FederalIncomeTaxWithheldAmt": "Federal Income Tax Withheld",
        "RentAmt": "Box 1 - Rents",
        "RoyaltyAmt": "Box 2 - Royalties",
        "OtherIncomeAmt": "Box 3 - Other Income",
    }

    # Common error patterns with translations
    ERROR_PATTERNS = [
        # Pattern type mismatches
        {
            "pattern": r"cvc-pattern-valid: Value '(.+?)' is not facet-valid with respect to pattern '(.+?)' for type '(.+?)'",
            "translator": "translate_pattern_error",
        },
        {
            "pattern": r"cvc-type\.3\.1\.3: The value '(.+?)' of element '(.+?)' is not valid",
            "translator": "translate_type_error",
        },
        # Length violations
        {
            "pattern": r"cvc-maxLength-valid: Value '(.+?)' with length = '(\d+)' is not facet-valid with respect to maxLength '(\d+)' for type '(.+?)'",
            "translator": "translate_maxlength_error",
        },
        {
            "pattern": r"cvc-minLength-valid: Value '(.+?)' with length = '(\d+)' is not facet-valid with respect to minLength '(\d+)' for type '(.+?)'",
            "translator": "translate_minlength_error",
        },
        # Required field violations
        {
            "pattern": r"cvc-complex-type\.2\.4\.a: Invalid content was found starting with element '(.+?)'",
            "translator": "translate_invalid_content",
        },
        {
            "pattern": r"cvc-complex-type\.2\.4\.b: The content of element '(.+?)' is not complete",
            "translator": "translate_incomplete_content",
        },
    ]

    def __init__(self):
        """Initialize the error translator."""
        pass

    def translate_error(self, error_message: str, line: Optional[int] = None,
                       column: Optional[int] = None) -> Dict[str, str]:
        """
        Translate a cryptic XML error into a user-friendly message.

        Returns a dict with:
        - field: The field name (e.g., "Middle Name")
        - message: User-friendly error message
        - fix: Suggested fix
        - severity: "error" or "warning"
        """
        # Try each pattern
        for pattern_info in self.ERROR_PATTERNS:
            match = re.search(pattern_info["pattern"], error_message, re.IGNORECASE)
            if match:
                translator_method = getattr(self, pattern_info["translator"])
                return translator_method(match, error_message)

        # No pattern matched - return generic translation
        return self._translate_generic(error_message)

    def translate_pattern_error(self, match: re.Match, full_error: str) -> Dict[str, str]:
        """Translate pattern validation errors (invalid characters)."""
        value = match.group(1)
        pattern = match.group(2)
        type_name = match.group(3)

        # Extract field name from context
        field = self._extract_field_from_context(full_error, type_name)
        field_name = self.FIELD_NAMES.get(field, field)

        # Special case: middle name with invalid characters
        if "MiddleNm" in type_name or "MiddleNm" in field:
            if "&" in value:
                return {
                    "field": "TIN Type",
                    "message": f"Recipient name contains '&' which indicates a business entity.",
                    "fix": "Change TIN Type from SSN to EIN. Business names should use EIN, not SSN.",
                    "severity": "error",
                    "highlight_field": "tin_type",
                }
            else:
                return {
                    "field": "Middle Name",
                    "message": f"Middle name '{value}' contains invalid characters.",
                    "fix": "Middle names can only contain letters (A-Z), hyphens, and spaces. Remove any numbers or special characters.",
                    "severity": "error",
                    "highlight_field": "name",
                }

        # Generic pattern error
        return {
            "field": field_name,
            "message": f"{field_name} contains invalid characters: '{value}'",
            "fix": f"Remove special characters. Allowed: letters, numbers, hyphens, spaces.",
            "severity": "error",
            "highlight_field": self._map_to_form_field(field),
        }

    def translate_type_error(self, match: re.Match, full_error: str) -> Dict[str, str]:
        """Translate type validation errors (follow-up to pattern errors)."""
        value = match.group(1)
        element = match.group(2)

        field_name = self.FIELD_NAMES.get(element, element)

        # This usually follows a pattern error, so provide context
        if "MiddleNm" in element:
            return {
                "field": "TIN Type",
                "message": f"Name parsing failed - appears to be a business entity.",
                "fix": "Check TIN Type. If this is a business (LLC, Inc, Corp), change TIN Type to EIN.",
                "severity": "error",
                "highlight_field": "tin_type",
            }

        return {
            "field": field_name,
            "message": f"{field_name} value '{value}' is invalid.",
            "fix": "Check the format and characters used in this field.",
            "severity": "error",
            "highlight_field": self._map_to_form_field(element),
        }

    def translate_maxlength_error(self, match: re.Match, full_error: str) -> Dict[str, str]:
        """Translate maximum length errors."""
        value = match.group(1)
        actual_length = int(match.group(2))
        max_length = int(match.group(3))
        type_name = match.group(4)

        field = self._extract_field_from_context(full_error, type_name)
        field_name = self.FIELD_NAMES.get(field, field)

        # Special case: last name too long (business name with wrong TIN type)
        if "LastNm" in type_name or "LastNm" in field:
            if actual_length > 25:  # Likely a business name
                return {
                    "field": "TIN Type",
                    "message": f"Name '{value}' is {actual_length} characters (max {max_length} for individuals).",
                    "fix": f"This appears to be a business name. Change TIN Type to EIN so the full business name can be used (75 char limit instead of {max_length}).",
                    "severity": "error",
                    "highlight_field": "tin_type",
                }

        return {
            "field": field_name,
            "message": f"{field_name} is too long: {actual_length} characters (max {max_length}).",
            "fix": f"Shorten to {max_length} characters or less.",
            "severity": "error",
            "highlight_field": self._map_to_form_field(field),
        }

    def translate_minlength_error(self, match: re.Match, full_error: str) -> Dict[str, str]:
        """Translate minimum length errors."""
        value = match.group(1)
        actual_length = int(match.group(2))
        min_length = int(match.group(3))
        type_name = match.group(4)

        field = self._extract_field_from_context(full_error, type_name)
        field_name = self.FIELD_NAMES.get(field, field)

        return {
            "field": field_name,
            "message": f"{field_name} is too short: {actual_length} characters (min {min_length}).",
            "fix": f"Must be at least {min_length} characters.",
            "severity": "error",
            "highlight_field": self._map_to_form_field(field),
        }

    def translate_invalid_content(self, match: re.Match, full_error: str) -> Dict[str, str]:
        """Translate invalid content errors."""
        element = match.group(1)
        field_name = self.FIELD_NAMES.get(element, element)

        return {
            "field": field_name,
            "message": f"Unexpected element: {element}",
            "fix": "This field may be in the wrong order or shouldn't be included.",
            "severity": "error",
            "highlight_field": self._map_to_form_field(element),
        }

    def translate_incomplete_content(self, match: re.Match, full_error: str) -> Dict[str, str]:
        """Translate incomplete content errors (missing required fields)."""
        element = match.group(1)
        field_name = self.FIELD_NAMES.get(element, element)

        return {
            "field": field_name,
            "message": f"Required field is missing in {field_name}.",
            "fix": "Check that all required fields are filled in.",
            "severity": "error",
            "highlight_field": self._map_to_form_field(element),
        }

    def _translate_generic(self, error_message: str) -> Dict[str, str]:
        """Provide a generic translation for unmatched errors."""
        # Try to extract element name
        element_match = re.search(r"element '(.+?)'", error_message)
        if element_match:
            element = element_match.group(1)
            field_name = self.FIELD_NAMES.get(element, element)
            return {
                "field": field_name,
                "message": error_message,
                "fix": "Review this field for format or content issues.",
                "severity": "error",
                "highlight_field": self._map_to_form_field(element),
            }

        return {
            "field": "Unknown",
            "message": error_message,
            "fix": "Please review the form data.",
            "severity": "error",
            "highlight_field": None,
        }

    def _extract_field_from_context(self, full_error: str, type_name: str) -> str:
        """Extract field name from error context."""
        # Look for element name in error
        match = re.search(r"element '(.+?)'", full_error)
        if match:
            return match.group(1)

        # Try to infer from type name
        type_to_field = {
            "PersonFirstNameType": "PersonFirstNm",
            "PersonMiddleNameType": "PersonMiddleNm",
            "PersonLastNameType": "PersonLastNm",
            "BusinessNameLine1Type": "BusinessNameLine1Txt",
            "BusinessNameLine2Type": "BusinessNameLine2Txt",
        }
        return type_to_field.get(type_name, type_name)

    def _map_to_form_field(self, xml_element: str) -> Optional[str]:
        """Map XML element names to form field identifiers."""
        mapping = {
            "PersonFirstNm": "name",
            "PersonMiddleNm": "name",
            "PersonLastNm": "name",
            "BusinessNameLine1Txt": "name",
            "BusinessNameLine2Txt": "name_line_2",
            "AddressLine1Txt": "address1",
            "AddressLine2Txt": "address2",
            "CityNm": "city",
            "StateAbbreviationCd": "state",
            "ZIPCd": "zip",
            "SSN": "tin",
            "EIN": "tin",
            "TIN": "tin",
        }
        return mapping.get(xml_element)


def translate_iris_errors(xml_errors: list) -> list:
    """
    Translate a list of XML validation errors into user-friendly messages.

    Args:
        xml_errors: List of error dicts from iris_xml_validator

    Returns:
        List of translated error dicts with field, message, fix, severity
    """
    translator = IRISErrorTranslator()
    translated = []

    for error in xml_errors:
        error_msg = error.get("message", "")
        line = error.get("line")
        column = error.get("column")

        translated_error = translator.translate_error(error_msg, line, column)

        # Add original error for debugging
        translated_error["original_error"] = error_msg
        if line:
            translated_error["line"] = line
        if column:
            translated_error["column"] = column

        translated.append(translated_error)

    return translated
