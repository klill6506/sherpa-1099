"""
Excel/CSV Import Service for 1099 data.

Handles:
- File upload and parsing
- Column mapping (auto-detect + manual)
- Data normalization
- Validation
- Promotion to canonical records
"""

import re
import hashlib
from typing import Optional, List, Dict, Any, Tuple, Union
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import pandas as pd

from supabase_client import get_supabase_client, log_activity


# =============================================================================
# CONSTANTS
# =============================================================================

VALID_STATES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI',
    'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN',
    'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH',
    'OK', 'OR', 'PA', 'PR', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA',
    'VI', 'WA', 'WV', 'WI', 'WY', 'AS', 'GU', 'MP', 'FM', 'MH', 'PW'
}

FORM_TYPES = ['1099-NEC', '1099-MISC', '1099-DIV', '1099-INT', '1099-B', '1099-R', '1099-S', '1098']


# =============================================================================
# NORMALIZATION FUNCTIONS
# =============================================================================

def detect_business_entity(name: str) -> bool:
    """
    Detect if a name appears to be a business entity based on common suffixes.

    Returns True if the name contains business entity indicators like LLC, Inc, Corp, etc.
    """
    if not name:
        return False

    name_upper = name.upper()
    business_indicators = [
        'LLC', 'L.L.C', 'L L C',
        'INC', 'INCORPORATED',
        'CORP', 'CORPORATION',
        'LTD', 'LIMITED',
        'CO', 'COMPANY',
        'LP', 'L.P',
        'LLP', 'L.L.P',
        'PLLC', 'P.L.L.C',
        'PA', 'P.A',
        'PC', 'P.C',
        'PROFESSIONAL ASSOCIATION',
        'PROFESSIONAL CORPORATION',
    ]

    for indicator in business_indicators:
        if indicator in name_upper:
            return True

    return False


def normalize_tin(tin: Any) -> Tuple[Optional[str], Optional[str], List[dict]]:
    """
    Normalize TIN (SSN/EIN) to standard format.

    Returns: (normalized_tin, tin_type, errors)
    """
    errors = []
    if tin is None or (isinstance(tin, float) and pd.isna(tin)):
        return None, None, [{'field': 'recipient_tin', 'code': 'MISSING_TIN',
                            'message': 'TIN is required', 'severity': 'error'}]

    # Convert to string and strip
    tin_str = str(tin).strip()

    # Remove common formatting
    tin_clean = re.sub(r'[^0-9]', '', tin_str)

    if len(tin_clean) != 9:
        return tin_str, None, [{'field': 'recipient_tin', 'code': 'INVALID_TIN_LENGTH',
                               'message': f'TIN must be 9 digits, got {len(tin_clean)}',
                               'severity': 'error'}]

    # Try to detect type from original format
    # SSN format: XXX-XX-XXXX or XXX XX XXXX
    # EIN format: XX-XXXXXXX
    ssn_pattern = re.match(r'^\d{3}[\s\-]?\d{2}[\s\-]?\d{4}$', tin_str)
    ein_pattern = re.match(r'^\d{2}[\s\-]?\d{7}$', tin_str)

    if ssn_pattern and not ein_pattern:
        # Clearly SSN format
        tin_type = 'SSN'
        formatted = f"{tin_clean[:3]}-{tin_clean[3:5]}-{tin_clean[5:]}"
    elif ein_pattern and not ssn_pattern:
        # Clearly EIN format
        tin_type = 'EIN'
        formatted = f"{tin_clean[:2]}-{tin_clean[2:]}"
    else:
        # Ambiguous - use heuristics based on first digits
        first_two = int(tin_clean[:2])

        # Common EIN prefixes that are unlikely SSN area numbers
        # EINs starting with 00-06 or 07-19 are very common
        # SSNs can't start with 000, 666, or 9XX (except ITIN)
        if first_two < 10 or first_two in (20, 26, 27):
            # Likely EIN (low prefixes or known EIN-only codes)
            tin_type = 'EIN'
            formatted = f"{tin_clean[:2]}-{tin_clean[2:]}"
        else:
            # Default to SSN for ambiguous cases (most 1099 recipients are individuals)
            tin_type = 'SSN'
            formatted = f"{tin_clean[:3]}-{tin_clean[3:5]}-{tin_clean[5:]}"

    # Validate based on detected type
    if tin_type == 'SSN':
        if tin_clean[:3] == '000' or tin_clean[3:5] == '00' or tin_clean[5:] == '0000':
            errors.append({'field': 'recipient_tin', 'code': 'INVALID_SSN',
                          'message': 'SSN contains invalid segment (all zeros)',
                          'severity': 'warning'})
        if tin_clean[:3] == '666':
            errors.append({'field': 'recipient_tin', 'code': 'INVALID_SSN',
                          'message': 'SSN area number 666 is invalid',
                          'severity': 'warning'})

    return formatted, tin_type, errors


def normalize_state(state: Any) -> Tuple[Optional[str], List[dict]]:
    """Normalize state to 2-letter code."""
    errors: List[dict] = []
    if state is None or (isinstance(state, float) and pd.isna(state)):
        return None, [{'field': 'recipient_state', 'code': 'MISSING_STATE',
                      'message': 'State is required', 'severity': 'error'}]

    state_str = str(state).strip().upper()

    # Common state name mappings
    state_names = {
        'ALABAMA': 'AL', 'ALASKA': 'AK', 'ARIZONA': 'AZ', 'ARKANSAS': 'AR',
        'CALIFORNIA': 'CA', 'COLORADO': 'CO', 'CONNECTICUT': 'CT', 'DELAWARE': 'DE',
        'FLORIDA': 'FL', 'GEORGIA': 'GA', 'HAWAII': 'HI', 'IDAHO': 'ID',
        'ILLINOIS': 'IL', 'INDIANA': 'IN', 'IOWA': 'IA', 'KANSAS': 'KS',
        'KENTUCKY': 'KY', 'LOUISIANA': 'LA', 'MAINE': 'ME', 'MARYLAND': 'MD',
        'MASSACHUSETTS': 'MA', 'MICHIGAN': 'MI', 'MINNESOTA': 'MN', 'MISSISSIPPI': 'MS',
        'MISSOURI': 'MO', 'MONTANA': 'MT', 'NEBRASKA': 'NE', 'NEVADA': 'NV',
        'NEW HAMPSHIRE': 'NH', 'NEW JERSEY': 'NJ', 'NEW MEXICO': 'NM', 'NEW YORK': 'NY',
        'NORTH CAROLINA': 'NC', 'NORTH DAKOTA': 'ND', 'OHIO': 'OH', 'OKLAHOMA': 'OK',
        'OREGON': 'OR', 'PENNSYLVANIA': 'PA', 'RHODE ISLAND': 'RI', 'SOUTH CAROLINA': 'SC',
        'SOUTH DAKOTA': 'SD', 'TENNESSEE': 'TN', 'TEXAS': 'TX', 'UTAH': 'UT',
        'VERMONT': 'VT', 'VIRGINIA': 'VA', 'WASHINGTON': 'WA', 'WEST VIRGINIA': 'WV',
        'WISCONSIN': 'WI', 'WYOMING': 'WY', 'DISTRICT OF COLUMBIA': 'DC',
        'PUERTO RICO': 'PR', 'VIRGIN ISLANDS': 'VI'
    }

    # Try full name first
    if state_str in state_names:
        return state_names[state_str], []

    # Already 2-letter code?
    if len(state_str) == 2 and state_str in VALID_STATES:
        return state_str, []

    # Invalid
    return state_str[:2] if len(state_str) >= 2 else state_str, [
        {'field': 'recipient_state', 'code': 'INVALID_STATE',
         'message': f'Invalid state: {state_str}', 'severity': 'error'}
    ]


def normalize_zip(zip_code: Any) -> Tuple[Optional[str], List[dict]]:
    """Normalize ZIP code to 5 or 9 digit format."""
    errors: List[dict] = []
    if zip_code is None or (isinstance(zip_code, float) and pd.isna(zip_code)):
        return None, [{'field': 'recipient_zip', 'code': 'MISSING_ZIP',
                      'message': 'ZIP code is required', 'severity': 'error'}]

    # Handle numeric ZIP codes that lost leading zeros
    zip_str = str(zip_code).strip()

    # Remove any non-numeric except hyphen
    zip_clean = re.sub(r'[^0-9-]', '', zip_str)
    zip_digits = re.sub(r'[^0-9]', '', zip_clean)

    # Pad with leading zeros if needed
    if len(zip_digits) < 5:
        zip_digits = zip_digits.zfill(5)

    if len(zip_digits) == 5:
        return zip_digits, []
    elif len(zip_digits) == 9:
        return f"{zip_digits[:5]}-{zip_digits[5:]}", []
    else:
        return zip_clean, [{'field': 'recipient_zip', 'code': 'INVALID_ZIP',
                          'message': f'ZIP must be 5 or 9 digits, got {len(zip_digits)}',
                          'severity': 'error'}]


def normalize_name(name: Any) -> Tuple[Optional[str], List[dict]]:
    """
    Normalize payee/business name for IRS compliance.

    IRS BusinessNameLine1Type pattern allows: A-Za-z0-9 # - ( ) & ' and space
    NOT allowed: periods, commas, colons, semicolons, etc.
    """
    import html
    errors = []
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None, [{'field': 'recipient_name', 'code': 'MISSING_NAME',
                      'message': 'Recipient name is required', 'severity': 'error'}]

    name_str = str(name).strip()

    # Decode HTML entities (e.g., &amp; -> &, &lt; -> <)
    name_str = html.unescape(name_str)

    # Remove extra whitespace
    name_str = ' '.join(name_str.split())

    # IRS-compliant sanitization: remove periods and commas (common in Inc., LLC., etc.)
    # These cause XML schema validation failures
    original_name = name_str
    name_str = name_str.replace('.', '').replace(',', '')

    # Keep only IRS-allowed characters: A-Za-z0-9 # - ( ) & ' and space
    name_str = re.sub(r'[^A-Za-z0-9#\-\(\)&\'\s]', '', name_str)

    # Collapse multiple spaces
    name_str = ' '.join(name_str.split())

    # Add info if name was modified
    if name_str != original_name.replace('.', '').replace(',', ''):
        errors.append({'field': 'recipient_name', 'code': 'NAME_SANITIZED',
                      'message': f'Name sanitized for IRS compliance',
                      'severity': 'info'})

    # Truncate to IRS limit (75 chars for BusinessNameLine1Txt)
    if len(name_str) > 75:
        errors.append({'field': 'recipient_name', 'code': 'NAME_TRUNCATED',
                      'message': f'Name truncated from {len(name_str)} to 75 chars',
                      'severity': 'warning'})
        name_str = name_str[:75]

    if len(name_str) < 1:
        return None, [{'field': 'recipient_name', 'code': 'MISSING_NAME',
                      'message': 'Recipient name is required', 'severity': 'error'}]

    return name_str, errors


def normalize_address(address: Any) -> Tuple[Optional[str], List[dict]]:
    """
    Normalize address line for IRS compliance.

    IRS StreetAddressType pattern allows: A-Za-z0-9 - / and space
    NOT allowed: periods, commas, #, etc.
    """
    import html
    errors = []
    if address is None or (isinstance(address, float) and pd.isna(address)):
        return None, []

    addr_str = str(address).strip()

    # Decode HTML entities (e.g., &amp; -> &)
    addr_str = html.unescape(addr_str)

    addr_str = ' '.join(addr_str.split())

    # IRS-compliant sanitization: remove periods and commas (common in Dr., St., Ave., etc.)
    addr_str = addr_str.replace('.', '').replace(',', '')

    # Replace # with "No " (common for apartment/suite numbers)
    addr_str = addr_str.replace('#', 'No ')

    # Keep only IRS-allowed characters: A-Za-z0-9 - / and space
    addr_str = re.sub(r'[^A-Za-z0-9\-/\s]', '', addr_str)

    # Collapse multiple spaces
    addr_str = ' '.join(addr_str.split())

    # Truncate to IRS limit (35 chars for AddressLine1Txt)
    if len(addr_str) > 35:
        errors.append({'field': 'address', 'code': 'ADDRESS_TRUNCATED',
                      'message': f'Address truncated from {len(addr_str)} to 35 chars',
                      'severity': 'warning'})
        addr_str = addr_str[:35]

    return addr_str if addr_str else None, errors


def normalize_amount(amount: Any, field_name: str) -> Tuple[Optional[float], List[dict]]:
    """Normalize monetary amount."""
    errors = []
    if amount is None or (isinstance(amount, float) and pd.isna(amount)):
        return None, []

    try:
        # Handle string amounts with currency symbols
        if isinstance(amount, str):
            amount = re.sub(r'[,$()]', '', amount.strip())
            if amount.startswith('-') or amount.endswith('-'):
                amount = '-' + amount.replace('-', '')

        value = float(amount)

        # Validate range
        if value < 0:
            errors.append({'field': field_name, 'code': 'NEGATIVE_AMOUNT',
                          'message': f'{field_name} cannot be negative: {value}',
                          'severity': 'error'})

        if value > 99999999.99:
            errors.append({'field': field_name, 'code': 'AMOUNT_TOO_LARGE',
                          'message': f'{field_name} exceeds maximum: {value}',
                          'severity': 'error'})

        # Round to cents
        return round(value, 2), errors

    except (ValueError, InvalidOperation):
        return None, [{'field': field_name, 'code': 'INVALID_AMOUNT',
                      'message': f'Cannot parse amount: {amount}', 'severity': 'error'}]


def normalize_city(city: Any) -> Tuple[Optional[str], List[dict]]:
    """Normalize city name."""
    import html
    errors: List[dict] = []
    if city is None or (isinstance(city, float) and pd.isna(city)):
        return None, [{'field': 'recipient_city', 'code': 'MISSING_CITY',
                      'message': 'City is required', 'severity': 'error'}]

    city_str = str(city).strip()

    # Decode HTML entities (e.g., &amp; -> &)
    city_str = html.unescape(city_str)

    city_str = ' '.join(city_str.split())
    city_str = re.sub(r'[^\w\s\.\-\']', '', city_str)

    if len(city_str) > 25:
        city_str = city_str[:25]

    return city_str if city_str else None, errors


def normalize_date(date_val: Any, field_name: str, for_database: bool = True) -> Tuple[Optional[str], List[dict]]:
    """
    Normalize date to standard format.

    Accepts various formats: YYYY-MM-DD, MM/DD/YYYY, M/D/YY, etc.

    Args:
        date_val: Raw date value
        field_name: Field name for error messages
        for_database: If True, returns YYYY-MM-DD (PostgreSQL). If False, returns MM/DD/YYYY (IRS forms).

    Returns: (formatted_date_string, errors)
    """
    errors = []
    if date_val is None or (isinstance(date_val, float) and pd.isna(date_val)):
        return None, []

    date_str = str(date_val).strip()
    if not date_str:
        return None, []

    try:
        # Try parsing common date formats
        parsed_date = None

        # Try pandas datetime parsing (handles many formats)
        try:
            parsed_date = pd.to_datetime(date_str)
        except:
            pass

        if parsed_date is None:
            # Try specific formats
            for fmt in ['%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%m/%d/%y', '%d-%b-%Y']:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue

        if parsed_date is None:
            return date_str, [{'field': field_name, 'code': 'INVALID_DATE',
                              'message': f'Cannot parse date: {date_str}', 'severity': 'warning'}]

        # Format based on target
        if for_database:
            return parsed_date.strftime('%Y-%m-%d'), errors  # PostgreSQL format
        else:
            return parsed_date.strftime('%m/%d/%Y'), errors  # IRS display format

    except Exception:
        return date_str, [{'field': field_name, 'code': 'INVALID_DATE',
                         'message': f'Cannot parse date: {date_str}', 'severity': 'warning'}]


def normalize_boolean(val: Any, field_name: str) -> Tuple[Optional[bool], List[dict]]:
    """Normalize boolean/checkbox values."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None, []

    if isinstance(val, bool):
        return val, []

    val_str = str(val).strip().lower()
    if val_str in ('true', 'yes', 'y', '1', 'x', 'checked'):
        return True, []
    elif val_str in ('false', 'no', 'n', '0', '', 'unchecked'):
        return False, []

    return None, [{'field': field_name, 'code': 'INVALID_BOOLEAN',
                  'message': f'Cannot parse boolean: {val}', 'severity': 'warning'}]


# =============================================================================
# COLUMN MAPPING
# =============================================================================

def get_column_aliases() -> Dict[str, List[str]]:
    """Load column aliases from database."""
    client = get_supabase_client()
    response = client.table("column_aliases").select("*").order("priority", desc=True).execute()

    aliases: Dict[str, List[str]] = {}
    for row in response.data:
        target = row['target_field']
        alias = row['alias'].lower()
        if target not in aliases:
            aliases[target] = []
        aliases[target].append(alias)

    return aliases


def auto_map_columns(df_columns: List[str], aliases: Optional[Dict[str, List[str]]] = None, form_type: Optional[str] = None) -> Dict[str, str]:
    """
    Auto-detect column mapping based on aliases.

    Args:
        df_columns: List of column names from the DataFrame
        aliases: Optional pre-loaded aliases dict
        form_type: Optional form type to enable form-specific mappings

    Returns: {source_column: target_field}
    """
    if aliases is None:
        aliases = get_column_aliases()

    # Add hardcoded aliases for common template column names
    # These supplement the database aliases
    hardcoded_aliases = {
        'recipient_name': ['recipient name1', 'name1', 'payee name', 'recipient name'],
        'recipient_name_line2': ['recipient name2', 'name2', 'name line 2'],
        'recipient_tin': ['recipienttaxid', 'recipient taxid', 'recipient tax id', 'taxid', 'tax id', 'tin', 'ssn', 'ein'],
        'recipient_address1': ['address1', 'address', 'street', 'street address'],
        'recipient_address2': ['address2', 'address line 2', 'apt', 'suite'],
        'recipient_city': ['city'],
        'recipient_state': ['state'],
        'recipient_zip': ['zipcode', 'zip code', 'zip', 'postal'],
        'recipient_email': ['emailaddress', 'email address', 'email', 'e-mail'],
        'account_number': ['accountnum', 'account num', 'account number', 'acct', 'account'],
        # NEC boxes
        'nec_box1': ['box1_nec', 'box 1 nec', 'nec box 1', 'nec box1', 'nonemployee compensation', 'compensation', 'amount'],
        'nec_box4': ['box4_fedwithheld', 'box4_fed_withheld', 'federal withheld', 'fed withheld'],
        # MISC boxes - key fix: add box1_rents
        'misc_box1': ['box1_rents', 'box1 rents', 'box 1 rents', 'rents', 'rent'],
        'misc_box2': ['box2_royalties', 'box2 royalties', 'royalties', 'royalty'],
        'misc_box3': ['box3_otherincome', 'box3 otherincome', 'box3_ otherincome', 'other income', 'other'],
        'misc_box4': ['box4_fedwithheld', 'misc fed withheld'],
        'misc_box6': ['box6', 'medical', 'medical payments'],
        'misc_box10': ['box10', 'attorney', 'gross proceeds attorney'],
        # 1099-S boxes
        's_box1_date_closing': ['date of closing', 'closing date', 'date closing', 's_box1', 'box 1 closing', '1 date of closing'],
        's_box2_gross_proceeds': ['gross proceeds', 'proceeds', 'sale amount', 's_box2', 'box 2 proceeds', '2. gross proceeds', '2 gross proceeds'],
        's_box3_property_address': ['property address', 'property description', 'legal description', 's_box3', 'box 3 property'],
        's_box4_property_services': ['property services', 'received property', 's_box4', '4. rec prop or serv', 'rec prop or serv'],
        's_box5_foreign_person': ['foreign person', 'foreign buyer', 's_box5', '5. foreign person'],
        's_box6_buyers_tax': ['buyers tax', 'buyer tax', 'real estate tax', 's_box6', 'box 6 tax', '6. buyers part of real estate tax', 'buyers part of real estate tax'],
        # 1098 boxes
        'f1098_box1_mortgage_interest': ['mortgage interest', 'interest received', 'interest paid', '1098_box1', 'box 1 mortgage', '1. mortgage interest'],
        'f1098_box2_outstanding_principal': ['outstanding principal', 'principal balance', 'mortgage principal', '1098_box2', '2. mortgage principal'],
        'f1098_box3_origination_date': ['origination date', 'mortgage origination', 'loan origination', '1098_box3', '3. origin date', 'origin date'],
        'f1098_box4_refund_interest': ['refund interest', 'overpaid interest', '1098_box4', '4. refund of int', 'refund of int'],
        'f1098_box5_mortgage_insurance': ['mortgage insurance', 'pmi', 'insurance premiums', '1098_box5', '5. mip', 'mip'],
        'f1098_box6_points_paid': ['points paid', 'points', '1098_box6', '6. points'],
        'f1098_box8_property_address': ['1098 property address', '1098_box8', '8. address'],
        'f1098_box9_num_properties': ['number of properties', 'num properties', '1098_box9', '9. no. of prop', 'no. of prop'],
        'f1098_box10_other': ['1098 other', '1098_box10', '10. prop taxes', 'prop taxes'],
        'f1098_box11_acquisition_date': ['acquisition date', 'property acquisition', '1098_box11', '11 acq date', 'acq date'],
    }

    # Add form-type-specific aliases for generic BOX1, BOX2, etc. column names
    # These only apply when we know the form type from the sheet name
    if form_type == '1099-S':
        # 1099-S uses generic BOX1-BOX6 columns
        # Also add 'address' here (not globally) to avoid conflict with recipient_address1
        form_specific = {
            's_box1_date_closing': ['box1', 'box 1'],
            's_box2_gross_proceeds': ['box2', 'box 2'],
            's_box3_property_address': ['box3', 'box 3', 'address'],
            's_box4_property_services': ['box4', 'box 4'],
            's_box5_foreign_person': ['box5', 'box 5'],
            's_box6_buyers_tax': ['box6', 'box 6'],
        }
        for target, alias_list in form_specific.items():
            if target not in hardcoded_aliases:
                hardcoded_aliases[target] = []
            hardcoded_aliases[target].extend(alias_list)
    elif form_type == '1098':
        # 1098 uses generic BOX1-BOX11 columns
        # Also add 'address' here (not globally) to avoid conflict with recipient_address1
        form_specific = {
            'f1098_box1_mortgage_interest': ['box1', 'box 1'],
            'f1098_box2_outstanding_principal': ['box2', 'box 2'],
            'f1098_box3_origination_date': ['box3', 'box 3'],
            'f1098_box4_refund_interest': ['box4', 'box 4'],
            'f1098_box5_mortgage_insurance': ['box5', 'box 5'],
            'f1098_box6_points_paid': ['box6', 'box 6'],
            # Box 7 is "same address" checkbox - not currently mapped
            'f1098_box8_property_address': ['box8', 'box 8', 'address'],
            'f1098_box9_num_properties': ['box9', 'box 9'],
            'f1098_box10_other': ['box10', 'box 10'],
            'f1098_box11_acquisition_date': ['box11', 'box 11'],
        }
        for target, alias_list in form_specific.items():
            if target not in hardcoded_aliases:
                hardcoded_aliases[target] = []
            hardcoded_aliases[target].extend(alias_list)

    # Merge hardcoded with database aliases
    for target, alias_list in hardcoded_aliases.items():
        if target not in aliases:
            aliases[target] = []
        for a in alias_list:
            if a.lower() not in [x.lower() for x in aliases[target]]:
                aliases[target].append(a.lower())

    mapping = {}
    df_cols_lower = {col.lower().strip(): col for col in df_columns}

    # Also try with underscores replaced by spaces
    df_cols_normalized = {}
    for col in df_columns:
        normalized = col.lower().strip().replace('_', ' ')
        df_cols_normalized[normalized] = col
        df_cols_normalized[col.lower().strip()] = col

    for target_field, alias_list in aliases.items():
        for alias in alias_list:
            alias_lower = alias.lower()
            alias_normalized = alias_lower.replace('_', ' ')
            # Try exact match first
            if alias_lower in df_cols_lower:
                source_col = df_cols_lower[alias_lower]
                if source_col not in mapping:
                    mapping[source_col] = target_field
                break
            # Try normalized (underscores as spaces)
            elif alias_normalized in df_cols_normalized:
                source_col = df_cols_normalized[alias_normalized]
                if source_col not in mapping:
                    mapping[source_col] = target_field
                break

    return mapping


# =============================================================================
# IMPORT SERVICE CLASS
# =============================================================================

class ImportService:
    """Service for handling Excel/CSV imports."""

    def __init__(self):
        self.client = get_supabase_client()

    def parse_filer_info(self, file_content: bytes, filename: str) -> Optional[Dict[str, Any]]:
        """
        Parse filer information from the 'Filer Information' sheet.

        Returns filer data dict or None if sheet doesn't exist.
        """
        from io import BytesIO

        file_ext = Path(filename).suffix.lower()
        if file_ext not in ['.xlsx', '.xls']:
            return None

        try:
            # Read the Filer Information sheet (no header - it's label/value format)
            xl = pd.ExcelFile(BytesIO(file_content))

            # Case-insensitive search for filer information sheet
            filer_sheet_name = None
            for sheet in xl.sheet_names:
                if sheet.lower().strip() == 'filer information':
                    filer_sheet_name = sheet
                    break

            if filer_sheet_name is None:
                print(f"DEBUG: Sheets found: {xl.sheet_names}")
                print(f"DEBUG: No 'Filer Information' sheet found")
                return None

            df = pd.read_excel(xl, sheet_name=filer_sheet_name, header=None, dtype=str)

            # Parse the label/value pairs
            # The sheet has labels in column 0 and values in column 1
            filer_data = {}
            print(f"DEBUG parse_filer_info: Parsing Filer Information sheet, {len(df)} rows")

            for idx, row in df.iterrows():
                label = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
                value = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else None
                print(f"DEBUG parse_filer_info: Row {idx}: label='{label}', value='{value}'")

                # Map labels to filer fields
                label_lower = label.lower()

                if 'filing year' in label_lower:
                    filer_data['tax_year'] = value
                elif 'filer taxid' in label_lower or 'company / filer taxid' in label_lower:
                    filer_data['tin'] = value
                elif 'filer name1' in label_lower or 'company / filer name1' in label_lower:
                    filer_data['name'] = value
                elif 'filer name2' in label_lower or 'company / filer name2' in label_lower:
                    filer_data['name_line_2'] = value
                elif label_lower == 'address1':
                    filer_data['address1'] = value
                elif label_lower == 'city':
                    filer_data['city'] = value
                elif label_lower == 'state':
                    filer_data['state'] = value
                elif label_lower in ('zipcode', 'zip'):
                    filer_data['zip'] = value
                elif 'telephone' in label_lower or 'phone' in label_lower:
                    filer_data['phone'] = value

            # Normalize the TIN
            if filer_data.get('tin'):
                tin_normalized, tin_type, _ = normalize_tin(filer_data['tin'])
                filer_data['tin'] = tin_normalized
                filer_data['tin_type'] = tin_type or 'EIN'  # Filers are usually companies

            # Normalize filer names (IRS-compliant: remove periods, commas)
            if filer_data.get('name'):
                name_normalized, _ = normalize_name(filer_data['name'])
                filer_data['name'] = name_normalized

            if filer_data.get('name_line_2'):
                name2_normalized, _ = normalize_name(filer_data['name_line_2'])
                filer_data['name_line_2'] = name2_normalized

            # Normalize filer address (IRS-compliant: remove periods, commas)
            if filer_data.get('address1'):
                addr_normalized, _ = normalize_address(filer_data['address1'])
                filer_data['address1'] = addr_normalized

            # Normalize state and zip
            if filer_data.get('state'):
                state_normalized, _ = normalize_state(filer_data['state'])
                filer_data['state'] = state_normalized

            if filer_data.get('zip'):
                zip_normalized, _ = normalize_zip(filer_data['zip'])
                filer_data['zip'] = zip_normalized

            print(f"DEBUG parse_filer_info: Parsed filer_data = {filer_data}")
            if not filer_data.get('name'):
                print(f"DEBUG parse_filer_info: No filer name found, returning None")
                return None
            return filer_data

        except Exception as e:
            print(f"Error parsing filer info: {e}")
            import traceback
            traceback.print_exc()
            return None

    def find_or_create_filer(self, filer_data: Dict[str, Any]) -> Optional[str]:
        """
        Find existing filer by TIN or create a new one.

        Returns filer ID.
        """
        if not filer_data.get('tin'):
            return None

        # Look for existing filer by TIN
        response = self.client.table('filers').select('id, name, tin').eq('tin', filer_data['tin']).execute()

        if response.data:
            # Found existing filer - update it with new data
            filer_id = response.data[0]['id']
            update_data = {k: v for k, v in filer_data.items() if v is not None and k != 'tax_year'}
            if update_data:
                self.client.table('filers').update(update_data).eq('id', filer_id).execute()
            log_activity(
                action='filer_updated_from_import',
                entity_type='filer',
                entity_id=filer_id,
                filer_id=filer_id,
                details={'name': filer_data.get('name'), 'tin': filer_data.get('tin')}
            )
            return filer_id
        else:
            # Create new filer
            insert_data = {k: v for k, v in filer_data.items() if v is not None and k != 'tax_year'}
            insert_data['is_active'] = True
            response = self.client.table('filers').insert(insert_data).execute()

            if response.data:
                filer_id = response.data[0]['id']
                log_activity(
                    action='filer_created_from_import',
                    entity_type='filer',
                    entity_id=filer_id,
                    filer_id=filer_id,
                    details={'name': filer_data.get('name'), 'tin': filer_data.get('tin')}
                )
                return filer_id

        return None

    def get_sheet_names(self, file_content: bytes, filename: str) -> List[str]:
        """Get list of sheet names from an Excel file."""
        from io import BytesIO

        file_ext = Path(filename).suffix.lower()
        if file_ext not in ['.xlsx', '.xls']:
            return []

        try:
            xl = pd.ExcelFile(BytesIO(file_content))
            return xl.sheet_names
        except Exception:
            return []

    def create_batch(
        self,
        operating_year_id: str,
        filename: str,
        file_content: bytes,
        filer_id: Optional[str] = None
    ) -> Optional[dict]:
        """Create a new import batch."""
        file_hash = hashlib.sha256(file_content).hexdigest()

        batch_data = {
            'operating_year_id': operating_year_id,
            'filer_id': filer_id,
            'filename': filename,
            'file_size': len(file_content),
            'file_hash': file_hash,
            'status': 'uploaded',
        }

        response = self.client.table('import_batches').insert(batch_data).execute()
        batch = response.data[0] if response.data else None

        if batch:
            log_activity(
                action='import_batch_created',
                entity_type='import_batch',
                entity_id=batch['id'],
                operating_year_id=operating_year_id,
                filer_id=filer_id,
                details={'filename': filename, 'size': len(file_content)}
            )

        return batch

    def parse_file(self, file_content: bytes, filename: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
        """
        Parse Excel or CSV file into DataFrame.

        Args:
            file_content: Raw file bytes
            filename: Original filename (for extension detection)
            sheet_name: For Excel files, which sheet to read (default: first data sheet)
        """
        from io import BytesIO

        file_ext = Path(filename).suffix.lower()

        if file_ext in ['.xlsx', '.xls']:
            xl = pd.ExcelFile(BytesIO(file_content))

            # If no sheet specified, find the first data sheet (skip Filer Information)
            if sheet_name is None:
                data_sheets = [s for s in xl.sheet_names if s != 'Filer Information']
                sheet_name = data_sheets[0] if data_sheets else xl.sheet_names[0]

            df = pd.read_excel(xl, sheet_name=sheet_name, dtype=str)
        elif file_ext == '.csv':
            df = pd.read_csv(BytesIO(file_content), dtype=str)
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

        # Clean column names
        df.columns = [str(col).strip() for col in df.columns]

        return df

    def detect_form_type_from_sheet_name(self, sheet_name: str) -> str:
        """
        Detect form type from sheet name.

        Common patterns:
        - "1099-NEC", "1099NEC", "NEC" -> 1099-NEC
        - "1099-MISC", "1099MISC", "MISC" -> 1099-MISC
        - "1099-S", "1099S" -> 1099-S
        - "1098" -> 1098
        """
        sheet_upper = sheet_name.upper().replace(" ", "").replace("-", "")

        if "1099NEC" in sheet_upper or sheet_upper == "NEC":
            return "1099-NEC"
        elif "1099MISC" in sheet_upper or sheet_upper == "MISC":
            return "1099-MISC"
        elif "1099S" in sheet_upper:
            return "1099-S"
        elif "1099DIV" in sheet_upper or sheet_upper == "DIV":
            return "1099-DIV"
        elif "1099INT" in sheet_upper or sheet_upper == "INT":
            return "1099-INT"
        elif "1098" in sheet_upper:
            return "1098"
        else:
            # Default based on content detection during normalization
            return "1099-NEC"

    def import_all_sheets(
        self,
        file_content: bytes,
        filename: str,
        operating_year_id: str,
    ) -> Dict[str, Any]:
        """
        Import ALL data sheets from a workbook at once.

        1. Parse filer info from 'Filer Information' sheet
        2. Create/update filer in database
        3. For each data sheet, create a batch and import rows
        4. Auto-detect form type from sheet name

        Returns dict with filer info and list of batch results per sheet.
        """
        result: Dict[str, Any] = {
            'filer_id': None,
            'filer_data': None,
            'filer_created': False,
            'sheets_imported': [],
            'total_rows': 0,
            'errors': []
        }

        # Step 1: Parse filer information
        print(f"DEBUG import_all_sheets: Starting import for '{filename}'")
        filer_data = self.parse_filer_info(file_content, filename)
        result['filer_data'] = filer_data
        print(f"DEBUG import_all_sheets: Filer data parsed: {filer_data}")

        # Step 2: Create/update filer
        if filer_data:
            existing = self.client.table('filers').select('id').eq('tin', filer_data.get('tin', '')).execute()
            result['filer_created'] = len(existing.data) == 0
            filer_id = self.find_or_create_filer(filer_data)
            result['filer_id'] = filer_id
            print(f"DEBUG import_all_sheets: Filer ID: {filer_id}, created: {result['filer_created']}")
        else:
            # Get sheet names to help with error message
            sheets = self.get_sheet_names(file_content, filename)
            result['errors'].append(f"No 'Filer Information' sheet found. Sheets in workbook: {sheets}")
            return result

        # Step 3: Get all data sheets
        sheets = self.get_sheet_names(file_content, filename)
        print(f"DEBUG import_all_sheets: All sheets found: {sheets}")
        data_sheets = [s for s in sheets if s.lower().strip() != 'filer information']
        print(f"DEBUG import_all_sheets: Data sheets: {data_sheets}")

        if not data_sheets:
            result['errors'].append(f"No data sheets found in workbook. Sheets present: {sheets}")
            return result

        # Step 4: Process each data sheet
        for sheet_name in data_sheets:
            sheet_result = {
                'sheet_name': sheet_name,
                'form_type': self.detect_form_type_from_sheet_name(sheet_name),
                'batch_id': None,
                'row_count': 0,
                'error': None
            }

            try:
                print(f"DEBUG: Processing sheet '{sheet_name}'")
                df = self.parse_file(file_content, filename, sheet_name=sheet_name)
                print(f"DEBUG: Sheet '{sheet_name}' has {len(df)} rows, columns: {list(df.columns)}")

                # Skip empty sheets (also check if all rows are NaN)
                if len(df) == 0:
                    sheet_result['error'] = "Sheet is empty"
                    result['sheets_imported'].append(sheet_result)
                    continue

                # Also skip sheets where first row (first data row) is all NaN
                if df.iloc[0].isna().all():
                    # Drop rows that are completely empty
                    df = df.dropna(how='all')
                    print(f"DEBUG: After dropping empty rows, '{sheet_name}' has {len(df)} rows")
                    if len(df) == 0:
                        sheet_result['error'] = "Sheet has no data rows"
                        result['sheets_imported'].append(sheet_result)
                        continue

                sheet_result['row_count'] = len(df)
                result['total_rows'] += len(df)

                # Create batch for this sheet
                batch = self.create_batch(
                    operating_year_id=operating_year_id,
                    filename=f"{filename} [{sheet_name}]",
                    file_content=file_content,
                    filer_id=filer_id
                )

                if batch:
                    sheet_result['batch_id'] = batch['id']

                    # Store raw rows
                    self.store_raw_rows(batch['id'], df)

                    # Auto-map columns (pass form_type for form-specific BOX mappings)
                    mapping = auto_map_columns(list(df.columns), form_type=sheet_result['form_type'])
                    self.apply_column_mapping(batch['id'], mapping)

            except Exception as e:
                sheet_result['error'] = str(e)

            result['sheets_imported'].append(sheet_result)

        log_activity(
            action='import_multi_sheet',
            entity_type='import',
            entity_id=result['filer_id'],
            filer_id=result['filer_id'],
            operating_year_id=operating_year_id,
            details={
                'filename': filename,
                'sheets': len(result['sheets_imported']),
                'total_rows': result['total_rows']
            }
        )

        return result

    def quick_import(
        self,
        file_content: bytes,
        filename: str,
        operating_year_id: str,
    ) -> Dict[str, Any]:
        """
        Quick import: Parse, validate, and promote in ONE step.

        Directly creates recipients and forms from the spreadsheet data.
        No intermediate staging tables used.

        Returns dict with:
        - filer_id, filer_data, filer_created
        - forms_created: list of created form records
        - recipients_created: count
        - errors: list of any validation errors (row-level)
        - warnings: list of warnings
        """
        result: Dict[str, Any] = {
            'filer_id': None,
            'filer_data': None,
            'filer_created': False,
            'forms_created': [],
            'recipients_created': 0,
            'total_rows': 0,
            'imported_rows': 0,
            'errors': [],
            'warnings': [],
            'row_errors': []  # Individual row errors
        }

        # Step 1: Parse filer information
        print(f"DEBUG quick_import: Starting import for '{filename}'")
        filer_data = self.parse_filer_info(file_content, filename)
        result['filer_data'] = filer_data

        if not filer_data:
            sheets = self.get_sheet_names(file_content, filename)
            result['errors'].append(f"No 'Filer Information' sheet found. Sheets in workbook: {sheets}")
            return result

        # Step 2: Create/update filer
        existing = self.client.table('filers').select('id').eq('tin', filer_data.get('tin', '')).execute()
        result['filer_created'] = len(existing.data) == 0
        filer_id = self.find_or_create_filer(filer_data)
        result['filer_id'] = filer_id

        if not filer_id:
            result['errors'].append("Failed to create filer record")
            return result

        # Step 3: Get all data sheets
        sheets = self.get_sheet_names(file_content, filename)
        data_sheets = [s for s in sheets if s.lower().strip() != 'filer information']

        if not data_sheets:
            result['errors'].append(f"No data sheets found. Sheets present: {sheets}")
            return result

        # Step 4: Process each data sheet directly to forms
        for sheet_name in data_sheets:
            try:
                df = self.parse_file(file_content, filename, sheet_name=sheet_name)

                # Skip empty sheets
                if len(df) == 0:
                    continue

                # Drop completely empty rows
                df = df.dropna(how='all')
                if len(df) == 0:
                    continue

                # Detect form type from sheet name
                form_type = self.detect_form_type_from_sheet_name(sheet_name)

                # Get column mapping (pass form_type for form-specific BOX mappings)
                mapping = auto_map_columns(list(df.columns), form_type=form_type)
                reverse_map = {v: k for k, v in mapping.items()}

                def get_raw(row_data, field):
                    source_col = reverse_map.get(field)
                    return row_data.get(source_col) if source_col else None

                # Process each row
                for idx, row in df.iterrows():
                    result['total_rows'] += 1
                    row_data = row.to_dict()
                    row_data = {k: (None if pd.isna(v) else v) for k, v in row_data.items()}
                    row_num = idx + 2  # Account for header and 0-index

                    row_errors = []

                    # Normalize fields
                    name, errs = normalize_name(get_raw(row_data, 'recipient_name'))
                    row_errors.extend(errs)

                    # Name Line 2 (optional)
                    name_line_2_raw = get_raw(row_data, 'recipient_name_line2')
                    name_line_2 = None
                    if name_line_2_raw and not pd.isna(name_line_2_raw):
                        name_line_2, errs = normalize_name(name_line_2_raw)
                        row_errors.extend(errs)

                    tin, tin_type, errs = normalize_tin(get_raw(row_data, 'recipient_tin'))
                    row_errors.extend(errs)

                    # Check if TIN type matches entity type
                    if name and tin_type:
                        is_business_name = detect_business_entity(name)
                        if is_business_name and tin_type == 'SSN':
                            row_errors.append({
                                'field': 'recipient_tin',
                                'code': 'TIN_TYPE_MISMATCH',
                                'message': f'Name "{name}" appears to be a business (LLC/Inc/Corp) but TIN type is SSN. Should be EIN.',
                                'severity': 'warning'
                            })
                        elif not is_business_name and tin_type == 'EIN':
                            row_errors.append({
                                'field': 'recipient_tin',
                                'code': 'TIN_TYPE_MISMATCH',
                                'message': f'Name "{name}" appears to be an individual but TIN type is EIN. Should be SSN.',
                                'severity': 'warning'
                            })

                    address1, errs = normalize_address(get_raw(row_data, 'recipient_address1'))
                    row_errors.extend(errs)

                    address2, _ = normalize_address(get_raw(row_data, 'recipient_address2'))

                    city, errs = normalize_city(get_raw(row_data, 'recipient_city'))
                    row_errors.extend(errs)

                    state, errs = normalize_state(get_raw(row_data, 'recipient_state'))
                    row_errors.extend(errs)

                    zip_code, errs = normalize_zip(get_raw(row_data, 'recipient_zip'))
                    row_errors.extend(errs)

                    # Check for critical errors
                    critical_errors = [e for e in row_errors if e['severity'] == 'error']
                    if critical_errors:
                        result['row_errors'].append({
                            'sheet': sheet_name,
                            'row': row_num,
                            'name': name or get_raw(row_data, 'recipient_name'),
                            'errors': critical_errors
                        })
                        continue  # Skip this row

                    # Normalize amounts based on form type
                    nec_box1, _ = normalize_amount(get_raw(row_data, 'nec_box1'), 'nec_box1')
                    nec_box4, _ = normalize_amount(get_raw(row_data, 'nec_box4'), 'nec_box4')
                    misc_box1, _ = normalize_amount(get_raw(row_data, 'misc_box1'), 'misc_box1')

                    # 1099-S fields
                    s_box1_date, _ = normalize_date(get_raw(row_data, 's_box1_date_closing'), 's_box1_date_closing')
                    s_box2_proceeds, _ = normalize_amount(get_raw(row_data, 's_box2_gross_proceeds'), 's_box2_gross_proceeds')
                    s_box3_address = get_raw(row_data, 's_box3_property_address')
                    if s_box3_address and not pd.isna(s_box3_address):
                        s_box3_address = str(s_box3_address).strip()
                    else:
                        s_box3_address = None
                    s_box4_services, _ = normalize_boolean(get_raw(row_data, 's_box4_property_services'), 's_box4_property_services')
                    s_box5_foreign, _ = normalize_boolean(get_raw(row_data, 's_box5_foreign_person'), 's_box5_foreign_person')
                    s_box6_tax, _ = normalize_amount(get_raw(row_data, 's_box6_buyers_tax'), 's_box6_buyers_tax')

                    # 1098 fields
                    f1098_box1, _ = normalize_amount(get_raw(row_data, 'f1098_box1_mortgage_interest'), 'f1098_box1_mortgage_interest')
                    f1098_box2, _ = normalize_amount(get_raw(row_data, 'f1098_box2_outstanding_principal'), 'f1098_box2_outstanding_principal')
                    f1098_box3, _ = normalize_date(get_raw(row_data, 'f1098_box3_origination_date'), 'f1098_box3_origination_date')
                    f1098_box4, _ = normalize_amount(get_raw(row_data, 'f1098_box4_refund_interest'), 'f1098_box4_refund_interest')
                    f1098_box5, _ = normalize_amount(get_raw(row_data, 'f1098_box5_mortgage_insurance'), 'f1098_box5_mortgage_insurance')
                    f1098_box6, _ = normalize_amount(get_raw(row_data, 'f1098_box6_points_paid'), 'f1098_box6_points_paid')
                    f1098_box8 = get_raw(row_data, 'f1098_box8_property_address')
                    if f1098_box8 and not pd.isna(f1098_box8):
                        f1098_box8 = str(f1098_box8).strip()
                    else:
                        f1098_box8 = None
                    f1098_box9 = get_raw(row_data, 'f1098_box9_num_properties')
                    if f1098_box9 and not pd.isna(f1098_box9):
                        try:
                            f1098_box9 = int(float(f1098_box9))
                        except:
                            f1098_box9 = None
                    else:
                        f1098_box9 = None
                    f1098_box10, _ = normalize_amount(get_raw(row_data, 'f1098_box10_other'), 'f1098_box10_other')
                    f1098_box11, _ = normalize_date(get_raw(row_data, 'f1098_box11_acquisition_date'), 'f1098_box11_acquisition_date')

                    # Override form type based on data if needed
                    if misc_box1 and not nec_box1:
                        form_type = '1099-MISC'
                    elif nec_box1 and not misc_box1:
                        form_type = '1099-NEC'
                    elif s_box2_proceeds or s_box1_date:
                        form_type = '1099-S'
                    elif f1098_box1 or f1098_box2:
                        form_type = '1098'

                    # Find or create recipient
                    existing_recip = self.client.table('recipients').select('id').eq('filer_id', filer_id).eq('tin', tin).execute().data

                    if existing_recip:
                        recipient_id = existing_recip[0]['id']
                        # Update recipient info
                        update_data = {
                            'name': name,
                            'address1': address1,
                            'address2': address2,
                            'city': city,
                            'state': state,
                            'zip': zip_code,
                        }
                        if name_line_2:
                            update_data['name_line_2'] = name_line_2
                        self.client.table('recipients').update(update_data).eq('id', recipient_id).execute()
                    else:
                        recip_data = {
                            'filer_id': filer_id,
                            'name': name,
                            'tin': tin,
                            'tin_type': tin_type or 'SSN',
                            'address1': address1,
                            'address2': address2,
                            'city': city,
                            'state': state,
                            'zip': zip_code,
                        }
                        if name_line_2:
                            recip_data['name_line_2'] = name_line_2
                        recip_result = self.client.table('recipients').insert(recip_data).execute()
                        recipient_id = recip_result.data[0]['id']
                        result['recipients_created'] += 1

                    # Check if form already exists for this recipient/filer/year/type
                    existing_form = self.client.table('forms_1099').select('id').eq(
                        'filer_id', filer_id
                    ).eq(
                        'recipient_id', recipient_id
                    ).eq(
                        'operating_year_id', operating_year_id
                    ).eq(
                        'form_type', form_type
                    ).execute().data

                    # Build form data
                    form_data = {
                        'status': 'ready',  # Ready for printing/filing
                    }

                    # Add amount fields based on form type
                    if form_type == '1099-NEC':
                        form_data['nec_box1'] = nec_box1 or 0
                        if nec_box4:
                            form_data['nec_box4'] = nec_box4
                    elif form_type == '1099-MISC':
                        form_data['misc_box1'] = misc_box1 or 0
                        # Add other MISC boxes as needed
                        for box in ['misc_box2', 'misc_box3', 'misc_box4', 'misc_box5',
                                   'misc_box6', 'misc_box8', 'misc_box9', 'misc_box10']:
                            val, _ = normalize_amount(get_raw(row_data, box), box)
                            if val:
                                form_data[box] = val
                    elif form_type == '1099-S':
                        if s_box1_date:
                            form_data['s_box1_date_closing'] = s_box1_date
                        if s_box2_proceeds:
                            form_data['s_box2_gross_proceeds'] = s_box2_proceeds
                        if s_box3_address:
                            form_data['s_box3_property_address'] = s_box3_address
                        if s_box4_services is not None:
                            form_data['s_box4_property_services'] = s_box4_services
                        if s_box5_foreign is not None:
                            form_data['s_box5_foreign_person'] = s_box5_foreign
                        if s_box6_tax:
                            form_data['s_box6_buyers_tax'] = s_box6_tax
                    elif form_type == '1098':
                        if f1098_box1:
                            form_data['f1098_box1_mortgage_interest'] = f1098_box1
                        if f1098_box2:
                            form_data['f1098_box2_outstanding_principal'] = f1098_box2
                        if f1098_box3:
                            form_data['f1098_box3_origination_date'] = f1098_box3
                        if f1098_box4:
                            form_data['f1098_box4_refund_interest'] = f1098_box4
                        if f1098_box5:
                            form_data['f1098_box5_mortgage_insurance'] = f1098_box5
                        if f1098_box6:
                            form_data['f1098_box6_points_paid'] = f1098_box6
                        if f1098_box8:
                            form_data['f1098_box8_property_address'] = f1098_box8
                        if f1098_box9:
                            form_data['f1098_box9_num_properties'] = f1098_box9
                        if f1098_box10:
                            form_data['f1098_box10_other'] = f1098_box10
                        if f1098_box11:
                            form_data['f1098_box11_acquisition_date'] = f1098_box11

                    if existing_form:
                        # Update existing form
                        form_result = self.client.table('forms_1099').update(form_data).eq('id', existing_form[0]['id']).execute()
                        result['forms_created'].append(form_result.data[0])
                    else:
                        # Create new form
                        form_data['filer_id'] = filer_id
                        form_data['recipient_id'] = recipient_id
                        form_data['operating_year_id'] = operating_year_id
                        form_data['form_type'] = form_type
                        form_result = self.client.table('forms_1099').insert(form_data).execute()
                        result['forms_created'].append(form_result.data[0])

                    result['imported_rows'] += 1

            except Exception as e:
                result['errors'].append(f"Error processing sheet '{sheet_name}': {str(e)}")

        log_activity(
            action='quick_import',
            entity_type='import',
            entity_id=result['filer_id'],
            filer_id=result['filer_id'],
            operating_year_id=operating_year_id,
            details={
                'filename': filename,
                'forms_created': len(result['forms_created']),
                'recipients_created': result['recipients_created'],
                'total_rows': result['total_rows'],
                'imported_rows': result['imported_rows'],
                'errors': len(result['row_errors'])
            }
        )

        return result

    def import_workbook(
        self,
        file_content: bytes,
        filename: str,
        operating_year_id: str,
        sheet_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Full import workflow for a workbook (single sheet):
        1. Parse filer info from 'Filer Information' sheet
        2. Create/update filer in database
        3. Parse recipient data from specified sheet (or first data sheet)
        4. Create import batch linked to filer

        Returns dict with filer_id, filer_data, batch_id, sheet_name, row_count
        """
        result: Dict[str, Any] = {
            'filer_id': None,
            'filer_data': None,
            'filer_created': False,
            'batch_id': None,
            'sheet_name': None,
            'row_count': 0,
            'errors': []
        }

        # Step 1: Parse filer information
        filer_data = self.parse_filer_info(file_content, filename)
        result['filer_data'] = filer_data

        # Step 2: Create/update filer
        if filer_data:
            # Check if filer existed before
            existing = self.client.table('filers').select('id').eq('tin', filer_data.get('tin', '')).execute()
            result['filer_created'] = len(existing.data) == 0

            filer_id = self.find_or_create_filer(filer_data)
            result['filer_id'] = filer_id
        else:
            result['errors'].append("No filer information found in workbook")

        # Step 3: Determine which sheet to import
        sheets = self.get_sheet_names(file_content, filename)
        data_sheets = [s for s in sheets if s != 'Filer Information']

        if sheet_name and sheet_name in sheets:
            target_sheet = sheet_name
        elif data_sheets:
            # Default to first data sheet (usually 1099-NEC)
            target_sheet = data_sheets[0]
        else:
            result['errors'].append("No data sheets found in workbook")
            return result

        result['sheet_name'] = target_sheet

        # Step 4: Parse the data sheet
        try:
            df = self.parse_file(file_content, filename, sheet_name=target_sheet)
            result['row_count'] = len(df)

            # Step 5: Create batch
            batch = self.create_batch(
                operating_year_id=operating_year_id,
                filename=filename,
                file_content=file_content,
                filer_id=result['filer_id']
            )
            result['batch_id'] = batch['id'] if batch else None

            # Step 6: Store raw rows
            if batch:
                self.store_raw_rows(batch['id'], df)

        except Exception as e:
            result['errors'].append(f"Error parsing data sheet: {str(e)}")

        return result

    def store_raw_rows(self, batch_id: str, df: pd.DataFrame) -> int:
        """Store raw rows from DataFrame into import_rows."""
        rows_to_insert = []

        for idx, row in df.iterrows():
            raw_data = row.to_dict()
            # Convert NaN to None for JSON
            raw_data = {k: (None if pd.isna(v) else v) for k, v in raw_data.items()}

            rows_to_insert.append({
                'batch_id': batch_id,
                'row_number': idx + 2,  # +2 for header row and 0-index
                'raw_data': raw_data,
                'status': 'pending'
            })

        # Insert in batches of 100
        for i in range(0, len(rows_to_insert), 100):
            batch = rows_to_insert[i:i+100]
            self.client.table('import_rows').insert(batch).execute()

        # Update batch total
        self.client.table('import_batches').update({
            'total_rows': len(rows_to_insert)
        }).eq('id', batch_id).execute()

        return len(rows_to_insert)

    def apply_column_mapping(self, batch_id: str, mapping: Dict[str, str]) -> None:
        """Apply column mapping to a batch."""
        self.client.table('import_batches').update({
            'column_mapping': mapping,
            'status': 'mapping'
        }).eq('id', batch_id).execute()

    def normalize_batch(self, batch_id: str) -> Dict[str, int]:
        """
        Normalize all rows in a batch.

        Returns: {'valid': n, 'errors': n, 'warnings': n}
        """
        # Get batch with mapping
        batch = self.client.table('import_batches').select('*').eq('id', batch_id).single().execute().data
        mapping = batch.get('column_mapping', {})

        if not mapping:
            raise ValueError("Column mapping not set for batch")

        # Reverse mapping for lookup
        reverse_map = {v: k for k, v in mapping.items()}

        # Get all rows
        rows = self.client.table('import_rows').select('*').eq('batch_id', batch_id).execute().data

        stats = {'valid': 0, 'errors': 0, 'warnings': 0}

        for row in rows:
            raw = row['raw_data']
            normalized: Dict[str, Any] = {}
            all_errors: List[dict] = []

            # Extract and normalize each field
            def get_raw(field):
                source_col = reverse_map.get(field)
                return raw.get(source_col) if source_col else None

            # Name (Line 1)
            val, errs = normalize_name(get_raw('recipient_name'))
            normalized['recipient_name'] = val
            all_errors.extend(errs)

            # Name Line 2 (optional, also needs IRS sanitization)
            name2_raw = get_raw('recipient_name_line2')
            if name2_raw and not pd.isna(name2_raw):
                val, errs = normalize_name(name2_raw)
                normalized['recipient_name_line2'] = val
                all_errors.extend([{**e, 'field': 'recipient_name_line2'} for e in errs])

            # TIN
            val, tin_type, errs = normalize_tin(get_raw('recipient_tin'))
            normalized['recipient_tin'] = val
            normalized['recipient_tin_type'] = tin_type
            all_errors.extend(errs)

            # Address
            val, errs = normalize_address(get_raw('recipient_address1'))
            normalized['recipient_address1'] = val
            all_errors.extend([{**e, 'field': 'recipient_address1'} for e in errs])

            val, errs = normalize_address(get_raw('recipient_address2'))
            normalized['recipient_address2'] = val
            all_errors.extend([{**e, 'field': 'recipient_address2'} for e in errs])

            # City/State/ZIP
            val, errs = normalize_city(get_raw('recipient_city'))
            normalized['recipient_city'] = val
            all_errors.extend(errs)

            val, errs = normalize_state(get_raw('recipient_state'))
            normalized['recipient_state'] = val
            all_errors.extend(errs)

            val, errs = normalize_zip(get_raw('recipient_zip'))
            normalized['recipient_zip'] = val
            all_errors.extend(errs)

            # Amounts - NEC
            amount_val, errs = normalize_amount(get_raw('nec_box1'), 'nec_box1')
            normalized['nec_box1'] = amount_val
            all_errors.extend(errs)

            amount_val, errs = normalize_amount(get_raw('nec_box4'), 'nec_box4')
            normalized['nec_box4'] = amount_val
            all_errors.extend(errs)

            # Amounts - MISC
            for box in ['misc_box1', 'misc_box2', 'misc_box3', 'misc_box4', 'misc_box5',
                       'misc_box6', 'misc_box8', 'misc_box9', 'misc_box10', 'misc_box11',
                       'misc_box12', 'misc_box14']:
                amount_val, errs = normalize_amount(get_raw(box), box)
                normalized[box] = amount_val
                all_errors.extend(errs)

            # 1099-S fields
            date_val, errs = normalize_date(get_raw('s_box1_date_closing'), 's_box1_date_closing')
            normalized['s_box1_date_closing'] = date_val
            all_errors.extend(errs)

            amount_val, errs = normalize_amount(get_raw('s_box2_gross_proceeds'), 's_box2_gross_proceeds')
            normalized['s_box2_gross_proceeds'] = amount_val
            all_errors.extend(errs)

            # Property address is just text
            prop_addr = get_raw('s_box3_property_address')
            if prop_addr and not pd.isna(prop_addr):
                normalized['s_box3_property_address'] = str(prop_addr).strip()

            bool_val, errs = normalize_boolean(get_raw('s_box4_property_services'), 's_box4_property_services')
            normalized['s_box4_property_services'] = bool_val
            all_errors.extend(errs)

            bool_val, errs = normalize_boolean(get_raw('s_box5_foreign_person'), 's_box5_foreign_person')
            normalized['s_box5_foreign_person'] = bool_val
            all_errors.extend(errs)

            amount_val, errs = normalize_amount(get_raw('s_box6_buyers_tax'), 's_box6_buyers_tax')
            normalized['s_box6_buyers_tax'] = amount_val
            all_errors.extend(errs)

            # 1098 fields
            amount_val, errs = normalize_amount(get_raw('f1098_box1_mortgage_interest'), 'f1098_box1_mortgage_interest')
            normalized['f1098_box1_mortgage_interest'] = amount_val
            all_errors.extend(errs)

            amount_val, errs = normalize_amount(get_raw('f1098_box2_outstanding_principal'), 'f1098_box2_outstanding_principal')
            normalized['f1098_box2_outstanding_principal'] = amount_val
            all_errors.extend(errs)

            date_val, errs = normalize_date(get_raw('f1098_box3_origination_date'), 'f1098_box3_origination_date')
            normalized['f1098_box3_origination_date'] = date_val
            all_errors.extend(errs)

            amount_val, errs = normalize_amount(get_raw('f1098_box4_refund_interest'), 'f1098_box4_refund_interest')
            normalized['f1098_box4_refund_interest'] = amount_val
            all_errors.extend(errs)

            amount_val, errs = normalize_amount(get_raw('f1098_box5_mortgage_insurance'), 'f1098_box5_mortgage_insurance')
            normalized['f1098_box5_mortgage_insurance'] = amount_val
            all_errors.extend(errs)

            amount_val, errs = normalize_amount(get_raw('f1098_box6_points_paid'), 'f1098_box6_points_paid')
            normalized['f1098_box6_points_paid'] = amount_val
            all_errors.extend(errs)

            prop_addr = get_raw('f1098_box8_property_address')
            if prop_addr and not pd.isna(prop_addr):
                normalized['f1098_box8_property_address'] = str(prop_addr).strip()

            num_props = get_raw('f1098_box9_num_properties')
            if num_props and not pd.isna(num_props):
                try:
                    normalized['f1098_box9_num_properties'] = int(float(num_props))
                except:
                    pass

            amount_val, errs = normalize_amount(get_raw('f1098_box10_other'), 'f1098_box10_other')
            normalized['f1098_box10_other'] = amount_val
            all_errors.extend(errs)

            date_val, errs = normalize_date(get_raw('f1098_box11_acquisition_date'), 'f1098_box11_acquisition_date')
            normalized['f1098_box11_acquisition_date'] = date_val
            all_errors.extend(errs)

            # Detect form type based on data
            if normalized.get('nec_box1'):
                normalized['form_type'] = '1099-NEC'
            elif any(normalized.get(f'misc_box{i}') for i in [1,2,3,4,5,6,8,9,10,11,12,14]):
                normalized['form_type'] = '1099-MISC'
            elif normalized.get('s_box2_gross_proceeds') or normalized.get('s_box1_date_closing'):
                normalized['form_type'] = '1099-S'
            elif normalized.get('f1098_box1_mortgage_interest') or normalized.get('f1098_box2_outstanding_principal'):
                normalized['form_type'] = '1098'
            else:
                normalized['form_type'] = '1099-NEC'  # Default

            # Determine status
            has_errors = any(e['severity'] == 'error' for e in all_errors)
            has_warnings = any(e['severity'] == 'warning' for e in all_errors)

            if has_errors:
                status = 'error'
                stats['errors'] += 1
            elif has_warnings:
                status = 'warning'
                stats['warnings'] += 1
            else:
                status = 'valid'
                stats['valid'] += 1

            # Update row
            update_data = {
                'status': status,
                'validation_errors': all_errors if all_errors else None,
                **{k: v for k, v in normalized.items() if v is not None}
            }

            self.client.table('import_rows').update(update_data).eq('id', row['id']).execute()

        # Update batch status and counts
        self.client.table('import_batches').update({
            'status': 'validated',
            'valid_rows': stats['valid'],
            'error_rows': stats['errors'],
            'warning_rows': stats['warnings'],
            'validated_at': datetime.utcnow().isoformat()
        }).eq('id', batch_id).execute()

        log_activity(
            action='import_batch_validated',
            entity_type='import_batch',
            entity_id=batch_id,
            details=stats
        )

        return stats

    def get_batch(self, batch_id: str) -> dict:
        """Get batch details."""
        return self.client.table('import_batches').select('*').eq('id', batch_id).single().execute().data

    def get_batch_rows(
        self,
        batch_id: str,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[dict]:
        """Get rows for a batch with optional filtering."""
        query = self.client.table('import_rows').select('*').eq('batch_id', batch_id)

        if status:
            query = query.eq('status', status)

        query = query.order('row_number').range(offset, offset + limit - 1)
        return query.execute().data

    def update_row(self, row_id: str, updates: dict) -> dict:
        """Update a single import row."""
        return self.client.table('import_rows').update(updates).eq('id', row_id).execute().data[0]

    def promote_batch(self, batch_id: str, filer_id: str) -> Dict[str, int]:
        """
        Promote valid rows to canonical recipients and forms tables.

        Returns: {'recipients_created': n, 'forms_created': n, 'skipped': n}
        """
        batch = self.get_batch(batch_id)
        operating_year_id = batch['operating_year_id']

        # Get valid rows only
        rows = self.client.table('import_rows').select('*').eq('batch_id', batch_id).eq('status', 'valid').execute().data

        stats = {'recipients_created': 0, 'forms_created': 0, 'skipped': 0}

        for row in rows:
            try:
                # Check if recipient already exists (by TIN)
                existing = self.client.table('recipients').select('id').eq('filer_id', filer_id).eq('tin', row['recipient_tin']).execute().data

                if existing:
                    recipient_id = existing[0]['id']
                else:
                    # Create recipient
                    recipient_data = {
                        'filer_id': filer_id,
                        'name': row['recipient_name'],
                        'name_line_2': row.get('recipient_name_line2'),
                        'tin': row['recipient_tin'],
                        'tin_type': row.get('recipient_tin_type', 'SSN'),
                        'address1': row['recipient_address1'],
                        'address2': row.get('recipient_address2'),
                        'city': row['recipient_city'],
                        'state': row['recipient_state'],
                        'zip': row['recipient_zip'],
                        'account_number': row.get('account_number'),
                    }
                    result = self.client.table('recipients').insert(recipient_data).execute()
                    recipient_id = result.data[0]['id']
                    stats['recipients_created'] += 1

                # Create form
                form_data = {
                    'filer_id': filer_id,
                    'recipient_id': recipient_id,
                    'operating_year_id': operating_year_id,
                    'form_type': row.get('form_type', '1099-NEC'),
                    'status': 'draft',
                    # NEC fields
                    'nec_box1': row.get('nec_box1'),
                    'nec_box4': row.get('nec_box4'),
                    # MISC fields
                    'misc_box1': row.get('misc_box1'),
                    'misc_box2': row.get('misc_box2'),
                    'misc_box3': row.get('misc_box3'),
                    'misc_box4': row.get('misc_box4'),
                    'misc_box5': row.get('misc_box5'),
                    'misc_box6': row.get('misc_box6'),
                    'misc_box8': row.get('misc_box8'),
                    'misc_box9': row.get('misc_box9'),
                    'misc_box10': row.get('misc_box10'),
                    'misc_box11': row.get('misc_box11'),
                    'misc_box12': row.get('misc_box12'),
                    'misc_box14': row.get('misc_box14'),
                    # 1099-S fields
                    's_box1_date_closing': row.get('s_box1_date_closing'),
                    's_box2_gross_proceeds': row.get('s_box2_gross_proceeds'),
                    's_box3_property_address': row.get('s_box3_property_address'),
                    's_box4_property_services': row.get('s_box4_property_services'),
                    's_box5_foreign_person': row.get('s_box5_foreign_person'),
                    's_box6_buyers_tax': row.get('s_box6_buyers_tax'),
                    # 1098 fields
                    'f1098_box1_mortgage_interest': row.get('f1098_box1_mortgage_interest'),
                    'f1098_box2_outstanding_principal': row.get('f1098_box2_outstanding_principal'),
                    'f1098_box3_origination_date': row.get('f1098_box3_origination_date'),
                    'f1098_box4_refund_interest': row.get('f1098_box4_refund_interest'),
                    'f1098_box5_mortgage_insurance': row.get('f1098_box5_mortgage_insurance'),
                    'f1098_box6_points_paid': row.get('f1098_box6_points_paid'),
                    'f1098_box8_property_address': row.get('f1098_box8_property_address'),
                    'f1098_box9_num_properties': row.get('f1098_box9_num_properties'),
                    'f1098_box10_other': row.get('f1098_box10_other'),
                    'f1098_box11_acquisition_date': row.get('f1098_box11_acquisition_date'),
                    # State fields
                    'state1_code': row.get('state1_code'),
                    'state1_id': row.get('state1_id'),
                    'state1_income': row.get('state1_income'),
                    'state1_withheld': row.get('state1_withheld'),
                }
                # Remove None values
                form_data = {k: v for k, v in form_data.items() if v is not None}

                result = self.client.table('forms_1099').insert(form_data).execute()
                form_id = result.data[0]['id']
                stats['forms_created'] += 1

                # Update import row with promoted IDs
                self.client.table('import_rows').update({
                    'promoted_recipient_id': recipient_id,
                    'promoted_form_id': form_id,
                    'status': 'promoted'
                }).eq('id', row['id']).execute()

            except Exception as e:
                stats['skipped'] += 1
                # Log error but continue
                self.client.table('import_rows').update({
                    'validation_errors': [{'field': 'promotion', 'code': 'PROMOTE_FAILED',
                                          'message': str(e), 'severity': 'error'}]
                }).eq('id', row['id']).execute()

        # Update batch status
        self.client.table('import_batches').update({
            'status': 'promoted',
            'filer_id': filer_id,
            'promoted_at': datetime.utcnow().isoformat()
        }).eq('id', batch_id).execute()

        log_activity(
            action='import_batch_promoted',
            entity_type='import_batch',
            entity_id=batch_id,
            filer_id=filer_id,
            operating_year_id=operating_year_id,
            details=stats
        )

        return stats
