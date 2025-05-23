from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, Event, TicketType, User, Transaction, PaymentStatus, UserRole, PaymentMethod, TransactionTicket
from config import Config
# Import Paystack functionalities
from paystack import initialize_paystack_payment, refund_paystack_payment
# Import M-Pesa functionalities
from mpesa_intergration import STKPush, normalize_phone_number, RefundTransaction
from email_utils import send_email
from itsdangerous import URLSafeSerializer
import qrcode
import logging
import os
import datetime
import uuid
import requests
import io
import base64
from sqlalchemy.exc import OperationalError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        qr_codes_data = []
        qr_codes_images = []
        
        # Update all tickets status and generate QR codes
        for trans_ticket in transaction_tickets:
            ticket = Ticket.query.get(trans_ticket.ticket_id)
            if not ticket:
                logger.warning(f"Ticket with ID {trans_ticket.ticket_id} not found")
                continue
                
            # Update ticket status
            ticket.payment_status = PaymentStatus.PAID
            
            # Generate QR code for this ticket
            qr_code_data, qr_code_image = generate_qr_code(ticket)
            
            tickets.append(ticket)
            qr_codes_data.append(qr_code_data)
            qr_codes_images.append(qr_code_image)
            
            # Log success
            logger.info(f"Ticket {ticket.id} marked as PAID. Payment Ref: {transaction.payment_reference}")
        
        db.session.commit()
        
        # Send confirmation email with all QR codes
        if tickets:
            user = User.query.get(tickets[0].user_id)
            send_confirmation_email(user, tickets, transaction, qr_codes_data, qr_codes_images)
        
    except Exception as e:
        logger.error(f"Error updating tickets for transaction {transaction.id}: {str(e)}")
        raise

def generate_qr_code(ticket):
    """Generates a QR code with a secure encrypted URL and returns it as a base64-encoded image."""
  
    qr_code_data = ticket.qr_code
    
    # Generate QR code image
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_code_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    qr_code_images = base64.b64encode(buffered.getvalue()).decode()
    
    return qr_code_data, qr_code_images

def send_confirmation_email(user, tickets, transaction, qr_codes_data, qr_codes_images, is_new=True):
    """Sends an email with multiple ticket details and embedded QR codes."""
    if not tickets:
        logger.error("No tickets to send email for")
        return
        
    # Get event details from the first ticket (all tickets are for the same event)
    first_ticket = tickets[0]
    event = Event.query.get(first_ticket.event_id)
    
    event_date = event.date.strftime('%A, %B %d, %Y') if event.date else "Date not available"
    start_time = event.start_time.strftime('%H:%M:%S') if event.start_time else "Start time not available"
    end_time = event.end_time.strftime('%H:%M:%S') if event.end_time else "Till Late"
    
    subject = f"🎫 {'Your' if is_new else 'Updated'} Tickets Confirmation - {event.name} 🎫"
    
    # Start building the HTML email body
    body = f"""
    <!DOCTYPE html>
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
            .wrapper {{
                padding: 20px;
                max-width: 600px;
                margin: 0 auto;
            }}
            .header {{
                background: linear-gradient(135deg, #6a3093 0%, #4a154b 100%);
                color: white;
                padding: 25px 15px;
                text-align: center;
                border-radius: 10px 10px 0 0;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }}
            .header h1 {{
                margin: 0;
                font-size: 24px;
                letter-spacing: 0.5px;
            }}
            .content {{
                background-color: white;
                padding: 25px 20px;
                border-radius: 0 0 10px 10px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }}
            .event-details {{
                margin-bottom: 25px;
                border-bottom: 1px solid #eee;
                padding-bottom: 20px;
            }}
            .event-property {{
                display: flex;
                margin-bottom: 10px;
                flex-wrap: wrap;
            }}
            .property-label {{
                font-weight: 600;
                min-width: 100px;
                color: #4a154b;
                margin-bottom: 10px;
            }}
            .property-value {{
                flex-grow: 1;
                word-wrap: break-word;
            }}
            .qr-container {{
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 20px;
                margin: 25px 0;
            }}
            .qr-code {{
                    flex: 1 1 180px;
                    text-align: center;
                    margin-bottom: 15px;
                    padding: 15px;
                    border: 1px solid #eaeaea;
                    border-radius: 10px;
                    background-color: white;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.05);
                    transition: transform 0.3s ease;
            }}
            .qr-code:hover {{
                transform: translateY(-5px);
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            }}
            .ticket-label {{
               font-weight: 600;
                margin-bottom: 10px;
                color: #4a154b;
                font-size: 15px;
                padding: 5px 10px;
                background-color: #f6f3ff;
                border-radius: 20px;
                display: inline-block;
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
            .footer {{
                margin-top: 30px;
                text-align: center;
                color: #777;
                font-size: 14px;
                padding-top: 20px;
                border-top: 1px solid #eee;
            }}
            .highlight {{
                background-color: #f6f3ff;
                padding: 15px;
                border-radius: 8px;
                margin: 15px 0;
                border-left: 4px solid #4a154b;
            }}
            .btn, .btn-download {{
                display: inline-block;
                padding: 10px 20px;
                background: linear-gradient(135deg, #6a3093 0%, #4a154b 100%);
                color: white;
                text-decoration: none;
                border-radius: 5px;
                font-weight: 500;
                margin-top: 15px;
                text-align: center;
            }}
            .btn-download {{
                padding: 6px 12px;
                font-size: 13px;
                margin-top: 8px;
                transition: all 0.3s ease;
            }}
            .btn-download:hover {{
                background: linear-gradient(135deg, #7b3dab 0%, #5c1a5e 100%);
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            }}
            .download-link {{
                margin-top: 5px;
            }}
            .ticket-id {{
                font-size: 12px;
                color: #777;
                margin-top: 5px;
            }}
            .qr-img {{
                   width: 100%;
                    max-width: 180px;
                    height: auto;
                    padding: 10px;
                    background-color: white;
                    border-radius: 5px;
                    margin: 10px auto;
                    display: block;
            }}
            @media only screen and (max-width: 480px) {{
                .content {{
                    padding: 20px 15px;
                }}
                .wrapper {{
                    padding: 15px;
                }}
                .header h1 {{
                    font-size: 22px ;
                }}
                .qr-code {{
                    flex: 1 1 100%;
                }}
                .event-property {{
                    flex-direction: column;
                }}
                .property-label {{
                    min-width: 100%;
                    margin-bottom: 5px;
                }}
                .qr-img {{
                    width: 150px;
                    height: 150px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="wrapper">
            <div class="header">
                <h1>🎫 Ticket Confirmation 🎫</h1>
            </div>
            <div class="content">
                <p>Dear {user.full_name} ({user.phone_number}),</p>
                
                <div class="highlight">
                    <h2>🎉 Your Ticket Booking is {'Confirmed' if is_new else 'Updated'}! 🎉</h2>
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
                
                <div class="qr-container">
    """
    
    
    for i, (ticket, qr_image, qr_data) in enumerate(zip(tickets, qr_codes_images, qr_codes_data)):
        ticket_type = TicketType.query.get(ticket.ticket_type_id)
        ticket_type_name = ticket_type.type_name if ticket_type else "Standard"
        
        # Create a unique filename for download
        download_filename = f"ticket_{ticket.id}_{str(ticket_type_name).replace(' ', '_')}.png"

        
        body += f"""
                <div class="qr-code">
                    <div class="ticket-label">{ticket_type_name}</div>
                    <a href="data:image/png;base64,{qr_image}" download="{download_filename}">
                        <img src="data:image/png;base64,{qr_image}" alt="Ticket QR Code" class="qr-img">
                    </a>
                    <div class="ticket-id">Ticket #{i+1} · ID: {ticket.id}</div>
                    <div class="download-link">
                        <a href="data:image/png;base64,{qr_image}" download="{download_filename}" class="btn-download">Download QR</a>
                    </div>
                </div>
        """
    
    # Complete the HTML email
    body += """
                </div>
                
                <div class="highlight">
                    <p>You can share these QR codes with your guests. Each code can only be scanned once.</p>
                    <p>Save this email or download the QR codes for quicker entry.</p>
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
    
    try:
        send_email(user.email, subject, body, html=True)
        logger.info(f"Confirmation email sent to {user.email} with {len(tickets)} tickets")
    except Exception as e:
        logger.error(f"Error sending confirmation email: {str(e)}")

class TicketResource(Resource):

    @jwt_required()
    def get(self, ticket_id=None):
        """Get a specific ticket or all tickets for the authenticated user."""
        try:
            identity = get_jwt_identity()  # Get authenticated user ID
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
                    "price": ticket_type.price,
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
                        "price": ticket_type.price,
                        "status": ticket.payment_status.value,
                        "purchase_date": ticket.purchase_date.strftime('%Y-%m-%d %H:%M:%S') if ticket.purchase_date else None
                    })
                return ticket_list, 200

        except Exception as e:
            logger.error(f"Error checking ticket status: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def post(self):
        """Create new tickets for the authenticated user after successful payment."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if user.role != UserRole.ATTENDEE:
                return {"error": "Only attendees can purchase tickets"}, 403

            data = request.get_json()
            required_fields = ["event_id", "ticket_type_id", "quantity", "payment_method"]
            if not all(field in data for field in required_fields):
                return {"error": "Missing required fields"}, 400

            event = Event.query.get(data["event_id"])
            if not event:
                return {"error": "Event not found"}, 404

            ticket_type = TicketType.query.filter_by(id=data["ticket_type_id"], event_id=event.id).first()
            if not ticket_type:
                return {"error": "Ticket type not found for this event"}, 404

            if ticket_type.quantity == 0:
                return {"error": "Tickets for this type are sold out"}, 400

            quantity = int(data["quantity"])
            if quantity <= 0:
                return {"error": "Quantity must be at least 1"}, 400

            if ticket_type.quantity < quantity:
                return {"error": f"Only {ticket_type.quantity} tickets are available"}, 400

            amount = ticket_type.price * quantity

            # Generate a unique payment reference
            payment_reference = str(uuid.uuid4())

            # Create a new Transaction first (PENDING for now)
            transaction = Transaction(
                amount_paid=amount,
                payment_status=PaymentStatus.PENDING,
                payment_reference=payment_reference,
                payment_method=data["payment_method"].upper(),
                timestamp=datetime.datetime.utcnow(),
                user_id=user.id
            )
            db.session.add(transaction)
            db.session.flush()  # Get the transaction.id before commit
            
            tickets = []
            
            # Create individual tickets (one per quantity)
            for _ in range(quantity):
                temp_qr_code = f"pending_{uuid.uuid4()}"
                new_ticket = Ticket(
                    event_id=event.id,
                    ticket_type_id=ticket_type.id,
                    quantity=1,  # Each ticket record represents a single ticket
                    phone_number=user.phone_number,
                    email=user.email,
                    payment_status=PaymentStatus.PENDING,
                    transaction_id=transaction.id,
                    user_id=user.id,
                    qr_code=temp_qr_code
                )
                db.session.add(new_ticket)
                db.session.flush()  # Get the ticket.id before commit
                
                # Create relationship in the TransactionTicket table
                transaction_ticket = TransactionTicket(
                    transaction_id=transaction.id,
                    ticket_id=new_ticket.id
                )
                db.session.add(transaction_ticket)
                tickets.append(new_ticket)
            
            db.session.commit()

            # Process Payment
            if data["payment_method"] == "Mpesa":
                if "phone_number" not in data or normalize_phone_number(data["phone_number"]) != normalize_phone_number(user.phone_number):
                    return {"error": "Phone number must be the registered one"}, 400

                # Initiate STK Push using the imported class
                mpesa_data = {
                    "phone_number": user.phone_number,
                    "amount": amount,
                    "transaction_id": transaction.id  # Pass the transaction ID for reference
                }
                mpesa = STKPush()
                response, status_code = mpesa.post(mpesa_data)

                if status_code == 200:
                    return response, status_code
                else:
                    # If STK Push fails, revert the ticket creation
                    for ticket in tickets:
                        db.session.delete(ticket)
                    db.session.delete(transaction)
                    db.session.commit()
                    return response, status_code

            elif data["payment_method"] == "Paystack":
                if not user.email:
                    return {"error": "User email is required for Paystack payment"}, 400

                # Initialize Paystack payment
                init = initialize_paystack_payment(user.email, int(amount * 100))
                if isinstance(init, dict) and "error" in init:
                    # Remote error – roll back and bubble up
                    for ticket in tickets:
                        db.session.delete(ticket)
                    db.session.delete(transaction)
                    db.session.commit()
                    return init, 502  # or 400

                # Save the Paystack reference
                transaction.payment_reference = init["reference"]
                db.session.commit()
                logger.info(f"Paystack payment initialized with reference: {init['reference']}")
                # Return the authorization URL so front-end can redirect
                return {
                    "message": "Payment initialized",
                    "authorization_url": init["authorization_url"],
                    "reference": init["reference"]
                }, 200

            else:
                for ticket in tickets:
                    db.session.delete(ticket)
                db.session.delete(transaction)
                db.session.commit()
                return {"error": "Invalid payment method"}, 400

        except OperationalError as e:
            logger.error(f"Database error: {e}")
            return {"error": "Database connection error"}, 500

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error initializing payment: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def put(self, ticket_id):
        """Update a ticket (Only the ticket owner can update)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            ticket = Ticket.query.filter_by(id=ticket_id, user_id=user.id).first()

            if not ticket:
                return {"error": "Ticket not found or does not belong to you"}, 404

            data = request.get_json()
            original_quantity = ticket.quantity

            if "quantity" in data:
                new_quantity = data["quantity"]

                if ticket.email is not None:  # Check if email is present
                    return {"error": "Tickets for which confirmation emails have been sent cannot have their quantity reduced or be cancelled for a refund."}, 400

                if new_quantity <= 0:
                    return {"error": "Quantity must be at least 1"}, 400

                ticket_type = TicketType.query.get(ticket.ticket_type_id)
                if not ticket_type:
                    return {"error": "Ticket type not found"}, 404

                original_total_price = ticket.total_price
                ticket.quantity = new_quantity
                new_total_price = ticket.total_price

                price_difference = original_total_price - new_total_price

                transaction = ticket.transaction
                if price_difference > 0:  # Quantity reduced, initiate refund
                    if transaction:
                        if transaction.payment_method == PaymentMethod.MPESA:
                            # Initiate M-Pesa refund for the price difference
                            refund_data = {
                                "transaction_id": transaction.merchant_request_id,
                                "amount": float(price_difference)
                            }
                            mpesa_refund = RefundTransaction()
                            refund_response, refund_status = mpesa_refund.post(refund_data)

                            if refund_status == 200:
                                db.session.commit()
                                return {"message": "Ticket quantity updated and M-Pesa refund initiated.", "refund_details": refund_response}, 200
                            else:
                                db.session.rollback()
                                return {"error": "Error initiating M-Pesa refund.", "details": refund_response}, 500
                        elif transaction.payment_method == PaymentMethod.PAYSTACK:
                            # Initiate Paystack refund for the price difference
                            refund_amount = int(price_difference * 100)  # Amount in kobo/cents
                            refund_result = refund_paystack_payment(transaction.payment_reference, refund_amount)
                            if isinstance(refund_result, dict) and "error" not in refund_result:
                                db.session.commit()
                                return {"message": "Ticket quantity updated and Paystack refund initiated.", "refund_details": refund_result}, 200
                            else:
                                db.session.rollback()
                                return {"error": "Error initiating Paystack refund.", "details": refund_result}, 500
                        else:
                            db.session.commit()  # If no transaction, just update quantity
                            return {"message": "Ticket quantity updated."}, 200
                elif price_difference < 0:  # Quantity increased, you might want to handle additional payment here
                    db.session.commit()
                    return {"message": "Ticket quantity updated, additional payment might be required."}, 200
                else:
                    db.session.commit()
                    return {"message": "Ticket quantity updated."}, 200

            if "status" in data:
                pass  # You might want to handle other status updates here if needed

            db.session.commit()
            return {"message": "Ticket updated successfully"}, 200

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating ticket: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def delete(self, ticket_id):
        """Cancel a ticket (Only the ticket owner can delete)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            ticket = Ticket.query.filter_by(id=ticket_id, user_id=user.id).first()

            if not ticket:
                return {"error": "Ticket not found or does not belong to you"}, 404

            if ticket.email is not None:  # Check if email is present
                return {"error": "Tickets for which confirmation emails have been sent cannot be cancelled for a refund."}, 400

            transaction = ticket.transaction
            if transaction:
                if transaction.payment_method == PaymentMethod.MPESA:
                    # Initiate full M-Pesa refund
                    refund_data = {
                        "transaction_id": transaction.merchant_request_id,
                        "amount": float(ticket.total_price)
                    }
                    mpesa_refund = RefundTransaction()
                    refund_response, refund_status = mpesa_refund.post(refund_data)

                    if refund_status == 200:
                        qr_code_paths = [
                            f"static/qrcodes/ticket_{ticket.id}.png",
                            f"static/qrcodes/ticket_{ticket.id}.png"
                        ]
                        db.session.delete(ticket)
                        db.session.commit()

                        for path in qr_code_paths:
                            if os.path.exists(path):
                                os.remove(path)

                        return {"message": "Ticket cancelled and M-Pesa refund initiated.", "refund_details": refund_response}, 200
                    else:
                        return {"error": "Error initiating M-Pesa refund for cancellation.", "details": refund_response}, 500
                elif transaction.payment_method == PaymentMethod.PAYSTACK:
                    # Initiate full Paystack refund
                    refund_amount = int(float(ticket.total_price) * 100)  # Amount in kobo/cents
                    refund_result = refund_paystack_payment(transaction.payment_reference, refund_amount)
                    if isinstance(refund_result, dict) and "error" not in refund_result:
                        qr_code_paths = [
                            f"static/qrcodes/ticket_{ticket.id}.png",
                            f"static/qrcodes/ticket_{ticket.id}.png"
                        ]
                        db.session.delete(ticket)
                        db.session.commit()

                        for path in qr_code_paths:
                            if os.path.exists(path):
                                os.remove(path)

                        return {"message": "Ticket cancelled and Paystack refund initiated.", "refund_details": refund_result}, 200
                    else:
                        return {"error": "Error initiating Paystack refund for cancellation.", "details": refund_result}, 500
                else:
                    # If no transaction, just delete the ticket without refund
                    qr_code_paths = [
                        f"static/qrcodes/ticket_{ticket.id}.png",
                        f"static/qrcodes/ticket_{ticket.id}.png"
                    ]
                    db.session.delete(ticket)
                    db.session.commit()

                    for path in qr_code_paths:
                        if os.path.exists(path):
                            os.remove(path)

                    return {"message": "Ticket cancelled."}, 200

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error cancelling ticket: {e}")
            return {"error": "An internal error occurred"}, 500

def register_ticket_resources(api):
    """Registers ticket-related resources with Flask-RESTful API."""
    api.add_resource(TicketResource, "/tickets", "/tickets/<int:ticket_id>")