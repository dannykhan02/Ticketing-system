import mimetypes
import os
import logging
from flask_mail import Mail, Message
from config import Config  # Ensure MAIL_DEFAULT_SENDER is set
from flask import current_app

# Initialize Mail globally — must be attached via mail.init_app(app)
mail = Mail()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_email(recipient: str, subject: str, body: str, is_html: bool = False) -> bool:
    """Send a basic email (text or HTML)."""
    try:
        msg = Message(
            subject=subject,
            recipients=[recipient],
            sender=Config.MAIL_DEFAULT_SENDER
        )
        if is_html:
            msg.html = body
        else:
            msg.body = body

        mail.send(msg)
        logger.info(f"Email sent to {recipient}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {recipient}: {e}")
        return False


def send_email_with_attachment(
    recipient: str,
    subject: str,
    body: str,
    attachment_path: str = None,
    attachments: list = None,
    is_html: bool = False
) -> bool:
    """
    Send an email with support for HTML or plain text content,
    a single attachment via file path, or multiple attachments via a list.

    `attachments` should be a list of dicts with keys:
    - 'filename': str
    - 'content_type': str (e.g., 'application/pdf')
    - 'content': bytes
    """
    try:
        msg = Message(
            subject=subject,
            recipients=[recipient],
            sender=Config.MAIL_DEFAULT_SENDER
        )

        # Set message body
        if is_html:
            msg.html = body
        else:
            msg.body = body

        # Handle single attachment from file path
        if attachment_path and os.path.exists(attachment_path) and os.path.getsize(attachment_path) > 0:
            mime_type, _ = mimetypes.guess_type(attachment_path)
            mime_type = mime_type or 'application/octet-stream'
            with open(attachment_path, 'rb') as f:
                msg.attach(
                    filename=os.path.basename(attachment_path),
                    content_type=mime_type,
                    data=f.read()
                )
            logger.info(f"Attached file from path: {attachment_path}")
        elif attachment_path:
            logger.warning(f"Attachment skipped. File not found or empty: {attachment_path}")

        # Handle multiple attachments from list
        if attachments:
            for item in attachments:
                try:
                    msg.attach(
                        filename=item['filename'],
                        content_type=item['content_type'],
                        data=item['content']
                    )
                    logger.info(f"Attached file: {item['filename']}")
                except KeyError as ke:
                    logger.warning(f"Attachment missing key: {ke} — Skipped.")

        # Send the email
        mail.send(msg)
        logger.info(f"Email with attachment(s) sent to {recipient}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email with attachment to {recipient}: {e}")
        return False
