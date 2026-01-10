"""
1098 PDF Generator - Official Template Overlay Approach.

Generates IRS Form 1098 Copy B (Mortgage Interest Statement)
by overlaying data onto the official IRS template.

Template: Blank 1098 2025 Official Template.pdf
"""

import io
import json
from pathlib import Path
from typing import Optional, List, cast
from decimal import Decimal

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import black


PAGE_W, PAGE_H = letter  # 612 x 792 points

# Template and config paths (relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "Blank 1098 2025 Official Template.pdf"
CONFIG_PATH = PROJECT_ROOT / "config" / "1098_2025_copyb.json"


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load 1098 coordinate configuration from JSON file."""
    path = config_path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"1098 config not found: {path}")
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
    """
    if not tin:
        return ""

    digits_only = ''.join(c for c in tin if c.isalnum())

    if len(digits_only) < 4:
        return tin

    last_4 = digits_only[-4:]

    if '-' in tin:
        parts = tin.split('-')
        if len(parts) == 3 and len(parts[0]) == 3 and len(parts[1]) == 2:
            return f"***-**-{last_4}"
        elif len(parts) == 2 and len(parts[0]) == 2:
            return f"**-***{last_4}"

    masked_len = len(digits_only) - 4
    return '*' * masked_len + last_4


def wrap_text(text: str, max_width: float, font_name: str, font_size: float) -> List[str]:
    """Simple word-wrap for multi-line text fields."""
    if not text:
        return []

    avg_char_width = font_size * 0.5
    chars_per_line = int(max_width / avg_char_width)

    lines = []
    for paragraph in text.split('\n'):
        words = paragraph.split()
        current_line = []
        current_length = 0

        for word in words:
            word_length = len(word)
            if current_length + word_length + (1 if current_line else 0) <= chars_per_line:
                current_line.append(word)
                current_length += word_length + (1 if len(current_line) > 1 else 0)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_length = word_length

        if current_line:
            lines.append(' '.join(current_line))

    return lines


def create_overlay(
    coords: dict,
    recipient_name: str,
    recipient_street: str,
    recipient_city_state_zip: str,
    recipient_tin: str,
    recipient_phone: str = "",
    payer_name: str = "",
    payer_line2: str = "",
    payer_street: str = "",
    payer_city_state_zip: str = "",
    payer_tin: str = "",
    account_number: str = "",
    box1_mortgage_interest: Decimal = Decimal("0"),
    box2_outstanding_principal: Decimal = Decimal("0"),
    box3_origination_date: str = "",
    box4_refund_interest: Decimal = Decimal("0"),
    box5_mortgage_insurance: Decimal = Decimal("0"),
    box6_points_paid: Decimal = Decimal("0"),
    box8_property_address: str = "",
    box9_num_properties: str = "",
    box10_other: Decimal = Decimal("0"),
    box11_acquisition_date: str = "",
    corrected: bool = False,
    static_labels: dict = None,
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

    def draw_multiline(key: str, text: str):
        """Draw multi-line text with word wrapping."""
        if not text or key not in coords:
            return
        info = coords[key]
        font = info.get("font", "Helvetica")
        size = info.get("size", 10)
        max_width = info.get("max_width", 250)
        line_height = info.get("line_height", size + 2)
        max_lines = info.get("max_lines", 4)

        c.setFont(font, size)
        c.setFillColor(black)

        x = info["x"]
        y = fitz_to_rl_y(cast(float, info["y"]))

        lines = wrap_text(text, max_width, font, size)
        for i, line in enumerate(lines[:max_lines]):
            c.drawString(x, y - (i * line_height), line)

    # Draw recipient (lender) info
    draw_text("recipient_name", recipient_name)
    draw_text("recipient_street", recipient_street)
    draw_text("recipient_city_state_zip", recipient_city_state_zip)
    draw_text("recipient_phone", recipient_phone)

    # Draw TINs
    draw_text("recipient_tin", recipient_tin)
    draw_text("payer_tin", payer_tin)

    # Draw payer (borrower) info
    draw_text("payer_name", payer_name)
    draw_text("payer_line2", payer_line2)
    draw_text("payer_street", payer_street)
    draw_text("payer_city_state_zip", payer_city_state_zip)

    # Draw account number
    draw_text("account_number", account_number)

    # Draw boxes
    draw_text("box1_mortgage_interest", format_money(box1_mortgage_interest))
    draw_text("box2_outstanding_principal", format_money(box2_outstanding_principal))
    draw_text("box3_origination_date", box3_origination_date)
    draw_text("box4_refund_interest", format_money(box4_refund_interest))
    draw_text("box5_mortgage_insurance", format_money(box5_mortgage_insurance))
    draw_text("box6_points_paid", format_money(box6_points_paid))

    # Box 8 - property address (multi-line)
    draw_multiline("box8_property_address", box8_property_address)

    draw_text("box9_num_properties", box9_num_properties)
    draw_text("box10_other", format_money(box10_other))
    draw_text("box11_acquisition_date", box11_acquisition_date)

    # Draw CORRECTED checkbox if needed
    if corrected:
        draw_text("corrected_x", "X")

    # Draw static labels (verbiage missing from blank template)
    if static_labels:
        for key, info in static_labels.items():
            if key.startswith("_"):
                continue
            text = info.get("text", "")
            if not text:
                continue
            font = info.get("font", "Helvetica")
            size = info.get("size", 6)
            c.setFont(font, size)
            c.setFillColor(black)
            x = info["x"]
            y = fitz_to_rl_y(cast(float, info["y"]))
            c.drawString(x, y, text)

    c.showPage()
    c.save()
    packet.seek(0)
    return packet.getvalue()


def merge_overlay_with_template(template_path: Path, overlay_bytes: bytes, wipe_rects: dict = None) -> bytes:
    """
    Merge overlay PDF onto template PDF and wipe out specified areas.

    Uses PyMuPDF exclusively for efficient merging without resource duplication.
    """
    import fitz  # PyMuPDF

    template_doc = fitz.open(str(template_path))
    overlay_doc = fitz.open(stream=overlay_bytes, filetype="pdf")

    template_page = template_doc[0]

    template_page.show_pdf_page(
        template_page.rect,
        overlay_doc,
        0,
        overlay=True,
    )

    if wipe_rects:
        for name, rect_coords in wipe_rects.items():
            if name.startswith("_"):
                continue
            if not isinstance(rect_coords, list) or len(rect_coords) != 4:
                continue

            x0, y0_down, x1, y1_down = rect_coords
            rect = fitz.Rect(x0, y0_down, x1, y1_down)
            template_page.add_redact_annot(rect, fill=(1, 1, 1))

    if wipe_rects:
        template_page.apply_redactions()

    output = io.BytesIO()
    template_doc.save(
        output,
        garbage=4,
        deflate=True,
        clean=True,
    )
    template_doc.close()
    overlay_doc.close()
    output.seek(0)
    return output.getvalue()


def generate_1098_copyb(
    recipient_name: str,
    recipient_address_lines: list,
    recipient_tin: str,
    payer_name: str,
    payer_address_lines: list,
    payer_tin: str,
    recipient_phone: str = "",
    account_number: str = "",
    tax_year: int = 2025,
    box1_mortgage_interest: Decimal = Decimal("0"),
    box2_outstanding_principal: Decimal = Decimal("0"),
    box3_origination_date: str = "",
    box4_refund_interest: Decimal = Decimal("0"),
    box5_mortgage_insurance: Decimal = Decimal("0"),
    box6_points_paid: Decimal = Decimal("0"),
    box8_property_address: str = "",
    box9_num_properties: str = "",
    box10_other: Decimal = Decimal("0"),
    box11_acquisition_date: str = "",
    corrected: bool = False,
    template_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    mask_payer_tin: bool = True,
) -> bytes:
    """
    Generate 1098 Copy B PDF using official IRS template overlay.

    Args:
        recipient_name: Recipient/Lender name
        recipient_address_lines: List of address lines [street, city_state_zip]
        recipient_tin: Recipient's TIN (formatted)
        payer_name: Payer/Borrower name
        payer_address_lines: List of address lines [street, city_state_zip]
        payer_tin: Payer's TIN (formatted)
        recipient_phone: Optional phone number
        account_number: Optional account/loan number
        tax_year: Tax year
        box1_mortgage_interest: Mortgage interest received
        box2_outstanding_principal: Outstanding mortgage principal
        box3_origination_date: Mortgage origination date
        box4_refund_interest: Refund of overpaid interest
        box5_mortgage_insurance: Mortgage insurance premiums
        box6_points_paid: Points paid on purchase
        box8_property_address: Property address if different from payer
        box9_num_properties: Number of mortgaged properties
        box10_other: Other amount
        box11_acquisition_date: Acquisition date of property
        corrected: Whether this is a corrected form
        template_path: Optional custom template path
        config_path: Optional custom config path
        mask_payer_tin: Mask payer TIN showing only last 4 digits (default True for Copy B)

    Returns:
        PDF as bytes
    """
    config = load_config(config_path)
    coords = config.get("coords", {})

    if template_path is None:
        template_path = TEMPLATE_PATH

    if not template_path.exists():
        raise FileNotFoundError(f"1098 template not found: {template_path}")

    # Build address strings
    recipient_street = recipient_address_lines[0] if len(recipient_address_lines) > 0 else ""
    recipient_city_state_zip = recipient_address_lines[1] if len(recipient_address_lines) > 1 else ""

    # Handle payer address
    payer_line2 = ""
    if len(payer_address_lines) == 1:
        payer_street = ""
        payer_city_state_zip = payer_address_lines[0]
    elif len(payer_address_lines) == 2:
        payer_street = payer_address_lines[0]
        payer_city_state_zip = payer_address_lines[1]
    elif len(payer_address_lines) >= 3:
        payer_line2 = payer_address_lines[0]
        payer_street = payer_address_lines[1]
        payer_city_state_zip = payer_address_lines[2]
    else:
        payer_street = ""
        payer_city_state_zip = ""

    # Mask payer TIN if requested (default for Copy B)
    display_payer_tin = mask_tin(payer_tin) if mask_payer_tin else payer_tin

    # Get static labels from config
    static_labels = config.get("static_labels", {})

    # Create overlay
    overlay_bytes = create_overlay(
        coords=coords,
        recipient_name=recipient_name,
        recipient_street=recipient_street,
        recipient_city_state_zip=recipient_city_state_zip,
        recipient_tin=recipient_tin,
        recipient_phone=recipient_phone,
        payer_name=payer_name,
        payer_line2=payer_line2,
        payer_street=payer_street,
        payer_city_state_zip=payer_city_state_zip,
        payer_tin=display_payer_tin,
        account_number=account_number,
        box1_mortgage_interest=box1_mortgage_interest,
        box2_outstanding_principal=box2_outstanding_principal,
        box3_origination_date=box3_origination_date,
        box4_refund_interest=box4_refund_interest,
        box5_mortgage_insurance=box5_mortgage_insurance,
        box6_points_paid=box6_points_paid,
        box8_property_address=box8_property_address,
        box9_num_properties=box9_num_properties,
        box10_other=box10_other,
        box11_acquisition_date=box11_acquisition_date,
        corrected=corrected,
        static_labels=static_labels,
    )

    wipe_rects = config.get("wipe_rects", {})
    return merge_overlay_with_template(template_path, overlay_bytes, wipe_rects)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    pdf_bytes = generate_1098_copyb(
        recipient_name="ABC Mortgage Company",
        recipient_address_lines=[
            "100 Finance Blvd",
            "Atlanta, GA 30301"
        ],
        recipient_tin="58-1234567",
        recipient_phone="(404) 555-1234",
        payer_name="John Q. Homeowner",
        payer_address_lines=[
            "456 Oak Lane",
            "Marietta, GA 30060"
        ],
        payer_tin="123-45-6789",
        account_number="LOAN-2025-001",
        tax_year=2025,
        box1_mortgage_interest=Decimal("12500.00"),
        box2_outstanding_principal=Decimal("285000.00"),
        box3_origination_date="03/15/2020",
        box5_mortgage_insurance=Decimal("1200.00"),
    )

    output_path = Path(__file__).parent.parent / "test_1098_output.pdf"
    output_path.write_bytes(pdf_bytes)
    print(f"Generated {output_path} ({len(pdf_bytes)} bytes)")
