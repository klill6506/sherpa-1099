"""
Email Router for Sherpa 1099.

Endpoints for emailing 1099 PDFs to recipients via SMTP.
"""

import os
import smtplib
import ssl
import logging
from email.message import EmailMessage
from typing import Optional, List
from io import BytesIO

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import sys
sys.path.insert(0, "src")

from supabase_client import get_supabase_client
from .pdf import get_form_with_relations, generate_1099_pdf, get_forms_batch

logger = logging.getLogger(__name__)

router = APIRouter()


class EmailResult(BaseModel):
    """Result of an email send operation."""
    form_id: str
    recipient_name: str
    recipient_email: str
    success: bool
    error: Optional[str] = None


class EmailAllResponse(BaseModel):
    """Response for email all operation."""
    sent: int
    skipped: int
    failed: int
    results: List[EmailResult]


def get_smtp_config() -> dict:
    """Get SMTP configuration from environment variables."""
    return {
        "server": os.environ.get("SMTP_SERVER", "localhost"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "username": os.environ.get("SMTP_USERNAME"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "from_email": os.environ.get("SMTP_FROM_EMAIL", os.environ.get("SMTP_USERNAME", "no-reply@example.com")),
        "from_name": os.environ.get("SMTP_FROM_NAME", "Sherpa 1099"),
        "use_tls": os.environ.get("SMTP_USE_TLS", "1").lower() in ("1", "true", "yes"),
        "use_ssl": os.environ.get("SMTP_USE_SSL", "0").lower() in ("1", "true", "yes"),
    }


def send_email_with_attachment(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    attachment_bytes: bytes,
    attachment_filename: str,
    config: dict
) -> None:
    """
    Send an email with a PDF attachment via SMTP.

    Raises exception on failure.
    """
    msg = EmailMessage()
    msg["From"] = f"{config['from_name']} <{config['from_email']}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    # Attach the PDF
    msg.add_attachment(
        attachment_bytes,
        maintype="application",
        subtype="pdf",
        filename=attachment_filename
    )

    context = ssl.create_default_context()

    if config["use_ssl"]:
        # SSL from the start (port 465)
        with smtplib.SMTP_SSL(config["server"], config["port"], timeout=30, context=context) as smtp:
            if config["username"] and config["password"]:
                smtp.login(config["username"], config["password"])
            smtp.send_message(msg)
    else:
        # STARTTLS (port 587)
        with smtplib.SMTP(config["server"], config["port"], timeout=30) as smtp:
            smtp.ehlo()
            if config["use_tls"]:
                smtp.starttls(context=context)
                smtp.ehlo()
            if config["username"] and config["password"]:
                smtp.login(config["username"], config["password"])
            smtp.send_message(msg)

    logger.info(f"Email sent to {to_email} (subject: {subject})")


@router.post("/{form_id}", response_model=EmailResult)
async def email_single_form(form_id: str):
    """
    Email a single 1099 form PDF to the recipient.

    The recipient must have an email address on file.
    """
    # Get form data
    data = get_form_with_relations(form_id)

    recipient = data["recipient"]
    recipient_email = recipient.get("email")
    recipient_name = recipient.get("name", "Recipient")

    if not recipient_email:
        raise HTTPException(
            status_code=400,
            detail=f"Recipient {recipient_name} does not have an email address on file"
        )

    # Generate PDF
    try:
        pdf_bytes = generate_1099_pdf(
            form_data=data["form"],
            filer_data=data["filer"],
            recipient_data=recipient,
            copy_type="B"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Failed to generate PDF: {str(e)}")

    # Build email content
    form_type = data["form"]["form_type"]
    tax_year = data["form"]["tax_year"]
    filer_name = data["filer"]["name"]

    subject = f"Your {tax_year} {form_type} from {filer_name}"
    body = f"""Dear {recipient_name},

Please find attached your {form_type} form for tax year {tax_year}.

This form reports income you received from {filer_name}. Please retain this for your tax records.

If you have any questions, please contact {filer_name}.

Thank you.
"""

    # Build filename
    safe_name = recipient_name.replace(" ", "_").replace(",", "")[:30]
    filename = f"{form_type.replace('-', '')}_{tax_year}_{safe_name}.pdf"

    # Send email
    config = get_smtp_config()

    try:
        send_email_with_attachment(
            to_email=recipient_email,
            to_name=recipient_name,
            subject=subject,
            body=body,
            attachment_bytes=pdf_bytes,
            attachment_filename=filename,
            config=config
        )
        return EmailResult(
            form_id=form_id,
            recipient_name=recipient_name,
            recipient_email=recipient_email,
            success=True
        )
    except Exception as e:
        logger.error(f"Failed to email {form_id} to {recipient_email}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@router.post("/filer/{filer_id}/all", response_model=EmailAllResponse)
async def email_all_filer_forms(filer_id: str):
    """
    Email all 1099 forms for a filer to recipients that have email addresses.

    Recipients without email addresses are skipped.
    Returns a summary of sent, skipped, and failed emails.
    """
    client = get_supabase_client()

    # Get all forms for this filer
    forms_result = client.table("forms_1099").select("id").eq("filer_id", filer_id).execute()

    if not forms_result.data:
        raise HTTPException(status_code=404, detail="No forms found for this filer")

    form_ids = [f["id"] for f in forms_result.data]

    # Batch fetch all form data
    forms_data = get_forms_batch(form_ids)

    if not forms_data:
        raise HTTPException(status_code=400, detail="No valid forms found")

    # Get SMTP config once
    config = get_smtp_config()

    results = []
    sent = 0
    skipped = 0
    failed = 0

    for data in forms_data:
        form = data["form"]
        filer = data["filer"]
        recipient = data["recipient"]

        form_id = form["id"]
        recipient_name = recipient.get("name", "Unknown")
        recipient_email = recipient.get("email")

        # Skip if no email
        if not recipient_email:
            results.append(EmailResult(
                form_id=form_id,
                recipient_name=recipient_name,
                recipient_email="",
                success=False,
                error="No email address"
            ))
            skipped += 1
            continue

        # Generate PDF
        try:
            pdf_bytes = generate_1099_pdf(
                form_data=form,
                filer_data=filer,
                recipient_data=recipient,
                copy_type="B"
            )
        except Exception as e:
            results.append(EmailResult(
                form_id=form_id,
                recipient_name=recipient_name,
                recipient_email=recipient_email,
                success=False,
                error=f"PDF generation failed: {str(e)}"
            ))
            failed += 1
            continue

        # Build email content
        form_type = form["form_type"]
        tax_year = form["tax_year"]
        filer_name = filer["name"]

        subject = f"Your {tax_year} {form_type} from {filer_name}"
        body = f"""Dear {recipient_name},

Please find attached your {form_type} form for tax year {tax_year}.

This form reports income you received from {filer_name}. Please retain this for your tax records.

If you have any questions, please contact {filer_name}.

Thank you.
"""

        safe_name = recipient_name.replace(" ", "_").replace(",", "")[:30]
        filename = f"{form_type.replace('-', '')}_{tax_year}_{safe_name}.pdf"

        # Send email
        try:
            send_email_with_attachment(
                to_email=recipient_email,
                to_name=recipient_name,
                subject=subject,
                body=body,
                attachment_bytes=pdf_bytes,
                attachment_filename=filename,
                config=config
            )
            results.append(EmailResult(
                form_id=form_id,
                recipient_name=recipient_name,
                recipient_email=recipient_email,
                success=True
            ))
            sent += 1
        except Exception as e:
            logger.error(f"Failed to email {form_id} to {recipient_email}: {e}")
            results.append(EmailResult(
                form_id=form_id,
                recipient_name=recipient_name,
                recipient_email=recipient_email,
                success=False,
                error=str(e)
            ))
            failed += 1

    return EmailAllResponse(
        sent=sent,
        skipped=skipped,
        failed=failed,
        results=results
    )
