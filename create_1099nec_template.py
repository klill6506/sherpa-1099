#!/usr/bin/env python3
"""
Create a blank 1099-NEC Copy B template from scratch using reportlab.
Sized to fit in 9x5.5" envelope with windows.

Window positions (from envelope specs):
- 0.5" from left edge
- Recipient window bottom: 1.5" from bottom of envelope

When letter paper (8.5x11) is tri-folded into envelope:
- Top third shows through top window (payer)
- Middle third shows through bottom window (recipient)
"""

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import black, white, HexColor

PAGE_W, PAGE_H = letter  # 612 x 792 points (8.5" x 11")

# Light gray for form boxes
LIGHT_GRAY = HexColor("#E6E6E6")


def draw_text(c, text, x, y, size=8, bold=False):
    """Draw text at position."""
    font = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font, size)
    c.drawString(x, y, text)


def create_1099nec_template(output_path, year="2025"):
    """Create blank 1099-NEC template."""
    c = canvas.Canvas(output_path, pagesize=letter)
    c.setStrokeColor(black)
    c.setLineWidth(0.5)

    # === FORM DIMENSIONS ===
    LEFT_MARGIN = 0.4 * inch
    FORM_WIDTH = 7.6 * inch

    # Form positioning
    FORM_TOP = PAGE_H - 0.5 * inch
    form_height = 4.5 * inch
    form_bottom = FORM_TOP - form_height

    # Left column (payer/recipient) width
    left_col_width = 4.0 * inch
    right_col_left = LEFT_MARGIN + left_col_width
    right_col_width = FORM_WIDTH - left_col_width

    # === OUTER BORDER ===
    c.setLineWidth(1)
    c.rect(LEFT_MARGIN, form_bottom, FORM_WIDTH, form_height)
    c.setLineWidth(0.5)

    # === CORRECTED CHECKBOX (above form) ===
    checkbox_x = LEFT_MARGIN + FORM_WIDTH - 1.6 * inch
    checkbox_y = FORM_TOP + 8
    c.rect(checkbox_x, checkbox_y, 8, 8)
    draw_text(c, "CORRECTED (if checked)", checkbox_x + 12, checkbox_y + 1, 7)

    # === HEADER BOX (OMB, Form, Year) - top right inside form ===
    header_left = LEFT_MARGIN + 4.0 * inch
    header_width = 1.4 * inch
    header_top = FORM_TOP

    # OMB box (gray)
    c.setFillColor(LIGHT_GRAY)
    c.rect(header_left, header_top - 0.20*inch, header_width, 0.20*inch, fill=1, stroke=1)
    c.setFillColor(black)
    draw_text(c, "OMB No. 1545-0116", header_left + 8, header_top - 0.15*inch, 7)

    # Form 1099-NEC box
    c.rect(header_left, header_top - 0.45*inch, header_width, 0.25*inch, stroke=1)
    draw_text(c, "Form 1099-NEC", header_left + 12, header_top - 0.36*inch, 10, bold=True)

    # Rev date (no box)
    draw_text(c, "(Rev. April 2025)", header_left + 20, header_top - 0.56*inch, 7)

    # For calendar year box
    c.rect(header_left, header_top - 0.75*inch, header_width, 0.15*inch, stroke=1)
    draw_text(c, "For calendar year", header_left + 22, header_top - 0.70*inch, 7)

    # Year box with year
    c.setLineWidth(1)
    c.rect(header_left, header_top - 1.0*inch, header_width, 0.25*inch, stroke=1)
    c.setLineWidth(0.5)
    draw_text(c, year, header_left + 45, header_top - 0.92*inch, 16, bold=True)

    # === TITLE (right of header) ===
    title_left = header_left + header_width + 0.15*inch
    draw_text(c, "Nonemployee", title_left, header_top - 0.28*inch, 12, bold=True)
    draw_text(c, "Compensation", title_left, header_top - 0.48*inch, 12, bold=True)
    draw_text(c, "Copy B", title_left + 0.55*inch, header_top - 0.72*inch, 12, bold=True)
    draw_text(c, "For Recipient", title_left + 0.25*inch, header_top - 0.92*inch, 10, bold=True)

    # === PAYER BOX (top-left, large for envelope window) ===
    payer_top = FORM_TOP
    payer_height = 1.15 * inch
    payer_bottom = payer_top - payer_height

    c.rect(LEFT_MARGIN, payer_bottom, left_col_width, payer_height)
    draw_text(c, "PAYER'S name, street address, city or town, state or province, country, ZIP",
              LEFT_MARGIN + 3, payer_top - 10, 6)
    draw_text(c, "or foreign postal code, and telephone no.", LEFT_MARGIN + 3, payer_top - 19, 6)

    # === PAYER TIN / RECIPIENT TIN ROW ===
    tin_top = payer_bottom
    tin_height = 0.30 * inch
    tin_bottom = tin_top - tin_height
    payer_tin_width = 2.0 * inch

    # Payer TIN
    c.rect(LEFT_MARGIN, tin_bottom, payer_tin_width, tin_height)
    draw_text(c, "PAYER'S TIN", LEFT_MARGIN + 3, tin_top - 10, 6)

    # Recipient TIN
    c.rect(LEFT_MARGIN + payer_tin_width, tin_bottom, left_col_width - payer_tin_width, tin_height)
    draw_text(c, "RECIPIENT'S TIN", LEFT_MARGIN + payer_tin_width + 3, tin_top - 10, 6)

    # === RECIPIENT NAME BOX ===
    recip_name_top = tin_bottom
    recip_name_height = 0.35 * inch
    recip_name_bottom = recip_name_top - recip_name_height

    c.rect(LEFT_MARGIN, recip_name_bottom, left_col_width, recip_name_height)
    draw_text(c, "RECIPIENT'S name", LEFT_MARGIN + 3, recip_name_top - 10, 6)

    # === STREET ADDRESS BOX ===
    street_top = recip_name_bottom
    street_height = 0.35 * inch
    street_bottom = street_top - street_height

    c.rect(LEFT_MARGIN, street_bottom, left_col_width, street_height)
    draw_text(c, "Street address (including apt. no.)", LEFT_MARGIN + 3, street_top - 10, 6)

    # === CITY BOX ===
    city_top = street_bottom
    city_height = 0.35 * inch
    city_bottom = city_top - city_height

    c.rect(LEFT_MARGIN, city_bottom, left_col_width, city_height)
    draw_text(c, "City or town, state or province, country, and ZIP or foreign postal code",
              LEFT_MARGIN + 3, city_top - 10, 6)

    # === ACCOUNT NUMBER BOX ===
    acct_top = city_bottom
    acct_height = 0.30 * inch
    acct_bottom = acct_top - acct_height

    c.rect(LEFT_MARGIN, acct_bottom, left_col_width, acct_height)
    draw_text(c, "Account number (see instructions)", LEFT_MARGIN + 3, acct_top - 10, 6)

    # === RIGHT SIDE BOXES ===
    # Box 1 - Nonemployee compensation
    box1_top = payer_bottom
    box1_height = 0.50 * inch
    box1_bottom = box1_top - box1_height
    box1_width = right_col_width * 0.52

    # Gray header
    c.setFillColor(LIGHT_GRAY)
    c.rect(right_col_left, box1_top - 0.15*inch, box1_width, 0.15*inch, fill=1, stroke=1)
    c.setFillColor(black)
    draw_text(c, "1 Nonemployee compensation", right_col_left + 3, box1_top - 11, 6)
    # Box outline
    c.rect(right_col_left, box1_bottom, box1_width, box1_height)
    draw_text(c, "$", right_col_left + 3, box1_bottom + 8, 9)

    # Box 2 - Direct sales
    box2_top = box1_bottom
    box2_height = 0.38 * inch
    box2_bottom = box2_top - box2_height

    c.rect(right_col_left, box2_bottom, box1_width, box2_height)
    draw_text(c, "2 Payer made direct sales totaling $5,000 or more of", right_col_left + 3, box2_top - 10, 5.5)
    draw_text(c, "consumer products to recipient for resale", right_col_left + 6, box2_top - 19, 5.5)
    # Checkbox
    c.rect(right_col_left + box1_width - 15, box2_top - 22, 8, 8)

    # Box 3 - Excess golden parachute
    box3_top = box2_bottom
    box3_height = 0.38 * inch
    box3_bottom = box3_top - box3_height

    c.setFillColor(LIGHT_GRAY)
    c.rect(right_col_left, box3_top - 0.12*inch, box1_width, 0.12*inch, fill=1, stroke=1)
    c.setFillColor(black)
    draw_text(c, "3 Excess golden parachute payments", right_col_left + 3, box3_top - 9, 6)
    c.rect(right_col_left, box3_bottom, box1_width, box3_height)
    draw_text(c, "$", right_col_left + 3, box3_bottom + 8, 9)

    # Box 4 - Federal income tax withheld
    box4_top = box3_bottom
    box4_height = 0.38 * inch
    box4_bottom = box4_top - box4_height

    c.setFillColor(LIGHT_GRAY)
    c.rect(right_col_left, box4_top - 0.12*inch, box1_width, 0.12*inch, fill=1, stroke=1)
    c.setFillColor(black)
    draw_text(c, "4 Federal income tax withheld", right_col_left + 3, box4_top - 9, 6)
    c.rect(right_col_left, box4_bottom, box1_width, box4_height)
    draw_text(c, "$", right_col_left + 3, box4_bottom + 8, 9)

    # === BOXES 5, 6, 7 - State section ===
    state_top = box4_bottom
    state_height = 0.60 * inch
    state_bottom = state_top - state_height

    box5_width = box1_width * 0.45
    box6_width = box1_width * 0.30
    box7_width = box1_width * 0.25

    # Box 5 - State tax withheld
    c.setFillColor(LIGHT_GRAY)
    c.rect(right_col_left, state_top - 0.12*inch, box5_width, 0.12*inch, fill=1, stroke=1)
    c.setFillColor(black)
    draw_text(c, "5 State tax withheld", right_col_left + 2, state_top - 9, 5)
    c.rect(right_col_left, state_bottom, box5_width, state_height)
    # Two rows for two states
    c.line(right_col_left, state_bottom + state_height/2, right_col_left + box5_width, state_bottom + state_height/2)
    draw_text(c, "$", right_col_left + 2, state_bottom + state_height/2 + 10, 7)
    draw_text(c, "$", right_col_left + 2, state_bottom + 10, 7)

    # Box 6 - State/Payer's state no
    c.setFillColor(LIGHT_GRAY)
    c.rect(right_col_left + box5_width, state_top - 0.12*inch, box6_width, 0.12*inch, fill=1, stroke=1)
    c.setFillColor(black)
    draw_text(c, "6 State/Payer's state no.", right_col_left + box5_width + 2, state_top - 9, 5)
    c.rect(right_col_left + box5_width, state_bottom, box6_width, state_height)
    c.line(right_col_left + box5_width, state_bottom + state_height/2,
           right_col_left + box5_width + box6_width, state_bottom + state_height/2)

    # Box 7 - State income
    c.setFillColor(LIGHT_GRAY)
    c.rect(right_col_left + box5_width + box6_width, state_top - 0.12*inch, box7_width, 0.12*inch, fill=1, stroke=1)
    c.setFillColor(black)
    draw_text(c, "7 State income", right_col_left + box5_width + box6_width + 2, state_top - 9, 5)
    c.rect(right_col_left + box5_width + box6_width, state_bottom, box7_width, state_height)
    c.line(right_col_left + box5_width + box6_width, state_bottom + state_height/2,
           right_col_left + box5_width + box6_width + box7_width, state_bottom + state_height/2)
    draw_text(c, "$", right_col_left + box5_width + box6_width + 2, state_bottom + state_height/2 + 10, 7)
    draw_text(c, "$", right_col_left + box5_width + box6_width + 2, state_bottom + 10, 7)

    # === "This is important tax information" box (right side) ===
    info_left = right_col_left + box1_width
    info_width = right_col_width - box1_width
    info_top = box1_top
    info_bottom = state_bottom

    c.rect(info_left, info_bottom, info_width, info_top - info_bottom)

    info_lines = [
        "This is important tax",
        "information and is being",
        "furnished to the IRS. If you are",
        "required to file a return, a",
        "negligence penalty or other",
        "sanction may be imposed on",
        "you if this income is taxable",
        "and the IRS determines that it",
        "has not been reported."
    ]
    y = info_top - 15
    for line in info_lines:
        draw_text(c, line, info_left + 4, y, 6)
        y -= 10

    # === FOOTER ROW ===
    footer_y = form_bottom + 5
    draw_text(c, "Form 1099-NEC (Rev. 4-2025)", LEFT_MARGIN + 5, footer_y, 7)
    draw_text(c, "(keep for your records)", LEFT_MARGIN + 1.8*inch, footer_y, 7)
    draw_text(c, "www.irs.gov/Form1099NEC", LEFT_MARGIN + 3.2*inch, footer_y, 7)
    draw_text(c, "Department of the Treasury - Internal Revenue Service", LEFT_MARGIN + 4.8*inch, footer_y, 7)

    # === INSTRUCTIONS SECTION (below form) ===
    instr_top = form_bottom - 0.25 * inch
    instr_left = LEFT_MARGIN
    max_width = FORM_WIDTH

    draw_text(c, "Instructions for Recipient", instr_left, instr_top, 11, bold=True)

    instructions = [
        "You received this form instead of Form W-2 because the payer did not consider you an employee and did not withhold income tax or social security and Medicare taxes.",
        "If you believe you are an employee and cannot get the payer to correct this form, report the amount shown in box 1 on the line for \"Wages, salaries, tips, etc.\" of Form 1040, 1040-SR, or 1040-NR. You must also complete Form 8919 and attach it to your return. For more information, see Pub. 1779.",
        "If you are not an employee but the amount in box 1 is not self-employment (SE) income (for example, it is income from a sporadic activity or a hobby), report the amount shown in box 1 on the \"Other income\" line (on Schedule 1 (Form 1040)).",
    ]

    box_instructions = [
        ("Recipient's TIN.", "For your protection, this form may show only the last four digits of your TIN (SSN, ITIN, ATIN, or EIN). However, the issuer has reported your complete TIN to the IRS."),
        ("Account number.", "May show an account or other unique number the payer assigned to distinguish your account."),
        ("Box 1.", "Shows nonemployee compensation. If the amount in this box is SE income, report it on Schedule C or F (Form 1040) if a sole proprietor, or on Form 1065 if a partnership."),
        ("Box 2.", "If checked, consumer products totaling $5,000 or more were sold to you for resale, on a buy-sell, deposit-commission, or other basis."),
        ("Box 3.", "Shows your total compensation of excess golden parachute payments subject to a 20% excise tax."),
        ("Box 4.", "Shows backup withholding. A payer must backup withhold if you did not give your TIN to the payer. Include this amount on your income tax return as tax withheld."),
        ("Boxes 5-7.", "State income tax withheld reporting boxes."),
        ("Future developments.", "For the latest information about Form 1099-NEC, go to www.irs.gov/Form1099NEC."),
    ]

    y = instr_top - 16
    font_size = 7

    # Paragraph instructions
    for para in instructions:
        words = para.split()
        line = ""
        for word in words:
            test = line + " " + word if line else word
            if c.stringWidth(test, "Helvetica", font_size) < max_width:
                line = test
            else:
                c.setFont("Helvetica", font_size)
                c.drawString(instr_left, y, line)
                y -= 10
                line = word
        if line:
            c.setFont("Helvetica", font_size)
            c.drawString(instr_left, y, line)
            y -= 12

    # Box instructions with bold labels
    for label, text in box_instructions:
        if y < 0.4 * inch:
            break
        c.setFont("Helvetica-Bold", font_size)
        c.drawString(instr_left, y, label)
        label_width = c.stringWidth(label, "Helvetica-Bold", font_size)
        c.setFont("Helvetica", font_size)

        # Wrap the rest
        remaining = " " + text
        words = remaining.split()
        line = ""
        first_line = True
        for word in words:
            if first_line:
                test = line + " " + word if line else word
                if c.stringWidth(label + test, "Helvetica", font_size) < max_width:
                    line = test
                else:
                    c.drawString(instr_left + label_width, y, line)
                    y -= 10
                    line = word
                    first_line = False
            else:
                test = line + " " + word if line else word
                if c.stringWidth(test, "Helvetica", font_size) < max_width:
                    line = test
                else:
                    c.drawString(instr_left, y, line)
                    y -= 10
                    line = word
        if line:
            if first_line:
                c.drawString(instr_left + label_width, y, line)
            else:
                c.drawString(instr_left, y, line)
            y -= 12

    c.save()
    print(f"Created template: {output_path}")


if __name__ == "__main__":
    create_1099nec_template("1099-NEC_template_blank.pdf", "2025")
