"""
1099 PDF Generator.

Generates printable 1099-NEC and 1099-MISC forms using ReportLab.
Forms match official IRS layout for Copy B (Recipient's copy).
"""

from io import BytesIO
from typing import Optional
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


def format_tin(tin: str, tin_type: str = "SSN") -> str:
    """Format TIN for display (XXX-XX-XXXX for SSN, XX-XXXXXXX for EIN)."""
    if not tin:
        return ""
    clean = tin.replace("-", "").replace(" ", "")
    if tin_type == "EIN" and len(clean) == 9:
        return f"{clean[:2]}-{clean[2:]}"
    elif len(clean) == 9:
        return f"{clean[:3]}-{clean[3:5]}-{clean[5:]}"
    return tin


def format_money(amount: Optional[Decimal]) -> str:
    """Format amount as money string."""
    if amount is None or amount == 0:
        return ""
    return f"{float(amount):,.2f}"


def generate_1099_nec_pdf(
    # Payer (Filer) info - THIS IS THE CLIENT/RECIPIENT OF THE 1099
    payer_name: str,
    payer_address: str,
    payer_city_state_zip: str,
    payer_tin: str,
    # Recipient info - THIS IS THE COMPANY PAYING (confusing IRS terminology)
    recipient_name: str,
    recipient_address: str,
    recipient_city_state_zip: str,
    recipient_tin: str,
    # Optional parameters
    payer_phone: str = "",
    recipient_tin_type: str = "SSN",
    recipient_account: str = "",
    # Form data
    tax_year: int = 2024,
    box1_compensation: Decimal = Decimal("0"),
    box4_federal_withheld: Decimal = Decimal("0"),
    box5_state_withheld: Decimal = Decimal("0"),
    box6_state_payer_no: str = "",
    box7_state_income: Decimal = Decimal("0"),
    # Options
    copy_type: str = "B",  # B=Recipient, C=Payer, 1=State, 2=Extra
    corrected: bool = False,
) -> bytes:
    """
    Generate a 1099-NEC PDF form matching official IRS layout.

    Note on terminology (per IRS):
    - PAYER = The person/company in the top-left box (who PAID the money)
    - RECIPIENT = The person/company who RECEIVED the money and gets the 1099

    Returns PDF as bytes.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Constants for positioning (matching IRS form layout)
    LEFT_MARGIN = 0.3 * inch
    TOP_MARGIN = height - 0.3 * inch
    FORM_WIDTH = 5.2 * inch  # Main form area width
    RIGHT_COL_X = 5.6 * inch  # Right column start

    # Line weights
    THICK_LINE = 1.0
    THIN_LINE = 0.5

    c.setLineWidth(THIN_LINE)

    # =========================================================================
    # TOP ROW: PAYER box (left) | Form ID box (center-right) | CORRECTED/Title (right)
    # =========================================================================

    # PAYER'S name box - top left (large box)
    payer_box_top = TOP_MARGIN
    payer_box_height = 1.5 * inch
    payer_box_width = 3.8 * inch

    c.setStrokeColor(colors.black)
    c.rect(LEFT_MARGIN, payer_box_top - payer_box_height, payer_box_width, payer_box_height)

    # Payer label
    c.setFont("Helvetica", 6)
    c.drawString(LEFT_MARGIN + 3, payer_box_top - 8,
                 "PAYER'S name, street address, city or town, state or province, country, ZIP or")
    c.drawString(LEFT_MARGIN + 3, payer_box_top - 15, "foreign postal code, and telephone no.")

    # Payer info (this is actually the FILER - who pays)
    c.setFont("Helvetica-Bold", 10)
    y_pos = payer_box_top - 32
    c.drawString(LEFT_MARGIN + 5, y_pos, payer_name)

    c.setFont("Helvetica", 9)
    y_pos -= 14
    # Split address if needed
    if payer_address:
        c.drawString(LEFT_MARGIN + 5, y_pos, payer_address)
        y_pos -= 12
    c.drawString(LEFT_MARGIN + 5, y_pos, payer_city_state_zip)

    # Phone number at bottom of payer box
    if payer_phone:
        c.setFont("Helvetica", 8)
        c.drawString(LEFT_MARGIN + 5, payer_box_top - payer_box_height + 8, payer_phone)

    # OMB / Form ID box (center-right area)
    omb_box_x = 4.2 * inch
    omb_box_width = 1.3 * inch
    omb_box_height = 0.9 * inch

    c.rect(omb_box_x, payer_box_top - omb_box_height, omb_box_width, omb_box_height)

    c.setFont("Helvetica", 7)
    c.drawString(omb_box_x + 5, payer_box_top - 10, "OMB No. 1545-0116")

    c.setFont("Helvetica-Bold", 8)
    c.drawString(omb_box_x + 5, payer_box_top - 22, f"Form 1099-NEC")

    c.setFont("Helvetica", 7)
    c.drawString(omb_box_x + 5, payer_box_top - 32, "(Rev. January 2024)")

    c.setFont("Helvetica", 7)
    c.drawString(omb_box_x + 5, payer_box_top - 48, "For calendar year")

    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(omb_box_x + omb_box_width / 2, payer_box_top - 75, str(tax_year))

    # CORRECTED checkbox and title (right side)
    right_title_x = 5.6 * inch

    # Corrected checkbox
    c.setFont("Helvetica", 7)
    c.rect(right_title_x, payer_box_top - 12, 8, 8)  # checkbox
    if corrected:
        c.setFont("Helvetica-Bold", 8)
        c.drawString(right_title_x + 2, payer_box_top - 10, "X")
    c.setFont("Helvetica", 7)
    c.drawString(right_title_x + 12, payer_box_top - 10, "CORRECTED")
    c.drawString(right_title_x + 12, payer_box_top - 19, "(if checked)")

    # Form title
    c.setFont("Helvetica-Bold", 11)
    c.drawString(right_title_x, payer_box_top - 38, "Nonemployee")
    c.drawString(right_title_x, payer_box_top - 50, "Compensation")

    # =========================================================================
    # Box 1 - Nonemployee compensation (below OMB box)
    # =========================================================================
    box1_top = payer_box_top - omb_box_height - 0.05 * inch
    box1_height = 0.5 * inch
    box1_width = omb_box_width

    c.rect(omb_box_x, box1_top - box1_height, box1_width, box1_height)

    c.setFont("Helvetica", 6)
    c.drawString(omb_box_x + 3, box1_top - 8, "1 Nonemployee compensation")

    c.setFont("Helvetica-Bold", 11)
    if box1_compensation:
        c.drawString(omb_box_x + 5, box1_top - box1_height + 10, f"$ {format_money(box1_compensation)}")

    # Copy B label (right of box 1)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(right_title_x, box1_top - 20, f"Copy {copy_type}")

    # =========================================================================
    # Box 2 - Direct sales checkbox (below box 1)
    # =========================================================================
    box2_top = box1_top - box1_height - 0.03 * inch
    box2_height = 0.4 * inch

    c.rect(omb_box_x, box2_top - box2_height, box1_width, box2_height)

    c.setFont("Helvetica", 5)
    c.drawString(omb_box_x + 3, box2_top - 7, "2 Payer made direct sales totaling $5,000 or more of")
    c.drawString(omb_box_x + 8, box2_top - 13, "consumer products to recipient for resale")

    # Checkbox for box 2
    c.rect(omb_box_x + box1_width - 15, box2_top - box2_height + 8, 8, 8)

    # "For Recipient" label
    c.setFont("Helvetica-Bold", 11)
    c.drawString(right_title_x, box2_top - 15, "For Recipient")

    # =========================================================================
    # RECIPIENT'S name box (left, below payer)
    # =========================================================================
    recipient_box_top = payer_box_top - payer_box_height - 0.03 * inch
    recipient_box_height = 1.3 * inch
    recipient_box_width = payer_box_width

    c.rect(LEFT_MARGIN, recipient_box_top - recipient_box_height, recipient_box_width, recipient_box_height)

    c.setFont("Helvetica", 6)
    c.drawString(LEFT_MARGIN + 3, recipient_box_top - 8, "RECIPIENT'S name and street address (including apt. no.)")

    # Recipient info
    c.setFont("Helvetica-Bold", 10)
    y_pos = recipient_box_top - 36  # Adjusted down from 24 (total 12 points)
    c.drawString(LEFT_MARGIN + 5, y_pos, recipient_name)

    c.setFont("Helvetica", 9)
    y_pos -= 14
    if recipient_address:
        c.drawString(LEFT_MARGIN + 5, y_pos, recipient_address)
        y_pos -= 12
    c.drawString(LEFT_MARGIN + 5, y_pos, recipient_city_state_zip)

    # =========================================================================
    # Box 3 - Reserved (next to box 2)
    # =========================================================================
    box3_top = box2_top - box2_height - 0.03 * inch
    box3_height = 0.35 * inch

    c.rect(omb_box_x, box3_top - box3_height, box1_width, box3_height)
    c.setFont("Helvetica", 6)
    c.drawString(omb_box_x + 3, box3_top - 8, "3")

    # Right side instructions text (small)
    c.setFont("Helvetica", 6)
    instruction_x = right_title_x
    inst_y = box3_top - 5
    instructions = [
        "This is important tax",
        "information and is being",
        "furnished to",
        "the Internal Revenue",
        "Service. If you are",
        "required to file a return,",
        "a negligence penalty or",
        "other sanction may be",
        "imposed on you if this",
        "income is",
        "taxable and the IRS",
        "determines that it",
        "has not been reported.",
    ]
    for line in instructions:
        c.drawString(instruction_x, inst_y, line)
        inst_y -= 8

    # =========================================================================
    # Box 4 - Federal income tax withheld
    # =========================================================================
    box4_top = box3_top - box3_height - 0.03 * inch
    box4_height = 0.5 * inch

    c.rect(omb_box_x, box4_top - box4_height, box1_width, box4_height)

    c.setFont("Helvetica", 6)
    c.drawString(omb_box_x + 3, box4_top - 8, "4 Federal income tax withheld")

    c.setFont("Helvetica-Bold", 11)
    c.drawString(omb_box_x + 5, box4_top - 20, "$")
    if box4_federal_withheld:
        c.drawString(omb_box_x + 15, box4_top - 20, format_money(box4_federal_withheld))

    # =========================================================================
    # Account number box (below recipient, left side)
    # =========================================================================
    acct_box_top = recipient_box_top - recipient_box_height - 0.03 * inch
    acct_box_height = 0.4 * inch
    acct_box_width = 2.0 * inch

    c.rect(LEFT_MARGIN, acct_box_top - acct_box_height, acct_box_width, acct_box_height)

    c.setFont("Helvetica", 6)
    c.drawString(LEFT_MARGIN + 3, acct_box_top - 8, "Account number (see instructions)")

    if recipient_account:
        c.setFont("Helvetica", 9)
        c.drawString(LEFT_MARGIN + 5, acct_box_top - acct_box_height + 10, recipient_account)

    # =========================================================================
    # Boxes 5, 6, 7 - State info (below box 4, and next to account number)
    # =========================================================================
    state_row_top = box4_top - box4_height - 0.03 * inch
    state_box_height = 0.4 * inch

    # Box 5 - State tax withheld
    box5_width = 1.0 * inch
    box5_x = acct_box_width + LEFT_MARGIN + 0.03 * inch

    c.rect(box5_x, state_row_top - state_box_height, box5_width, state_box_height)
    c.setFont("Helvetica", 6)
    c.drawString(box5_x + 3, state_row_top - 8, "5  State tax withheld")
    c.setFont("Helvetica", 9)
    c.drawString(box5_x + 5, state_row_top - 20, "$")
    if box5_state_withheld:
        c.drawString(box5_x + 15, state_row_top - 20, format_money(box5_state_withheld))

    # Box 6 - State/Payer's state no.
    box6_width = 1.2 * inch
    box6_x = box5_x + box5_width + 0.03 * inch

    c.rect(box6_x, state_row_top - state_box_height, box6_width, state_box_height)
    c.setFont("Helvetica", 6)
    c.drawString(box6_x + 3, state_row_top - 8, "6 State/Payer's state no.")
    if box6_state_payer_no:
        c.setFont("Helvetica", 8)
        c.drawString(box6_x + 5, state_row_top - state_box_height + 10, box6_state_payer_no)

    # =========================================================================
    # PAYER'S TIN and RECIPIENT'S TIN boxes (below account number)
    # =========================================================================
    tin_row_top = acct_box_top - acct_box_height - 0.03 * inch
    tin_box_height = 0.4 * inch
    tin_box_width = 1.5 * inch

    # Payer's TIN
    c.rect(LEFT_MARGIN, tin_row_top - tin_box_height, tin_box_width, tin_box_height)
    c.setFont("Helvetica", 6)
    c.drawString(LEFT_MARGIN + 3, tin_row_top - 8, "PAYER'S TIN")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(LEFT_MARGIN + 5, tin_row_top - tin_box_height + 10, format_tin(payer_tin, "EIN"))

    # Recipient's TIN
    recip_tin_x = LEFT_MARGIN + tin_box_width + 0.03 * inch
    c.rect(recip_tin_x, tin_row_top - tin_box_height, tin_box_width, tin_box_height)
    c.setFont("Helvetica", 6)
    c.drawString(recip_tin_x + 3, tin_row_top - 8, "RECIPIENT'S TIN")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(recip_tin_x + 5, tin_row_top - tin_box_height + 10, format_tin(recipient_tin, recipient_tin_type))

    # Box 7 - State income (aligned with TIN row)
    box7_width = omb_box_width
    box7_x = omb_box_x

    c.rect(box7_x, tin_row_top - tin_box_height, box7_width, tin_box_height)
    c.setFont("Helvetica", 6)
    c.drawString(box7_x + 3, tin_row_top - 8, "7 State income")
    c.setFont("Helvetica", 9)
    c.drawString(box7_x + 5, tin_row_top - 20, "$")
    if box7_state_income:
        c.drawString(box7_x + 15, tin_row_top - 20, format_money(box7_state_income))

    # =========================================================================
    # Form footer line
    # =========================================================================
    footer_y = tin_row_top - tin_box_height - 0.15 * inch

    c.setFont("Helvetica-Bold", 8)
    c.drawString(LEFT_MARGIN, footer_y, "Form 1099-NEC")

    c.setFont("Helvetica", 7)
    c.drawString(LEFT_MARGIN + 1.0 * inch, footer_y, "(Rev. 1-2024)")
    c.drawString(LEFT_MARGIN + 1.8 * inch, footer_y, "(keep for your records)")
    c.drawString(LEFT_MARGIN + 3.2 * inch, footer_y, "www.irs.gov/Form1099NEC")

    c.setFont("Helvetica", 6)
    c.drawString(4.5 * inch, footer_y, "Department of the Treasury - Internal Revenue Service")

    # =========================================================================
    # Instructions section (bottom half of page)
    # =========================================================================
    inst_top = footer_y - 0.3 * inch
    c.setLineWidth(THICK_LINE)
    c.line(LEFT_MARGIN, inst_top, width - LEFT_MARGIN, inst_top)

    c.setFont("Helvetica-Bold", 8)
    c.drawString(LEFT_MARGIN, inst_top - 12, "Instructions for Recipient")

    c.setFont("Helvetica", 6)
    inst_text = [
        "You received this form instead of Form W-2 because the payer did not consider you",
        "an employee and did not withhold income tax or social security and Medicare tax.",
        "   If you believe you are an employee and cannot get the payer to correct this form,",
        "report the amount shown in box 1 on the line for \"Wages, salaries, tips, etc.\" of Form",
        "1040, 1040-SR, or 1040-NR. You must also complete Form 8919 and attach it to",
        "your return. For more information, see Pub. 1779, Independent Contractor or",
        "Employee.",
        "   If you are not an employee but the amount in box 1 is not self-employment (SE)",
        "income (for example, it is income from a sporadic activity or a hobby), report the",
        "amount shown in box 1 on the \"Other income\" line (on Schedule 1 (Form 1040)).",
        "Recipient's taxpayer identification number (TIN). For your protection, this form",
        "may show only the last four digits of your TIN (social security number (SSN),",
        "individual taxpayer identification number (ITIN), adoption taxpayer identification",
        "number (ATIN), or employer identification number (EIN)). However, the issuer has",
        "reported your complete TIN to the IRS.",
        "Account number. May show an account or other unique number the payer",
        "assigned to distinguish your account.",
        "Box 1. Shows nonemployee compensation. If the amount in this box is SE income,",
        "report it on Schedule C or F (Form 1040) if a sole proprietor, or on Form 1065 and",
        "Schedule K-1 (Form 1065) if a partnership, and the recipient/partner completes",
        "Schedule SE (Form 1040).",
    ]

    y = inst_top - 24
    for line in inst_text:
        c.drawString(LEFT_MARGIN, y, line)
        y -= 8

    # Right column instructions
    right_inst_x = 4.0 * inch
    right_inst = [
        "Note: If you are receiving payments on which no income, social security, and",
        "Medicare taxes are withheld, you should make estimated tax payments. See Form",
        "1040-ES (or Form 1040-ES (NR)). Individuals must report these amounts as",
        "explained in these box 1 instructions. Corporations, fiduciaries, and partnerships",
        "must report these amounts on the appropriate line of their tax returns.",
        "Box 2. If checked, consumer products totaling $5,000 or more were sold to you for",
        "resale, on a buy-sell, a deposit-commission, or other basis. Generally, report any",
        "income from your sale of these products on Schedule C (Form 1040).",
        "Box 3. Reserved for future use.",
        "Box 4. Shows backup withholding. A payer must backup withhold on certain",
        "payments if you did not give your TIN to the payer. See Form W-9, Request for",
        "Taxpayer Identification Number and Certification, for information on backup",
        "withholding. Include this amount on your income tax return as tax withheld.",
        "Boxes 5-7. State income tax withheld reporting boxes.",
        "Future developments. For the latest information about developments related to",
        "Form 1099-NEC and its instructions, such as legislation enacted after they were",
        "published, go to www.irs.gov/Form1099NEC.",
        "Free File Program. Go to www.irs.gov/FreeFile to see if you qualify for no-cost",
        "online federal tax preparation, e-filing, and direct deposit or payment options.",
    ]

    y = inst_top - 24
    for line in right_inst:
        c.drawString(right_inst_x, y, line)
        y -= 8

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def generate_1099_misc_pdf(
    # Payer (Filer) info
    payer_name: str,
    payer_address: str,
    payer_city_state_zip: str,
    payer_tin: str,
    # Recipient info
    recipient_name: str,
    recipient_address: str,
    recipient_city_state_zip: str,
    recipient_tin: str,
    # Optional parameters
    payer_phone: str = "",
    recipient_tin_type: str = "SSN",
    recipient_account: str = "",
    # Form data - boxes
    tax_year: int = 2024,
    box1_rents: Decimal = Decimal("0"),
    box2_royalties: Decimal = Decimal("0"),
    box3_other_income: Decimal = Decimal("0"),
    box4_federal_withheld: Decimal = Decimal("0"),
    box5_fishing_boat: Decimal = Decimal("0"),
    box6_medical: Decimal = Decimal("0"),
    box7_payer_direct_sales: bool = False,
    box8_substitute_payments: Decimal = Decimal("0"),
    box9_crop_insurance: Decimal = Decimal("0"),
    box10_gross_proceeds: Decimal = Decimal("0"),
    box11_fish_purchased: Decimal = Decimal("0"),
    box12_section_409a: Decimal = Decimal("0"),
    box14_excess_golden: Decimal = Decimal("0"),
    # State info
    box15_state_withheld: Decimal = Decimal("0"),
    box16_state_id: str = "",
    box17_state_income: Decimal = Decimal("0"),
    state_code: str = "",
    # Options
    copy_type: str = "B",
    corrected: bool = False,
) -> bytes:
    """
    Generate a 1099-MISC PDF form.
    TODO: Update to match official IRS layout like 1099-NEC.
    """
    # For now, generate a simplified version
    # This should be updated to match official IRS 1099-MISC layout
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    LEFT_MARGIN = 0.3 * inch
    TOP_MARGIN = height - 0.3 * inch

    # Title
    c.setFont("Helvetica-Bold", 14)
    c.drawString(LEFT_MARGIN, TOP_MARGIN - 20, f"Form 1099-MISC - Tax Year {tax_year}")
    c.setFont("Helvetica", 10)
    c.drawString(LEFT_MARGIN, TOP_MARGIN - 35, "Miscellaneous Information")
    c.drawString(LEFT_MARGIN, TOP_MARGIN - 50, f"Copy {copy_type} - For Recipient")

    if corrected:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(5 * inch, TOP_MARGIN - 20, "CORRECTED")

    # Payer info
    y = TOP_MARGIN - 80
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LEFT_MARGIN, y, "PAYER:")
    c.setFont("Helvetica", 9)
    y -= 12
    c.drawString(LEFT_MARGIN, y, payer_name)
    y -= 12
    c.drawString(LEFT_MARGIN, y, payer_address)
    y -= 12
    c.drawString(LEFT_MARGIN, y, payer_city_state_zip)
    y -= 12
    c.drawString(LEFT_MARGIN, y, f"TIN: {format_tin(payer_tin, 'EIN')}")

    # Recipient info
    y -= 25
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LEFT_MARGIN, y, "RECIPIENT:")
    c.setFont("Helvetica", 9)
    y -= 12
    c.drawString(LEFT_MARGIN, y, recipient_name)
    y -= 12
    c.drawString(LEFT_MARGIN, y, recipient_address)
    y -= 12
    c.drawString(LEFT_MARGIN, y, recipient_city_state_zip)
    y -= 12
    c.drawString(LEFT_MARGIN, y, f"TIN: {format_tin(recipient_tin, recipient_tin_type)}")

    # Amounts
    y -= 30
    c.setFont("Helvetica-Bold", 9)
    c.drawString(LEFT_MARGIN, y, "AMOUNTS:")

    amounts = [
        ("1. Rents", box1_rents),
        ("2. Royalties", box2_royalties),
        ("3. Other income", box3_other_income),
        ("4. Federal income tax withheld", box4_federal_withheld),
        ("5. Fishing boat proceeds", box5_fishing_boat),
        ("6. Medical and health care payments", box6_medical),
        ("8. Substitute payments", box8_substitute_payments),
        ("9. Crop insurance proceeds", box9_crop_insurance),
        ("10. Gross proceeds to attorney", box10_gross_proceeds),
        ("11. Fish purchased for resale", box11_fish_purchased),
        ("12. Section 409A deferrals", box12_section_409a),
        ("14. Excess golden parachute", box14_excess_golden),
    ]

    c.setFont("Helvetica", 9)
    for label, amount in amounts:
        if amount:
            y -= 12
            c.drawString(LEFT_MARGIN + 10, y, f"{label}: ${format_money(amount)}")

    # State info
    if box15_state_withheld or box17_state_income:
        y -= 20
        c.setFont("Helvetica-Bold", 9)
        c.drawString(LEFT_MARGIN, y, "STATE INFO:")
        c.setFont("Helvetica", 9)
        if box15_state_withheld:
            y -= 12
            c.drawString(LEFT_MARGIN + 10, y, f"15. State tax withheld: ${format_money(box15_state_withheld)}")
        if box16_state_id:
            y -= 12
            c.drawString(LEFT_MARGIN + 10, y, f"16. State/Payer's state no.: {state_code} {box16_state_id}")
        if box17_state_income:
            y -= 12
            c.drawString(LEFT_MARGIN + 10, y, f"17. State income: ${format_money(box17_state_income)}")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def generate_1099_pdf(form_data: dict, filer_data: dict, recipient_data: dict, copy_type: str = "B") -> bytes:
    """
    Generate appropriate 1099 PDF based on form type.

    Args:
        form_data: Form record from forms_1099 table
        filer_data: Filer record from filers table (the PAYER - who pays)
        recipient_data: Recipient record from recipients table (who receives the 1099)
        copy_type: B=Recipient, C=Payer, 1=State, 2=Extra

    Returns:
        PDF bytes
    """
    form_type = form_data.get("form_type", "1099-NEC")
    tax_year = form_data.get("tax_year", 2024)

    # Build addresses
    filer_address = filer_data.get("address1", "")
    if filer_data.get("address2"):
        filer_address += f", {filer_data['address2']}"
    filer_city_state_zip = f"{filer_data.get('city', '')}, {filer_data.get('state', '')} {filer_data.get('zip', '')}"

    recipient_address = recipient_data.get("address1", "")
    if recipient_data.get("address2"):
        recipient_address += f", {recipient_data['address2']}"
    recipient_city_state_zip = f"{recipient_data.get('city', '')}, {recipient_data.get('state', '')} {recipient_data.get('zip', '')}"

    if form_type == "1099-NEC":
        return generate_1099_nec_pdf(
            # Payer = Filer (who pays the money)
            payer_name=filer_data.get("name", ""),
            payer_address=filer_address,
            payer_city_state_zip=filer_city_state_zip,
            payer_tin=filer_data.get("tin", ""),
            payer_phone=filer_data.get("phone", ""),
            # Recipient = who receives the 1099
            recipient_name=recipient_data.get("name", ""),
            recipient_address=recipient_address,
            recipient_city_state_zip=recipient_city_state_zip,
            recipient_tin=recipient_data.get("tin", ""),
            recipient_tin_type=recipient_data.get("tin_type", "SSN"),
            recipient_account=recipient_data.get("account_number", ""),
            tax_year=tax_year,
            box1_compensation=Decimal(str(form_data.get("nec_box1", 0) or 0)),
            box4_federal_withheld=Decimal(str(form_data.get("nec_box4", 0) or 0)),
            box5_state_withheld=Decimal(str(form_data.get("state1_withheld", 0) or 0)),
            box6_state_payer_no=f"{form_data.get('state1_code', '')} {form_data.get('state1_id', '')}".strip(),
            box7_state_income=Decimal(str(form_data.get("state1_income", 0) or 0)),
            copy_type=copy_type,
            corrected=form_data.get("is_correction", False),
        )

    elif form_type == "1099-MISC":
        return generate_1099_misc_pdf(
            payer_name=filer_data.get("name", ""),
            payer_address=filer_address,
            payer_city_state_zip=filer_city_state_zip,
            payer_tin=filer_data.get("tin", ""),
            payer_phone=filer_data.get("phone", ""),
            recipient_name=recipient_data.get("name", ""),
            recipient_address=recipient_address,
            recipient_city_state_zip=recipient_city_state_zip,
            recipient_tin=recipient_data.get("tin", ""),
            recipient_tin_type=recipient_data.get("tin_type", "SSN"),
            recipient_account=recipient_data.get("account_number", ""),
            tax_year=tax_year,
            box1_rents=Decimal(str(form_data.get("misc_box1", 0) or 0)),
            box2_royalties=Decimal(str(form_data.get("misc_box2", 0) or 0)),
            box3_other_income=Decimal(str(form_data.get("misc_box3", 0) or 0)),
            box4_federal_withheld=Decimal(str(form_data.get("misc_box4", 0) or 0)),
            box5_fishing_boat=Decimal(str(form_data.get("misc_box5", 0) or 0)),
            box6_medical=Decimal(str(form_data.get("misc_box6", 0) or 0)),
            box7_payer_direct_sales=form_data.get("misc_box7", False),
            box8_substitute_payments=Decimal(str(form_data.get("misc_box8", 0) or 0)),
            box9_crop_insurance=Decimal(str(form_data.get("misc_box9", 0) or 0)),
            box10_gross_proceeds=Decimal(str(form_data.get("misc_box10", 0) or 0)),
            box11_fish_purchased=Decimal(str(form_data.get("misc_box11", 0) or 0)),
            box12_section_409a=Decimal(str(form_data.get("misc_box12", 0) or 0)),
            box14_excess_golden=Decimal(str(form_data.get("misc_box14", 0) or 0)),
            box15_state_withheld=Decimal(str(form_data.get("state1_withheld", 0) or 0)),
            box16_state_id=form_data.get("state1_id", "") or "",
            box17_state_income=Decimal(str(form_data.get("state1_income", 0) or 0)),
            state_code=form_data.get("state1_code", "") or "",
            copy_type=copy_type,
            corrected=form_data.get("is_correction", False),
        )

    else:
        raise ValueError(f"Unsupported form type: {form_type}")


# Test function
if __name__ == "__main__":
    from decimal import Decimal

    pdf_bytes = generate_1099_nec_pdf(
        payer_name="Euguene Baldwin",
        payer_address="280 High Ridge Dr",
        payer_city_state_zip="Athens, GA 30606",
        payer_tin="420-52-8244",
        payer_phone="706-549-6503",
        recipient_name="Arnolds Home Healthcare LLC",
        recipient_address="Patricia Arnold",
        recipient_city_state_zip="875 Belmont Rd\nAthens, GA 30605",
        recipient_tin="XX-XXX2488",
        recipient_tin_type="EIN",
        recipient_account="EFM3993900",
        tax_year=2024,
        box1_compensation=Decimal("118734.00"),
        copy_type="B",
    )

    with open("test_1099_nec.pdf", "wb") as f:
        f.write(pdf_bytes)
    print(f"Generated test_1099_nec.pdf ({len(pdf_bytes)} bytes)")
