"""
Debug Form Coordinates Tool.

Generates a PDF with coordinate crosshairs and labels overlaid on the form template.
This makes it easy to visually tune field positions without trial-and-error.

Usage:
    python tools/debug_form_coords.py --form 1099s --out debug_1099s.pdf
    python tools/debug_form_coords.py --form misc --out debug_misc_coords.pdf
    python tools/debug_form_coords.py --form nec --out debug_nec_coords.pdf
    python tools/debug_form_coords.py --form 1099s --grid  # Include coordinate grid
"""

import argparse
import io
import json
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import red, blue, black, green
from pypdf import PdfReader, PdfWriter


PAGE_W, PAGE_H = letter  # 612 x 792 points
PROJECT_ROOT = Path(__file__).parent.parent

# Form configurations
FORMS = {
    "1098": {
        "template": PROJECT_ROOT / "Blank 1098 2025 Official Template.pdf",
        "config": PROJECT_ROOT / "config" / "1098_2025_copyb.json",
    },
    "1099s": {
        "template": PROJECT_ROOT / "Blank 1099S 2025 Official Template.pdf",
        "config": PROJECT_ROOT / "config" / "1099s_2025_copyb.json",
    },
    "misc": {
        "template": PROJECT_ROOT / "1099-Misc Official 2025.pdf",
        "config": PROJECT_ROOT / "config" / "1099_misc_2025_copyb.json",
    },
    "nec": {
        "template": PROJECT_ROOT / "New Official 1099-NEC.pdf",
        "config": PROJECT_ROOT / "1099nec_config.json",
    },
}


def fitz_to_rl_y(y_fitz: float) -> float:
    """Convert y-down coordinate (from top) to reportlab y (from bottom)."""
    return PAGE_H - y_fitz


def draw_crosshair(c: canvas.Canvas, x: float, y: float, size: float = 10):
    """Draw a small crosshair at the given position."""
    c.setStrokeColor(red)
    c.setLineWidth(0.5)
    # Horizontal line
    c.line(x - size / 2, y, x + size / 2, y)
    # Vertical line
    c.line(x, y - size / 2, x, y + size / 2)
    # Small dot at center
    c.circle(x, y, 1.5, fill=1)


def draw_grid(c: canvas.Canvas, step: int = 50):
    """Draw a coordinate grid for reference."""
    c.saveState()
    c.setStrokeColor(blue)
    c.setStrokeAlpha(0.15)
    c.setLineWidth(0.5)

    # Vertical lines
    for x in range(0, int(PAGE_W) + 1, step):
        c.line(x, 0, x, PAGE_H)

    # Horizontal lines
    for y in range(0, int(PAGE_H) + 1, step):
        c.line(0, y, PAGE_W, y)

    # Draw coordinate labels
    c.setFillColor(blue)
    c.setFillAlpha(0.5)
    c.setFont("Helvetica", 6)

    # X-axis labels (at bottom)
    for x in range(0, int(PAGE_W) + 1, step):
        c.drawString(x + 2, 5, str(x))

    # Y-axis labels (y-down values, at left side)
    for y in range(0, int(PAGE_H) + 1, step):
        y_down = int(PAGE_H - y)
        c.drawString(2, y + 2, str(y_down))

    c.restoreState()


def create_debug_overlay(coords: dict, show_grid: bool = False) -> bytes:
    """Create an overlay PDF with crosshairs and labels at each coordinate."""
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)

    # Draw optional grid first (so it's behind the crosshairs)
    if show_grid:
        draw_grid(c)

    for key, info in coords.items():
        # Skip comment entries
        if key.startswith("_"):
            continue

        x = info.get("x")
        y_fitz = info.get("y")
        if x is None or y_fitz is None:
            continue

        # Convert to reportlab y
        y = fitz_to_rl_y(y_fitz)

        # Draw crosshair
        draw_crosshair(c, x, y)

        # Draw label (small text next to crosshair)
        c.setFont("Helvetica", 5)
        c.setFillColor(red)
        # Truncate long key names
        label = key[:18] + ".." if len(key) > 18 else key
        # Position label to the right and slightly above
        c.drawString(x + 8, y + 2, label)

        # Also draw the raw coordinates
        c.setFont("Helvetica", 4)
        c.setFillColor(green)
        c.drawString(x + 8, y - 5, f"({x}, {y_fitz})")

    c.showPage()
    c.save()
    packet.seek(0)
    return packet.getvalue()


def merge_overlay_with_template(template_path: Path, overlay_bytes: bytes) -> bytes:
    """Merge debug overlay onto template PDF."""
    template_reader = PdfReader(str(template_path))
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))

    writer = PdfWriter()

    # Get template page and merge debug overlay
    page = template_reader.pages[0]
    page.merge_page(overlay_reader.pages[0])
    writer.add_page(page)

    # Write merged PDF to bytes
    output = io.BytesIO()
    writer.write(output)
    output.seek(0)
    return output.getvalue()


def generate_debug_pdf(form_type: str, output_path: str, show_grid: bool = False):
    """Generate a debug PDF with coordinate markers."""
    # Normalize form type (allow "1099s", "1099-s", etc.)
    form_key = form_type.lower().replace("-", "").replace("1099", "")
    if form_key == "s":
        form_key = "1099s"

    if form_key not in FORMS:
        raise ValueError(f"Unknown form type: {form_type}. Available: {list(FORMS.keys())}")

    form_info = FORMS[form_key]
    template_path = form_info["template"]
    config_path = form_info["config"]

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    # Load config
    with open(config_path, "r") as f:
        config = json.load(f)

    coords = config.get("coords", {})
    if not coords:
        raise ValueError(f"No coordinates found in config: {config_path}")

    coord_count = len([k for k in coords if not k.startswith("_")])
    print(f"Form type: {form_key}")
    print(f"Template: {template_path}")
    print(f"Config: {config_path}")
    print(f"Coordinates: {coord_count} fields")
    print(f"Grid overlay: {'Yes' if show_grid else 'No'}")

    # Create debug overlay
    overlay_bytes = create_debug_overlay(coords, show_grid=show_grid)

    # Merge with template
    pdf_bytes = merge_overlay_with_template(template_path, overlay_bytes)

    # Write output
    output = Path(output_path)
    output.write_bytes(pdf_bytes)
    print(f"Generated: {output} ({len(pdf_bytes)} bytes)")


def main():
    parser = argparse.ArgumentParser(
        description="Generate debug PDF with coordinate crosshairs for form field tuning"
    )
    parser.add_argument(
        "--form",
        choices=["1098", "1099s", "misc", "nec"],
        required=True,
        help="Form type to generate debug overlay for"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output PDF path (default: debug_{form}_coords.pdf)"
    )
    parser.add_argument(
        "--grid",
        action="store_true",
        help="Include coordinate grid overlay for easier tuning"
    )

    args = parser.parse_args()

    output_path = args.out or f"debug_{args.form}_coords.pdf"

    try:
        generate_debug_pdf(args.form, output_path, show_grid=args.grid)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
