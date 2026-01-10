"""
1098 Test Generator.

Generates a sample 1098 PDF for testing and coordinate verification.

Usage:
    python tools/gen_1098.py --out test_1098.pdf
"""

import argparse
from decimal import Decimal
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pdf_1098_overlay import generate_1098_copyb


def generate_test_pdf(output_path: str):
    """Generate a test 1098 PDF with sample data."""

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
        box4_refund_interest=Decimal("0"),
        box5_mortgage_insurance=Decimal("1200.00"),
        box6_points_paid=Decimal("0"),
        box8_property_address="",
        box9_num_properties="",
        box10_other=Decimal("0"),
        box11_acquisition_date="",
        mask_payer_tin=True,
    )

    output = Path(output_path)
    output.write_bytes(pdf_bytes)
    print(f"Generated: {output} ({len(pdf_bytes)} bytes)")
    print()
    print("Test data used:")
    print(f"  Recipient: ABC Mortgage Company")
    print(f"  Recipient TIN: 58-1234567")
    print(f"  Payer: John Q. Homeowner")
    print(f"  Payer TIN: ***-**-6789 (masked)")
    print(f"  Box 1 (Mortgage Interest): $12,500.00")
    print(f"  Box 2 (Outstanding Principal): $285,000.00")
    print(f"  Box 3 (Origination Date): 03/15/2020")
    print(f"  Box 5 (Mortgage Insurance): $1,200.00")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a test 1098 PDF with sample data"
    )
    parser.add_argument(
        "--out",
        default="test_1098.pdf",
        help="Output PDF path (default: test_1098.pdf)"
    )

    args = parser.parse_args()

    try:
        generate_test_pdf(args.out)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
