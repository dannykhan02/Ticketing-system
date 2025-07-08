from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from io import BytesIO
import qrcode
import base64
import re
from datetime import datetime
from email_utils import send_email_with_attachment
from ticket import generate_qr_attachment
from model import db, Ticket, User, UserRole, Event, TicketType
import logging
import mimetypes

logger = logging.getLogger(__name__)

class TicketResource(Resource):
    """
    Handles operations related to individual tickets (e.g., fetching a single ticket).
    This is a placeholder and should be implemented based on your application's needs.
    """
    @jwt_required()
    def get(self, ticket_id):
        # Example: Fetch a single ticket by ID for the authenticated user
        user_id = get_jwt_identity()
        ticket = Ticket.query.filter_by(id=ticket_id, user_id=user_id).first()
        if not ticket:
            return {"error": "Ticket not found or does not belong to you"}, 404

        # You would typically serialize the ticket object here
        return {
            "ticket_id": ticket.id,
            "event_name": ticket.event.name,
            "ticket_type": ticket.ticket_type.type_name.value,
            "purchase_date": ticket.purchase_date.strftime('%Y-%m-%d %H:%M:%S')
        }, 200

class TicketQRCodeEmailResource(Resource):
    """Allow attendee to view their tickets and email QR codes"""

    def _validate_email(self, email):
        """Validate email format"""
        if not email:
            return False
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

    def _get_qr_code_image(self, ticket):
        """Retrieve existing QR code from ticket and convert to image"""
        try:
            # Check if ticket has QR code
            if not ticket.qr_code:
                raise ValueError("Ticket does not have a QR code")

            # Create QR code image from existing QR code data
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )
            qr.add_data(ticket.qr_code)
            qr.make(fit=True)

            # Generate image
            qr_img = qr.make_image(fill_color="#1a1a1a", back_color="#ffffff")

            # Save to buffer
            buffer = BytesIO()
            qr_img.save(buffer, format="PNG")
            buffer.seek(0)

            return buffer.read()

        except Exception as e:
            logger.error(f"QR code image creation failed: {e}")
            raise

    def _create_email_content(self, user, ticket, event):
        """Create HTML email content with event details and embedded QR code"""
        # Format event date and time
        event_date = event.date.strftime('%A, %B %d, %Y') if event.date else "Date not available"
        start_time = event.start_time.strftime('%H:%M:%S') if event.start_time else "Start time not available"
        end_time = event.end_time.strftime('%H:%M:%S') if event.end_time else "Till Late"

        # Create HTML email content
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');

        body {{
            font-family: 'Poppins', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 0;
            background-color: #f5f5f5;
        }}
        .email-container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}
        .email-header {{
            background: linear-gradient(135deg, #6a3093 0%, #4a154b 100%);
            color: white;
            padding: 25px 15px;
            text-align: center;
        }}
        .email-header h1 {{
            margin: 0;
            font-size: 24px;
            letter-spacing: 0.5px;
        }}
        .email-body {{
            padding: 25px 20px;
        }}
        .event-details {{
            margin-bottom: 25px;
            border-bottom: 1px solid #eee;
            padding-bottom: 20px;
        }}
        .event-property {{
            display: flex;
            margin-bottom: 12px;
            align-items: flex-start;
            gap: 10px;
        }}
        .property-label {{
            font-weight: 600;
            min-width: 100px;
            color: #4a154b;
            flex-shrink: 0;
        }}
        .property-value {{
            flex: 1;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }}
        .ticket-type-section {{
            margin-bottom: 30px;
            padding: 20px;
            background-color: #f8f9fa;
            border-radius: 8px;
        }}
        .ticket-type-section h3 {{
            margin-top: 0;
            color: #4a154b;
        }}
        .ticket-list {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 15px;
        }}
        .ticket-item {{
            background-color: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
            transition: transform 0.3s ease;
        }}
        .ticket-item:hover {{
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}
        .qr-box {{
            text-align: center;
        }}
        .qr-code-img {{
            width: 150px;
            height: 150px;
            margin: 0 auto;
            display: block;
        }}
        .qr-instructions {{
            margin-top: 10px;
            color: #6c757d;
            font-size: 12px;
        }}
        .ticket-id {{
            font-size: 11px;
            color: #777;
            margin-top: 5px;
        }}
        .highlight {{
            background-color: #f6f3ff;
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
            border-left: 4px solid #4a154b;
        }}
        .footer {{
            margin-top: 30px;
            text-align: center;
            color: #777;
            font-size: 14px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }}
        .section-title {{
            position: relative;
            padding-left: 15px;
            margin-top: 30px;
            color: #4a154b;
            font-weight: 600;
        }}
        .section-title:before {{
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            height: 100%;
            width: 5px;
            background: linear-gradient(135deg, #6a3093 0%, #4a154b 100%);
            border-radius: 5px;
        }}

        /* Mobile Responsive Styles */
        @media only screen and (max-width: 480px) {{
            .email-body {{
                padding: 20px 15px;
            }}
            .event-property {{
                flex-direction: column;
                gap: 2px;
                margin-bottom: 15px;
                padding-bottom: 10px;
                border-bottom: 1px solid #f0f0f0;
            }}
            .property-label {{
                min-width: auto;
                margin-bottom: 3px;
                font-size: 14px;
            }}
            .property-value {{
                font-size: 14px;
                margin-left: 0;
            }}
            .ticket-list {{
                grid-template-columns: 1fr;
                gap: 15px;
            }}
            .qr-code-img {{
                width: 120px;
                height: 120px;
            }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="email-header">
            <h1>🎫 Your Ticket QR Code 🎫</h1>
        </div>
        <div class="email-body">
            <p>Dear {user.full_name},</p>

            <div class="highlight">
                <h2>🎉 Your Ticket QR Code is Ready! 🎉</h2>
            </div>

            <div class="event-details">
                <h3 class="section-title">📌 Event Details</h3>

                <div class="event-property">
                    <div class="property-label">Event:</div>
                    <div class="property-value">{event.name}</div>
                </div>

                <div class="event-property">
                    <div class="property-label">Location:</div>
                    <div class="property-value">{event.location}</div>
                </div>

                <div class="event-property">
                    <div class="property-label">Date:</div>
                    <div class="property-value">{event_date}</div>
                </div>

                <div class="event-property">
                    <div class="property-label">Time:</div>
                    <div class="property-value">{start_time} - {end_time}</div>
                </div>

                <div class="event-property">
                    <div class="property-label">Description:</div>
                    <div class="property-value">{event.description}</div>
                </div>
            </div>

            <h3 class="section-title">🎟️ Ticket Details</h3>

            <div class="event-property">
                <div class="property-label">Ticket ID:</div>
                <div class="property-value">{ticket.id}</div>
            </div>

            <div class="event-property">
                <div class="property-label">Ticket Type:</div>
                <div class="property-value">{ticket.ticket_type.type_name.value if hasattr(ticket.ticket_type.type_name, 'value') else str(ticket.ticket_type.type_name)}</div>
            </div>

            <div class="event-property">
                <div class="property-label">Quantity:</div>
                <div class="property-value">{ticket.quantity}</div>
            </div>

            <div class="event-property">
                <div class="property-label">Price:</div>
                <div class="property-value">${float(ticket.ticket_type.price):.2f}</div>
            </div>

            <div class="event-property">
                <div class="property-label">Purchase Date:</div>
                <div class="property-value">{ticket.purchase_date.strftime('%B %d, %Y')}</div>
            </div>

            <h3 class="section-title">📱 Your QR Code</h3>
            <p>Please present this code at the entrance for seamless check-in.</p>

            <div class="ticket-list">
                <div class="ticket-item">
                    <div class="qr-box">
                        <img src="cid:qr_{ticket.id}" class="qr-code-img" alt="Ticket QR Code">
                        <div class="qr-instructions">
                            Present this QR code at the event entrance
                        </div>
                        <div class="ticket-id">ID: {ticket.id}</div>
                    </div>
                </div>
            </div>

            <div class="highlight">
                <p>You can share this QR code with your guests. Each code can only be scanned once.</p>
                <p>Save this email for quicker entry at the event.</p>
            </div>

            <div class="footer">
                <p>Thank you for your purchase! We look forward to seeing you at the event.</p>
                <p>If you have any questions, please contact our support team.</p>
            </div>
        </div>
    </div>
</body>
</html>
"""
        subject = "🎟️ Your Ticket QR Code for the Event"

        # Create text version
        text_content = f"""Hi {user.full_name},
🎉 Your Ticket QR Code is Ready! 🎉
Event Details:
- Event: {event.name}
- Location: {event.location}
- Date: {event_date}
- Time: {start_time} - {end_time}
- Description: {event.description}
Ticket Details:
- Ticket ID: {ticket.id}
- Ticket Type: {ticket.ticket_type.type_name.value if hasattr(ticket.ticket_type.type_name, 'value') else str(ticket.ticket_type.type_name)}
- Quantity: {ticket.quantity}
- Price: ${float(ticket.ticket_type.price):.2f}
- Purchase Date: {ticket.purchase_date.strftime('%B %d, %Y')}
Please present the attached QR code at the event entrance for scanning.
Thank you for your purchase! We look forward to seeing you at the event.
If you have any questions, please contact our support team."""

        return subject, html_content, text_content
    
    @jwt_required()
    def get(self):
        """Return only QR code images for user's tickets"""
        try:
            user_id = get_jwt_identity()
            user = User.query.get(user_id)

            if not user:
                return {"error": "User not found"}, 404
            if str(user.role).upper() != "ATTENDEE":
                return {"error": "Only attendees can access ticket QR codes"}, 403

            tickets = Ticket.query.filter_by(user_id=user.id).all()
            if not tickets:
                return {"message": "No tickets found", "qr_codes": []}, 200

            qr_codes = []
            for ticket in tickets:
                if not ticket.qr_code:
                    continue
                filename, img_bytes = generate_qr_attachment(ticket)
                if not img_bytes:
                    continue
                base64_img = base64.b64encode(img_bytes).decode("utf-8")
                qr_codes.append({
                    "ticket_id": ticket.id,
                    "qr_code_base64": base64_img,
                    "filename": filename
                })

            return {
                "user_id": user.id,
                "user_name": user.full_name,
                "total_qr_codes": len(qr_codes),
                "qr_codes": qr_codes
            }, 200

        except Exception as e:
            logger.error("Error retrieving ticket QR codes", exc_info=True)
            return {"error": "Internal server error"}, 500

    @jwt_required()
    def post(self):
        """Send QR code to friends if user bought multiple tickets"""
        try:
            data = request.get_json() or {}
            ticket_id = data.get('ticket_id')
            recipient_emails = data.get("recipient_email")

            if isinstance(recipient_emails, str):
                recipient_emails = [recipient_emails]

            if not recipient_emails or not isinstance(recipient_emails, list):
                return {"error": "recipient_email must be a valid email or list of emails"}, 400

            valid_emails = [email.strip().lower() for email in recipient_emails if self._validate_email(email)]
            if not valid_emails:
                return {"error": "No valid recipient emails provided"}, 400

            if not ticket_id:
                return {"error": "ticket_id is required"}, 400

            try:
                ticket_id = int(ticket_id)
            except (ValueError, TypeError):
                return {"error": "Invalid ticket_id format"}, 400

            user_id = get_jwt_identity()
            user = User.query.get(user_id)
            if not user:
                return {"error": "User not found"}, 404
            if str(user.role).upper() != "ATTENDEE":
                return {"error": "Only attendees can email ticket QR codes"}, 403

            ticket = Ticket.query.filter_by(id=ticket_id, user_id=user.id).first()
            if not ticket:
                return {"error": "Ticket not found or does not belong to you"}, 404
            if not ticket.qr_code:
                return {"error": "Ticket does not have a QR code"}, 400
            if ticket.quantity <= 1:
                return {"error": "You must purchase more than 1 ticket to send to others"}, 400

            expected = ticket.quantity - 1
            if len(valid_emails) != expected:
                return {
                    "error": f"You bought {ticket.quantity} tickets. Provide exactly {expected} email(s) for friends."
                }, 400

            event = ticket.event
            if not event:
                return {"error": "Event not found"}, 404

            qr_bytes = self._get_qr_code_image(ticket)
            subject, html_body, text_body = self._create_email_content(user, ticket, event)

            attachment = [{
                "filename": f"ticket_{ticket.id}_qr_code.png",
                "content_type": "image/png",
                "content": qr_bytes,
                "headers": [("Content-ID", f"<qr_{ticket.id}>")]
            }]

            sent = []
            failed = []
            for email in valid_emails:
                try:
                    success = send_email_with_attachment(
                        recipient=email,
                        subject=subject,
                        body=text_body,
                        html=html_body,
                        attachments=attachment
                    )
                    if success:
                        sent.append(email)
                    else:
                        failed.append(email)
                except Exception as e:
                    logger.error(f"Failed to send email to {email}", exc_info=True)
                    failed.append(email)

            return {
                "message": "QR code email attempt complete",
                "ticket_id": ticket.id,
                "event_name": event.name,
                "quantity": ticket.quantity,
                "sent_to_friends": sent,
                "failed_to_send": failed,
                "your_ticket": "Reserved for your use (not emailed)",
                "timestamp": datetime.utcnow().isoformat()
            }, 207 if failed else 200

        except Exception as e:
            logger.error("Unexpected error in QR code email endpoint", exc_info=True)
            return {"error": "Internal server error"}, 500

    def register_qrcode_ticket_resources(api):
        """Register the Ticket and TicketQRCodeEmail resources with the API."""
        api.add_resource(TicketResource, "/tickets/<int:ticket_id>")
        api.add_resource(TicketQRCodeEmailResource, "/tickets", "/tickets/email-qrcode")
   