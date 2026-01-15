"""
Invoice Generator for Sherpa 1099.

Generates PDF invoices for 1099 preparation services.
"""

from io import BytesIO
from datetime import date
from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


# Company information
COMPANY_NAME = "The Tax Shelter"
COMPANY_ADDRESS = "630 Hawthorne Ave"
COMPANY_CITY_STATE_ZIP = "Athens, GA 30606"

# Pricing
SETUP_FEE = Decimal("150.00")
PER_FORM_FEE = Decimal("7.00")

# Invoice number starting point (will be: 26001, 26002, etc.)
INVOICE_NUMBER_PREFIX = "26"


def generate_invoice_number(filer_id: str) -> str:
    """
    Generate a unique invoice number based on filer ID.

    Uses the last 3 digits of the filer UUID hash to create uniqueness.
    Format: 26XXX where XXX is derived from filer_id
    """
    # Use hash of filer_id to generate a consistent number
    hash_val = abs(hash(filer_id)) % 1000
    return f"{INVOICE_NUMBER_PREFIX}{hash_val:03d}"


def generate_invoice_pdf(
    filer_name: str,
    filer_id: str,
    form_count: int,
    filer_address: str = "",
    filer_city_state_zip: str = "",
    invoice_date: date = None,
) -> bytes:
    """
    Generate a PDF invoice for 1099 preparation services.

    Args:
        filer_name: Name of the client/filer being invoiced
        filer_id: UUID of the filer (used for invoice number)
        form_count: Number of 1099 forms prepared
        filer_address: Filer's street address
        filer_city_state_zip: Filer's city, state, zip
        invoice_date: Date for the invoice (defaults to today)

    Returns:
        PDF file as bytes
    """
    if invoice_date is None:
        invoice_date = date.today()

    # Calculate totals
    setup_fee = SETUP_FEE
    forms_total = PER_FORM_FEE * form_count
    grand_total = setup_fee + forms_total

    # Generate invoice number
    invoice_number = generate_invoice_number(filer_id)

    # Create PDF buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )

    # Styles
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a1a2e'),
        spaceAfter=6,
    )

    company_style = ParagraphStyle(
        'Company',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#333333'),
        leading=14,
    )

    header_style = ParagraphStyle(
        'Header',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#666666'),
    )

    normal_style = ParagraphStyle(
        'NormalText',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#333333'),
    )

    right_align_style = ParagraphStyle(
        'RightAlign',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#333333'),
        alignment=2,  # Right align
    )

    # Build document elements
    elements = []

    # INVOICE title centered at top
    invoice_title_style = ParagraphStyle(
        'InvoiceLabel',
        parent=styles['Heading1'],
        fontSize=28,
        textColor=colors.HexColor('#d4a537'),  # Sherpa amber
        alignment=1,  # Center
        spaceAfter=20,
    )
    elements.append(Paragraph("INVOICE", invoice_title_style))

    # Header row: Company info on left, Invoice details on right
    header_data = [
        [
            Paragraph(f"<b>{COMPANY_NAME}</b><br/>{COMPANY_ADDRESS}<br/>{COMPANY_CITY_STATE_ZIP}", company_style),
            Paragraph(f"<b>Invoice #:</b> {invoice_number}<br/><b>Date:</b> {invoice_date.strftime('%B %d, %Y')}", right_align_style),
        ]
    ]
    header_table = Table(header_data, colWidths=[3.5*inch, 3.5*inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.4*inch))

    # Bill To with filer address
    elements.append(Paragraph("Bill To:", header_style))
    elements.append(Spacer(1, 0.1*inch))
    bill_to_text = f"<b>{filer_name}</b>"
    if filer_address:
        bill_to_text += f"<br/>{filer_address}"
    if filer_city_state_zip:
        bill_to_text += f"<br/>{filer_city_state_zip}"
    elements.append(Paragraph(bill_to_text, normal_style))
    elements.append(Spacer(1, 0.4*inch))

    # Services Description
    elements.append(Paragraph("Services:", header_style))
    elements.append(Spacer(1, 0.1*inch))
    elements.append(Paragraph(f"<b>1099 Preparation - Tax Year {invoice_date.year - 1}</b>", normal_style))
    elements.append(Spacer(1, 0.3*inch))

    # Line Items Table
    items_data = [
        ["Description", "Qty", "Rate", "Amount"],
        ["Setup Fee", "1", f"${setup_fee:.2f}", f"${setup_fee:.2f}"],
        [f"1099 Forms Prepared", str(form_count), f"${PER_FORM_FEE:.2f}", f"${forms_total:.2f}"],
        ["", "", "", ""],
        ["", "", "TOTAL:", f"${grand_total:.2f}"],
    ]

    items_table = Table(items_data, colWidths=[3.5*inch, 0.75*inch, 1*inch, 1.25*inch])
    items_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a2e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),

        # Data rows
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#333333')),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),

        # Alignment
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),

        # Total row styling
        ('FONTNAME', (2, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (2, -1), (-1, -1), 12),
        ('TEXTCOLOR', (3, -1), (3, -1), colors.HexColor('#d4a537')),

        # Grid lines
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#1a1a2e')),
        ('LINEBELOW', (0, 1), (-1, -3), 0.5, colors.HexColor('#e0e0e0')),
        ('LINEABOVE', (2, -1), (-1, -1), 1, colors.HexColor('#333333')),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 0.5*inch))

    # Thank you note
    thanks_style = ParagraphStyle(
        'Thanks',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#666666'),
        alignment=1,  # Center
    )
    elements.append(Paragraph("Thank you for your business!", thanks_style))

    # Build PDF
    doc.build(elements)

    # Get PDF bytes
    buffer.seek(0)
    return buffer.read()
