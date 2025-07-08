from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from io import BytesIO
import qrcode
import re
from datetime import datetime
from email_utils import send_email_with_attachment
from model import db, Ticket, User, UserRole, Event, TicketType
import logging

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
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=4,
            )
            qr.add_data(ticket.qr_code)
            qr.make(fit=True)
            
            # Generate image
            qr_img = qr.make_image(fill_color="black", back_color="white")
            
            # Save to buffer
            buffer = BytesIO()
            qr_img.save(buffer, format="PNG")
            buffer.seek(0)
            
            return buffer.read()
            
        except Exception as e:
            logger.error(f"QR code image creation failed: {e}")
            raise
    
    def _create_email_content(self, user, ticket, event):
        """Create email subject and body with event details"""
        subject = "🎟️ QR Codes for the Events You Paid For"
        
        # Format event date and time
        event_date = event.date.strftime('%B %d, %Y') if event.date else 'TBD'
        event_time = event.start_time.strftime('%I:%M %p') if event.start_time else 'TBD'
        end_time = event.end_time.strftime('%I:%M %p') if event.end_time else 'Till Late'
        
        # Casual, friendly email body with detailed event information
        body = f"""Hi {user.full_name or 'there'},

I hope you're doing well!

Just wanted to share with you the QR codes for the event(s) you paid for. You'll need these codes for entry at the venue, so please keep them safe and easily accessible on your phone.

👇 Here are your ticket(s):

📅 EVENT DETAILS:
Event: {event.name}
Date: {event_date}
Time: {event_time} - {end_time}
Location: {event.location}

🎫 TICKET DETAILS:
Ticket ID: {ticket.id}
Ticket Type: {ticket.ticket_type.type_name.value if hasattr(ticket.ticket_type.type_name, 'value') else str(ticket.ticket_type.type_name)}
Quantity: {ticket.quantity}
Price: ${float(ticket.ticket_type.price):.2f}
Purchase Date: {ticket.purchase_date.strftime('%B %d, %Y')}

[QR code attached to this email]

Let me know if you have any trouble accessing them.

See you at the event!

Best,
The Event Team"""
        return subject, body
    
    @jwt_required()
    def get(self):
        """Get all tickets with event details for the authenticated user"""
        try:
            # Get authenticated user
            user_id = get_jwt_identity()
            user = User.query.get(user_id)
            
            if not user:
                logger.warning(f"User {user_id} not found")
                return {"error": "User not found"}, 404
            
            # Check user role
            if str(user.role).upper() != "ATTENDEE":
                logger.warning(f"Non-attendee user {user_id} attempted to access tickets")
                return {"error": "Only attendees can access ticket information"}, 403
            
            # Get all tickets for the user
            tickets = Ticket.query.filter_by(user_id=user.id).all()
            
            if not tickets:
                return {"message": "No tickets found", "tickets": []}, 200
            
            ticket_list = []
            for ticket in tickets:
                event = ticket.event
                ticket_type = ticket.ticket_type
                
                # Format event details
                event_details = {
                    "event_id": event.id,
                    "event_name": event.name,
                    "event_description": event.description,
                    "event_date": event.date.strftime('%Y-%m-%d') if event.date else None,
                    "event_start_time": event.start_time.strftime('%H:%M:%S') if event.start_time else None,
                    "event_end_time": event.end_time.strftime('%H:%M:%S') if event.end_time else None,
                    "event_location": event.location,
                    "event_image": event.image,
                    "organizer": {
                        "id": event.organizer.id,
                        "company_name": event.organizer.company_name,
                        "company_description": event.organizer.company_description
                    } if event.organizer else None
                }
                
                # Ticket details
                ticket_info = {
                    "ticket_id": ticket.id,
                    "ticket_type": ticket_type.type_name.value if hasattr(ticket_type.type_name, 'value') else str(ticket_type.type_name),
                    "quantity": ticket.quantity,
                    "price": float(ticket_type.price),
                    "payment_status": ticket.payment_status.value,
                    "purchase_date": ticket.purchase_date.strftime('%Y-%m-%d %H:%M:%S') if ticket.purchase_date else None,
                    "has_qr_code": bool(ticket.qr_code),
                    "qr_code_available": bool(ticket.qr_code)
                }
                
                # Combine event and ticket information
                ticket_list.append({
                    **ticket_info,
                    "event_details": event_details
                })
            
            logger.info(f"Retrieved {len(ticket_list)} tickets for user {user_id}")
            return {
                "user_id": user_id,
                "user_name": user.full_name,
                "tickets": ticket_list,
                "total_tickets": len(ticket_list)
            }, 200
            
        except Exception as e:
            logger.error(f"Error retrieving tickets: {e}", exc_info=True)
            return {"error": "Internal server error"}, 500
    
    @jwt_required()
    def post(self):
        """Send QR code for a specific ticket to a provided email (attendees only)"""
        try:
            # Parse and validate input
            data = request.get_json() or {}
            ticket_id = data.get('ticket_id')
            recipient_email = data.get('recipient_email', '').strip().lower()
            
            # Validate required fields
            if not ticket_id:
                logger.warning("Email QR request missing ticket_id")
                return {"error": "ticket_id is required"}, 400
            
            # Validate ticket_id format
            try:
                ticket_id = int(ticket_id)
            except (ValueError, TypeError):
                return {"error": "Invalid ticket_id format"}, 400
            
            # Get authenticated user
            user_id = get_jwt_identity()
            user = User.query.get(user_id)
            
            if not user:
                logger.warning(f"User {user_id} not found during QR email request")
                return {"error": "User not found"}, 404
            
            # Check user role
            if str(user.role).upper() != "ATTENDEE":
                logger.warning(f"Non-attendee user {user_id} attempted to email QR code")
                return {"error": "Only attendees can email ticket QR codes"}, 403
            
            # Find ticket that belongs to user with event details
            ticket = Ticket.query.filter_by(id=ticket_id, user_id=user.id).first()
            
            if not ticket:
                logger.warning(f"Ticket {ticket_id} not found for user {user_id}")
                return {"error": "Ticket not found or does not belong to you"}, 404
            
            # Check if ticket has QR code
            if not ticket.qr_code:
                logger.warning(f"Ticket {ticket_id} does not have a QR code")
                return {"error": "Ticket does not have a QR code available"}, 400
            
            # Get event details
            event = ticket.event
            if not event:
                logger.error(f"Event not found for ticket {ticket_id}")
                return {"error": "Event information not available"}, 404
            
            # Determine recipient email with priority order
            if not recipient_email:
                recipient_email = ticket.email or user.email
            
            # Validate final recipient email
            if not recipient_email:
                return {"error": "No recipient_email provided and none available on record"}, 400
            
            if not self._validate_email(recipient_email):
                return {"error": "Invalid email format"}, 400
            
            # Get QR code image from existing ticket QR code
            try:
                qr_bytes = self._get_qr_code_image(ticket)
            except Exception as e:
                logger.error(f"QR code image creation failed for ticket {ticket_id}: {e}")
                return {"error": "Failed to process QR code"}, 500
            
            # Prepare email attachment
            attachment = [{
                "filename": f"ticket_{ticket.id}_qr_code.png",
                "content_type": "image/png",
                "content": qr_bytes
            }]
            
            # Create email content with event details
            subject, body = self._create_email_content(user, ticket, event)
            
            # Send email with enhanced error handling
            try:
                email_sent = send_email_with_attachment(
                    recipient=recipient_email,
                    subject=subject,
                    body=body,
                    attachments=attachment,
                    is_html=False
                )
                
                if not email_sent:
                    logger.error(f"Email sending failed for ticket {ticket_id} to {recipient_email}")
                    return {"error": "Failed to send email. Please try again later."}, 500
                
            except Exception as e:
                logger.error(f"Email sending exception for ticket {ticket_id}: {e}")
                return {"error": "Email service temporarily unavailable"}, 503
            
            # Log successful email sending
            logger.info(f"Existing QR code email sent successfully for ticket {ticket_id} to {recipient_email}")
            
            return {
                "message": f"QR code sent successfully to {recipient_email}",
                "ticket_id": ticket_id,
                "event_name": event.name,
                "event_date": event.date.strftime('%Y-%m-%d') if event.date else None,
                "sent_to": recipient_email,
                "timestamp": datetime.utcnow().isoformat()
            }, 200
            
        except Exception as e:
            logger.error(f"Unexpected error in ticket QR email: {e}", exc_info=True)
            return {"error": "Internal server error"}, 500

def register_ticket_resources(api):
    """Registers ticket-related resources with Flask-RESTful API."""
    api.add_resource(TicketResource, "/tickets/<int:ticket_id>")
    api.add_resource(TicketQRCodeEmailResource, "/tickets", "/tickets/email-qrcode")