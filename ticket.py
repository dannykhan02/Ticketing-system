from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, Event, TicketType, User, Transaction, PaymentStatus, TicketTypeEnum
from config import Config
from paystack import InitializePayment as PaystackInitializePayment, VerifyPayment as PaystackVerifyPayment, RefundPayment as PaystackRefundPayment
from mpesa_intergration import STKPush as MpesaSTKPush, TransactionStatus as MpesaTransactionStatus, RefundTransaction as MpesaRefundTransaction
import logging
import base64
import os
from datetime import datetime
from email_utils import send_email
import qrcode
from itsdangerous import URLSafeSerializer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TicketUtils:
    @staticmethod
    def generate_qr_code(ticket, directory="qrcodes"):
        """Generates a QR code with a secure encrypted URL and stores it in the specified directory."""
        serializer = URLSafeSerializer(Config.SECRET_KEY)
        encrypted_data = serializer.dumps({"ticket_id": ticket.id, "event_id": ticket.event_id})
        qr_code_data = f"http://127.0.0.1:5000/validate_ticket?id={encrypted_data}"
        qr_code_img = qrcode.make(qr_code_data)

        qr_directory = f"static/{directory}"
        os.makedirs(qr_directory, exist_ok=True)
        qr_code_path = f"{qr_directory}/ticket_{ticket.id}.png"
        qr_code_img.save(qr_code_path)

        return qr_code_img, qr_code_path

    @staticmethod
    def send_confirmation_email(user, ticket, qr_code_path, is_new=True):
        """Sends an email with the ticket details and QR code."""
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
        - **Amount Paid:** {ticket.amount_paid}
        - **Payment Method:** {ticket.transaction.payment_method}

        📩 **Your QR Code:**
        Your {'unique' if is_new else 'updated'} QR code is attached to this email. Please present it at the entrance for seamless check-in.
        """
        try:
            send_email(user.email, subject, body, attachment_path=qr_code_path)
        except Exception as e:
            logger.error(f"Error sending email: {e}")


class TicketTypeResource(Resource):
    @jwt_required()
    def post(self):
        """Create a ticket type for an event (Only the event's organizer)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if user.role.value != "ORGANIZER":
                return {"error": "Only organizers can create ticket types"}, 403

            data = request.get_json()
            required_fields = ["event_id", "type_name", "price", "quantity"]

            for field in required_fields:
                if field not in data:
                    return {"error": f"Missing field: {field}"}, 400

            event = Event.query.get(data["event_id"])
            if not event:
                return {"error": "Event not found"}, 404

            if event.user_id != user.id:
                return {"error": "You can only create ticket types for your own events"}, 403

            type_name = data["type_name"].upper()
            valid_types = [e.name for e in TicketTypeEnum]
            if type_name not in valid_types:
                return {"error": f"Invalid type_name. Allowed values: {', '.join(valid_types)}"}, 400

            try:
                price = float(data["price"])
                quantity = int(data["quantity"])
            except ValueError:
                return {"error": "Price must be a valid number and quantity must be an integer"}, 400

            if price <= 0 or quantity <= 0:
                return {"error": "Price and quantity must be greater than zero"}, 400

            ticket_type = TicketType(
                event_id=event.id,
                type_name=type_name,
                price=price,
                quantity=quantity
            )

            db.session.add(ticket_type)
            db.session.commit()

            return {"message": "Ticket type created successfully", "ticket_type": ticket_type.as_dict()}, 201

        except Exception as e:
            logger.error(f"Error creating ticket type: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def get(self, ticket_type_id=None):
        """Retrieve all ticket types or a specific one."""
        if ticket_type_id:
            ticket_type = TicketType.query.get(ticket_type_id)
            if not ticket_type:
                return {"message": "Ticket type not found"}, 404
            return {"ticket_type": ticket_type.as_dict()}, 200

        ticket_types = TicketType.query.all()
        return {"ticket_types": [ticket.as_dict() for ticket in ticket_types]}, 200

    @jwt_required()
    def put(self, ticket_type_id):
        """Update a ticket type (Only the event organizer can update)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if user.role.value != "ORGANIZER":
                return {"error": "Only organizers can update ticket types"}, 403

            ticket_type = TicketType.query.get(ticket_type_id)
            if not ticket_type:
                return {"error": "Ticket type not found"}, 404

            event = Event.query.get(ticket_type.event_id)
            if event.user_id != user.id:
                return {"error": "Only the event organizer can update this ticket type"}, 403

            data = request.get_json()
            allowed_fields = ["type_name", "price", "quantity"]

            if "type_name" in data:
                type_name = data["type_name"].upper()
                if type_name not in [e.name for e in TicketTypeEnum]:
                    return {"error": f"Invalid type_name. Allowed values: {', '.join(e.name for e in TicketTypeEnum)}"}, 400
                ticket_type.type_name = type_name

            for field in ["price", "quantity"]:
                if field in data:
                    try:
                        if field == "price":
                            data[field] = float(data[field])
                        elif field == "quantity":
                            data[field] = int(data[field])
                    except ValueError:
                        return {"error": f"Invalid data type for {field}"}, 400

                    if data[field] <= 0:
                        return {"error": f"{field.capitalize()} must be greater than zero"}, 400

                    setattr(ticket_type, field, data[field])

            db.session.commit()
            return {"message": "Ticket type updated successfully", "ticket_type": ticket_type.as_dict()}, 200

        except Exception as e:
            logger.error(f"Error updating ticket type: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def delete(self, ticket_type_id):
        """Delete a ticket type (Only the event organizer can delete)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if user.role.value != "ORGANIZER":
                return {"error": "Only organizers can delete ticket types"}, 403

            ticket_type = TicketType.query.get(ticket_type_id)
            if not ticket_type:
                return {"error": "Ticket type not found"}, 404

            event = Event.query.get(ticket_type.event_id)
            if event.user_id != user.id:
                return {"error": "Only the event organizer can delete this ticket type"}, 403

            db.session.delete(ticket_type)
            db.session.commit()
            return {"message": "Ticket type deleted successfully"}, 200

        except Exception as e:
            logger.error(f"Error deleting ticket type: {e}")
            return {"error": "An internal error occurred"}, 500


class TicketResource(Resource):
    @jwt_required()
    def get(self):
        """Retrieve all tickets booked by the authenticated user."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            tickets = Ticket.query.filter_by(user_id=user.id).all()

            if not tickets:
                return {"message": "No tickets found"}, 200

            return {"tickets": [ticket.as_dict() for ticket in tickets]}, 200

        except Exception as e:
            logger.error(f"Error retrieving tickets: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def post(self):
        """Create a new ticket for the authenticated user after payment."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            data = request.get_json()
            required_fields = ["event_id", "ticket_type_id", "quantity", "payment_method", "transaction_id"]
            if not all(field in data for field in required_fields):
                return {"error": "Missing required fields"}, 400

            event = Event.query.get(data["event_id"])
            if not event:
                return {"error": "Event not found"}, 404

            ticket_type = TicketType.query.filter_by(id=data["ticket_type_id"], event_id=event.id).first()
            if not ticket_type or data["quantity"] <= 0 or ticket_type.quantity < data["quantity"]:
                return {"error": "Invalid ticket request"}, 400

            # Verify payment
            transaction = Transaction.query.filter_by(payment_reference=data["transaction_id"]).first()
            if not transaction or transaction.payment_status != PaymentStatus.SUCCESS:
                return {"error": "Payment not verified or failed"}, 400

            ticket_type.quantity -= data["quantity"]

            ticket = Ticket(
                user_id=user.id,
                event_id=event.id,
                ticket_type_id=ticket_type.id,
                quantity=data["quantity"],
                phone_number=user.phone_number,
                email=user.email,
                transaction_id=data["transaction_id"],
                qr_code=None,
                amount_paid=transaction.amount_paid  # Include amount paid
            )
            db.session.add(ticket)
            db.session.commit()

            qr_code_img, qr_code_path = TicketUtils.generate_qr_code(ticket, directory="qrcodes")
            with open(qr_code_path, "rb") as f:
                ticket.qr_code = base64.b64encode(f.read()).decode()

            db.session.commit()
            TicketUtils.send_confirmation_email(user, ticket, qr_code_path, is_new=True)

            return {"message": "Ticket created successfully", "ticket_id": ticket.id}, 201

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating ticket: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def put(self, ticket_id):
        """Update an existing ticket's details for the authenticated user after payment."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            ticket = Ticket.query.get(ticket_id)
            if not ticket or ticket.user_id != user.id:
                return {"error": "Ticket not found or unauthorized"}, 404

            data = request.get_json()
            required_fields = ["ticket_type_id", "quantity", "payment_method", "transaction_id"]
            if not all(field in data for field in required_fields):
                return {"error": "Missing required fields: ticket_type_id, quantity, payment_method, transaction_id"}, 400

            new_ticket_type = TicketType.query.filter_by(id=data["ticket_type_id"]).first()
            if not new_ticket_type:
                return {"error": "Invalid ticket type"}, 400

            if data["quantity"] <= 0:
                return {"error": "Quantity must be at least 1"}, 400

            if new_ticket_type.quantity < data["quantity"]:
                return {"error": "Not enough tickets available"}, 400

            # Verify payment
            transaction = Transaction.query.filter_by(payment_reference=data["transaction_id"]).first()
            if not transaction or transaction.payment_status != PaymentStatus.SUCCESS:
                return {"error": "Payment not verified or failed"}, 400

            # Handle refund if the new quantity is less than the original
            if data["quantity"] < ticket.quantity:
                refund_amount = (ticket.quantity - data["quantity"]) * ticket.ticket_type.price
                # Process refund logic here
                if transaction.payment_method == 'Paystack':
                    refund_response = PaystackRefundPayment.post({
                        "reference": transaction.payment_reference,
                        "amount": refund_amount
                    })
                    if refund_response.get("status"):
                        transaction.payment_status = PaymentStatus.REFUNDED
                        db.session.commit()
                    else:
                        return {"error": "Failed to initiate refund with Paystack", "details": refund_response.get("message", "Unknown error")}, 400
                elif transaction.payment_method == 'Mpesa':
                    refund_response = MpesaRefundTransaction.post({
                        "transaction_id": transaction.payment_reference,
                        "amount": refund_amount
                    })
                    if refund_response.get("ResponseCode") == "0":
                        transaction.payment_status = PaymentStatus.REFUNDED
                        db.session.commit()
                    else:
                        return {"error": "Failed to initiate refund with M-Pesa", "details": refund_response.get("ResponseDescription", "Unknown error")}, 400

            old_ticket_type = TicketType.query.get(ticket.ticket_type_id)
            old_ticket_type.quantity += ticket.quantity

            new_ticket_type.quantity -= data["quantity"]

            ticket.ticket_type_id = new_ticket_type.id
            ticket.quantity = data["quantity"]
            ticket.purchase_date = datetime.utcnow()
            ticket.amount_paid = transaction.amount_paid  # Update amount paid

            qr_code_img, qr_code_path = TicketUtils.generate_qr_code(ticket, directory="qrcodes")
            with open(qr_code_path, "rb") as f:
                ticket.qr_code = base64.b64encode(f.read()).decode()

            db.session.commit()
            TicketUtils.send_confirmation_email(user, ticket, qr_code_path, is_new=False)

            return {"message": "Ticket updated successfully", "ticket_id": ticket.id}, 200

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

            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                return {"error": "Ticket not found"}, 404

            if ticket.user_id != user.id:
                return {"error": "You can only cancel your own tickets"}, 403

            ticket_type = TicketType.query.get(ticket.ticket_type_id)
            if ticket_type:
                ticket_type.quantity += ticket.quantity

            qr_code_paths = [
                f"static/qrcodes/ticket_{ticket.id}.png",
                f"static/qrcodes/ticket_{ticket.id}.png"
            ]

            db.session.delete(ticket)
            db.session.commit()

            for path in qr_code_paths:
                if os.path.exists(path):
                    os.remove(path)
                    logger.info(f"Deleted QR code: {path}")
                else:
                    logger.warning(f"File not found: {path}")

            return {"message": "Ticket cancelled successfully"}, 200

        except Exception as e:
            logger.error(f"Error cancelling ticket: {e}")
            return {"error": "An internal error occurred"}, 500


def register_ticket_resources(api):
    """Registers ticket-related resources with Flask-RESTful API."""
    api.add_resource(TicketResource, "/tickets", "/tickets/<int:ticket_id>")
    api.add_resource(TicketTypeResource, "/ticket-types", "/ticket-types/<int:ticket_type_id>")
