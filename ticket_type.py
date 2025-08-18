from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func
from model import db, Event, TicketType, User, TicketTypeEnum, UserRole, Organizer
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TicketTypeResource(Resource):
    @jwt_required()
    def post(self):
        """Create a ticket type for an event (Only the event's organizer)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if user.role != UserRole.ORGANIZER:
                return {"error": "Only organizers can create ticket types"}, 403

            data = request.get_json()
            required_fields = ["event_id", "type_name", "price", "quantity"]

            for field in required_fields:
                if field not in data:
                    return {"error": f"Missing field: {field}"}, 400

            event = Event.query.get(data["event_id"])
            if not event:
                return {"error": "Event not found"}, 404

            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"error": "Organizer profile not found"}, 404

            if event.organizer_id != organizer.id:
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
        """Retrieve ticket types for events owned by the logged-in organizer."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user or user.role != UserRole.ORGANIZER:
                return {"error": "Only organizers can view ticket types for their events"}, 403

            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"error": "Organizer profile not found"}, 404

            if ticket_type_id:
                ticket_type = TicketType.query.get(ticket_type_id)
                if not ticket_type:
                    return {"error": "Ticket type not found"}, 404
                if ticket_type.event.organizer_id != organizer.id:
                    return {"error": "You do not have permission to view this ticket type"}, 403
                return {"ticket_type": ticket_type.as_dict()}, 200

            # Fetch all ticket types for events owned by the organizer
            events = Event.query.filter_by(organizer_id=organizer.id).all()
            event_ids = [event.id for event in events]
            ticket_types = TicketType.query.filter(TicketType.event_id.in_(event_ids)).all()
            return {"ticket_types": [ticket_type.as_dict() for ticket_type in ticket_types]}, 200

        except Exception as e:
            logger.error(f"Error fetching ticket types: {e}")
            return {"error": "An internal error occurred"}, 500

    @jwt_required()
    def put(self, ticket_type_id):
        """Update a ticket type (Only the event organizer can update)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if user.role != UserRole.ORGANIZER:
                return {"error": "Only organizers can update ticket types"}, 403

            ticket_type = TicketType.query.get(ticket_type_id)
            if not ticket_type:
                return {"error": "Ticket type not found"}, 404

            event = Event.query.get(ticket_type.event_id)
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"error": "Organizer profile not found"}, 404
            if event.organizer_id != organizer.id:
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

            if user.role != UserRole.ORGANIZER:
                return {"error": "Only organizers can delete ticket types"}, 403

            ticket_type = TicketType.query.get(ticket_type_id)
            if not ticket_type:
                return {"error": "Ticket type not found"}, 404

            event = Event.query.get(ticket_type.event_id)
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"error": "Organizer profile not found"}, 404
            if event.organizer_id != organizer.id:
                return {"error": "Only the event organizer can delete this ticket type"}, 403

            db.session.delete(ticket_type)
            db.session.commit()
            return {"message": "Ticket type deleted successfully"}, 200

        except Exception as e:
            logger.error(f"Error deleting ticket type: {e}")
            return {"error": "An internal error occurred"}, 500

class PublicTicketTypeResource(Resource):
    def get(self, event_id):
        """Public: Get all ticket types for a specific event (for attendees to view and purchase)."""
        ticket_types = TicketType.query.filter_by(event_id=event_id).all()
        return {"ticket_types": [tt.as_dict() for tt in ticket_types]}, 200

class LowestPriceTicketResource(Resource):
    @jwt_required()
    def get(self, event_id=None):
        """Get the lowest price ticket type for events (accessible to all logged-in users)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            if event_id:
                # Get lowest price ticket for a specific event
                lowest_ticket = TicketType.query.filter_by(event_id=event_id).order_by(TicketType.price.asc()).first()
                
                if not lowest_ticket:
                    return {"error": "No ticket types found for this event"}, 404
                
                result = {
                    "event_id": event_id,
                    "lowest_price_ticket": {
                        "id": lowest_ticket.id,
                        "type_name": lowest_ticket.type_name.value if hasattr(lowest_ticket.type_name, 'value') else str(lowest_ticket.type_name),
                        "price": lowest_ticket.price,
                        "remaining_quantity": lowest_ticket.quantity
                    }
                }
                return result, 200
            
            else:
                # Get lowest price ticket for all events (for home page)
                # Using a subquery to find the minimum price for each event
                subquery = db.session.query(
                    TicketType.event_id,
                    func.min(TicketType.price).label('min_price')
                ).group_by(TicketType.event_id).subquery()
                
                # Join with the original table to get complete ticket information
                lowest_tickets = db.session.query(TicketType).join(
                    subquery,
                    (TicketType.event_id == subquery.c.event_id) & 
                    (TicketType.price == subquery.c.min_price)
                ).all()
                
                # Group by event_id to handle cases where multiple tickets have the same lowest price
                events_lowest_tickets = {}
                for ticket in lowest_tickets:
                    if ticket.event_id not in events_lowest_tickets:
                        events_lowest_tickets[ticket.event_id] = ticket
                
                result = []
                for event_id, ticket in events_lowest_tickets.items():
                    result.append({
                        "event_id": event_id,
                        "lowest_price_ticket": {
                            "id": ticket.id,
                            "type_name": ticket.type_name.value if hasattr(ticket.type_name, 'value') else str(ticket.type_name),
                            "price": ticket.price,
                            "remaining_quantity": ticket.quantity
                        }
                    })
                
                return {"events_lowest_prices": result}, 200

        except Exception as e:
            logger.error(f"Error fetching lowest price tickets: {e}")
            return {"error": "An internal error occurred"}, 500

def register_ticket_type_resources(api):
    """Registers ticket type resources with Flask-RESTful API."""
    api.add_resource(TicketTypeResource, "/ticket-types", "/ticket-types/<int:ticket_type_id>")
    api.add_resource(PublicTicketTypeResource, "/events/<int:event_id>/ticket-types")
    api.add_resource(LowestPriceTicketResource, "/ticket-types/lowest-price", "/ticket-types/lowest-price/<int:event_id>")