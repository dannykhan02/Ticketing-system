import os
import qrcode
import base64
from io import BytesIO
from email_utils import send_email
from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime
from model import db, Ticket, Event, TicketType, User, UserRole
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import TicketTypeEnum 

class TicketTypeResource(Resource):
    @jwt_required()
    def post(self):
        """Create a ticket type for an event (Only the event's organizer)."""
        try:
            identity = get_jwt_identity()  # Get logged-in user's ID
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if user.role.value != "ORGANIZER":
                return {"error": "Only organizers can create ticket types"}, 403

            data = request.get_json()
            required_fields = ["event_id", "type_name", "price", "quantity"]

            # Check for missing fields
            for field in required_fields:
                if field not in data:
                    return {"error": f"Missing field: {field}"}, 400

            # Validate event
            event = Event.query.get(data["event_id"])
            if not event:
                return {"error": "Event not found"}, 404

            # Ensure the user is the organizer of this event
            if not event or event.user_id != user.id: 
                return {"error": "You can only create ticket types for your own events"}, 403

            # Convert type_name to uppercase for consistency
            type_name = data["type_name"].upper()

            # Validate type_name against TicketTypeEnum
            valid_types = [e.name for e in TicketTypeEnum]
            if type_name not in valid_types:
                return {"error": f"Invalid type_name. Allowed values: {', '.join(valid_types)}"}, 400

            # Validate price and quantity
            try:
                price = float(data["price"])
                quantity = int(data["quantity"])
            except ValueError:
                return {"error": "Price must be a valid number and quantity must be an integer"}, 400

            if price <= 0 or quantity <= 0:
                return {"error": "Price and quantity must be greater than zero"}, 400

            # Create ticket type
            ticket_type = TicketType(
                event_id=event.id,
                type_name=type_name,  # Store uppercase type_name
                price=price,
                quantity=quantity
            )

            db.session.add(ticket_type)
            db.session.commit()

            return {"message": "Ticket type created successfully", "ticket_type": ticket_type.as_dict()}, 201
        
        except Exception as e:
            return {"error": str(e)}, 500

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

            # Ensure only the event organizer can update this ticket type
            event = Event.query.get(ticket_type.event_id)
            if not event or event.user_id != user.id: 
                return {"error": "Only the event organizer can update this ticket type"}, 403

            data = request.get_json()
            allowed_fields = ["type_name", "price", "quantity"]

            # Update type_name if provided
            if "type_name" in data:
                type_name = data["type_name"].upper()
                if type_name not in [e.name for e in TicketTypeEnum]:
                    return {"error": f"Invalid type_name. Allowed values: {', '.join(e.name for e in TicketTypeEnum)}"}, 400
                ticket_type.type_name = type_name

            # Validate and update price and quantity
            for field in ["price", "quantity"]:
                if field in data:
                    try:
                        if field == "price":
                            data[field] = float(data[field])  # Ensure price is a float
                        elif field == "quantity":
                            data[field] = int(data[field])  # Ensure quantity is an integer
                    except ValueError:
                        return {"error": f"Invalid data type for {field}"}, 400

                    if data[field] <= 0:
                        return {"error": f"{field.capitalize()} must be greater than zero"}, 400

                    setattr(ticket_type, field, data[field])

            db.session.commit()
            return {"message": "Ticket type updated successfully", "ticket_type": ticket_type.as_dict()}, 200

        except Exception as e:
            return {"error": str(e)}, 500


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

            # Ensure only the event organizer can delete this ticket type
            event = Event.query.get(ticket_type.event_id)
            if not event or event.user_id != user.id: 
                return {"error": "Only the event organizer can delete this ticket type"}, 403

            db.session.delete(ticket_type)
            db.session.commit()
            return {"message": "Ticket type deleted successfully"}, 200

        except Exception as e:
            return {"error": str(e)}, 500
 

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
            return {"error": str(e)}, 500

    @jwt_required()
    def post(self):
        """Create a new ticket and send a QR code via email."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            data = request.get_json()
            required_fields = ["event_id", "ticket_type_id", "quantity"]

            # ✅ Validate request data
            if not all(field in data for field in required_fields):
                return {"error": "Missing required fields: event_id, ticket_type_id, quantity"}, 400

            event = Event.query.get(data["event_id"])
            if not event:
                return {"error": "Event not found"}, 404

            ticket_type = TicketType.query.filter_by(id=data["ticket_type_id"], event_id=event.id).first()
            if not ticket_type:
                return {"error": "Invalid ticket type for this event"}, 400

            if data["quantity"] <= 0:
                return {"error": "Quantity must be at least 1"}, 400

            # ✅ Check ticket availability
            if ticket_type.quantity < data["quantity"]:
                return {"error": "Not enough tickets available"}, 400

            # ✅ Deduct available ticket quantity
            ticket_type.quantity -= data["quantity"]

            # ✅ Create a new ticket
            ticket = Ticket(
                user_id=user.id,
                event_id=event.id,
                ticket_type_id=ticket_type.id,
                quantity=data["quantity"]
            )

            db.session.add(ticket)
            db.session.commit()  # Commit to get ticket ID for QR code

            # ✅ Generate QR Code
            qr_code_data = f"Ticket ID: {ticket.id}, Event: {event.name}, User: {user.email}, Type: {ticket_type.type_name}"
            qr_code_img = qrcode.make(qr_code_data)

            buffer = BytesIO()
            qr_code_img.save(buffer, format="PNG")
            qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()

            ticket.qr_code = qr_code_base64  # Store base64 QR code in DB

            # ✅ Save QR Code as a file
            qr_directory = "static/qrcodes"
            os.makedirs(qr_directory, exist_ok=True)  # Ensure directory exists
            qr_code_path = f"{qr_directory}/ticket_{ticket.id}.png"

            with open(qr_code_path, "wb") as f:
                f.write(buffer.getvalue())

            # ✅ Send Ticket Confirmation Email
            subject = "Your Ticket Confirmation"
            body = f"""
            Dear {user.email} ({user.phone_number}),


            Your ticket has been successfully booked!

            Ticket ID: {ticket.id}
            Event: {event.name}
            Quantity: {ticket.quantity}

            Please find your QR code attached.
            """

            try:
                send_email(user.email, subject, body, attachment_path=qr_code_path)
            except Exception as e:
                print(f"Error sending email: {e}")

            db.session.commit()
            return {"message": "Ticket created successfully", "ticket_id": ticket.id}, 201

        except Exception as e:
            db.session.rollback()  # Rollback on error
            print(f"Error creating ticket: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def put(self, ticket_id):
        """Update a ticket's details (only the ticket owner can edit)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                return {"error": "Ticket not found"}, 404

            if ticket.user_id != user.id:
                return {"error": "You can only edit your own tickets"}, 403

            data = request.get_json()
            allowed_fields = ["ticket_type_id", "quantity"]

            if not any(field in data for field in allowed_fields):
                return {"error": "Provide at least one field to update: ticket_type_id or quantity"}, 400

            updated = False

            # ✅ Update Ticket Type
            if "ticket_type_id" in data:
                new_ticket_type = TicketType.query.filter_by(id=data["ticket_type_id"], event_id=ticket.event_id).first()
                if not new_ticket_type:
                    return {"error": "Invalid ticket type for this event"}, 400
                ticket.ticket_type_id = new_ticket_type.id
                updated = True

            # ✅ Update Quantity
            if "quantity" in data:
                if data["quantity"] <= 0:
                    return {"error": "Quantity must be at least 1"}, 400

                old_quantity = ticket.quantity
                new_quantity = data["quantity"]
                ticket_type = TicketType.query.get(ticket.ticket_type_id)

                if new_quantity > old_quantity:
                    additional_tickets_needed = new_quantity - old_quantity
                    if ticket_type.quantity < additional_tickets_needed:
                        return {"error": "Not enough tickets available"}, 400
                    ticket_type.quantity -= additional_tickets_needed
                elif new_quantity < old_quantity:
                    refunded_tickets = old_quantity - new_quantity
                    ticket_type.quantity += refunded_tickets

                ticket.quantity = new_quantity
                updated = True

            # ✅ Update QR Code and Send Email
            if updated:
                qr_code_data = f"Ticket ID: {ticket.id}, Event: {ticket.event.name}, User: {user.email}, Type: {ticket.ticket_type.type_name}"
                qr_code_img = qrcode.make(qr_code_data)

                buffer = BytesIO()
                qr_code_img.save(buffer, format="PNG")
                qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()

                ticket.qr_code = qr_code_base64  # Store base64 QR code in DB

                # Save QR Code as a file
                qr_directory = "static/qrcodes"
                os.makedirs(qr_directory, exist_ok=True)  # Ensure directory exists
                qr_code_path = f"{qr_directory}/ticket_{ticket.id}.png"

                with open(qr_code_path, "wb") as f:
                    f.write(buffer.getvalue())

                # ✅ Send Updated Ticket Email
                subject = "Your Updated Ticket Information"
                body = f"""
                Dear {user.email} ({user.phone_number}),


                Your ticket details have been updated successfully!

                Ticket ID: {ticket.id}
                Event: {ticket.event_id}
                Quantity: {ticket.quantity}

                Find your updated QR code attached.
                """

                try:
                    send_email(user.email, subject, body, attachment_path=qr_code_path)
                except Exception as e:
                    print(f"Error sending email: {e}")

            db.session.commit()
            return {"message": "Ticket updated successfully"}, 200

        except Exception as e:
            db.session.rollback()  # Rollback in case of error
            print(f"Error updating ticket: {e}")
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

            db.session.delete(ticket)
            db.session.commit()

            return {"message": "Ticket cancelled successfully"}, 200

        except Exception as e:
            return {"error": str(e)}, 500




def register_ticket_resources(api):
    """Registers ticket-related resources with Flask-RESTful API."""
    api.add_resource(TicketTypeResource, "/ticket-types", "/ticket-types/<int:ticket_type_id>")
    api.add_resource(TicketResource, "/tickets", "/tickets/<int:ticket_id>")