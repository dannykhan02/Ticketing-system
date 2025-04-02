import os
import uuid
import cv2
from itsdangerous import URLSafeSerializer
from config import Config
from flask import request, send_file, current_app
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from datetime import datetime
from model import db, Ticket, Scan, User
from pyzbar.pyzbar import decode
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TicketValidationResource(Resource):
    @jwt_required()
    def get(self, ticket_id):
        """
        Retrieve a ticket's QR code.
        Only users with the "SECURITY" role can perform this action.
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user or user.role.value != "SECURITY":
                return {"message": "Only security personnel can retrieve QR codes"}, 403

            ticket = Ticket.query.get(ticket_id)
            if not ticket:
                return {"message": "Ticket not found"}, 404

            # Check for QR code in both possible directories
            qr_code_path = self.find_qr_code_path(ticket.id)
            if not qr_code_path:
                return {"message": "QR code image not found"}, 404

            return send_file(qr_code_path, mimetype="image/png")

        except Exception as e:
            logger.error(f"Error retrieving QR code: {str(e)}")
            return {"message": f"An error occurred: {str(e)}"}, 500

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

            if 'qr_image' not in request.files:
                return {"message": "QR code image is required"}, 400

            qr_image = request.files['qr_image']

            # Validate file type (Optional)
            if qr_image.filename == '':
                return {"message": "Invalid QR code file"}, 400

            # Save temp QR image
            temp_qr_filename = secure_filename(f"{uuid.uuid4().hex}.png")
            temp_qr_path = os.path.join(current_app.root_path, "static/qrcodes", temp_qr_filename)
            os.makedirs(os.path.dirname(temp_qr_path), exist_ok=True)
            qr_image.save(temp_qr_path)

            # Decode the QR code
            qr_code_content = self.decode_qr_code(temp_qr_path)

            # Remove temp file
            os.remove(temp_qr_path)

            if not qr_code_content:
                return {"message": "Failed to decode QR code"}, 400

            # Extract ticket data
            ticket_data = self.extract_ticket_data(qr_code_content)

            if not ticket_data or not isinstance(ticket_data, tuple) or len(ticket_data) != 2:
                return {"message": "Invalid or tampered QR code"}, 400

            ticket_id, event_id = ticket_data

            logger.info(f"🔎 Ticket ID: {ticket_id}, Event ID: {event_id}")  # Debugging Step 5

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

    def decode_qr_code(self, image_path):
        """
        Decodes the QR code from an image file.
        """
        try:
            image = cv2.imread(image_path)
            if image is None:
                return None

            decoded_objects = decode(image)
            if not decoded_objects:
                return None

            for obj in decoded_objects:
                qr_data = obj.data.decode('utf-8').strip()
                logger.info(f"🔍 Extracted QR Code Content: {qr_data}")  # Debugging output
                return qr_data

        except Exception as e:
            logger.error(f"Error decoding QR code: {str(e)}")
            return None

    def extract_ticket_data(self, qr_code_content):
        """Extracts ticket data from QR code content."""
        serializer = URLSafeSerializer(Config.SECRET_KEY)
        try:
            logger.info(f"🔍 Raw QR Code Content: {qr_code_content}")
            
            # Extract the encrypted data from the URL
            if "?id=" in qr_code_content:
                encrypted_data = qr_code_content.split("?id=")[1]
            else:
                encrypted_data = qr_code_content
                
            logger.info(f"🔍 Extracted Encrypted Data: {encrypted_data}")
            
            # Decrypt and validate the data
            data = serializer.loads(encrypted_data)
            
            # Ensure required fields are present
            if not all(k in data for k in ["ticket_id", "event_id"]):
                raise ValueError("Missing required fields in ticket data")
                
            logger.info(f"✅ Successfully Extracted Data: {data}")
            return data["ticket_id"], data["event_id"]
            
        except Exception as e:
            logger.error(f"❌ Error extracting ticket data: {str(e)}")
            return None, None

    def find_qr_code_path(self, ticket_id):
        """
        Finds the QR code path for a given ticket ID.
        """
        potential_paths = [
            f"static/qrcode/ticket_{ticket_id}.png",
            f"static/qrcodes/ticket_{ticket_id}.png"
        ]
        for path in potential_paths:
            if os.path.exists(path):
                return path
        return None

def register_ticket_validation_resources(api):
    """Registers the TicketValidationResource routes with Flask-RESTful API."""
    api.add_resource(TicketValidationResource, "/validate_ticket", endpoint="validate_ticket")
    api.add_resource(TicketValidationResource, "/ticket/<int:ticket_id>", endpoint="ticket_validation")