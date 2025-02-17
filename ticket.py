import qrcode
import base64
from io import BytesIO
from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime
from model import db, Ticket, Event, TicketType, User, UserRole
from flask_jwt_extended import jwt_required, get_jwt_identity
import enum
from model import TicketTypeEnum 

class TicketTypeResource(Resource):
    """Resource for managing ticket types (Only for organizers)."""

    @jwt_required()
    def post(self):
        """Create a ticket type for an event (Organizers only)."""
        current_user = get_jwt_identity()
        
        if not isinstance(current_user, dict) or "id" not in current_user:
            return {"error": "Invalid JWT identity format"}, 400

        user_id = current_user["id"]
        user = User.query.get(user_id)

        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can create ticket types"}, 403

        data = request.get_json()
        required_fields = ["event_id", "type_name", "price", "quantity"]

        if not all(field in data for field in required_fields):
            return {"message": "Missing required fields (event_id, type_name, price, quantity)"}, 400
        
        # Convert type_name to uppercase for validation
        type_name = data["type_name"].upper()
        if type_name not in [e.name for e in TicketTypeEnum]:
            return {"error": f"Invalid type_name. Allowed values: {', '.join(e.name for e in TicketTypeEnum)}"}, 400

        event = Event.query.get(data["event_id"])
        if not event:
            return {"error": "Event not found"}, 404

        # Create ticket type
        ticket_type = TicketType(
            event_id=event.id,
            type_name=type_name,  # Ensure stored type_name is uppercase
            price=data["price"],
            quantity=data["quantity"]
        )
        db.session.add(ticket_type)
        db.session.commit()

        return {"message": "Ticket type created successfully", "ticket_type": ticket_type.as_dict()}, 201

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
        current_user = get_jwt_identity()

        if not isinstance(current_user, dict) or "id" not in current_user:
            return {"error": "Invalid JWT identity format"}, 400

        user_id = current_user["id"]
        user = User.query.get(user_id)

        ticket_type = TicketType.query.get(ticket_type_id)
        if not ticket_type:
            return {"message": "Ticket type not found"}, 404

        event = Event.query.get(ticket_type.event_id)
        if not event or event.user_id != user.id:  # Change organizer_id to user_id
            return {"message": "Only the event organizer can update this ticket type"}, 403

        # Get request data
        data = request.get_json()
        allowed_fields = ["type_name", "price", "quantity"]

        if "type_name" in data:
            type_name = data["type_name"].upper()
            if type_name not in [e.name for e in TicketTypeEnum]:
                return {"error": f"Invalid type_name. Allowed values: {', '.join(e.name for e in TicketTypeEnum)}"}, 400
            ticket_type.type_name = type_name

        # Update fields if provided
        for field in allowed_fields:
            if field in data and field != "type_name":
                setattr(ticket_type, field, data[field])

        db.session.commit()
        return {"message": "Ticket type updated successfully", "ticket_type": ticket_type.as_dict()}, 200

    @jwt_required()
    def delete(self, ticket_type_id):
        """Delete a ticket type (Only the event organizer can delete)."""
        current_user = get_jwt_identity()

        if not isinstance(current_user, dict) or "id" not in current_user:
            return {"error": "Invalid JWT identity format"}, 400

        user_id = current_user["id"]
        user = User.query.get(user_id)

        ticket_type = TicketType.query.get(ticket_type_id)
        if not ticket_type:
            return {"message": "Ticket type not found"}, 404

        event = Event.query.get(ticket_type.event_id)
        if not event or event.user_id != user.id:
            return {"message": "Only the event organizer can delete this ticket type"}, 403

        db.session.delete(ticket_type)
        db.session.commit()
        return {"message": "Ticket type deleted successfully"}, 200


class TicketResource(Resource):
    @jwt_required()
    def post(self):
        """Book a ticket for an event. Generates a QR code."""
        current_user = get_jwt_identity()

        if not isinstance(current_user, dict) or "id" not in current_user:
            return {"error": "Invalid JWT identity format"}, 400

        user_id = current_user["id"]
        user = User.query.get(user_id)

        if not user:
            return {"error": "User not found"}, 404

        # Get the booking data (including phone number)
        data = request.get_json()
        required_fields = ["event_id", "ticket_type_id", "quantity", "phone_number", "email"]

        if not all(field in data for field in required_fields):
            return {"message": "Missing event_id, ticket_type_id, quantity, phone_number, or email"}, 400

        # Ensure the phone number and email match the registered ones
        if data["phone_number"] != user.phone_number:
            return {"error": "Phone number does not match the registered number"}, 400
        
        if data["email"] != user.email:
            return {"error": "Email does not match the registered email"}, 400

        event = Event.query.get(data["event_id"])
        if not event:
            return {"error": "Event not found"}, 404

        ticket_type = TicketType.query.get(data["ticket_type_id"])
        if not ticket_type or ticket_type.event_id != event.id:
            return {"error": "Invalid ticket type for this event"}, 400

        # Check ticket availability
        if ticket_type.quantity < data["quantity"]:
            return {"error": "Not enough tickets available"}, 400

        # Update ticket availability (optimistically, without explicit lock)
        ticket_type.quantity -= data["quantity"]
        db.session.commit()

        # Create the ticket
        ticket = Ticket(
            user_id=user.id,
            event_id=event.id,
            ticket_type_id=ticket_type.id,
            quantity=data["quantity"],
            phone_number=user.phone_number,  # Store the phone number in the ticket
            email=user.email,  # Store the email in the ticket
            purchase_date=datetime.utcnow()
        )
        db.session.add(ticket)
        db.session.commit()

        # Generate QR Code
        qr_code_data = f"Ticket ID: {ticket.id}, Event: {event.name}, User: {user.email}, Type: {ticket_type.type_name}"
        qr_code_img = qrcode.make(qr_code_data)

        # Convert QR Code to Base64
        buffer = BytesIO()
        qr_code_img.save(buffer, format="PNG")
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()

        # Update the ticket with the generated QR code
        ticket.qr_code = qr_code_base64
        db.session.commit()

        return {
            "ticket": ticket.as_dict(),
            "qr_code": f"data:image/png;base64,{qr_code_base64}"
        }, 201



    @jwt_required()
    def delete(self, ticket_id):
        """Cancel a ticket (Only the ticket owner can delete)."""
        current_user = get_jwt_identity()

        if not isinstance(current_user, dict) or "id" not in current_user:
            return {"error": "Invalid JWT identity format"}, 400

        user_id = current_user["id"]
        ticket = Ticket.query.get(ticket_id)

        if not ticket:
            return {"message": "Ticket not found"}, 404

        if ticket.user_id != user_id:
            return {"message": "You can only cancel your own tickets"}, 403

        # Refund tickets back to available quantity
        ticket_type = TicketType.query.get(ticket.ticket_type_id)
        if ticket_type:
            ticket_type.quantity += ticket.quantity
            db.session.commit()

        db.session.delete(ticket)
        db.session.commit()
        return {"message": "Ticket cancelled successfully"}, 200


def register_ticket_resources(api):
    """Registers ticket-related resources with Flask-RESTful API."""
    api.add_resource(TicketTypeResource, "/ticket-types", "/ticket-types/<int:ticket_type_id>")
    api.add_resource(TicketResource, "/tickets", "/tickets/<int:ticket_id>")

