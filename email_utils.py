import mimetypes
from flask_mail import Mail, Message
from config import Config # Assuming you have a config.py with MAIL_DEFAULT_SENDER etc.
from flask import current_app # Required if you're initializing mail with app context
import logging
import os

# Initialize Mail (but attach it to the Flask app later, e.g., mail.init_app(app))
mail = Mail()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_email(to, subject, body, html=False):
    """Send an email with the given subject and body."""
    try:
        msg = Message(
            subject,
            recipients=[to],
            sender=Config.MAIL_DEFAULT_SENDER # Assuming Config.MAIL_DEFAULT_SENDER is defined
        )

        if html:
            msg.html = body
        else:
            msg.body = body

        mail.send(msg)
        logger.info(f"Email sent successfully to {to}")
    except Exception as e:
        logger.error(f"Error sending email to {to}: {str(e)}")
        raise # Re-raise the exception for the caller to handle


def send_email_with_attachment(recipient, subject, body, attachment_path=None):
    """Function to send an email with an optional attachment."""
    msg = Message(
        subject=subject,
        recipients=[recipient],
        body=body,
        sender=Config.MAIL_DEFAULT_SENDER,
    )

    # Attach file if provided and it exists
    if attachment_path and os.path.exists(attachment_path) and os.path.getsize(attachment_path) > 0:
        try:
            mime_type, _ = mimetypes.guess_type(attachment_path)
            mime_type = mime_type or "application/octet-stream"  # Default MIME type if unknown
            with open(attachment_path, "rb") as file:
                msg.attach(
                    filename=os.path.basename(attachment_path), # Use os.path.basename for cleaner filename
                    content_type=mime_type,
                    data=file.read(),
                )
            logger.info(f"Attached file {os.path.basename(attachment_path)} to email.")
        except Exception as e:
            logger.error(f"Error attaching file {attachment_path}: {e}")
    else:
        if attachment_path: # Only log if an attachment path was actually provided
            logger.warning(f"Attachment file not found or is empty at {attachment_path}. Skipping attachment.")

    # Send email with error handling
    try:
        mail.send(msg)
        logger.info(f"Email with attachment sent successfully to {recipient}")
    except Exception as e:
        logger.error(f"Error sending email with attachment to {recipient}: {e}")
        raise # Re-raise the exception for the caller to handle