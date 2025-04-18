from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, Event, TicketType, User, Transaction, PaymentStatus, UserRole, PaymentMethod
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
import base64
import requests
import io

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def complete_ticket_operation(transaction):
    """Updates ticket status once payment is successful and sends confirmation email."""
    try:
        logger.info(f"Completing ticket operation for Transaction ID: {transaction.id}")
        ticket = Ticket.query.filter_by(transaction_id=transaction.id).first()
        if not ticket:
            logging.error(f"Ticket with transaction ID {transaction.id} not found.")
            raise ValueError("Ticket not found")

        # Update ticket status
        ticket.payment_status = PaymentStatus.PAID
        db.session.commit()

        # Log success
        logger.info(f"Ticket {ticket.id} marked as PAID. Payment Ref: {transaction.payment_reference}")

        # Generate QR code
        qr_code_data, qr_code_image = generate_qr_code(ticket)

        # Send confirmation email
        user = User.query.get(ticket.user_id)
        send_confirmation_email(user, ticket, qr_code_data, qr_code_image)

    except Exception as e:
        logger.error(f"Error updating ticket {transaction.id}: {str(e)}")
        raise

def generate_qr_code(ticket):
    """Generates a QR code with a secure encrypted URL and returns it as a base64-encoded image."""
    serializer = URLSafeSerializer(Config.SECRET_KEY)
    encrypted_data = serializer.dumps({"ticket_id": ticket.id, "event_id": ticket.event_id})
    qr_code_data = f"https://ticketing-system-994g.onrender.com/validate_ticket?id={encrypted_data}"
    
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
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    return qr_code_data, img_str

def send_confirmation_email(user, ticket, qr_code_data, qr_code_image, is_new=True):
    """Sends an email with the ticket details and embedded QR code."""
    event = ticket.event
    ticket_type = ticket.ticket_type
    event_date = event.date.strftime('%A, %B %d, %Y') if event.date else "Date not available"
    start_time = event.start_time.strftime('%H:%M:%S') if event.start_time else "Start time not available"
    end_time = event.end_time.strftime('%H:%M:%S') if event.end_time else "Till Late"

    subject = f"🎟 {'Your' if is_new else 'Updated'} Ticket Confirmation - {event.name} 🎟"
    body = f"""
    Dear {user.email} ({user.phone_number}),

    🎉 **Your Ticket Booking is {'Confirmed' if is_new else 'Updated'}!** 🎉

    📌 **Event Details:**
    - **Event:** {event.name}
    - **Location:** {event.location}
    - **Date:** {event_date}
    - **Time:** {start_time} - {end_time}
    - **Description:** {event.description}

    🎟 **Your Ticket:**
    - **Type:** {ticket_type.type_name}
    - **Quantity:** {ticket.quantity}
    - **Purchase Date:** {ticket.purchase_date.strftime('%Y-%m-%d %H:%M:%S')}
    - **Scanned:** {'Yes' if ticket.scanned else 'No'}
    - **Amount Paid:** {ticket.total_price}
    - **Payment Method:** {ticket.transaction.payment_method.value if ticket.transaction else 'Pending'}

    📩 **Your QR Code:**
    <img src="data:image/png;base64,{qr_code_image}" alt="Ticket QR Code" style="display:block; margin:20px auto; width:200px; height:200px;">
    
    Your {'unique' if is_new else 'updated'} QR code is also available as text: {qr_code_data}
    Please present this code at the entrance for seamless check-in.
    """
    try:
        send_email(user.email, subject, body, html=True)
    except Exception as e:
        logger.error(f"Error sending email: {e}")


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
                return {"ticket_id": ticket.id, "status": ticket.payment_status.value}, 200
            else:
                tickets = Ticket.query.filter_by(user_id=user.id).all()
                ticket_list = [{"ticket_id": ticket.id, "status": ticket.payment_status.value} for ticket in tickets]
                return jsonify(ticket_list), 200

        except Exception as e:
            logger.error(f"Error checking ticket status: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def post(self):
        """Create a new ticket for the authenticated user after successful payment."""
        try:
            # Get the authenticated user's identity
            identity = get_jwt_identity()
            user = User.query.get(identity)

            # Log the user object for debugging
            logger.info(f"Authenticated user: {user}")

            # Ensure the user exists
            if not user:
                return {"error": "User not found"}, 404

            # Ensure the user is an attendee
            if user.role != UserRole.ATTENDEE:
                return {"error": "Only attendees can purchase tickets"}, 403

            # Parse and validate the request data
            data = request.get_json()
            required_fields = ["event_id", "ticket_type_id", "quantity", "payment_method"]
            if not all(field in data for field in required_fields):
                return {"error": "Missing required fields"}, 400

            # Validate the event
            event = Event.query.get(data["event_id"])
            if not event:
                return {"error": "Event not found"}, 404

            # Validate the ticket type
            ticket_type = TicketType.query.filter_by(id=data["ticket_type_id"], event_id=event.id).first()
            if not ticket_type:
                return {"error": "Ticket type not found for this event"}, 404

            # Check ticket availability
            if ticket_type.quantity == 0:
                return {"error": "Tickets for this type are sold out"}, 400

            if data["quantity"] <= 0:
                return {"error": "Quantity must be at least 1"}, 400

            if ticket_type.quantity < data["quantity"]:
                return {"error": f"Only {ticket_type.quantity} tickets are available"}, 400

            # Calculate the total price
            amount = ticket_type.price * data["quantity"]

            # Generate a unique transaction ID for the ticket (this will be a string initially)
            temp_transaction_id = str(uuid.uuid4())[:8]

            # Store the initial ticket information with PENDING status
            new_ticket = Ticket(
                event_id=event.id,
                ticket_type_id=ticket_type.id,
                quantity=data["quantity"],
                phone_number=user.phone_number,
                email=user.email,  # Assuming the user object has an email field
                payment_status=PaymentStatus.PENDING,
                transaction_id=None,  # Initialize as None, will be updated with the Transaction ID
                user_id=user.id  # Associate the ticket with the authenticated user
            )
            db.session.add(new_ticket)
            db.session.commit() # Commit here to get the new_ticket.id

            logger.info(f"Created Ticket ID: {new_ticket.id} with temporary Transaction ID: {temp_transaction_id}")

            # Process Payment
            if data["payment_method"] == "Mpesa":
                if "phone_number" not in data or normalize_phone_number(data["phone_number"]) != normalize_phone_number(user.phone_number):
                    return {"error": "Phone number must be the registered one"}, 400

                # Initiate STK Push using the imported class
                mpesa_data = {
                    "phone_number": user.phone_number,
                    "amount": amount,
                    "ticket_id": new_ticket.id,  # Pass the ticket ID for reference
                    "transaction_id": temp_transaction_id # Pass the temporary transaction ID
                }
                mpesa = STKPush()
                response, status_code = mpesa.post(mpesa_data) # Expecting 2 return values now

                if status_code == 200:
                    # Create a new transaction record for M-Pesa
                    new_transaction = Transaction(
                        amount_paid=amount,
                        payment_status=PaymentStatus.PENDING,
                        payment_method=PaymentMethod.MPESA,
                        timestamp=datetime.datetime.now(),
                        ticket_id=new_ticket.id,
                        user_id=user.id,
                        merchant_request_id=response.get('MerchantRequestID'),
                        checkout_request_id=response.get('CheckoutRequestID')
                    )
                    db.session.add(new_transaction)
                    db.session.commit()

                    new_ticket.transaction_id = new_transaction.id # Set the transaction_id on the ticket
                    db.session.commit()

                    logger.info(f"Created M-Pesa Transaction ID: {new_transaction.id} for Ticket ID: {new_ticket.id}")
                    return response, status_code
                else:
                    # If STK Push fails, revert the ticket creation
                    db.session.delete(new_ticket)
                    db.session.commit()
                    return response, status_code

            elif data["payment_method"] == "Paystack":
                # Ensure the user has a valid email
                if not user.email:
                    return {"error": "User email is required for Paystack payment"}, 400

                # Initialize Paystack payment using the imported function
                paystack_response = initialize_paystack_payment(user.email, int(amount * 100))

                if isinstance(paystack_response, dict) and "authorization_url" in paystack_response:
                    authorization_url = paystack_response["authorization_url"]
                    reference = paystack_response["reference"]

                    # Create a new transaction for Paystack
                    new_transaction = Transaction(
                        amount_paid=amount,
                        payment_status=PaymentStatus.PENDING,  # Will be updated by webhook
                        payment_method=PaymentMethod.PAYSTACK,
                        timestamp=datetime.datetime.now(),
                        ticket_id=new_ticket.id,
                        user_id=user.id,  # Set the user_id here
                        payment_reference=reference
                    )
                    db.session.add(new_transaction)
                    db.session.commit()

                    new_ticket.transaction_id = new_transaction.id # Set the transaction_id on the ticket
                    db.session.commit()

                    logger.info(f"Created Paystack Transaction ID: {new_transaction.id} for Ticket ID: {new_ticket.id}")
                    return {"message": "Payment initialized", "authorization_url": authorization_url, "reference": reference}, 200
                else:
                    # Handle errors from the Paystack initialization function
                    logger.error(f"Paystack initialization failed: {paystack_response}")
                    db.session.delete(new_ticket)
                    db.session.commit()
                    return paystack_response, 500

            else:
                # If the payment method is invalid, delete the ticket and return an error
                db.session.delete(new_ticket)
                db.session.commit()
                return {"error": "Invalid payment method"}, 400

        except Exception as e:
            # Rollback the session in case of an error
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
                            refund_amount = int(price_difference * 100) # Amount in kobo/cents
                            refund_result = refund_paystack_payment(transaction.payment_reference, refund_amount)
                            if isinstance(refund_result, dict) and "error" not in refund_result:
                                db.session.commit()
                                return {"message": "Ticket quantity updated and Paystack refund initiated.", "refund_details": refund_result}, 200
                            else:
                                db.session.rollback()
                                return {"error": "Error initiating Paystack refund.", "details": refund_result}, 500
                        else:
                            db.session.commit() # If no transaction, just update quantity
                            return {"message": "Ticket quantity updated."}, 200
                elif price_difference < 0: # Quantity increased, you might want to handle additional payment here
                    db.session.commit()
                    return {"message": "Ticket quantity updated, additional payment might be required."}, 200
                else:
                    db.session.commit()
                    return {"message": "Ticket quantity updated."}, 200

            if "status" in data:
                pass # You might want to handle other status updates here if needed

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

            if ticket.email is not None: # Check if email is present
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
                    refund_amount = int(float(ticket.total_price) * 100) # Amount in kobo/cents
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
    pass