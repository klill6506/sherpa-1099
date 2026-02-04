"""
1099-NEC PDF Generator - Official Template Overlay Approach.

Generates IRS Form 1099-NEC Copy B by overlaying data onto the official IRS template.
This produces forms that match the official IRS layout exactly.

Template: 1099-NEC_template_blank.pdf (Official IRS Form 1099-NEC Rev. April 2025)
"""

import io
import json
import os
import sys
from pathlib import Path
from typing import Optional, cast
from decimal import Decimal
from contextlib import contextmanager

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black

# Suppress MuPDF warnings at module load time (before any fitz.open calls)
import fitz
fitz.TOOLS.mupdf_warnings(False)


@contextmanager
def suppress_stderr():
    """Temporarily suppress stderr output (for MuPDF C-level errors)."""
    # Save the original stderr
    original_stderr = sys.stderr
    # Redirect stderr to devnull
    sys.stderr = open(os.devnull, 'w')
    try:
        yield
    finally:
        sys.stderr.close()
        sys.stderr = original_stderr


PAGE_W, PAGE_H = letter  # 612 x 792 points

# Template and config paths (relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "New Official 1099-NEC.pdf"
CONFIG_PATH = PROJECT_ROOT / "config" / "1099_nec_2025_copyb.json"


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load NEC coordinate configuration from JSON file."""
    path = config_path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"NEC config not found: {path}")
    with open(path, "r") as f:
        return json.load(f)


def fitz_to_rl_y(y_fitz: float) -> float:
    """Convert y-down coordinate (from top) to reportlab y (from bottom)."""
    return PAGE_H - y_fitz


def format_money(amount: Optional[Decimal]) -> str:
    """Format amount as money string with commas and 2 decimals."""
    if amount is None or amount == 0:
        return ""
    return f"{float(amount):,.2f}"


def format_phone(phone: str) -> str:
    """
    Format phone number with hyphens if needed.

    Examples:
        "7063531711"    -> "706-353-1711"
        "706-353-1711"  -> "706-353-1711" (already formatted)
        "(706) 353-1711" -> "(706) 353-1711" (already formatted)
        "353-1711"      -> "353-1711" (7 digits, local)
        ""              -> ""
    """
    if not phone:
        return ""

    # If it already has formatting (hyphens, parens, spaces), return as-is
    if '-' in phone or '(' in phone or ' ' in phone:
        return phone

    # Extract digits only
    digits = ''.join(c for c in phone if c.isdigit())

    if len(digits) == 10:
        # Standard US format: XXX-XXX-XXXX
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    elif len(digits) == 7:
        # Local format: XXX-XXXX
        return f"{digits[:3]}-{digits[3:]}"
    elif len(digits) == 11 and digits[0] == '1':
        # With country code: 1-XXX-XXX-XXXX
        return f"1-{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    else:
        # Unknown format, return original
        return phone


def mask_tin(tin: str) -> str:
    """
    Mask a TIN for Copy B (recipient copy), showing only last 4 digits.

    Examples:
        "123-45-6789" -> "***-**-6789"
        "12-3456789"  -> "**-***6789"
        "123456789"   -> "*****6789"
    """
    if not tin:
        return ""

    # Remove all non-alphanumeric characters to get raw digits
    digits_only = ''.join(c for c in tin if c.isalnum())

    if len(digits_only) < 4:
        return tin  # Too short to mask

    # Get last 4 digits
    last_4 = digits_only[-4:]

    # Rebuild with same format but masked
    # SSN format: XXX-XX-XXXX -> ***-**-XXXX
    if '-' in tin:
        parts = tin.split('-')
        if len(parts) == 3 and len(parts[0]) == 3 and len(parts[1]) == 2:
            # SSN format
            return f"***-**-{last_4}"
        elif len(parts) == 2 and len(parts[0]) == 2:
            # EIN format: XX-XXXXXXX -> **-***XXXX
            return f"**-***{last_4}"

    # Default: just mask all but last 4
    masked_len = len(digits_only) - 4
    return '*' * masked_len + last_4


def create_overlay(
    coords: dict,
    payer_name: str,
    payer_line2: str = "",
    payer_street: str = "",
    payer_city_state_zip: str = "",
    payer_tin: str = "",
    payer_phone: str = "",
    recipient_name: str = "",
    recipient_line2: str = "",
    recipient_street: str = "",
    recipient_city_state_zip: str = "",
    recipient_tin: str = "",
    account_number: str = "",
    box1_amount: Decimal = Decimal("0"),
    box3_amount: Decimal = Decimal("0"),
    box4_amount: Decimal = Decimal("0"),
    box5_amount: Decimal = Decimal("0"),
    box6_state: str = "",
    box7_amount: Decimal = Decimal("0"),
    corrected: bool = False,
) -> bytes:
    """Create the overlay PDF with form data."""
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)

    def draw_text(key: str, text: str):
        if not text or key not in coords:
            return
        info = coords[key]
        font = info.get("font", "Helvetica")
        size = info.get("size", 10)
        c.setFont(font, size)
        c.setFillColor(black)

        x = info["x"]
        y = fitz_to_rl_y(cast(float, info["y"]))

        if info.get("align") == "right":
            c.drawRightString(x, y, str(text))
        else:
            c.drawString(x, y, str(text))

    # Draw labels
    draw_text("payer_label", "PAYER'S name, street address, city, state, ZIP code, and telephone no.")
    draw_text("recipient_label", "RECIPIENT'S name, street address, city, state, and ZIP code")

    # Draw payer info
    draw_text("payer_name", payer_name)
    draw_text("payer_line2", payer_line2)
    draw_text("payer_street", payer_street)
    draw_text("payer_city_state_zip", payer_city_state_zip)
    draw_text("payer_phone", format_phone(payer_phone))

    # Draw TINs
    draw_text("payer_tin", payer_tin)
    draw_text("recipient_tin", recipient_tin)

    # Draw recipient info
    draw_text("recipient_name", recipient_name)
    draw_text("recipient_line2", recipient_line2)
    draw_text("recipient_street", recipient_street)
    draw_text("recipient_city_state_zip", recipient_city_state_zip)

    # Draw account number
    draw_text("account_number", account_number)

    # Draw amounts
    draw_text("box1_amount", format_money(box1_amount))
    draw_text("box3_amount", format_money(box3_amount))
    draw_text("box4_amount", format_money(box4_amount))
    draw_text("box5_amount", format_money(box5_amount))
    # Only draw box6_state if it has a real value (not None or empty)
    if box6_state and box6_state != "None":
        draw_text("box6_state", box6_state)
    draw_text("box7_amount", format_money(box7_amount))

    # Draw CORRECTED checkbox if needed
    if corrected:
        draw_text("corrected_x", "X")

    c.showPage()
    c.save()
    packet.seek(0)
    return packet.getvalue()


def merge_overlay_with_template(template_path: Path, overlay_bytes: bytes) -> bytes:
    """Merge overlay PDF onto template PDF and remove barcode by redaction.

    Uses PyMuPDF exclusively for efficient merging without resource duplication.
    """
    # Open template with stderr suppressed to hide MuPDF xref errors
    with suppress_stderr():
        template_doc = fitz.open(str(template_path))
    overlay_doc = fitz.open(stream=overlay_bytes, filetype="pdf")

    template_page = template_doc[0]

    # Overlay the text onto the template using show_pdf_page
    # This is more efficient than pypdf merge as it doesn't duplicate resources
    template_page.show_pdf_page(
        template_page.rect,  # Full page
        overlay_doc,
        0,  # Page number
        overlay=True,  # Place on top
    )

    # Barcode location (measured from user):
    # - Right side: 0.5 inches from right edge
    # - Left side: 2 inches from right edge
    # - Bottom: 0.75 inches from bottom
    # - Top: 1.75 inches from bottom
    # Convert to points (72 points = 1 inch)
    page_height = template_page.rect.height
    barcode_rect = fitz.Rect(
        468,                        # left (612 - 2*72 = 468)
        page_height - 126,          # top (page_height - 1.75*72)
        576,                        # right (612 - 0.5*72 = 576)
        page_height - 54            # bottom (page_height - 0.75*72)
    )

    # Add redaction annotation and apply it (fills with white)
    template_page.add_redact_annot(barcode_rect, fill=(1, 1, 1))  # White fill
    template_page.apply_redactions()

    # Save with optimization - garbage collection and compression
    output = io.BytesIO()
    template_doc.save(
        output,
        garbage=4,      # Maximum garbage collection
        deflate=True,   # Compress streams
        clean=True,     # Clean content streams
    )
    template_doc.close()
    overlay_doc.close()
    output.seek(0)
    return output.getvalue()


def generate_1099_nec_overlay(
    payer_name: str,
    payer_address_lines: list,
    payer_tin: str,
    recipient_name: str,
    recipient_address_lines: list,
    recipient_tin: str,
    payer_phone: str = "",
    payer_line2: str = "",
    recipient_account: str = "",
    tax_year: int = 2025,
    box1_compensation: Decimal = Decimal("0"),
    box3_golden_parachute: Decimal = Decimal("0"),
    box4_federal_withheld: Decimal = Decimal("0"),
    box5_state_withheld: Decimal = Decimal("0"),
    box6_state_payer_no: str = "",
    box7_state_income: Decimal = Decimal("0"),
    corrected: bool = False,
    template_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    mask_recipient_tin: bool = True,
) -> bytes:
    """
    Generate 1099-NEC PDF using official IRS template overlay.

    Args:
        payer_name: Payer/Filer name
        payer_address_lines: List of address lines [street, city_state_zip]
        payer_tin: Payer's TIN (formatted)
        recipient_name: Recipient name
        recipient_address_lines: List of address lines [street, city_state_zip]
        recipient_tin: Recipient's TIN (formatted)
        payer_phone: Optional phone number
        recipient_account: Optional account number
        tax_year: Tax year (for template selection)
        box1_compensation: Nonemployee compensation amount
        box3_golden_parachute: Excess golden parachute payments
        box4_federal_withheld: Federal income tax withheld
        box5_state_withheld: State tax withheld
        box6_state_payer_no: State/Payer's state no.
        box7_state_income: State income
        corrected: Whether this is a corrected form
        template_path: Optional custom template path
        config_path: Optional custom config path
        mask_recipient_tin: Mask recipient TIN showing only last 4 digits (default True for Copy B)

    Returns:
        PDF as bytes
    """
    # Load config
    config = load_config(config_path)
    coords = config.get("coords", {})

    # Use provided template or default
    if template_path is None:
        template_path = TEMPLATE_PATH

    if not template_path.exists():
        raise FileNotFoundError(f"NEC template not found: {template_path}")

    # Build address strings
    payer_street = payer_address_lines[0] if len(payer_address_lines) > 0 else ""
    payer_city_state_zip = payer_address_lines[1] if len(payer_address_lines) > 1 else ""

    # Handle recipient address - may have name_line_2, street, and city_state_zip
    # The template has separate fields for each line
    recipient_line2 = ""
    if len(recipient_address_lines) == 1:
        # Only city/state/zip
        recipient_street = ""
        recipient_city_state_zip = recipient_address_lines[0]
    elif len(recipient_address_lines) == 2:
        # Street and city/state/zip
        recipient_street = recipient_address_lines[0]
        recipient_city_state_zip = recipient_address_lines[1]
    elif len(recipient_address_lines) >= 3:
        # Name line 2, street, city/state/zip - each on its own line
        recipient_line2 = recipient_address_lines[0]
        recipient_street = recipient_address_lines[1]
        recipient_city_state_zip = recipient_address_lines[2]
    else:
        recipient_street = ""
        recipient_city_state_zip = ""

    # Mask recipient TIN if requested (default for Copy B)
    display_recipient_tin = mask_tin(recipient_tin) if mask_recipient_tin else recipient_tin

    # Create overlay
    overlay_bytes = create_overlay(
        coords=coords,
        payer_name=payer_name,
        payer_line2=payer_line2,
        payer_street=payer_street,
        payer_city_state_zip=payer_city_state_zip,
        payer_tin=payer_tin,
        payer_phone=payer_phone,
        recipient_name=recipient_name,
        recipient_line2=recipient_line2,
        recipient_street=recipient_street,
        recipient_city_state_zip=recipient_city_state_zip,
        recipient_tin=display_recipient_tin,
        account_number=recipient_account,
        box1_amount=box1_compensation,
        box3_amount=box3_golden_parachute,
        box4_amount=box4_federal_withheld,
        box5_amount=box5_state_withheld,
        box6_state=box6_state_payer_no,
        box7_amount=box7_state_income,
        corrected=corrected,
    )

    # Merge with template
    return merge_overlay_with_template(template_path, overlay_bytes)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    # Test with sample data matching test_2025_v11.pdf
    pdf_bytes = generate_1099_nec_overlay(
        payer_name="Euguene Baldwin",
        payer_address_lines=[
            "280 High Ridge Dr",
            "Athens, GA 30606"
        ],
        payer_tin="58-1234567",
        payer_phone="",
        recipient_name="Arnolds Home Healthcare LLC",
        recipient_address_lines=[
            "Patricia Arnold",
            "875 Belmont Rd",
            "Athens, GA 30605"
        ],
        recipient_tin="123-45-6789",
        recipient_account="ACCT-2025-001234",
        tax_year=2025,
        box1_compensation=Decimal("15750.00"),
    )

    output_path = Path(__file__).parent.parent / "test_overlay_output.pdf"
    output_path.write_bytes(pdf_bytes)
    print(f"Generated {output_path} ({len(pdf_bytes)} bytes)")
