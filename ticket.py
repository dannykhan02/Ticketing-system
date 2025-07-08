from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, Event, TicketType, User, Transaction, PaymentStatus, UserRole, PaymentMethod, TransactionTicket
from config import Config
# Import Paystack functionalities
from paystack import initialize_paystack_payment, refund_paystack_payment
# Import M-Pesa functionalities
from mpesa_intergration import STKPush, normalize_phone_number, RefundTransaction, get_access_token
from email_utils import mail
import mimetypes
from flask_mail import Message
from itsdangerous import URLSafeSerializer
import qrcode
import logging
import os
from datetime import datetime
 
import uuid
import requests
import io
import time 
from io import BytesIO
import base64
from sqlalchemy.exc import OperationalError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORTCODE = os.getenv("BUSINESS_SHORTCODE")
PASSKEY = os.getenv("PASSKEY")
CALLBACK_URL = os.getenv("CALLBACK_URL")
def get_valid_phone(request_json, user):
    """
    Returns a cleaned phone number or raises ValueError
    """
    raw_from_body = request_json.get("phone_number")
    raw_from_user = user.phone_number
    if not raw_from_body:
        raise ValueError("phone_number missing in request")
    if not raw_from_user:
        raise ValueError("Your profile has no phone_number; update it first")

    return normalize_phone_number(raw_from_body), normalize_phone_number(raw_from_user)

def complete_ticket_operation(transaction):
    """Updates ticket status once payment is successful and sends confirmation email."""
    try:
        logger.info(f"Completing ticket operation for Transaction ID: {transaction.id}")
        
        # Get all tickets associated with this transaction
        transaction_tickets = TransactionTicket.query.filter_by(transaction_id=transaction.id).all()
        
        if not transaction_tickets:
            logging.error(f"No tickets found for transaction ID {transaction.id}")
            raise ValueError("No tickets found for this transaction")
        
        tickets = []
        qr_attachments = []  # Changed from separate arrays to attachment tuples
        
        # Update all tickets status and generate QR code attachments
        for trans_ticket in transaction_tickets:
            ticket = Ticket.query.get(trans_ticket.ticket_id)
            if not ticket:
                logger.warning(f"Ticket with ID {trans_ticket.ticket_id} not found")
                continue
            
            # Update ticket status
            ticket.payment_status = PaymentStatus.PAID
            
            # Generate QR code attachment for this ticket
            qr_filename, qr_data = generate_qr_attachment(ticket)
            
            # Only add if QR code generation was successful
            if qr_filename and qr_data:
                tickets.append(ticket)
                qr_attachments.append((ticket, qr_filename, qr_data))
                
                # Log success
                logger.info(f"Ticket {ticket.id} marked as PAID. Payment Ref: {transaction.payment_reference}")
            else:
                logger.error(f"Failed to generate QR code for ticket {ticket.id}")
        
        db.session.commit()
        
        # Send confirmation email with QR code attachments
        if tickets:
            user = User.query.get(tickets[0].user_id)
            send_ticket_confirmation_email(user, tickets, transaction, qr_attachments)
        else:
            logger.error("No valid tickets with QR codes to send email for")
            
    except Exception as e:
        logger.error(f"Error updating tickets for transaction {transaction.id}: {str(e)}")
        db.session.rollback()  # Add rollback on error
        raise

def generate_qr_attachment(ticket):
    """Generate QR code file with enhanced security and visual appeal"""
    try:
        # Check if ticket has qr_code data, fallback to ticket ID
        qr_code_data = getattr(ticket, 'qr_code', None) or str(ticket.id)
        
        if not qr_code_data:
            logging.error(f"Ticket {ticket.id} has no QR code data")
            return None, None
            
        logger.info(f"Generating QR attachment for ticket {ticket.id} with data: {str(qr_code_data)[:50]}...")
        
        # Create QR code with enhanced settings
        qr = qrcode.QRCode(
            version=None, 
            error_correction=qrcode.constants.ERROR_CORRECT_H,  
            box_size=10, 
            border=4,  
        )
        
        qr.add_data(qr_code_data)
        qr.make(fit=True)
        
        img = qr.make_image(
            fill_color="#1a1a1a", 
            back_color="#ffffff",  
            image_factory=None  
        )
        
        # Convert to PNG with high quality
        img_buffer = BytesIO()
        img.save(img_buffer, format="PNG", quality=100)
        img_buffer.seek(0)
        
        # Generate filename using ticket ID
        filename = f"ticket_{ticket.id}.png"
        
        logger.info(f"Successfully generated QR attachment for ticket {ticket.id}")
        return (filename, img_buffer.getvalue())
        
    except Exception as e:
        logging.error(f"QR generation failed for ticket {ticket.id}: {str(e)}")
        return None, None

def send_ticket_confirmation_email(user, tickets, transaction, qr_attachments):
    """Send confirmation email with QR code attachments using Message format"""
    try:
        if not tickets:
            logger.error("No tickets to send email for")
            return False
        
        # Validate that we have matching data
        if len(tickets) != len(qr_attachments):
            logger.error("Mismatch between tickets and QR attachments")
            return False
            
        first_ticket = tickets[0]
        event = Event.query.get(first_ticket.event_id)
        
        if not event:
            logger.error(f"Event not found for ticket {first_ticket.id}")
            return False
        
        # Format event details
        event_date = event.date.strftime('%A, %B %d, %Y') if event.date else "Date not available"
        start_time = event.start_time.strftime('%H:%M:%S') if event.start_time else "Start time not available"
        end_time = event.end_time.strftime('%H:%M:%S') if event.end_time else "Till Late"
        
        # Group tickets by type for better organization
        tickets_by_type = {}
        for ticket in tickets:
            ticket_type = TicketType.query.get(ticket.ticket_type_id)
            ticket_type_name = ticket_type.type_name if ticket_type else "Standard"
            
            if ticket_type_name not in tickets_by_type:
                tickets_by_type[ticket_type_name] = []
            tickets_by_type[ticket_type_name].append(ticket)
        
        # Create ticket type sections
        ticket_type_sections = ""
        for ticket_type_name, type_tickets in tickets_by_type.items():
            ticket_type_sections += f"""
                <div class="ticket-type-section">
                    <h3>{ticket_type_name} ({len(type_tickets)} tickets)</h3>
                    <div class="ticket-list">
                        {''.join([f'''
                            <div class="ticket-item">
                                <div class="qr-box">
                                    <img src="cid:qr_{ticket.id}" 
                                         class="qr-code-img"
                                         alt="Ticket QR Code">
                                    <div class="qr-instructions">
                                        Ticket #{idx + 1} - Present this QR code at the event entrance
                                    </div>
                                    <div class="ticket-id">ID: {ticket.id}</div>
                                </div>
                            </div>
                        ''' for idx, ticket in enumerate(type_tickets)])}
                    </div>
                </div>
            """
        
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
                    <h1>🎫 Ticket Confirmation 🎫</h1>
                </div>
                <div class="email-body">
                    <p>Dear {user.full_name} ({user.phone_number}),</p>
                    
                    <div class="highlight">
                        <h2>🎉 Your Ticket Booking is Confirmed! 🎉</h2>
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
                    
                    <h3 class="section-title">🎟️ Ticket Summary</h3>
                    
                    <div class="event-property">
                        <div class="property-label">Total Tickets:</div>
                        <div class="property-value">{len(tickets)}</div>
                    </div>
                    
                    <div class="event-property">
                        <div class="property-label">Purchase Date:</div>
                        <div class="property-value">{tickets[0].purchase_date.strftime('%Y-%m-%d %H:%M:%S')}</div>
                    </div>
                    
                    <div class="event-property">
                        <div class="property-label">Amount Paid:</div>
                        <div class="property-value">{transaction.amount_paid}</div>
                    </div>
                    
                    <div class="event-property">
                        <div class="property-label">Payment Method:</div>
                        <div class="property-value">{transaction.payment_method.value if transaction else 'Pending'}</div>
                    </div>
                    
                    <div class="event-property">
                        <div class="property-label">Reference:</div>
                        <div class="property-value">{transaction.payment_reference}</div>
                    </div>
                    
                    <h3 class="section-title">📱 Your QR Codes</h3>
                    <p>Please present these codes at the entrance for seamless check-in. Each QR code represents one ticket.</p>
                    
                    {ticket_type_sections}
                    
                    <div class="highlight">
                        <p>You can share these QR codes with your guests. Each code can only be scanned once.</p>
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
        
        # Create text version
        text_content = f"""Hi {user.full_name},

            🎉 Your Ticket Booking is Confirmed! 🎉

            Event Details:
            - Event: {event.name}
            - Location: {event.location}
            - Date: {event_date}
            - Time: {start_time} - {end_time}
            - Description: {event.description}

            Ticket Summary:
            - Total Tickets: {len(tickets)}
            - Purchase Date: {tickets[0].purchase_date.strftime('%Y-%m-%d %H:%M:%S')}
            - Amount Paid: {transaction.amount_paid}
            - Payment Method: {transaction.payment_method.value if transaction else 'Pending'}
            - Reference: {transaction.payment_reference}

            You have purchased the following tickets:
            {chr(10).join([f"- {TicketType.query.get(ticket.ticket_type_id).type_name if TicketType.query.get(ticket.ticket_type_id) else 'Standard'} (ID: {ticket.id})" for ticket in tickets])}

            Please present the attached QR codes at the event entrance for scanning.

            Thank you for your purchase! We look forward to seeing you at the event.

            If you have any questions, please contact our support team."""

        # Create email message with attachments
        msg = Message(
            subject=f"🎫 Your Tickets Confirmation - {event.name} 🎫",
            recipients=[user.email],
            sender=(Config.MAIL_DEFAULT_SENDER, Config.MAIL_USERNAME),
            charset="utf-8"
        )
        
        # Set HTML and text content
        msg.html = html_content
        msg.body = text_content
        
        # Attach QR codes with Content-ID for embedding
        for ticket, qr_filename, qr_data in qr_attachments:
            mime_type, _ = mimetypes.guess_type(qr_filename)
            mime_type = mime_type or "application/octet-stream"

            msg.attach(
                filename=qr_filename,
                content_type=mime_type,
                data=qr_data,
                headers=[("Content-ID", f"<qr_{ticket.id}>")]
            )

    # Try to send the email
        try:
            mail.send(msg)
            logger.info(f"Confirmation email sent to {user.email} with {len(qr_attachments)} tickets")
            return True
        except Exception as e:
            logger.error(f"Error sending confirmation email to {user.email}: {e}")
            return False
    except Exception as e:
        logger.error(f"Error sending confirmation email: {str(e)}")
        return False



class TicketResource(Resource):

    @jwt_required()
    def get(self, ticket_id=None):
        """Get a specific ticket or all tickets for the authenticated user."""
        try:
            identity = get_jwt_identity()  
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if ticket_id:
                ticket = Ticket.query.filter_by(id=ticket_id, user_id=user.id).first()
                if not ticket:
                    return {"error": "Ticket not found or does not belong to you"}, 404
                event = ticket.event
                ticket_type = ticket.ticket_type
                return {
                    "ticket_id": ticket.id,
                    "event": event.name,
                    "date": event.date.strftime('%Y-%m-%d') if event.date else None,
                    "time": event.start_time.strftime('%H:%M:%S') if event.start_time else None,
                    "location": event.location,
                    "ticket_type": ticket_type.type_name.value if hasattr(ticket_type.type_name, "value") else str(ticket_type.type_name),
                    "quantity": ticket.quantity,
                    "price":  float(ticket_type.price),
                    "status": ticket.payment_status.value,
                    "purchase_date": ticket.purchase_date.strftime('%Y-%m-%d %H:%M:%S') if ticket.purchase_date else None
                }, 200
            else:
                tickets = Ticket.query.filter_by(user_id=user.id).all()
                ticket_list = []
                for ticket in tickets:
                    event = ticket.event
                    ticket_type = ticket.ticket_type
                    ticket_list.append({
                        "ticket_id": ticket.id,
                        "event": event.name,
                        "date": event.date.strftime('%Y-%m-%d') if event.date else None,
                        "time": event.start_time.strftime('%H:%M:%S') if event.start_time else None,
                        "location": event.location,
                        "ticket_type": ticket_type.type_name.value if hasattr(ticket_type.type_name, "value") else str(ticket_type.type_name),
                        "quantity": ticket.quantity,
                        "price":  float(ticket_type.price),
                        "status": ticket.payment_status.value,
                        "purchase_date": ticket.purchase_date.strftime('%Y-%m-%d %H:%M:%S') if ticket.purchase_date else None
                    })
                return ticket_list, 200

        except Exception as e:
            logger.error(f"Error checking ticket status: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def post(self):
        logger.info("=== TICKET CREATION STARTED ===")

        try:
            identity = get_jwt_identity()
            logger.info(f"JWT Identity retrieved: {identity}")

            user = User.query.get(identity)
            if not user:
                logger.error(f"User not found for identity: {identity}")
                return {"error": "User not found"}, 404

            logger.info(f"User found: ID={user.id}, Email={user.email}, Phone={user.phone_number}")
            data = request.get_json()
            logger.info(f"Request data received: {data}")

            required_fields = ["event_id", "ticket_type_id", "quantity", "payment_method"]
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                logger.error(f"Missing required fields: {missing_fields}")
                return {"error": "Missing required fields"}, 400

            event = Event.query.get(data["event_id"])
            if not event:
                logger.error(f"Event not found: {data['event_id']}")
                return {"error": "Event not found"}, 404

            logger.info(f"Event found: ID={event.id}, Name={getattr(event, 'name', 'N/A')}")

            ticket_type = TicketType.query.filter_by(id=data["ticket_type_id"], event_id=event.id).first()
            if not ticket_type:
                logger.error(f"Ticket type not found: {data['ticket_type_id']} for event {event.id}")
                return {"error": "Ticket type not found for this event"}, 404

            logger.info(f"Ticket type found: ID={ticket_type.id}, Price={ticket_type.price}, Available={ticket_type.quantity}")

            if ticket_type.quantity == 0:
                logger.warning(f"Ticket type {ticket_type.id} is sold out")
                return {"error": "Tickets for this type are sold out"}, 400

            quantity = int(data["quantity"])
            logger.info(f"Requested quantity: {quantity}")

            if quantity <= 0:
                logger.error(f"Invalid quantity requested: {quantity}")
                return {"error": "Quantity must be at least 1"}, 400

            if ticket_type.quantity < quantity:
                logger.error(f"Insufficient tickets: requested={quantity}, available={ticket_type.quantity}")
                return {"error": f"Only {ticket_type.quantity} tickets are available"}, 400

            amount = ticket_type.price * quantity
            logger.info(f"Total amount calculated: {amount}")

            payment_reference = str(uuid.uuid4())
            logger.info(f"Payment reference generated: {payment_reference}")

            logger.info("Creating transaction record...")
            transaction = Transaction(
                amount_paid=amount,
                payment_status=PaymentStatus.PENDING,
                payment_reference=payment_reference,
                payment_method=data["payment_method"].upper(),
                timestamp=datetime.utcnow(),
                user_id=user.id
            )
            db.session.add(transaction)
            db.session.flush()

            if not transaction.id:
                logger.error("Failed to create transaction - no ID assigned")
                db.session.rollback()
                return {"error": "Failed to create transaction"}, 500

            logger.info(f"Transaction created successfully: ID={transaction.id}")

            logger.info(f"Creating {quantity} ticket records...")
            tickets = []
            transaction_tickets = []

            for i in range(quantity):
                temp_qr_code = f"pending_{uuid.uuid4()}"
                new_ticket = Ticket(
                    event_id=event.id,
                    ticket_type_id=ticket_type.id,
                    quantity=1,
                    phone_number=user.phone_number,
                    email=user.email,
                    payment_status=PaymentStatus.PENDING,
                    transaction_id=transaction.id,
                    user_id=user.id,
                    qr_code=temp_qr_code
                )
                db.session.add(new_ticket)
                tickets.append(new_ticket)
                logger.debug(f"Created ticket {i+1}/{quantity} with temp QR: {temp_qr_code}")

            db.session.flush()

            failed_tickets = [i for i, ticket in enumerate(tickets) if not ticket.id]
            if failed_tickets:
                logger.error(f"Failed to create tickets at indices: {failed_tickets}")
                db.session.rollback()
                return {"error": "Failed to create tickets"}, 500

            logger.info(f"All {len(tickets)} tickets created successfully")

            logger.info("Creating transaction-ticket relationships...")
            for i, ticket in enumerate(tickets):
                transaction_ticket = TransactionTicket(
                    transaction_id=transaction.id,
                    ticket_id=ticket.id
                )
                db.session.add(transaction_ticket)
                transaction_tickets.append(transaction_ticket)
                logger.debug(f"Created relationship {i+1}: transaction={transaction.id}, ticket={ticket.id}")

            db.session.commit()
            logger.info("Transaction and tickets committed to database")

            payment_method = data["payment_method"].upper()
            logger.info(f"Processing payment via {payment_method}")

            if payment_method == "MPESA":
                logger.info("=== MPESA PAYMENT PROCESSING ===")

                if "phone_number" not in data:
                    logger.error("Phone number not provided in request data")
                    self._rollback_transaction(transaction, tickets, transaction_tickets)
                    return {"error": "Phone number must be the registered one"}, 400

                user_phone_normalized = normalize_phone_number(user.phone_number)
                request_phone_normalized = normalize_phone_number(data["phone_number"])

                logger.info(f"Phone validation: user={user_phone_normalized}, request={request_phone_normalized}")

                if request_phone_normalized != user_phone_normalized:
                    logger.error("Phone number mismatch - rolling back transaction")
                    self._rollback_transaction(transaction, tickets, transaction_tickets)
                    return {"error": "Phone number must be the registered one"}, 400

                mpesa_data = {
                    "phone_number": user.phone_number,
                    "amount": float(amount),
                    "transaction_id": transaction.id
                }
                logger.info(f"M-Pesa request data: {mpesa_data}")

                logger.info("Initiating STK Push...")
                mpesa = STKPush()
                response, status_code = mpesa.post(mpesa_data)

                logger.info(f"STK Push response: status={status_code}, response={response}")

                if status_code == 200:
                    logger.info("STK Push successful")

                    if 'MerchantRequestID' in response:
                        transaction.merchant_request_id = response['MerchantRequestID']
                        logger.info(f"Stored MerchantRequestID: {response['MerchantRequestID']}")
                    elif 'merchant_request_id' in response:
                        transaction.merchant_request_id = response['merchant_request_id']
                        logger.info(f"Stored merchant_request_id: {response['merchant_request_id']}")

                    if 'CheckoutRequestID' in response:
                        transaction.checkout_request_id = response['CheckoutRequestID']
                        logger.info(f"Stored CheckoutRequestID: {response['CheckoutRequestID']}")
                    elif 'checkout_request_id' in response:
                        transaction.checkout_request_id = response['checkout_request_id']
                        logger.info(f"Stored checkout_request_id: {response['checkout_request_id']}")

                    db.session.commit()

                    checkout_request_id = response.get('CheckoutRequestID') or response.get('checkout_request_id')
                    if checkout_request_id:
                        logger.info(f"Starting status check for CheckoutRequestID: {checkout_request_id}")
                        return self._handle_mpesa_with_status_check(transaction, checkout_request_id, tickets, transaction_tickets)
                    else:
                        logger.warning("No CheckoutRequestID in response, returning STK Push response")
                        return response, status_code
                else:
                    logger.error(f"STK Push failed with status {status_code}")
                    self._rollback_transaction(transaction, tickets, transaction_tickets)
                    return {"error": "M-PESA payment initiation failed", "response": response}, status_code

            elif payment_method == "PAYSTACK":
                logger.info("=== PAYSTACK PAYMENT PROCESSING ===")

                if not user.email:
                    logger.error("User email not available for Paystack payment")
                    self._rollback_transaction(transaction, tickets, transaction_tickets)
                    return {"error": "User email is required for Paystack payment"}, 400

                logger.info(f"Initializing Paystack payment for email: {user.email}, amount: {amount}")
                init = initialize_paystack_payment(user.email, int(amount * 100))

                if isinstance(init, dict) and "error" in init:
                    logger.error(f"Paystack initialization failed: {init}")
                    self._rollback_transaction(transaction, tickets, transaction_tickets)
                    return init, 502

                transaction.payment_reference = init["reference"]
                db.session.commit()
                logger.info(f"Paystack payment initialized with reference: {init['reference']}")

                return {
                    "message": "Payment initialized",
                    "authorization_url": init["authorization_url"],
                    "reference": init["reference"]
                }, 200

            else:
                logger.error(f"Invalid payment method: {payment_method}")
                self._rollback_transaction(transaction, tickets, transaction_tickets)
                return {"error": "Invalid payment method"}, 400

        except OperationalError as e:
            logger.error(f"Database operational error: {e}")
            db.session.rollback()
            return {"error": "Database connection error"}, 500
        except Exception as e:
            logger.error(f"Unexpected error in ticket creation: {e}", exc_info=True)
            db.session.rollback()
            return {"error": "An internal error occurred"}, 500

def register_ticket_resources(api):
    """Registers ticket-related resources with Flask-RESTful API."""
    api.add_resource(TicketResource, "/tickets", "/tickets/<int:ticket_id>")