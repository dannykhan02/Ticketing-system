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
    """Checks if a filename has an allowed image extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class EventResource(Resource):
    @jwt_required(optional=True) # Make JWT optional for public GET access to events
    def get(self, event_id=None):
        """Retrieve an event by ID or return all events if no ID is provided."""
        current_user_id = get_jwt_identity() # Get user ID if logged in
        user = User.query.get(current_user_id) if current_user_id else None

        if event_id:
            event = Event.query.get(event_id)
            if event:
                # Optional: Restrict viewing details based on role if needed
                # For a public listing, this check might not be necessary for GET /events/<id>
                # If restricted, uncomment and adjust logic:
                # organizer = Organizer.query.filter_by(user_id=user.id).first() if user else None
                # if event.organizer_id != (organizer.id if organizer else None) and (user and user.role.value != "ADMIN"):
                #     return {"message": "You do not have permission to view this event details"}, 403

                return event.as_dict(), 200
            return {"message": "Event not found"}, 404
        else:
            # This part fetches ALL events - typically for a public listing or admin view
            # Consider adding pagination or filtering if the number of events is large
            events = Event.query.all()
            return [event.as_dict() for event in events], 200


    @jwt_required()
    def post(self):
        """Create a new event (Only organizers can create events)."""
        try:
            identity = get_jwt_identity()  # Get current user ID
            user = User.query.get(identity) # Get current user object

            # Check if the user exists and has the ORGANIZER role
            if not user or user.role.value != UserRole.ORGANIZER: # Use Enum directly
                return {"message": "Only organizers can create events"}, 403

            # Find the Organizer profile linked to this user
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            # A user with ORGANIZER role should have a profile, but handle defensively
            if not organizer:
                return {"message": "Organizer profile not found for this user. Please complete your organizer registration."}, 404


            # Get form data and files (assuming form-data for creation with file upload)
            data = request.form
            files = request.files

            # Validate required fields
            required_fields = ["name", "description", "date", "start_time", "location"]
            for field in required_fields:
                if field not in data or not data[field]: # Added check for empty strings
                    return {"message": f"Missing or empty required field: {field}"}, 400

            # Handle file upload if provided (expecting 'image_file' in files)
            image_url = None
            if 'image_file' in files:
                file = files['image_file']
                if file and file.filename != '':
                     # Optional: Check file size
                    file.seek(0, 2) # Move cursor to end of file
                    file_size = file.tell()
                    file.seek(0) # Move cursor back to beginning
                    if file_size > MAX_FILE_SIZE:
                         return {"message": f"File size exceeds the maximum limit of {MAX_FILE_SIZE // (1024 * 1024)}MB"}, 400 # Display size in MB

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
                # Ensure date format matches what frontend sends (%Y-%m-%d)
                event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                 return {"error": "Invalid date format for 'date'. Use YYYY-MM-DD"}, 400

            try:
                 # Ensure time format matches what frontend sends (%H:%M for HH:MM)
                 start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            except ValueError:
                return {"error": "Invalid start_time format. Use HH:MM"}, 400

            # Handle end_time (optional)
            end_time = None
            if "end_time" in data and data["end_time"]:
                 if data["end_time"].strip(): # Check if end_time is provided and not just whitespace
                     try:
                        # Ensure time format matches what frontend sends (%H:%M for HH:MM)
                        end_time = datetime.strptime(data["end_time"].strip(), "%H:%M").time()
                     except ValueError:
                         return {"error": "Invalid end_time format. Use HH:MM"}, 400
                 # If end_time is present in data but empty, it means no end time (Till Late), so end_time remains None


            # Create Event instance
            event = Event(
                name=data["name"].strip(), # Strip whitespace
                description=data["description"].strip(), # Strip whitespace
                date=event_date,
                start_time=start_time,
                end_time=end_time, # Can be None
                location=data["location"].strip(), # Strip whitespace
                image=image_url, # Can be None
                organizer_id=organizer.id # Link event to the organizer profile
            )

            # Validate time constraints (allowing overnight events handled in the model)
            # Assuming event.validate_datetime() method exists in your model
            try:
                 event.validate_datetime()
            except ValueError as e:
                 # Catch validation errors from the model itself
                 return {"error": str(e)}, 400


            db.session.add(event)
            db.session.commit() # Commit the new event

            # Fetch the created event including its relationships for the response
            created_event = Event.query.get(event.id)
            return {"message": "Event created successfully", "event": created_event.as_dict()}, 201

        except Exception as e:
            db.session.rollback() # Rollback the transaction on error
            logger.error(f"Error creating event: {str(e)}", exc_info=True) # Log traceback
            # Provide a more generic error message to the client
            return {"error": "An unexpected error occurred during event creation."}, 500


    @jwt_required()
    def put(self, event_id):
        """Update an existing event. Only the event's creator (organizer) or Admin can update it."""
        identity = get_jwt_identity() # Get current user ID
        user = User.query.get(identity) # Get current user object

        if not user:
             # This should ideally be caught by jwt_required(), but defensive check
             return {"error": "Authenticated user not found"}, 401

        event = Event.query.get(event_id)
        if not event:
            return {"error": "Event not found"}, 404

        # Find the organizer profile for the current user (if they are an organizer)
        organizer = Organizer.query.filter_by(user_id=user.id).first()

        # Check if the user is the event's organizer OR an Admin
        is_organizer = organizer and event.organizer_id == organizer.id
        is_admin = user.role.value == UserRole.ADMIN # Use Enum

        if not (is_organizer or is_admin):
            return {"message": "Only the event creator (organizer) or Admin can update this event"}, 403

        # Assuming JSON payload for PUT updates
        # Use request.get_json() which returns None if payload is not valid JSON
        data = request.get_json()

        if data is None: # Check if get_json() returned None
             return {"error": "Invalid JSON payload provided"}, 400
        if not data: # Check if JSON payload is empty
            return {"error": "No update data provided in JSON format"}, 400

        try:
            # Update event attributes based on provided data if they exist
            if "name" in data and data["name"] is not None: event.name = data["name"].strip()
            if "description" in data and data["description"] is not None: event.description = data["description"].strip()
            if "location" in data and data["location"] is not None: event.location = data["location"].strip()
            # Handle optional image update (allow setting to null or providing new URL string)
            # If 'image' key is present and its value is null, set event.image to None
            # If 'image' key is present and value is a string, update event.image
            if "image" in data:
                 event.image = data["image"] # This allows setting to null or a new URL string


            # Validate and update event date
            if "date" in data and data["date"] is not None:
                try:
                    event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
                     # Consider allowing future updates even if date is in the past for completed events
                    # if event_date < datetime.utcnow().date():
                    #      return {"error": "Event date cannot be in the past"}, 400 # Re-enable if strict future dating required
                    event.date = event_date
                except ValueError:
                    return {"error": "Invalid date format for 'date'. Use YYYY-MM-DD"}, 400

            # Validate and update start_time
            if "start_time" in data and data["start_time"] is not None:
                try:
                    # Use %H:%M for HH:MM format
                    event.start_time = datetime.strptime(data["start_time"], "%H:%M").time()
                except ValueError:
                    return {"error": "Invalid start_time format. Use HH:MM"}, 400

            # Validate and update end_time (optional)
            if "end_time" in data: # Check if the key exists in the payload
                 if data["end_time"] and data["end_time"].strip(): # Check if value is provided and not just whitespace
                     try:
                         # Use %H:%MM for HH:MM format
                         event.end_time = datetime.strptime(data["end_time"].strip(), "%H:%M").time()
                     except ValueError:
                         return {"error": "Invalid end_time format. Use HH:MM"}, 400
                 else:
                    # If 'end_time' key is present but value is empty string or null, set to None
                    event.end_time = None


            # Validate time logic after potential updates
            # Assuming event.validate_datetime() in the model handles this logic
            # This method should be called *after* updating date, start_time, and end_time
            try:
                 event.validate_datetime() # Call the validation method
            except ValueError as e:
                 # Catch validation errors from the model
                 return {"error": str(e)}, 400


            db.session.commit() # Commit the changes

            # Fetch the updated event to return its latest state
            updated_event = Event.query.get(event_id)
            return {"message": "Event updated successfully", "event": updated_event.as_dict()}, 200

        except Exception as e:
            db.session.rollback() # Rollback the transaction on error
            logger.error(f"Error updating event id {event_id}: {str(e)}", exc_info=True) # Log traceback
            # Provide a more generic error message to the client
            return {"error": "An unexpected error occurred during event update."}, 500


    @jwt_required()
    def delete(self, event_id):
        """Delete an event (Only the event creator or Admin can delete it)."""
        try:
            identity = get_jwt_identity() # Get current user ID
            user = User.query.get(identity) # Get current user object

            if not user:
                 # Defensive check, likely redundant with jwt_required()
                 return {"error": "Authenticated user not found"}, 401

            event = Event.query.get(event_id)
            if not event:
                return {"error": "Event not found"}, 404

            # Find the organizer profile for the current user (if they are an organizer)
            organizer = Organizer.query.filter_by(user_id=user.id).first()

            # Check if the user is the event's organizer OR an Admin
            is_organizer = organizer and event.organizer_id == organizer.id
            is_admin = user.role.value == UserRole.ADMIN # Use Enum

            if not (is_organizer or is_admin):
                return {"message": "Only the event creator (organizer) or Admin can delete this event"}, 403

            db.session.delete(event) # Stage the deletion
            db.session.commit() # Commit the deletion
            return {"message": "Event deleted successfully"}, 200
        except Exception as e:
             db.session.rollback() # Rollback in case of unexpected error before commit
             logger.error(f"Error deleting event id {event_id}: {str(e)}", exc_info=True) # Log traceback
             return {"error": "An unexpected error occurred during event deletion."}, 500


class EventLikeResource(Resource):
    """Resource for handling event likes."""

    @jwt_required()
    def post(self, event_id):
        """Like an event."""
        user_id = get_jwt_identity() # Get current user ID
        user = User.query.get(user_id) # Get user object

        if not user:
            return {"message": "User not found"}, 404 # Should not happen with jwt_required

        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404

        # Assuming event.likes is a relationship to users who liked the event
        # Check if the user has already liked the event
        if user in event.likes: # This check assumes 'event.likes' is a list or collection of User objects
            return {"message": "You have already liked this event"}, 400

        try:
            event.likes.append(user) # Add the user to the likes collection
            db.session.commit() # Commit the change
            # To get the likes count, you might need to refresh or query the relationship again
            # Or your as_dict() method on Event might compute this
            db.session.refresh(event) # Refresh to get the latest likes count
            return {"message": "Event liked successfully", "likes_count": len(event.likes)}, 200 # Use len() for relationship size
        except Exception as e:
            db.session.rollback() # Rollback on error
            logger.error(f"Error liking event {event_id} for user {user_id}: {str(e)}", exc_info=True)
            return {"error": "An unexpected error occurred while liking the event."}, 500


    @jwt_required()
    def delete(self, event_id):
        """Unlike an event."""
        user_id = get_jwt_identity() # Get current user ID
        user = User.query.get(user_id) # Get user object

        if not user:
             return {"message": "User not found"}, 404 # Should not happen with jwt_required

        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404

        # Check if the user has liked the event
        if user not in event.likes: # This check assumes 'event.likes' is a list or collection of User objects
            return {"message": "You have not liked this event"}, 400

        try:
            event.likes.remove(user) # Remove the user from the likes collection
            db.session.commit() # Commit the change
             # To get the latest likes count after removal
            db.session.refresh(event) # Refresh to get the latest likes count
            return {"message": "Event unliked successfully", "likes_count": len(event.likes)}, 200 # Use len() for relationship size
        except Exception as e:
            db.session.rollback() # Rollback on error
            logger.error(f"Error unliking event {event_id} for user {user_id}: {str(e)}", exc_info=True)
            return {"error": "An unexpected error occurred while unliking the event."}, 500


class OrganizerEventsResource(Resource):
    @jwt_required()
    def get(self):
        """Retrieve events created by the logged-in organizer."""
        current_user_id = get_jwt_identity() # Get current user ID
        user = User.query.get(current_user_id) # Get current user object

        # Check if the user exists and has the ORGANIZER role
        if not user or user.role.value != UserRole.ORGANIZER: # Use Enum
            return {"message": "Only organizers can access their events"}, 403

        # Find the Organizer profile linked to this user
        organizer = Organizer.query.filter_by(user_id=user.id).first()

        # If an organizer profile exists, filter events by organizer_id
        if organizer:
            # 👇 FIX: Filter by organizer_id instead of user_id
            # This is the correct way to query events linked to a specific organizer profile
            events = Event.query.filter_by(organizer_id=organizer.id).all()
            logger.info(f"Fetched events for organizer_id {organizer.id}: {len(events)} events") # Use logger
            event_list = [event.as_dict() for event in events] # Convert Event objects to dictionaries
            # logger.info(f"Event list as dicts: {event_list}") # Avoid logging potentially large data in production
            return event_list, 200
        else:
            # This case should ideally not happen if the user role is 'ORGANIZER',
            # but it's a safety check.
            logger.warning(f"User {current_user_id} has ORGANIZER role but no Organizer profile found.")
            return {"message": "Organizer profile not found for this user."}, 404


def register_event_resources(api):
    """Registers the EventResource routes with Flask-RESTful API."""
    # Main Event CRUD resource
    api.add_resource(EventResource, "/events", "/events/<int:event_id>")
    # Resource for logged-in organizer's specific events
    api.add_resource(OrganizerEventsResource, "/api/organizer/events")
    # Resource for liking/unliking events
    # Endpoints will be like POST /events/123/like and DELETE /events/123/like
    api.add_resource(EventLikeResource, "/events/<int:event_id>/like")


# Remove the misplaced comments/code from here:
# 📌 Endpoint: Register Event
# 📌 Endpoint: Register Event