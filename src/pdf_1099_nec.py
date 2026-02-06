"""
1099-NEC PDF Generator - Template Layer Approach.

Generates IRS Form 1099-NEC Copy B matching official layout.
Separates template (boxes, lines, labels) from data overlay for easy updates.

Reference: Official IRS Form 1099-NEC Copy B layout (2024/2025)
"""

from io import BytesIO
from typing import List, Optional, Dict, Any
from decimal import Decimal
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PayerInfo:
    """Payer (who pays the money) information."""
    name: str
    address_lines: List[str]  # Street, City/State/ZIP as separate lines
    tin: str
    phone: str = ""


@dataclass
class RecipientInfo:
    """Recipient (who receives the 1099) information."""
    name: str
    address_lines: List[str]
    tin: str  # Can be masked like "XX-XXX2488"
    account_number: str = ""


@dataclass
class FormAmounts:
    """1099-NEC box amounts."""
    box1_nonemployee_comp: Decimal = Decimal("0")
    box4_fed_withheld: Decimal = Decimal("0")
    box5_state_withheld: Decimal = Decimal("0")
    box6_state_payer_no: str = ""
    box7_state_income: Decimal = Decimal("0")


@dataclass
class FormFlags:
    """1099-NEC checkboxes and flags."""
    corrected: bool = False
    box2_direct_sales: bool = False


# =============================================================================
# FORMATTING HELPERS
# =============================================================================

def format_money(amount: Optional[Decimal]) -> str:
    """Format amount as money string with commas and 2 decimals."""
    if amount is None or amount == 0:
        return ""
    return f"{float(amount):,.2f}"


def format_tin(tin: str) -> str:
    """Return TIN as-is (already formatted or masked by caller)."""
    return tin if tin else ""


# =============================================================================
# TEMPLATE LAYER - Static form elements
# Coordinates matched to official IRS 1099-NEC Copy B
# =============================================================================

class Form1099NECTemplate:
    """
    Renders the static template layer for Form 1099-NEC Copy B.
    All coordinates are absolute, matching IRS layout.
    """

    # Page dimensions
    PAGE_WIDTH, PAGE_HEIGHT = letter  # 612 x 792 points

    # Form margins
    MARGIN_LEFT = 0.4 * inch
    MARGIN_RIGHT = 0.4 * inch
    MARGIN_TOP = 0.5 * inch

    # Form area boundaries
    FORM_LEFT = MARGIN_LEFT
    FORM_RIGHT = PAGE_WIDTH - MARGIN_RIGHT
    FORM_TOP = PAGE_HEIGHT - MARGIN_TOP
    FORM_WIDTH = FORM_RIGHT - FORM_LEFT

    # Line weights (matching IRS form)
    BORDER_WEIGHT = 1.0  # Outer borders
    BOX_WEIGHT = 0.5     # Box borders
    GRID_WEIGHT = 0.3    # Thin internal lines

    # Colors
    BLACK = colors.black

    # Key column positions (from left edge of form)
    # Left column: Payer/Recipient info
    LEFT_COL_WIDTH = 4.1 * inch

    # Middle column: Boxes 1, 2, 3, 4, 5, 6, 7
    MID_COL_LEFT = FORM_LEFT + LEFT_COL_WIDTH
    MID_COL_WIDTH = 1.65 * inch

    # Right column: OMB, Title area
    RIGHT_COL_LEFT = MID_COL_LEFT + MID_COL_WIDTH
    RIGHT_COL_WIDTH = FORM_RIGHT - RIGHT_COL_LEFT

    def __init__(self, c: canvas.Canvas, tax_year: int = 2025):
        self.c = c
        self.tax_year = tax_year
        # Track box positions for data overlay
        self.data_positions: Dict[str, Any] = {}

    def draw_template(self):
        """Draw the complete template layer."""
        self._draw_payer_section()
        self._draw_omb_section()
        self._draw_box1()
        self._draw_recipient_section()
        self._draw_box2()
        self._draw_box3()
        self._draw_box4()
        self._draw_bottom_row()
        # Draw title section AFTER bottom_row so we know tin_row_bottom
        self._draw_title_section()
        self._draw_form_footer()
        self._draw_instructions()

    def _draw_payer_section(self):
        """Draw PAYER'S name/address box (top-left, extends to middle column)."""
        c = self.c

        # Payer box spans from left to middle column
        box_left = self.FORM_LEFT
        box_top = self.FORM_TOP
        box_width = self.LEFT_COL_WIDTH + self.MID_COL_WIDTH
        box_height = 1.15 * inch

        # Draw box
        c.setStrokeColor(self.BLACK)
        c.setLineWidth(self.BORDER_WEIGHT)
        c.rect(box_left, box_top - box_height, box_width, box_height)

        # Label
        c.setFont("Helvetica", 5.5)
        c.drawString(box_left + 3, box_top - 9,
                     "PAYER'S name, street address, city or town, state or province, country, ZIP or")
        c.drawString(box_left + 3, box_top - 16, "foreign postal code, and telephone no.")

        # Store data position - data sits near bottom of box
        # Name starts high enough for 3 lines of address to fit above bottom
        self.data_positions['payer'] = {
            'name_x': box_left + 5,
            'name_y': box_top - box_height + 45,  # Close to bottom, room for 2 address lines below
            'phone_x': box_left + box_width - 75,
            'phone_y': box_top - box_height + 8,
        }
        self.payer_box_bottom = box_top - box_height

    def _draw_omb_section(self):
        """Draw OMB number box (top-right corner)."""
        c = self.c

        # OMB box position
        box_left = self.RIGHT_COL_LEFT
        box_top = self.FORM_TOP
        box_width = self.RIGHT_COL_WIDTH / 2
        box_height = 0.55 * inch

        # Draw box
        c.setLineWidth(self.BOX_WEIGHT)
        c.rect(box_left, box_top - box_height, box_width, box_height)

        # OMB text
        c.setFont("Helvetica", 6)
        c.drawString(box_left + 3, box_top - 10, "OMB No. 1545-0116")

        # Form number
        c.setFont("Helvetica-Bold", 8)
        c.drawString(box_left + 3, box_top - 22, "Form 1099-NEC")

        # Revision
        c.setFont("Helvetica", 6)
        c.drawString(box_left + 3, box_top - 33, f"(Rev. January {self.tax_year})")

        # Calendar year section
        year_box_left = box_left
        year_box_top = box_top - box_height
        year_box_height = 0.60 * inch

        c.setLineWidth(self.BOX_WEIGHT)
        c.rect(year_box_left, year_box_top - year_box_height, box_width, year_box_height)

        c.setFont("Helvetica", 6)
        c.drawCentredString(year_box_left + box_width / 2, year_box_top - 12, "For calendar year")

        # Large year
        c.setFont("Helvetica-Bold", 24)
        c.drawCentredString(year_box_left + box_width / 2, year_box_top - 42, str(self.tax_year))

        self.omb_box_right = box_left + box_width
        self.year_box_bottom = year_box_top - year_box_height

    def _draw_title_section(self):
        """Draw CORRECTED checkbox and title area (far right)."""
        c = self.c

        # Title section (right of OMB box)
        # This box runs from top down to align exactly with TIN row bottom
        title_left = self.omb_box_right
        title_top = self.FORM_TOP
        title_width = self.FORM_RIGHT - title_left
        title_bottom = self.tin_row_bottom  # Align with form bottom
        title_height = title_top - title_bottom

        # Draw box
        c.setLineWidth(self.BORDER_WEIGHT)
        c.rect(title_left, title_bottom, title_width, title_height)

        # CORRECTED checkbox
        checkbox_x = title_left + 5
        checkbox_y = title_top - 14
        c.setLineWidth(self.GRID_WEIGHT)
        c.rect(checkbox_x, checkbox_y, 8, 8)

        c.setFont("Helvetica-Bold", 7)
        c.drawString(checkbox_x + 12, checkbox_y + 2, "CORRECTED")
        c.setFont("Helvetica", 6)
        c.drawString(checkbox_x + 12, checkbox_y - 6, "(if checked)")

        self.data_positions['corrected_checkbox'] = {
            'x': checkbox_x,
            'y': checkbox_y,
            'size': 8
        }

        # "Nonemployee Compensation" title - use regular weight, smaller size
        c.setFont("Helvetica", 9)
        c.drawString(title_left + 5, title_top - 48, "Nonemployee")
        c.drawString(title_left + 5, title_top - 59, "Compensation")

        # "Copy B" and "For Recipient" - smaller, not so bold
        c.setFont("Helvetica-Bold", 10)
        c.drawString(title_left + 5, title_top - 82, "Copy B")

        c.setFont("Helvetica", 8)
        c.drawString(title_left + 5, title_top - 95, "For Recipient")

        # Important tax info text (right-aligned in box) - smaller font, tighter spacing
        # Must fit within the title box which is 2.85 inches tall
        c.setFont("Helvetica", 4.5)
        info_lines = [
            "This is important tax",
            "information and is being",
            "furnished to the Internal",
            "Revenue Service. If you",
            "are required to file a",
            "return, a negligence",
            "penalty or other sanction",
            "may be imposed on you if",
            "this income is taxable",
            "and the IRS determines",
            "that it has not been",
            "reported.",
        ]
        y = title_top - 108
        for line in info_lines:
            c.drawRightString(title_left + title_width - 3, y, line)
            y -= 6

        self.title_section_bottom = title_bottom

    def _draw_box1(self):
        """Draw Box 1 - Nonemployee compensation (below payer, in middle column)."""
        c = self.c

        # Box 1 is positioned at bottom of payer section, middle area
        box_left = self.MID_COL_LEFT
        box_top = self.payer_box_bottom
        box_width = self.MID_COL_WIDTH
        box_height = 0.40 * inch

        c.setLineWidth(self.BOX_WEIGHT)
        c.rect(box_left, box_top - box_height, box_width, box_height)

        # Label
        c.setFont("Helvetica", 5.5)
        c.drawString(box_left + 2, box_top - 9, "1 Nonemployee compensation")

        # Dollar sign
        c.setFont("Helvetica", 9)
        c.drawString(box_left + 3, box_top - box_height + 10, "$")

        self.data_positions['box1'] = {
            'x': box_left + 14,
            'y': box_top - box_height + 10,
            'right': box_left + box_width - 5
        }
        self.box1_bottom = box_top - box_height

    def _draw_recipient_section(self):
        """Draw RECIPIENT'S name and address box (left column, below payer)."""
        c = self.c

        # Recipient box spans left column
        box_left = self.FORM_LEFT
        box_top = self.payer_box_bottom
        box_width = self.LEFT_COL_WIDTH
        box_height = 1.45 * inch

        c.setLineWidth(self.BORDER_WEIGHT)
        c.rect(box_left, box_top - box_height, box_width, box_height)

        # Label
        c.setFont("Helvetica", 5.5)
        c.drawString(box_left + 3, box_top - 9, "RECIPIENT'S name and street address (including apt. no.)")

        # Data position - near bottom of box with room for address lines
        self.data_positions['recipient'] = {
            'name_x': box_left + 5,
            'name_y': box_top - box_height + 55,  # Close to bottom, room for 3 address lines below
        }
        self.recipient_box_bottom = box_top - box_height

    def _draw_box2(self):
        """Draw Box 2 - Direct sales checkbox (middle column, below box 1)."""
        c = self.c

        box_left = self.MID_COL_LEFT
        box_top = self.box1_bottom
        box_width = self.MID_COL_WIDTH
        box_height = 0.42 * inch

        c.setLineWidth(self.BOX_WEIGHT)
        c.rect(box_left, box_top - box_height, box_width, box_height)

        # Label text
        c.setFont("Helvetica", 5)
        c.drawString(box_left + 2, box_top - 8, "2 Payer made direct sales totaling $5,000 or more of")
        c.drawString(box_left + 6, box_top - 15, "consumer products to recipient for resale")

        # Checkbox (right side of box)
        checkbox_x = box_left + box_width - 14
        checkbox_y = box_top - box_height + 8
        c.setLineWidth(self.GRID_WEIGHT)
        c.rect(checkbox_x, checkbox_y, 8, 8)

        self.data_positions['box2_checkbox'] = {
            'x': checkbox_x,
            'y': checkbox_y,
            'size': 8
        }
        self.box2_bottom = box_top - box_height

    def _draw_box3(self):
        """Draw Box 3 - Reserved (middle column, below box 2)."""
        c = self.c

        box_left = self.MID_COL_LEFT
        box_top = self.box2_bottom
        box_width = self.MID_COL_WIDTH
        box_height = 0.35 * inch

        c.setLineWidth(self.BOX_WEIGHT)
        c.rect(box_left, box_top - box_height, box_width, box_height)

        # Label
        c.setFont("Helvetica", 5.5)
        c.drawString(box_left + 2, box_top - 9, "3")

        self.box3_bottom = box_top - box_height

    def _draw_box4(self):
        """Draw Box 4 - Federal income tax withheld (middle column, below box 3)."""
        c = self.c

        box_left = self.MID_COL_LEFT
        box_top = self.box3_bottom
        box_width = self.MID_COL_WIDTH
        box_height = 0.40 * inch

        c.setLineWidth(self.BOX_WEIGHT)
        c.rect(box_left, box_top - box_height, box_width, box_height)

        # Label
        c.setFont("Helvetica", 5.5)
        c.drawString(box_left + 2, box_top - 9, "4 Federal income tax withheld")

        # Dollar sign
        c.setFont("Helvetica", 9)
        c.drawString(box_left + 3, box_top - box_height + 10, "$")

        self.data_positions['box4'] = {
            'x': box_left + 14,
            'y': box_top - box_height + 10,
            'right': box_left + box_width - 5
        }
        self.box4_bottom = box_top - box_height

    def _draw_bottom_row(self):
        """Draw Account number, Boxes 5-6, TIN boxes, and Box 7."""
        c = self.c

        # Row position (below recipient box)
        row_top = self.recipient_box_bottom
        row_height = 0.40 * inch

        # Account number box (left portion)
        acct_left = self.FORM_LEFT
        acct_width = 1.85 * inch

        c.setLineWidth(self.BOX_WEIGHT)
        c.rect(acct_left, row_top - row_height, acct_width, row_height)

        c.setFont("Helvetica", 5.5)
        c.drawString(acct_left + 2, row_top - 9, "Account number (see instructions)")

        self.data_positions['account'] = {
            'x': acct_left + 4,
            'y': row_top - row_height + 10
        }

        # Box 5 - State tax withheld
        box5_left = acct_left + acct_width
        box5_width = 1.05 * inch

        c.rect(box5_left, row_top - row_height, box5_width, row_height)

        c.setFont("Helvetica", 5)
        c.drawString(box5_left + 2, row_top - 9, "5  State tax withheld")
        c.setFont("Helvetica", 8)
        c.drawString(box5_left + 3, row_top - row_height + 10, "$")

        self.data_positions['box5'] = {
            'x': box5_left + 14,
            'y': row_top - row_height + 10,
            'right': box5_left + box5_width - 4
        }

        # Box 6 - State/Payer's state no.
        box6_left = box5_left + box5_width
        box6_width = self.LEFT_COL_WIDTH - acct_width - box5_width

        c.rect(box6_left, row_top - row_height, box6_width, row_height)

        c.setFont("Helvetica", 5)
        c.drawString(box6_left + 2, row_top - 9, "6 State/Payer's state no.")

        self.data_positions['box6'] = {
            'x': box6_left + 3,
            'y': row_top - row_height + 10
        }

        self.state_row_bottom = row_top - row_height

        # Second row: TIN boxes and Box 7
        tin_row_top = self.state_row_bottom
        tin_row_height = 0.38 * inch

        # PAYER'S TIN
        payer_tin_left = self.FORM_LEFT
        payer_tin_width = 1.5 * inch

        c.rect(payer_tin_left, tin_row_top - tin_row_height, payer_tin_width, tin_row_height)

        c.setFont("Helvetica", 5.5)
        c.drawString(payer_tin_left + 2, tin_row_top - 9, "PAYER'S TIN")

        self.data_positions['payer_tin'] = {
            'x': payer_tin_left + 4,
            'y': tin_row_top - tin_row_height + 10
        }

        # RECIPIENT'S TIN
        recip_tin_left = payer_tin_left + payer_tin_width
        recip_tin_width = 1.5 * inch

        c.rect(recip_tin_left, tin_row_top - tin_row_height, recip_tin_width, tin_row_height)

        c.setFont("Helvetica", 5.5)
        c.drawString(recip_tin_left + 2, tin_row_top - 9, "RECIPIENT'S TIN")

        self.data_positions['recipient_tin'] = {
            'x': recip_tin_left + 4,
            'y': tin_row_top - tin_row_height + 10
        }

        # Box 7 - State income (spans remaining width in middle column area)
        box7_left = self.MID_COL_LEFT
        box7_width = self.MID_COL_WIDTH
        box7_top = self.box4_bottom

        c.rect(box7_left, box7_top - tin_row_height, box7_width, tin_row_height)

        c.setFont("Helvetica", 5.5)
        c.drawString(box7_left + 2, box7_top - 9, "7 State income")
        c.setFont("Helvetica", 8)
        c.drawString(box7_left + 3, box7_top - tin_row_height + 10, "$")

        self.data_positions['box7'] = {
            'x': box7_left + 14,
            'y': box7_top - tin_row_height + 10,
            'right': box7_left + box7_width - 4
        }

        self.tin_row_bottom = tin_row_top - tin_row_height

    def _draw_form_footer(self):
        """Draw the form footer line."""
        c = self.c

        footer_y = self.tin_row_bottom - 8

        c.setFont("Helvetica-Bold", 7)
        c.drawString(self.FORM_LEFT, footer_y, "Form 1099-NEC")

        c.setFont("Helvetica", 6)
        c.drawString(self.FORM_LEFT + 0.85 * inch, footer_y, f"(Rev. 1-{self.tax_year})")
        c.drawString(self.FORM_LEFT + 1.5 * inch, footer_y, "(keep for your records)")
        c.drawString(self.FORM_LEFT + 2.55 * inch, footer_y, "www.irs.gov/Form1099NEC")
        c.drawString(self.FORM_LEFT + 4.0 * inch, footer_y, "Department of the Treasury - Internal Revenue Service")

        self.footer_y = footer_y

    def _draw_instructions(self):
        """Draw the Instructions for Recipient section."""
        c = self.c

        inst_top = self.footer_y - 12

        # Separator line
        c.setLineWidth(self.BORDER_WEIGHT)
        c.line(self.FORM_LEFT, inst_top, self.FORM_RIGHT, inst_top)

        # Title
        c.setFont("Helvetica-Bold", 8)
        c.drawString(self.FORM_LEFT, inst_top - 12, "Instructions for Recipient")

        # Instruction text - two columns
        c.setFont("Helvetica", 5.5)

        # Left column
        left_lines = [
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
        for line in left_lines:
            c.drawString(self.FORM_LEFT, y, line)
            y -= 7

        # Right column
        right_x = 4.0 * inch
        right_lines = [
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
        for line in right_lines:
            c.drawString(right_x, y, line)
            y -= 7


# =============================================================================
# DATA OVERLAY LAYER
# =============================================================================

class Form1099NECDataOverlay:
    """Renders data values onto the template."""

    def __init__(self, c: canvas.Canvas, template: Form1099NECTemplate):
        self.c = c
        self.t = template

    def render_payer(self, payer: PayerInfo):
        """Render payer information."""
        c = self.c
        pos = self.t.data_positions['payer']

        # Name (no bold - regular weight)
        c.setFont("Helvetica", 10)
        c.drawString(pos['name_x'], pos['name_y'], payer.name)

        # Address lines
        c.setFont("Helvetica", 9)
        y = pos['name_y'] - 12
        for line in payer.address_lines:
            c.drawString(pos['name_x'], y, line)
            y -= 11

        # Phone (near box 1, right-aligned in payer area)
        if payer.phone:
            c.setFont("Helvetica", 9)
            c.drawString(pos['phone_x'], pos['phone_y'], payer.phone)

    def render_payer_tin(self, tin: str):
        """Render payer TIN."""
        c = self.c
        pos = self.t.data_positions['payer_tin']
        c.setFont("Helvetica", 10)
        c.drawString(pos['x'], pos['y'], format_tin(tin))

    def render_recipient(self, recipient: RecipientInfo):
        """Render recipient information."""
        c = self.c
        pos = self.t.data_positions['recipient']

        # Name (no bold - regular weight)
        c.setFont("Helvetica", 10)
        c.drawString(pos['name_x'], pos['name_y'], recipient.name)

        # Address lines
        c.setFont("Helvetica", 9)
        y = pos['name_y'] - 12
        for line in recipient.address_lines:
            c.drawString(pos['name_x'], y, line)
            y -= 11

    def render_recipient_tin(self, tin: str):
        """Render recipient TIN."""
        c = self.c
        pos = self.t.data_positions['recipient_tin']
        c.setFont("Helvetica", 10)
        c.drawString(pos['x'], pos['y'], format_tin(tin))

    def render_account(self, account_number: str):
        """Render account number."""
        if account_number:
            c = self.c
            pos = self.t.data_positions['account']
            c.setFont("Helvetica", 9)
            c.drawString(pos['x'], pos['y'], account_number)

    def render_amounts(self, amounts: FormAmounts, corrected: bool = False):
        """Render box amounts."""
        c = self.c

        # Box 1 - Nonemployee compensation (show 0.00 on corrections)
        if amounts.box1_nonemployee_comp or corrected:
            pos = self.t.data_positions['box1']
            c.setFont("Helvetica", 10)
            amt_str = format_money(amounts.box1_nonemployee_comp) if amounts.box1_nonemployee_comp else "0.00"
            c.drawRightString(pos['right'], pos['y'], amt_str)

        # Box 4 - Federal withheld
        if amounts.box4_fed_withheld:
            pos = self.t.data_positions['box4']
            c.setFont("Helvetica", 10)
            amt_str = format_money(amounts.box4_fed_withheld)
            c.drawRightString(pos['right'], pos['y'], amt_str)

        # Box 5 - State withheld
        if amounts.box5_state_withheld:
            pos = self.t.data_positions['box5']
            c.setFont("Helvetica", 9)
            amt_str = format_money(amounts.box5_state_withheld)
            c.drawRightString(pos['right'], pos['y'], amt_str)

        # Box 6 - State/Payer's state no
        if amounts.box6_state_payer_no:
            pos = self.t.data_positions['box6']
            c.setFont("Helvetica", 8)
            c.drawString(pos['x'], pos['y'], amounts.box6_state_payer_no)

        # Box 7 - State income
        if amounts.box7_state_income:
            pos = self.t.data_positions['box7']
            c.setFont("Helvetica", 9)
            amt_str = format_money(amounts.box7_state_income)
            c.drawRightString(pos['right'], pos['y'], amt_str)

    def render_flags(self, flags: FormFlags):
        """Render checkboxes."""
        c = self.c

        if flags.corrected:
            pos = self.t.data_positions['corrected_checkbox']
            c.setFont("Helvetica-Bold", 8)
            c.drawString(pos['x'] + 10, pos['y'] - 3, "x")

        if flags.box2_direct_sales:
            pos = self.t.data_positions['box2_checkbox']
            c.setFont("Helvetica-Bold", 8)
            c.drawString(pos['x'] + 2, pos['y'] + 1, "X")


# =============================================================================
# MAIN RENDER FUNCTION
# =============================================================================

def render_1099_nec_copy_b(
    tax_year: int,
    payer: PayerInfo,
    recipient: RecipientInfo,
    amounts: FormAmounts,
    flags: FormFlags,
) -> bytes:
    """
    Render a complete Form 1099-NEC Copy B.

    Args:
        tax_year: Tax year (e.g., 2025)
        payer: Payer information
        recipient: Recipient information
        amounts: Box amounts
        flags: Checkboxes/flags

    Returns:
        PDF as bytes
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    # Draw template layer
    template = Form1099NECTemplate(c, tax_year=tax_year)
    template.draw_template()

    # Draw data overlay
    overlay = Form1099NECDataOverlay(c, template)
    overlay.render_payer(payer)
    overlay.render_payer_tin(payer.tin)
    overlay.render_recipient(recipient)
    overlay.render_recipient_tin(recipient.tin)
    overlay.render_account(recipient.account_number)
    overlay.render_amounts(amounts, corrected=flags.corrected)
    overlay.render_flags(flags)

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


# =============================================================================
# CONVENIENCE WRAPPER FOR EXISTING API
# =============================================================================

def generate_1099_nec_pdf_v2(
    # Required parameters (no defaults)
    payer_name: str,
    payer_address_lines: List[str],
    payer_tin: str,
    recipient_name: str,
    recipient_address_lines: List[str],
    recipient_tin: str,
    # Optional parameters (with defaults)
    payer_phone: str = "",
    recipient_account: str = "",
    tax_year: int = 2025,
    box1_compensation: Decimal = Decimal("0"),
    box4_federal_withheld: Decimal = Decimal("0"),
    box5_state_withheld: Decimal = Decimal("0"),
    box6_state_payer_no: str = "",
    box7_state_income: Decimal = Decimal("0"),
    corrected: bool = False,
    box2_direct_sales: bool = False,
) -> bytes:
    """
    Generate 1099-NEC PDF with simple parameters.
    Convenience wrapper around render_1099_nec_copy_b.
    """
    payer = PayerInfo(
        name=payer_name,
        address_lines=payer_address_lines,
        tin=payer_tin,
        phone=payer_phone
    )

    recipient = RecipientInfo(
        name=recipient_name,
        address_lines=recipient_address_lines,
        tin=recipient_tin,
        account_number=recipient_account
    )

    amounts = FormAmounts(
        box1_nonemployee_comp=box1_compensation,
        box4_fed_withheld=box4_federal_withheld,
        box5_state_withheld=box5_state_withheld,
        box6_state_payer_no=box6_state_payer_no,
        box7_state_income=box7_state_income
    )

    flags = FormFlags(
        corrected=corrected,
        box2_direct_sales=box2_direct_sales
    )

    return render_1099_nec_copy_b(
        tax_year=tax_year,
        payer=payer,
        recipient=recipient,
        amounts=amounts,
        flags=flags,
    )


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    # Generate test PDF matching the 2024 reference data
    pdf_bytes = generate_1099_nec_pdf_v2(
        payer_name="Euguene Baldwin",
        payer_address_lines=[
            "280 High Ridge Dr",
            "Athens, GA 30606"
        ],
        payer_tin="420-52-8244",
        payer_phone="706-549-6503",
        recipient_name="Arnolds Home Healthcare LLC",
        recipient_address_lines=[
            "Patricia Arnold",
            "875 Belmont Rd",
            "Athens, GA 30605"
        ],
        recipient_tin="XX-XXX2488",
        recipient_account="EFM3993900",
        tax_year=2025,
        box1_compensation=Decimal("118734.00"),
    )

    with open("test_1099_nec_2025_v3.pdf", "wb") as f:
        f.write(pdf_bytes)
    print(f"Generated test_1099_nec_2025_v3.pdf ({len(pdf_bytes)} bytes)")
