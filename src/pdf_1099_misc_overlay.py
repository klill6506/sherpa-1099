"""
1099-MISC PDF Generator - Official Template Overlay Approach.

Generates IRS Form 1099-MISC Copy B by overlaying data onto the official IRS template.
This produces forms that match the official IRS layout exactly.

Template: 1099-Misc Official 2025.pdf (Official IRS Form 1099-MISC Rev. 2025)

NOTE: This module is separate from the NEC generator to avoid any risk of
changing NEC output. They share similar patterns but are maintained independently.
"""

import io
import json
from pathlib import Path
from typing import Optional, cast
from decimal import Decimal

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black


PAGE_W, PAGE_H = letter  # 612 x 792 points

# Template and config paths (relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "1099-Misc Official 2025.pdf"
CONFIG_PATH = PROJECT_ROOT / "config" / "1099_misc_2025_copyb.json"


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load MISC coordinate configuration from JSON file."""
    path = config_path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"MISC config not found: {path}")
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
    payer_street: str,
    payer_city_state_zip: str,
    payer_tin: str,
    payer_phone: str = "",
    recipient_name: str = "",
    recipient_line2: str = "",
    recipient_street: str = "",
    recipient_city_state_zip: str = "",
    recipient_tin: str = "",
    account_number: str = "",
    box1_rents: Decimal = Decimal("0"),
    box4_federal_withheld: Decimal = Decimal("0"),
    box15_state_withheld: Decimal = Decimal("0"),
    box16_state: str = "",
    box17_state_income: Decimal = Decimal("0"),
    corrected: bool = False,
) -> bytes:
    """Create the overlay PDF with form data using coordinates from config."""
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

    # Draw payer info
    draw_text("payer_name", payer_name)
    draw_text("payer_street", payer_street)
    draw_text("payer_city_state_zip", payer_city_state_zip)
    draw_text("payer_phone", payer_phone)

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

    # Draw amounts - MISC Box 1 is Rents (different from NEC Box 1 which is compensation)
    draw_text("box1_rents", format_money(box1_rents))
    draw_text("box4_federal_withheld", format_money(box4_federal_withheld))
    draw_text("box15_state_withheld", format_money(box15_state_withheld))

    # Only draw state if it has a real value
    if box16_state and box16_state != "None":
        draw_text("box16_state", box16_state)
    draw_text("box17_state_income", format_money(box17_state_income))

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
    import fitz  # PyMuPDF

    # Open template and overlay with PyMuPDF
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

    # Barcode location (same area as NEC - bottom right corner)
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


def generate_1099_misc_overlay(
    payer_name: str,
    payer_address_lines: list,
    payer_tin: str,
    recipient_name: str,
    recipient_address_lines: list,
    recipient_tin: str,
    payer_phone: str = "",
    recipient_account: str = "",
    tax_year: int = 2025,
    box1_rents: Decimal = Decimal("0"),
    box4_federal_withheld: Decimal = Decimal("0"),
    box15_state_withheld: Decimal = Decimal("0"),
    box16_state_payer_no: str = "",
    box17_state_income: Decimal = Decimal("0"),
    corrected: bool = False,
    template_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    mask_recipient_tin: bool = True,
) -> bytes:
    """
    Generate 1099-MISC PDF using official IRS template overlay.

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
        box1_rents: Rents amount (MISC Box 1)
        box4_federal_withheld: Federal income tax withheld
        box15_state_withheld: State tax withheld
        box16_state_payer_no: State/Payer's state no.
        box17_state_income: State income
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
        raise FileNotFoundError(f"MISC template not found: {template_path}")

    # Build address strings
    payer_street = payer_address_lines[0] if len(payer_address_lines) > 0 else ""
    payer_city_state_zip = payer_address_lines[1] if len(payer_address_lines) > 1 else ""

    # Handle recipient address - may have name_line_2, street, and city_state_zip
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
        box1_rents=box1_rents,
        box4_federal_withheld=box4_federal_withheld,
        box15_state_withheld=box15_state_withheld,
        box16_state=box16_state_payer_no,
        box17_state_income=box17_state_income,
        corrected=corrected,
    )

    # Merge with template
    return merge_overlay_with_template(template_path, overlay_bytes)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    # Test with sample data
    pdf_bytes = generate_1099_misc_overlay(
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
        box1_rents=Decimal("15750.00"),
    )

    output_path = Path(__file__).parent.parent / "test_misc_output.pdf"
    output_path.write_bytes(pdf_bytes)
    print(f"Generated {output_path} ({len(pdf_bytes)} bytes)")
