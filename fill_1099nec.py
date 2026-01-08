#!/usr/bin/env python3
"""
Fill a 1099-NEC template with data from JSON config.
Uses the blank template created by create_1099nec_template.py
"""

import argparse
import json
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import black
from pypdf import PdfReader, PdfWriter
import io

PAGE_W, PAGE_H = letter  # 612 x 792 points


def create_overlay(data: dict) -> bytes:
    """Create a PDF overlay with the filled data."""
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)

    # Form positioning (must match template exactly)
    LEFT_MARGIN = 0.4 * inch
    FORM_TOP = PAGE_H - 0.5 * inch
    left_col_width = 4.0 * inch
    right_col_left = LEFT_MARGIN + left_col_width

    # Box heights from template
    payer_height = 1.15 * inch
    tin_height = 0.30 * inch
    recip_name_height = 0.35 * inch
    street_height = 0.35 * inch
    city_height = 0.35 * inch
    acct_height = 0.30 * inch

    # Calculate Y positions (bottom of each box, then add offset for text)
    payer_bottom = FORM_TOP - payer_height
    tin_bottom = payer_bottom - tin_height
    recip_name_bottom = tin_bottom - recip_name_height
    street_bottom = recip_name_bottom - street_height
    city_bottom = street_bottom - city_height
    acct_bottom = city_bottom - acct_height

    # === PAYER INFO ===
    c.setFont("Helvetica", 10)
    payer_text_y = payer_bottom + 55  # Near top of payer box, below label

    if data.get("payer_name"):
        c.drawString(LEFT_MARGIN + 5, payer_text_y, data["payer_name"])
    if data.get("payer_street"):
        c.drawString(LEFT_MARGIN + 5, payer_text_y - 13, data["payer_street"])
    if data.get("payer_city"):
        c.drawString(LEFT_MARGIN + 5, payer_text_y - 26, data["payer_city"])
    if data.get("payer_phone"):
        c.drawString(LEFT_MARGIN + 5, payer_text_y - 39, data["payer_phone"])

    # === TINs ===
    c.setFont("Helvetica", 9)
    tin_text_y = tin_bottom + 6  # Near bottom of TIN boxes

    if data.get("payer_tin"):
        c.drawString(LEFT_MARGIN + 5, tin_text_y, data["payer_tin"])
    if data.get("recipient_tin"):
        c.drawString(LEFT_MARGIN + 2.0*inch + 5, tin_text_y, data["recipient_tin"])

    # === RECIPIENT INFO ===
    c.setFont("Helvetica", 10)

    # Recipient name - in the middle of the box
    if data.get("recipient_name"):
        c.drawString(LEFT_MARGIN + 5, recip_name_bottom + 8, data["recipient_name"])

    # Street address
    if data.get("recipient_street"):
        c.drawString(LEFT_MARGIN + 5, street_bottom + 8, data["recipient_street"])

    # City
    if data.get("recipient_city"):
        c.drawString(LEFT_MARGIN + 5, city_bottom + 8, data["recipient_city"])

    # Account number
    c.setFont("Helvetica", 9)
    if data.get("account_number"):
        c.drawString(LEFT_MARGIN + 5, acct_bottom + 6, data["account_number"])

    # === RIGHT SIDE BOXES ===
    # Box positions from template
    box1_bottom = payer_bottom - 0.50*inch
    box2_bottom = box1_bottom - 0.38*inch
    box3_bottom = box2_bottom - 0.38*inch
    box4_bottom = box3_bottom - 0.38*inch

    # Box 1 - Nonemployee compensation
    if data.get("box1_amount"):
        amt = data["box1_amount"]
        if isinstance(amt, (int, float)):
            amt = f"{amt:,.2f}"
        c.setFont("Helvetica", 10)
        c.drawString(right_col_left + 20, box1_bottom + 8, str(amt))

    # Box 4 - Federal income tax withheld
    if data.get("box4_amount"):
        amt = data["box4_amount"]
        if isinstance(amt, (int, float)):
            amt = f"{amt:,.2f}"
        c.setFont("Helvetica", 10)
        c.drawString(right_col_left + 20, box4_bottom + 8, str(amt))

    c.save()
    packet.seek(0)
    return packet.getvalue()


def fill_1099nec(template_path: str, config_path: str, output_path: str):
    """Fill the 1099-NEC template with data from config."""

    # Load config
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    data = config.get("data", config)  # Support both nested and flat format

    # Create overlay with data
    overlay_bytes = create_overlay(data)

    # Merge overlay onto template
    template = PdfReader(template_path)
    overlay = PdfReader(io.BytesIO(overlay_bytes))

    writer = PdfWriter()
    page = template.pages[0]
    page.merge_page(overlay.pages[0])
    writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)

    print(f"Created: {output_path}")


def main():
    ap = argparse.ArgumentParser(description="Fill 1099-NEC template with data")
    ap.add_argument("--template", default="1099-NEC_template_blank.pdf",
                    help="Blank template PDF")
    ap.add_argument("--config", default="1099nec_config.json",
                    help="JSON config with data")
    ap.add_argument("--out", default="1099-NEC_filled.pdf",
                    help="Output PDF path")
    args = ap.parse_args()

    fill_1099nec(args.template, args.config, args.out)


if __name__ == "__main__":
    main()
