import mimetypes
from flask_mail import Mail, Message
from config import Config
from flask import current_app
import logging

# Initialize Mail (but attach it to the Flask app later)
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
            sender=Config.MAIL_DEFAULT_SENDER
        )

        if html:
            msg.html = body
        else:
            msg.body = body

        mail.send(msg)  # ✅ Use the initialized mail object here
        logger.info(f"Email sent successfully to {to}")
    except Exception as e:
        logger.error(f"Error sending email to {to}: {str(e)}")
        raise


def send_email_with_attachment(recipient, subject, body, attachment_path=None):
    """Function to send an email with an optional attachment."""
    msg = Message(
        subject=subject,
        recipients=[recipient],
        body=body,
        sender=Config.MAIL_DEFAULT_SENDER,
    )

    # Attach file if provided
    if attachment_path:
        try:
            mime_type, _ = mimetypes.guess_type(attachment_path)
            mime_type = mime_type or "application/octet-stream"  # Default MIME type if unknown
            with open(attachment_path, "rb") as file:
                msg.attach(
                    filename=attachment_path.split("/")[-1],
                    content_type=mime_type,
                    data=file.read(),
                )
        except Exception as e:
            logger.error(f"Error attaching file: {e}")  # Handle file errors

    # Send email with error handling
    try:
        mail.send(msg)
        logger.info(f"Email with attachment sent successfully to {recipient}")
    except Exception as e:
        logger.error(f"Error sending email with attachment: {e}")  # Handle mail errors
