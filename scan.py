import os
from itsdangerous import URLSafeSerializer
from config import Config
from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from model import db, Ticket, Scan, User
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

            return {
                "message": "Ticket validated successfully",
                "ticket_id": ticket.id,
                "scanned_at": scan_entry.scanned_at.isoformat(),
                "scanned_by": user.id
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

def register_ticket_validation_resources(api):
    """Registers the TicketValidationResource routes with Flask-RESTful API."""
    api.add_resource(TicketValidationResource, "/validate_ticket", endpoint="validate_ticket")
