import json
from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime, timedelta
# Assuming your models are in 'model.py' and imported correctly
from model import db, Event, User, UserRole, Organizer # Ensure Organizer is imported
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import cloudinary.uploader
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# (Keep your existing EventResource class here - it's not the source of this error)
class EventResource(Resource):
    @jwt_required()
    def get(self, event_id=None):
        """Retrieve an event by ID or return all events if no ID is provided."""
        # You might want to add a check here to only allow viewing of own events for organizers,
        # or leave it open for public event listings if that's intended.
        if event_id:
            event = Event.query.get(event_id)
            if event:
                # Optional: Check if the user is the organizer or admin if restricting access
                # current_user_id = get_jwt_identity()
                # user = User.query.get(current_user_id)
                # organizer = Organizer.query.filter_by(user_id=user.id).first() if user else None
                # if event.organizer_id != (organizer.id if organizer else None) and (user and user.role.value != "ADMIN"):
                #     return {"message": "You do not have permission to view this event details"}, 403

                return event.as_dict(), 200
            return {"message": "Event not found"}, 404
        # This part fetches ALL events - often requires admin or is for public listing
        events = Event.query.all()
        return [event.as_dict() for event in events], 200

    @jwt_required()
    def post(self):
        """Create a new event (Only organizers can create events)."""
        try:
            identity = get_jwt_identity()  # Get current user ID
            user = User.query.get(identity) # Get current user object

            # Check if the user exists and has the ORGANIZER role
            if not user or user.role.value != "ORGANIZER":
                return {"message": "Only organizers can create events"}, 403

            # Find the Organizer profile linked to this user
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found for this user"}, 404 # Should ideally exist if role is ORGANIZER


            # Get form data and files
            data = request.form
            files = request.files

            # Validate required fields
            required_fields = ["name", "description", "date", "start_time", "location"]
            for field in required_fields:
                if field not in data or not data[field]: # Added check for empty strings
                    return {"message": f"Missing or empty field: {field}"}, 400

            # Handle file upload if provided
            image_url = None
            if 'image_file' in files: # Use a consistent file key, e.g., 'image_file'
                file = files['image_file']
                if file and file.filename != '':
                     # Optional: Check file size
                    file.seek(0, 2) # Move cursor to end of file
                    file_size = file.tell()
                    file.seek(0) # Move cursor back to beginning
                    if file_size > MAX_FILE_SIZE:
                         return {"message": f"File size exceeds the maximum limit of {MAX_FILE_SIZE // 1024 // 1024}MB"}, 400

                    if not allowed_file(file.filename):
                        return {"message": "Invalid file type. Allowed types: PNG, JPG, JPEG, GIF, WEBP"}, 400

                    try:
                        upload_result = cloudinary.uploader.upload(
                            file,
                            folder="event_images", # Specify a folder in Cloudinary
                            resource_type="auto"
                        )
                        image_url = upload_result.get('secure_url')
                        if not image_url:
                             raise Exception("Cloudinary upload failed, no URL returned")
                    except Exception as e:
                        logger.error(f"Error uploading event image to Cloudinary: {str(e)}")
                        return {"message": "Failed to upload event image"}, 500
            elif 'image_url' in data and data['image_url']: # Allow providing URL directly
                 image_url = data['image_url'] # Basic validation might be needed for the URL format

            # Parse date and time
            try:
                event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                 return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

            try:
                 # Adjust format string if using different time formats in frontend
                start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            except ValueError:
                return {"error": "Invalid start_time format. Use HH:MM"}, 400


            # Handle end_time (optional)
            end_time = None
            if "end_time" in data and data["end_time"]:
                 try:
                     # Adjust format string if using different time formats in frontend
                    end_time = datetime.strptime(data["end_time"], "%H:%M").time()
                 except ValueError:
                     return {"error": "Invalid end_time format. Use HH:MM"}, 400

            # Create Event instance
            event = Event(
                name=data["name"],
                description=data["description"],
                date=event_date,
                start_time=start_time,
                end_time=end_time, # Can be None
                location=data["location"],
                image=image_url, # Can be None
                organizer_id=organizer.id # Link event to the organizer profile
            )

            # Validate time constraints (allowing overnight events handled in the model)
            # The model's validate_datetime() method should handle this logic
            try:
                 # Assuming event.validate_datetime() method exists and handles time logic
                 event.validate_datetime()
            except ValueError as e:
                 return {"error": str(e)}, 400


            db.session.add(event)
            db.session.commit()
            return {"message": "Event created successfully", "event": event.as_dict()}, 201

        except Exception as e:
            db.session.rollback() # Rollback the transaction on error
            logger.error(f"Error creating event: {str(e)}")
            # Provide a more generic error message to the client
            return {"error": "An unexpected error occurred during event creation."}, 500


    @jwt_required()
    def put(self, event_id):
        """Update an existing event. Only the event's creator (organizer) or Admin can update it."""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        event = Event.query.get(event_id)

        if not user:
             return {"error": "Authenticated user not found"}, 401 # Use 401 if user not found after auth

        if not event:
            return {"error": "Event not found"}, 404

        # Find the organizer profile for the current user
        organizer = Organizer.query.filter_by(user_id=user.id).first()

        # Check if the user is the event's organizer OR an Admin
        is_organizer = organizer and event.organizer_id == organizer.id
        is_admin = user.role.value == "ADMIN"

        if not (is_organizer or is_admin):
            return {"message": "Only the event creator (organizer) or Admin can update this event"}, 403

        # Use request.get_json(force=True) if you're always sending JSON
        # Otherwise, check content type or use request.json
        data = request.get_json() # Assuming JSON payload for PUT updates

        if not data:
            return {"error": "No update data provided in JSON format"}, 400

        try:
            # Update event attributes based on provided data
            if "name" in data: event.name = data["name"]
            if "description" in data: event.description = data["description"]
            if "location" in data: event.location = data["location"]
            # Handle optional image update (e.g., allow setting to null or providing new URL)
            if "image" in data: event.image = data["image"]


            # Validate and update event date
            if "date" in data:
                try:
                    event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
                     # Consider allowing future updates even if date is in the past for completed events
                    # if event_date < datetime.utcnow().date():
                    #      return {"error": "Event date cannot be in the past"}, 400 # Re-enable if strict future dating required
                    event.date = event_date
                except ValueError:
                    return {"error": "Invalid date format for 'date'. Use YYYY-MM-DD"}, 400

            # Validate and update start_time
            if "start_time" in data:
                try:
                    event.start_time = datetime.strptime(data["start_time"], "%H:%M").time() # Use %H:%M for HH:MM format
                except ValueError:
                    return {"error": "Invalid start_time format. Use HH:MM"}, 400

            # Validate and update end_time (optional)
            if "end_time" in data:
                 if data["end_time"]: # Allow setting end_time to null/empty string to mean "Till Late"
                     try:
                         event.end_time = datetime.strptime(data["end_time"], "%H:%M").time() # Use %H:%MM for HH:MM format
                     except ValueError:
                         return {"error": "Invalid end_time format. Use HH:MM"}, 400
                 else:
                    event.end_time = None # Set to None if empty string or null is sent


            # Validate time logic after potential updates
            # Assuming event.validate_datetime() in the model handles this logic
            try:
                if event.start_time and event.end_time: # Only validate if both times are set
                     # This check might need to be adjusted based on your model's validation logic
                     # if event.start_time >= event.end_time: # Basic check without overnight consideration
                     #      return {"error": "Start time must be before end time"}, 400
                     pass # Model's validate_datetime should handle overnight logic
            except ValueError as e:
                return {"error": str(e)}, 400


            db.session.commit()
            # Fetch the updated event to return its latest state
            updated_event = Event.query.get(event_id)
            return {"message": "Event updated successfully", "event": updated_event.as_dict()}, 200

        except Exception as e:
            db.session.rollback() # Rollback the transaction on error
            logger.error(f"Error updating event: {str(e)}")
            # Provide a more generic error message to the client
            return {"error": "An unexpected error occurred during event update."}, 500


    @jwt_required()
    def delete(self, event_id):
        """Delete an event (Only the event creator or Admin can delete it)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user:
                 return {"error": "Authenticated user not found"}, 401

            event = Event.query.get(event_id)
            if not event:
                return {"error": "Event not found"}, 404

            # Find the organizer profile for the current user
            organizer = Organizer.query.filter_by(user_id=user.id).first()

            # Check if the user is the event's organizer OR an Admin
            is_organizer = organizer and event.organizer_id == organizer.id
            is_admin = user.role.value == "ADMIN"

            if not (is_organizer or is_admin):
                return {"message": "Only the event creator (organizer) or Admin can delete this event"}, 403

            db.session.delete(event)
            db.session.commit()
            return {"message": "Event deleted successfully"}, 200
        except Exception as e:
             db.session.rollback() # Rollback in case of unexpected error before commit
             logger.error(f"Error deleting event: {str(e)}")
             return {"error": "An unexpected error occurred during event deletion."}, 500


class OrganizerEventsResource(Resource):
    @jwt_required()
    def get(self):
        """Retrieve events created by the logged-in organizer."""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        # Check if the user exists and has the ORGANIZER role
        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can access their events"}, 403

        # Find the Organizer profile linked to this user
        organizer = Organizer.query.filter_by(user_id=user.id).first()

        # If an organizer profile exists, filter events by organizer_id
        if organizer:
            # 👇 FIX: Filter by organizer_id instead of user_id
            events = Event.query.filter_by(organizer_id=organizer.id).all()
            logger.info(f"Fetched events for organizer_id {organizer.id}: {len(events)} events") # Use logger
            event_list = [event.as_dict() for event in events]
            # logger.info(f"Event list as dicts: {event_list}") # Avoid logging potentially large data in production
            return event_list, 200
        else:
            # This case should ideally not happen if the user role is 'ORGANIZER'
            # but it's good practice to handle it.
            logger.warning(f"User {current_user_id} has ORGANIZER role but no Organizer profile.")
            return {"message": "Organizer profile not found"}, 404


def register_event_resources(api):
    """Registers the EventResource routes with Flask-RESTful API."""
    # Make sure the '/events' route is handled for getting ALL events (potentially public or admin)
    # And '/events/<int:event_id>' is for getting a specific event
    api.add_resource(EventResource, "/events", "/events/<int:event_id>")
    # The '/api/organizer/events' route is specifically for the logged-in organizer's events
    api.add_resource(OrganizerEventsResource, "/api/organizer/events")


# 📌 Endpoint: Register Event # This comment seems out of place here