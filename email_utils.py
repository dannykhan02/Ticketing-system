import mimetypes
from flask_mail import Mail, Message
from config import Config

# Initialize Mail (but attach it to the Flask app later)
mail = Mail()

def send_email(recipient, subject, body, attachment_path=None):
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
            print(f"Error attaching file: {e}")  # Handle file errors

    # Send email with error handling
    try:
        mail.send(msg)
        print(f"Email sent successfully to {recipient}")
    except Exception as e:
        print(f"Error sending email: {e}")  # Handle mail errors
