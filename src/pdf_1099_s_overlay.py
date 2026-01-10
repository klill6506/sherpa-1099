"""
1099-S PDF Generator - Official Template Overlay Approach.

Generates IRS Form 1099-S Copy B (Proceeds From Real Estate Transactions)
by overlaying data onto the official IRS template.

Template: 1099S 2025 Official Template.pdf

NOTE: This module is separate from NEC/MISC generators to avoid any risk of
changing their output. They share similar patterns but are maintained independently.
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
TEMPLATE_PATH = PROJECT_ROOT / "Blank 1099S 2025 Official Template.pdf"
CONFIG_PATH = PROJECT_ROOT / "config" / "1099s_2025_copyb.json"


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load 1099-S coordinate configuration from JSON file."""
    path = config_path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"1099-S config not found: {path}")
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


def wrap_text(text: str, max_width: float, font_name: str, font_size: float) -> List[str]:
    """
    Simple word-wrap for multi-line text fields.

    Uses approximate character width for Helvetica.
    """
    if not text:
        return []

    # Approximate average character width for Helvetica at given size
    # This is a simplification; for precision, use reportlab's stringWidth
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
    filer_name: str,
    filer_street: str,
    filer_city_state_zip: str,
    filer_tin: str,
    filer_phone: str = "",
    transferor_name: str = "",
    transferor_line2: str = "",
    transferor_street: str = "",
    transferor_city_state_zip: str = "",
    transferor_tin: str = "",
    account_number: str = "",
    box1_date_of_closing: str = "",
    box2_gross_proceeds: Decimal = Decimal("0"),
    box3_property_description: str = "",
    box4_property_services: bool = False,
    box5_foreign: bool = False,
    box6_buyers_tax: Decimal = Decimal("0"),
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

    def draw_checkbox(key: str, checked: bool):
        """Draw X for checkbox if checked."""
        if not checked or key not in coords:
            return
        info = coords[key]
        font = info.get("font", "Helvetica-Bold")
        size = info.get("size", 12)
        c.setFont(font, size)
        c.setFillColor(black)

        x = info["x"]
        y = fitz_to_rl_y(cast(float, info["y"]))
        c.drawString(x, y, "X")

    # Draw filer (payer) info
    draw_text("filer_name", filer_name)
    draw_text("filer_street", filer_street)
    draw_text("filer_city_state_zip", filer_city_state_zip)
    draw_text("filer_phone", filer_phone)

    # Draw TINs (different positions than NEC/MISC)
    draw_text("filer_tin", filer_tin)
    draw_text("transferor_tin", transferor_tin)

    # Draw transferor (recipient) info
    draw_text("transferor_name", transferor_name)
    draw_text("transferor_line2", transferor_line2)
    draw_text("transferor_street", transferor_street)
    draw_text("transferor_city_state_zip", transferor_city_state_zip)

    # Draw account number
    draw_text("account_number", account_number)

    # Draw Box 1 - Date of closing (MM/DD/YYYY format)
    draw_text("box1_date_of_closing", box1_date_of_closing)

    # Draw Box 2 - Gross proceeds
    draw_text("box2_gross_proceeds", format_money(box2_gross_proceeds))

    # Draw Box 3 - Property description (multi-line)
    draw_multiline("box3_property_description", box3_property_description)

    # Draw Box 4 - Property or services checkbox
    draw_checkbox("box4_checkbox", box4_property_services)

    # Draw Box 5 - Foreign transferor checkbox
    draw_checkbox("box5_foreign_checkbox", box5_foreign)

    # Draw Box 6 - Buyer's part of real estate tax
    draw_text("box6_buyers_tax", format_money(box6_buyers_tax))

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

            # Check if word wrapping is needed
            max_width = info.get("max_width")
            if max_width:
                line_height = info.get("line_height", size + 1)
                lines = wrap_text(text, max_width, font, size)
                for i, line in enumerate(lines):
                    c.drawString(x, y - (i * line_height), line)
            else:
                c.drawString(x, y, text)

    c.showPage()
    c.save()
    packet.seek(0)
    return packet.getvalue()


def merge_overlay_with_template(template_path: Path, overlay_bytes: bytes, wipe_rects: dict = None) -> bytes:
    """
    Merge overlay PDF onto template PDF and wipe out specified areas.

    Uses PyMuPDF exclusively for efficient merging without resource duplication.

    Args:
        template_path: Path to template PDF
        overlay_bytes: Overlay PDF as bytes
        wipe_rects: Dict of named rectangles to white-out, each is [x0, y0, x1, y1] in y-down coords
    """
    import fitz  # PyMuPDF

    # Open template and overlay with PyMuPDF
    template_doc = fitz.open(str(template_path))
    overlay_doc = fitz.open(stream=overlay_bytes, filetype="pdf")

    template_page = template_doc[0]
    overlay_page = overlay_doc[0]

    # Overlay the text onto the template using show_pdf_page
    # This is more efficient than pypdf merge as it doesn't duplicate resources
    template_page.show_pdf_page(
        template_page.rect,  # Full page
        overlay_doc,
        0,  # Page number
        overlay=True,  # Place on top
    )

    # Apply all wipe rectangles from config
    if wipe_rects:
        for name, rect_coords in wipe_rects.items():
            # Skip comment entries
            if name.startswith("_"):
                continue
            if not isinstance(rect_coords, list) or len(rect_coords) != 4:
                continue

            x0, y0_down, x1, y1_down = rect_coords
            rect = fitz.Rect(x0, y0_down, x1, y1_down)
            template_page.add_redact_annot(rect, fill=(1, 1, 1))  # White fill

    # Apply all redactions at once
    if wipe_rects:
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


def generate_1099s_copyb(
    filer_name: str,
    filer_address_lines: list,
    filer_tin: str,
    transferor_name: str,
    transferor_address_lines: list,
    transferor_tin: str,
    filer_phone: str = "",
    account_number: str = "",
    tax_year: int = 2025,
    box1_date_of_closing: str = "",
    box2_gross_proceeds: Decimal = Decimal("0"),
    box3_property_description: str = "",
    box4_property_services: bool = False,
    box5_foreign: bool = False,
    box6_buyers_tax: Decimal = Decimal("0"),
    corrected: bool = False,
    template_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    mask_transferor_tin: bool = True,
) -> bytes:
    """
    Generate 1099-S Copy B PDF using official IRS template overlay.

    Args:
        filer_name: Filer/Payer name (title company, escrow agent, etc.)
        filer_address_lines: List of address lines [street, city_state_zip]
        filer_tin: Filer's TIN (formatted)
        transferor_name: Transferor (seller) name
        transferor_address_lines: List of address lines [street, city_state_zip]
        transferor_tin: Transferor's TIN (formatted)
        filer_phone: Optional phone number
        account_number: Optional account/file number
        tax_year: Tax year (for template selection)
        box1_date_of_closing: Date of closing (MM/DD/YYYY format)
        box2_gross_proceeds: Gross proceeds from sale
        box3_property_description: Address or legal description of property
        box4_property_services: Check if transferor received property/services
        box5_foreign: Check if transferor is foreign person
        box6_buyers_tax: Buyer's part of real estate tax
        corrected: Whether this is a corrected form
        template_path: Optional custom template path
        config_path: Optional custom config path
        mask_transferor_tin: Mask transferor TIN showing only last 4 digits (default True for Copy B)

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
        raise FileNotFoundError(f"1099-S template not found: {template_path}")

    # Build address strings
    filer_street = filer_address_lines[0] if len(filer_address_lines) > 0 else ""
    filer_city_state_zip = filer_address_lines[1] if len(filer_address_lines) > 1 else ""

    # Handle transferor address - may have name_line_2, street, and city_state_zip
    transferor_line2 = ""
    if len(transferor_address_lines) == 1:
        # Only city/state/zip
        transferor_street = ""
        transferor_city_state_zip = transferor_address_lines[0]
    elif len(transferor_address_lines) == 2:
        # Street and city/state/zip
        transferor_street = transferor_address_lines[0]
        transferor_city_state_zip = transferor_address_lines[1]
    elif len(transferor_address_lines) >= 3:
        # Name line 2, street, city/state/zip - each on its own line
        transferor_line2 = transferor_address_lines[0]
        transferor_street = transferor_address_lines[1]
        transferor_city_state_zip = transferor_address_lines[2]
    else:
        transferor_street = ""
        transferor_city_state_zip = ""

    # Mask transferor TIN if requested (default for Copy B)
    display_transferor_tin = mask_tin(transferor_tin) if mask_transferor_tin else transferor_tin

    # Get static labels from config
    static_labels = config.get("static_labels", {})

    # Create overlay
    overlay_bytes = create_overlay(
        coords=coords,
        filer_name=filer_name,
        filer_street=filer_street,
        filer_city_state_zip=filer_city_state_zip,
        filer_tin=filer_tin,
        filer_phone=filer_phone,
        transferor_name=transferor_name,
        transferor_line2=transferor_line2,
        transferor_street=transferor_street,
        transferor_city_state_zip=transferor_city_state_zip,
        transferor_tin=display_transferor_tin,
        account_number=account_number,
        box1_date_of_closing=box1_date_of_closing,
        box2_gross_proceeds=box2_gross_proceeds,
        box3_property_description=box3_property_description,
        box4_property_services=box4_property_services,
        box5_foreign=box5_foreign,
        box6_buyers_tax=box6_buyers_tax,
        corrected=corrected,
        static_labels=static_labels,
    )

    # Get wipe rectangles from config
    wipe_rects = config.get("wipe_rects", {})

    # Merge with template and apply wipe areas
    return merge_overlay_with_template(template_path, overlay_bytes, wipe_rects)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    # Test with sample data
    pdf_bytes = generate_1099s_copyb(
        filer_name="ABC Title Company",
        filer_address_lines=[
            "100 Main Street",
            "Atlanta, GA 30301"
        ],
        filer_tin="58-1234567",
        filer_phone="(404) 555-1234",
        transferor_name="John Q. Seller",
        transferor_address_lines=[
            "456 Oak Lane",
            "Marietta, GA 30060"
        ],
        transferor_tin="123-45-6789",
        account_number="2025-CLOSE-001",
        tax_year=2025,
        box1_date_of_closing="01/15/2025",
        box2_gross_proceeds=Decimal("350000.00"),
        box3_property_description="123 Maple Street, Anytown, GA 30301\nLot 15, Block 3, Sunshine Subdivision",
        box4_property_services=False,
        box5_foreign=False,
        box6_buyers_tax=Decimal("2500.00"),
    )

    output_path = Path(__file__).parent.parent / "test_1099s_output.pdf"
    output_path.write_bytes(pdf_bytes)
    print(f"Generated {output_path} ({len(pdf_bytes)} bytes)")
