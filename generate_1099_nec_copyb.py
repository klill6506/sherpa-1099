#!/usr/bin/env python3
"""
Generate a Form 1099-NEC "Copy B - For Recipient" PDF that visually matches the provided template.

How it works
------------
1) Uses a single-page template PDF as the background (your existing 1099-NEC Copy B layout).
2) Creates an overlay PDF with white "wipe" rectangles + your 2025 data in the exact positions.
3) Merges overlay + background into the final PDF.

Configuration
-------------
All coordinates and data are loaded from a JSON config file (default: 1099nec_config.json).
You can tweak positions by editing the "coords" and "wipe_rects" sections in the JSON.

Coordinate system: y-down (0,0 is top-left, y increases downward) - matches most PDF tools.
"""

import argparse
import io
import json
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import white, black
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
import qrcode

PAGE_W, PAGE_H = letter  # 612 x 792 points


def fitz_to_rl_y(y_fitz: float) -> float:
    """Convert y-down coordinate to reportlab y (up from bottom)."""
    return PAGE_H - y_fitz


def bbox_fitz_to_rl(x0, y0, x1, y1):
    """Convert (x0,y0,x1,y1) with y-down to reportlab rect (x, y_bottom, w, h)."""
    return (x0, PAGE_H - y1, (x1 - x0), (y1 - y0))


def draw_overlay(overlay_path: Path, config: dict, blank: bool = False) -> None:
    """
    Create a 1-page overlay PDF.
    If blank=True, it only wipes the variable regions and sets year/revisions.
    """
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)

    coords = config.get("coords", {})
    wipe_rects = config.get("wipe_rects", {})
    qr_box = config.get("qr_box", {})
    data = config.get("data", {})
    year = str(config.get("year", 2025))

    def wipe_rect(x0, y0, x1, y1):
        c.setFillColor(white)
        c.setStrokeColor(white)
        rx, ry, rw, rh = bbox_fitz_to_rl(x0, y0, x1, y1)
        c.rect(rx, ry, rw, rh, fill=1, stroke=0)
        c.setFillColor(black)
        c.setStrokeColor(black)

    # Wipe areas from config
    for name, rect in wipe_rects.items():
        if name.startswith("_"):  # skip comments
            continue
        if isinstance(rect, list) and len(rect) == 4:
            wipe_rect(*rect)

    def draw_text(key: str, text: str):
        if text is None or key not in coords:
            return
        info = coords[key]
        if isinstance(info, dict) and "x" in info and "y" in info:
            font = info.get("font", "Helvetica")
            size = info.get("size", 10)
            c.setFont(font, size)
            c.drawString(info["x"], fitz_to_rl_y(info["y"]), str(text))

    # Year/revisions (always drawn)
    draw_text("rev_january", data.get("rev_january", f"(Rev. January {year})"))
    draw_text("rev_1", data.get("rev_1", f"(Rev. 1-{year})"))
    draw_text("year_big", year)

    if not blank:
        # Main fields
        draw_text("payer_label", "PAYER'S name, street address, city, state, ZIP")
        draw_text("payer_name", data.get("payer_name", ""))
        draw_text("payer_street", data.get("payer_street", ""))
        draw_text("payer_city", data.get("payer_city", ""))
        draw_text("payer_phone", data.get("payer_phone", ""))

        draw_text("recipient_label", "RECIPIENT'S name, street address, city, state, ZIP")
        draw_text("recipient_name", data.get("recipient_name", ""))
        draw_text("recipient_line2", data.get("recipient_line2", ""))
        draw_text("recipient_street", data.get("recipient_street", ""))
        draw_text("recipient_city", data.get("recipient_city", ""))

        if data.get("account_number"):
            draw_text("account_label", "Account number")
        draw_text("account_number", data.get("account_number", ""))
        draw_text("payer_tin", data.get("payer_tin", ""))
        draw_text("recipient_tin", data.get("recipient_tin", ""))

        amt = data.get("box1_amount", "")
        if isinstance(amt, (int, float)):
            amt = f"{amt:,.2f}"
        draw_text("box1_amount", amt)

        # Box 3 - Excess golden parachute payments (new for 2025)
        amt3 = data.get("box3_amount", "")
        if isinstance(amt3, (int, float)):
            amt3 = f"{amt3:,.2f}"
        draw_text("box3_amount", amt3)

        # Box 4 - Federal income tax withheld
        amt4 = data.get("box4_amount", "")
        if isinstance(amt4, (int, float)):
            amt4 = f"{amt4:,.2f}"
        draw_text("box4_amount", amt4)

        # Bottom-right block
        draw_text("docid", data.get("docid", ""))
        draw_text("challenge_key", data.get("challenge_key", ""))
        draw_text("get_form_url", data.get("get_form_url", ""))

        # QR code (optional)
        qr_url = data.get("qr_url") or data.get("get_form_url")
        if qr_url and qr_box:
            qr = qrcode.QRCode(border=0, box_size=2)
            qr.add_data(qr_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")

            x0 = qr_box.get("x0", 537)
            y0 = qr_box.get("y0", 677)
            x1 = qr_box.get("x1", 571)
            y1 = qr_box.get("y1", 711)
            w = x1 - x0
            h = y1 - y0
            x = x0
            y = PAGE_H - y1  # reportlab bottom
            c.drawImage(ImageReader(qr_img._img), x, y, width=w, height=h, mask="auto")

    c.showPage()
    c.save()
    packet.seek(0)
    overlay_path.write_bytes(packet.getvalue())


def merge(background_pdf: Path, overlay_pdf: Path, output_pdf: Path) -> None:
    """Merge overlay onto background (1 page)."""
    bg = PdfReader(str(background_pdf))
    ov = PdfReader(str(overlay_pdf))

    writer = PdfWriter()
    for i in range(len(bg.pages)):
        p = bg.pages[i]
        p.merge_page(ov.pages[i])
        writer.add_page(p)

    with output_pdf.open("wb") as f:
        writer.write(f)


def main():
    ap = argparse.ArgumentParser(description="Generate 1099-NEC Copy B PDF from JSON config")
    ap.add_argument("--template", required=True, help="Background template PDF (the sample 1099-NEC Copy B)")
    ap.add_argument("--config", default="1099nec_config.json", help="JSON config file with coords and data (default: 1099nec_config.json)")
    ap.add_argument("--out", required=True, help="Output PDF path")
    ap.add_argument("--blank", action="store_true", help="Create a blank template (no payer/recipient data)")
    args = ap.parse_args()

    template = Path(args.template)
    config_path = Path(args.config)
    out = Path(args.out)

    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        return

    config = json.loads(config_path.read_text(encoding="utf-8"))

    overlay = out.with_suffix(".overlay.pdf")
    draw_overlay(overlay, config, blank=args.blank)
    merge(template, overlay, out)
    overlay.unlink(missing_ok=True)

    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
