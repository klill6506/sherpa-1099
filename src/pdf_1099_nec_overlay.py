"""
1099-NEC PDF Generator - Official Template Overlay Approach.

Generates IRS Form 1099-NEC Copy B by overlaying data onto the official IRS template.
This produces forms that match the official IRS layout exactly.

Template: 1099-NEC_template_blank.pdf (Official IRS Form 1099-NEC Rev. April 2025)
"""

import io
from pathlib import Path
from typing import Optional
from decimal import Decimal

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black
from pypdf import PdfReader, PdfWriter


PAGE_W, PAGE_H = letter  # 612 x 792 points

# Template file path (relative to project root)
TEMPLATE_PATH = Path(__file__).parent.parent / "1099-NEC_template_blank.pdf"


def fitz_to_rl_y(y_fitz: float) -> float:
    """Convert y-down coordinate (from top) to reportlab y (from bottom)."""
    return PAGE_H - y_fitz


def format_money(amount: Optional[Decimal]) -> str:
    """Format amount as money string with commas and 2 decimals."""
    if amount is None or amount == 0:
        return ""
    return f"{float(amount):,.2f}"


# =============================================================================
# COORDINATE CONFIGURATION - Matched to 1099-NEC_template_blank.pdf
# All y values are y-down (from top of page)
# =============================================================================

# Coordinates from 1099nec_config.json that produced test_2025_v11.pdf
COORDS = {
    # Payer section
    "payer_name": {"x": 47, "y": 88, "size": 10, "font": "Helvetica"},
    "payer_street": {"x": 47, "y": 101, "size": 10, "font": "Helvetica"},
    "payer_city_state_zip": {"x": 47, "y": 114, "size": 10, "font": "Helvetica"},
    "payer_phone": {"x": 47, "y": 127, "size": 9, "font": "Helvetica"},

    # TINs row
    "payer_tin": {"x": 47, "y": 298, "size": 9, "font": "Helvetica"},
    "recipient_tin": {"x": 168, "y": 298, "size": 9, "font": "Helvetica"},

    # Recipient section
    "recipient_name": {"x": 47, "y": 182, "size": 10, "font": "Helvetica"},
    "recipient_line2": {"x": 47, "y": 195, "size": 10, "font": "Helvetica"},
    "recipient_street": {"x": 47, "y": 212, "size": 10, "font": "Helvetica"},
    "recipient_city_state_zip": {"x": 47, "y": 225, "size": 10, "font": "Helvetica"},

    # Account number
    "account_number": {"x": 47, "y": 274, "size": 9, "font": "Helvetica"},

    # Box 1 - Nonemployee compensation
    "box1_amount": {"x": 319, "y": 117, "size": 10, "font": "Helvetica"},

    # Box 3 - Excess golden parachute payments
    "box3_amount": {"x": 310, "y": 178, "size": 10, "font": "Helvetica"},

    # Box 4 - Federal income tax withheld
    "box4_amount": {"x": 310, "y": 214, "size": 10, "font": "Helvetica"},

    # Box 5 - State tax withheld
    "box5_amount": {"x": 310, "y": 250, "size": 9, "font": "Helvetica"},

    # Box 6 - State/Payer's state no.
    "box6_state": {"x": 380, "y": 250, "size": 9, "font": "Helvetica"},

    # Box 7 - State income
    "box7_amount": {"x": 480, "y": 250, "size": 9, "font": "Helvetica"},

    # CORRECTED checkbox (X mark position)
    "corrected_x": {"x": 502, "y": 20, "size": 12, "font": "Helvetica-Bold"},
}


def create_overlay(
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
        if not text or key not in COORDS:
            return
        info = COORDS[key]
        font = info.get("font", "Helvetica")
        size = info.get("size", 10)
        c.setFont(font, size)
        c.setFillColor(black)

        x = info["x"]
        y = fitz_to_rl_y(info["y"])

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

    # Draw amounts
    draw_text("box1_amount", format_money(box1_amount))
    draw_text("box3_amount", format_money(box3_amount))
    draw_text("box4_amount", format_money(box4_amount))
    draw_text("box5_amount", format_money(box5_amount))
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
    """Merge overlay PDF onto template PDF."""
    template_reader = PdfReader(str(template_path))
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))

    writer = PdfWriter()

    # Merge overlay onto template page
    page = template_reader.pages[0]
    page.merge_page(overlay_reader.pages[0])
    writer.add_page(page)

    # Write to bytes
    output = io.BytesIO()
    writer.write(output)
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
    recipient_account: str = "",
    tax_year: int = 2025,
    box1_compensation: Decimal = Decimal("0"),
    box3_golden_parachute: Decimal = Decimal("0"),
    box4_federal_withheld: Decimal = Decimal("0"),
    box5_state_withheld: Decimal = Decimal("0"),
    box6_state_payer_no: str = "",
    box7_state_income: Decimal = Decimal("0"),
    corrected: bool = False,
    template_path: Path = None,
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

    Returns:
        PDF as bytes
    """
    if template_path is None:
        template_path = TEMPLATE_PATH

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

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

    # Create overlay
    overlay_bytes = create_overlay(
        payer_name=payer_name,
        payer_street=payer_street,
        payer_city_state_zip=payer_city_state_zip,
        payer_tin=payer_tin,
        payer_phone=payer_phone,
        recipient_name=recipient_name,
        recipient_line2=recipient_line2,
        recipient_street=recipient_street,
        recipient_city_state_zip=recipient_city_state_zip,
        recipient_tin=recipient_tin,
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
