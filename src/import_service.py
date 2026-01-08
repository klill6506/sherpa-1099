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
from typing import Optional, List, Dict, Any, Tuple
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

FORM_TYPES = ['1099-NEC', '1099-MISC', '1099-DIV', '1099-INT', '1099-B', '1099-R', '1098']


# =============================================================================
# NORMALIZATION FUNCTIONS
# =============================================================================

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
    errors = []
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
    errors = []
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
    """Normalize payee name."""
    errors = []
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None, [{'field': 'recipient_name', 'code': 'MISSING_NAME',
                      'message': 'Recipient name is required', 'severity': 'error'}]

    name_str = str(name).strip()

    # Remove extra whitespace
    name_str = ' '.join(name_str.split())

    # Remove problematic characters (keep letters, numbers, common punctuation)
    name_str = re.sub(r'[^\w\s\.\,\-\'\&\/\(\)]', '', name_str)

    # Truncate to IRS limit (40 chars for name control purposes)
    if len(name_str) > 40:
        errors.append({'field': 'recipient_name', 'code': 'NAME_TRUNCATED',
                      'message': f'Name truncated from {len(name_str)} to 40 chars',
                      'severity': 'warning'})
        name_str = name_str[:40]

    if len(name_str) < 1:
        return None, [{'field': 'recipient_name', 'code': 'MISSING_NAME',
                      'message': 'Recipient name is required', 'severity': 'error'}]

    return name_str, errors


def normalize_address(address: Any) -> Tuple[Optional[str], List[dict]]:
    """Normalize address line."""
    errors = []
    if address is None or (isinstance(address, float) and pd.isna(address)):
        return None, []

    addr_str = str(address).strip()
    addr_str = ' '.join(addr_str.split())
    addr_str = re.sub(r'[^\w\s\.\,\-\#\/]', '', addr_str)

    if len(addr_str) > 40:
        errors.append({'field': 'address', 'code': 'ADDRESS_TRUNCATED',
                      'message': f'Address truncated from {len(addr_str)} to 40 chars',
                      'severity': 'warning'})
        addr_str = addr_str[:40]

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
    errors = []
    if city is None or (isinstance(city, float) and pd.isna(city)):
        return None, [{'field': 'recipient_city', 'code': 'MISSING_CITY',
                      'message': 'City is required', 'severity': 'error'}]

    city_str = str(city).strip()
    city_str = ' '.join(city_str.split())
    city_str = re.sub(r'[^\w\s\.\-\']', '', city_str)

    if len(city_str) > 25:
        city_str = city_str[:25]

    return city_str if city_str else None, errors


# =============================================================================
# COLUMN MAPPING
# =============================================================================

def get_column_aliases() -> Dict[str, List[str]]:
    """Load column aliases from database."""
    client = get_supabase_client()
    response = client.table("column_aliases").select("*").order("priority", desc=True).execute()

    aliases = {}
    for row in response.data:
        target = row['target_field']
        alias = row['alias'].lower()
        if target not in aliases:
            aliases[target] = []
        aliases[target].append(alias)

    return aliases


def auto_map_columns(df_columns: List[str], aliases: Dict[str, List[str]] = None) -> Dict[str, str]:
    """
    Auto-detect column mapping based on aliases.

    Returns: {source_column: target_field}
    """
    if aliases is None:
        aliases = get_column_aliases()

    mapping = {}
    df_cols_lower = {col.lower().strip(): col for col in df_columns}

    for target_field, alias_list in aliases.items():
        for alias in alias_list:
            if alias in df_cols_lower:
                source_col = df_cols_lower[alias]
                if source_col not in mapping:  # Don't overwrite
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
            if 'Filer Information' not in xl.sheet_names:
                return None

            df = pd.read_excel(xl, sheet_name='Filer Information', header=None, dtype=str)

            # Parse the label/value pairs
            # The sheet has labels in column 0 and values in column 1
            filer_data = {}

            for idx, row in df.iterrows():
                label = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
                value = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else None

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

            # Normalize state and zip
            if filer_data.get('state'):
                state_normalized, _ = normalize_state(filer_data['state'])
                filer_data['state'] = state_normalized

            if filer_data.get('zip'):
                zip_normalized, _ = normalize_zip(filer_data['zip'])
                filer_data['zip'] = zip_normalized

            return filer_data if filer_data.get('name') else None

        except Exception as e:
            print(f"Error parsing filer info: {e}")
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
        filer_id: str = None
    ) -> dict:
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

    def parse_file(self, file_content: bytes, filename: str, sheet_name: str = None) -> pd.DataFrame:
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

    def import_workbook(
        self,
        file_content: bytes,
        filename: str,
        operating_year_id: str,
        sheet_name: str = None
    ) -> Dict[str, Any]:
        """
        Full import workflow for a workbook:
        1. Parse filer info from 'Filer Information' sheet
        2. Create/update filer in database
        3. Parse recipient data from specified sheet (or first data sheet)
        4. Create import batch linked to filer

        Returns dict with filer_id, filer_data, batch_id, sheet_name, row_count
        """
        result = {
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
            normalized = {}
            all_errors = []

            # Extract and normalize each field
            def get_raw(field):
                source_col = reverse_map.get(field)
                return raw.get(source_col) if source_col else None

            # Name
            val, errs = normalize_name(get_raw('recipient_name'))
            normalized['recipient_name'] = val
            all_errors.extend(errs)

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
            val, errs = normalize_amount(get_raw('nec_box1'), 'nec_box1')
            normalized['nec_box1'] = val
            all_errors.extend(errs)

            val, errs = normalize_amount(get_raw('nec_box4'), 'nec_box4')
            normalized['nec_box4'] = val
            all_errors.extend(errs)

            # Amounts - MISC
            for box in ['misc_box1', 'misc_box2', 'misc_box3', 'misc_box4', 'misc_box5',
                       'misc_box6', 'misc_box8', 'misc_box9', 'misc_box10', 'misc_box11',
                       'misc_box12', 'misc_box14']:
                val, errs = normalize_amount(get_raw(box), box)
                normalized[box] = val
                all_errors.extend(errs)

            # Detect form type
            if normalized.get('nec_box1'):
                normalized['form_type'] = '1099-NEC'
            elif any(normalized.get(f'misc_box{i}') for i in [1,2,3,4,5,6,8,9,10,11,12,14]):
                normalized['form_type'] = '1099-MISC'
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
        status: str = None,
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
                    'nec_box1': row.get('nec_box1'),
                    'nec_box4': row.get('nec_box4'),
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
