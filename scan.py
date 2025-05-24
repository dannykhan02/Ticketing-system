import os
from itsdangerous import URLSafeSerializer
from config import Config
from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from model import db, Ticket, Scan, User, Event, TicketType, UserRole
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TicketValidationResource(Resource):
    @jwt_required()
    def post(self):
        """
        Validate a QR code and mark the ticket as scanned.
        Only users with the "SECURITY" role can perform this action.
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user or str(user.role).upper() != "SECURITY":
                return {"message": "Only security personnel can scan tickets"}, 403

            data = request.get_json()
            if not data or 'qr_code' not in data:
                return {"message": "QR code data is required"}, 400

            qr_code = data['qr_code']
            
            # Extract ticket data from QR code
            ticket_data = self.extract_ticket_data(qr_code)

            if not ticket_data or not isinstance(ticket_data, tuple) or len(ticket_data) != 2:
                return {"message": "Invalid or tampered QR code"}, 400

            ticket_id, event_id = ticket_data

            logger.info(f"🔎 Ticket ID: {ticket_id}, Event ID: {event_id}")

            # Ensure ticket_id is an integer
            if not str(ticket_id).isdigit():
                return {"message": "Invalid ticket ID"}, 400

            ticket_id = int(ticket_id)

            # Validate ticket existence
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                return {"message": "Invalid ticket"}, 404

            # Prevent duplicate scans
            if ticket.scanned:
                return {"message": "Ticket has already been scanned"}, 409

            # Register the scan
            scan_entry = Scan(ticket_id=ticket.id, scanned_at=datetime.utcnow(), scanned_by=user.id)
            ticket.scanned = True
            db.session.add(scan_entry)
            db.session.commit()

            # Get additional data for the response
            event = Event.query.get(ticket.event_id)
            ticket_type = TicketType.query.get(ticket.ticket_type_id)
            buyer = User.query.get(ticket.user_id)

            return {
                "message": "Ticket validated successfully",
                "data": {
                    "id": ticket.id,
                    "event": {
                        "title": event.name if event else "Unknown Event",
                        "start_time": event.date.strftime("%Y-%m-%dT%H:%M:%S") if event and event.date else None,
                        "location": event.location if event else None
                    },
                    "attendee_name": buyer.full_name if buyer else "Unknown",
                    "ticket_type": ticket_type.type_name.value if ticket_type and hasattr(ticket_type.type_name, 'value') else "Standard",
                    "event_id": ticket.event_id,
                    "scanned_at": scan_entry.scanned_at.isoformat(),
                    "scanned_by": user.full_name
                }
            }, 200

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error validating ticket: {str(e)}")
            return {"message": f"An error occurred: {str(e)}"}, 500

    def extract_ticket_data(self, qr_code_content):
        serializer = URLSafeSerializer(Config.SECRET_KEY)
        try:
            logger.info(f"🔍 Raw QR Code Content: {qr_code_content}")

            # Ensure only encrypted part is extracted
            if "?id=" in qr_code_content:
                qr_code_content = qr_code_content.split("?id=")[-1]

            logger.info(f"🔍 Extracted Encrypted Data: {qr_code_content}")

            data = serializer.loads(qr_code_content)

            logger.info(f"✅ Successfully Extracted: {data}")
            return data.get("ticket_id"), data.get("event_id")
        except Exception as e:
            logger.error(f"❌ Error extracting ticket data: {str(e)}")
            return None, None

class TicketVerificationResource(Resource):
    
    @jwt_required()
    def post(self, ticket_id):
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user or str(user.role).upper() != "SECURITY":
                return {"message": "Only security personnel can verify tickets"}, 403

            # Try to parse the ticket_id as an integer
            try:
                if isinstance(ticket_id, str) and ticket_id.startswith("ticket_"):
                    ticket_id = ticket_id.replace("ticket_", "")
                
                ticket_id = int(ticket_id)
            except ValueError:
                # If the ID is not a simple integer, it might be a QR code content
                validation_resource = TicketValidationResource()
                return validation_resource.post()

            # Find the ticket
            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                return {"message": "Invalid ticket"}, 404

            # Prevent duplicate scans
            if ticket.scanned:
                return {"message": "Ticket has already been scanned"}, 409

            # Register the scan
            scan_entry = Scan(ticket_id=ticket.id, scanned_at=datetime.utcnow(), scanned_by=user.id)
            ticket.scanned = True
            db.session.add(scan_entry)
            db.session.commit()

            # Get additional data for the response
            event = Event.query.get(ticket.event_id)
            ticket_type = TicketType.query.get(ticket.ticket_type_id)
            buyer = User.query.get(ticket.user_id)

            return {
                "message": "Ticket verified successfully",
                "data": {
                    "id": ticket.id,
                    "event": {
                        "title": event.name if event else "Unknown Event",
                        "start_time": event.date.strftime("%Y-%m-%dT%H:%M:%S") if event and event.date else None,
                        "location": event.location if event else None
                    },
                    "attendee_name": buyer.full_name if buyer else "Unknown",
                    "ticket_type": ticket_type.type_name.value if ticket_type and hasattr(ticket_type.type_name, 'value') else "Standard",
                    "event_id": ticket.event_id,
                    "scanned_at": scan_entry.scanned_at.isoformat(),
                    "scanned_by": user.full_name
                }
            }, 200

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error verifying ticket: {str(e)}")
            return {"message": f"An error occurred: {str(e)}"}, 500

def register_ticket_validation_resources(api):
    """Registers the ticket validation resources with Flask-RESTful API."""
    api.add_resource(TicketValidationResource, "/validate_ticket", endpoint="validate_ticket")
    # Add the new endpoint that matches what the frontend is calling
    api.add_resource(TicketVerificationResource, "/api/tickets/<string:ticket_id>/verify", endpoint="verify_ticket")