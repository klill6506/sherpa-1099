"""
1099-S Test Generator.

Generates a sample 1099-S PDF for testing and coordinate verification.

Usage:
    python tools/gen_1099s.py --out test_1099s.pdf
    python tools/gen_1099s.py --out test_1099s.pdf --checkbox  # Test with checkboxes
"""

import argparse
from decimal import Decimal
from pathlib import Path
import sys

# Add src to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pdf_1099_s_overlay import generate_1099s_copyb


def generate_test_pdf(output_path: str, test_checkboxes: bool = False):
    """Generate a test 1099-S PDF with sample data."""

    # Sample data matching what's in the config
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
        box3_property_description="123 Maple Street, Anytown, GA 30301\nLot 15, Block 3, Sunshine Subdivision\nParcel ID: 12-34-56-789",
        box4_property_services=test_checkboxes,  # Test checkbox
        box5_foreign=False,
        box6_buyers_tax=Decimal("2500.00"),
        mask_transferor_tin=True,  # Mask for Copy B
    )

    output = Path(output_path)
    output.write_bytes(pdf_bytes)
    print(f"Generated: {output} ({len(pdf_bytes)} bytes)")
    print()
    print("Test data used:")
    print(f"  Filer: ABC Title Company")
    print(f"  Filer TIN: 58-1234567")
    print(f"  Transferor: John Q. Seller")
    print(f"  Transferor TIN: ***-**-6789 (masked)")
    print(f"  Date of Closing: 01/15/2025")
    print(f"  Gross Proceeds: $350,000.00")
    print(f"  Property: 123 Maple Street... (multi-line)")
    print(f"  Box 4 (Property/Services): {'X' if test_checkboxes else 'unchecked'}")
    print(f"  Box 6 (Buyer's Tax): $2,500.00")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a test 1099-S PDF with sample data"
    )
    parser.add_argument(
        "--out",
        default="test_1099s.pdf",
        help="Output PDF path (default: test_1099s.pdf)"
    )
    parser.add_argument(
        "--checkbox",
        action="store_true",
        help="Test with Box 4 checkbox checked"
    )

    args = parser.parse_args()

    try:
        generate_test_pdf(args.out, test_checkboxes=args.checkbox)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
