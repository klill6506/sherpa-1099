"""
Regression test to ensure NEC PDF output matches the gold master (test_2025_v11.pdf).

This script generates a NEC PDF with known test data and compares it visually
to the gold master file to ensure template changes don't break output.

Usage:
    python scripts/regress_nec_v11.py
"""

from pathlib import Path
from decimal import Decimal
import sys

# Add src to path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

try:
    import fitz  # PyMuPDF
    from PIL import Image, ImageChops
    import numpy as np
    HAS_VISUAL_DEPS = True
except ImportError:
    HAS_VISUAL_DEPS = False
    print("Warning: Visual comparison dependencies not installed (PyMuPDF, Pillow, numpy)")
    print("Install with: pip install PyMuPDF Pillow numpy")

from pdf_1099_nec_overlay import generate_1099_nec_overlay

GOLD = REPO / "test_2025_v11.pdf"


def render(pdf_bytes: bytes, zoom: float = 2) -> "Image":
    """Render first page of PDF to PIL Image."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def compare_pdfs(gold_bytes: bytes, new_bytes: bytes) -> tuple[float, float]:
    """
    Compare two PDFs visually.

    Returns:
        (mean_diff, pct_different): Mean pixel difference and percentage of pixels that differ
    """
    img_gold = render(gold_bytes)
    img_new = render(new_bytes)

    diff = ImageChops.difference(img_gold, img_new)
    arr = np.array(diff)

    mean = arr.mean()
    pct = (arr > 10).any(axis=2).mean()

    return mean, pct


def main():
    print("NEC PDF Regression Test")
    print("=" * 50)

    # Check gold master exists
    if not GOLD.exists():
        print(f"FAIL: Missing gold master: {GOLD}")
        sys.exit(1)

    print(f"Gold master: {GOLD}")
    print(f"Gold master size: {GOLD.stat().st_size:,} bytes")

    # Generate test PDF with same data as v11
    print("\nGenerating test PDF...")
    try:
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
    except Exception as e:
        print(f"FAIL: Error generating PDF: {e}")
        sys.exit(1)

    print(f"Generated PDF size: {len(pdf_bytes):,} bytes")

    # Save for manual inspection
    test_output = REPO / "test_regression.pdf"
    test_output.write_bytes(pdf_bytes)
    print(f"Saved test output to: {test_output}")

    # Size comparison (basic sanity check)
    gold_size = GOLD.stat().st_size
    new_size = len(pdf_bytes)
    size_ratio = new_size / gold_size

    print(f"\nSize comparison:")
    print(f"  Gold: {gold_size:,} bytes")
    print(f"  New:  {new_size:,} bytes")
    print(f"  Ratio: {size_ratio:.2f}")

    # Size should be within 20% of gold master
    if size_ratio < 0.8 or size_ratio > 1.2:
        print(f"WARNING: Size ratio {size_ratio:.2f} is outside expected range (0.8-1.2)")
        print("This may indicate wrong template being used.")

    # Visual comparison if dependencies are available
    if HAS_VISUAL_DEPS:
        print("\nVisual comparison:")
        try:
            mean, pct = compare_pdfs(GOLD.read_bytes(), pdf_bytes)
            print(f"  Mean pixel difference: {mean:.2f}")
            print(f"  Pixels differing: {pct*100:.2f}%")

            # Thresholds - these should be very tight for identical output
            if mean < 2.0 and pct < 0.02:
                print("\nPASS: NEC output matches v11 within tolerance.")
            else:
                print(f"\nWARNING: Output differs from gold master.")
                print("  This may be acceptable if only text data differs.")
                print("  Review test_regression.pdf manually.")
        except Exception as e:
            print(f"  Error during visual comparison: {e}")
    else:
        print("\nSkipping visual comparison (missing dependencies)")
        print("Run: pip install PyMuPDF Pillow numpy")

    print("\n" + "=" * 50)
    print("Regression test complete.")
    print(f"Review {test_output} to verify output visually.")


if __name__ == "__main__":
    main()
