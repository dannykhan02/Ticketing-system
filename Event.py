import json
from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime, timedelta
from model import db, Event, User, UserRole, Organizer
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import cloudinary.uploader
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class EventResource(Resource):
    @jwt_required()
    def get(self, event_id=None):
        """Retrieve an event by ID or return all events if no ID is provided."""
        if event_id:
            event = Event.query.get(event_id)
            if event:
                return event.as_dict(), 200
            return {"message": "Event not found"}, 404
        events = Event.query.all()
        return [event.as_dict() for event in events], 200

    @jwt_required()
    def post(self):
        """Create a new event (Only organizers can create events)."""
        try:
            identity = get_jwt_identity()  # Get current user
            user = User.query.get(identity)
            
            if not user or user.role.value != "ORGANIZER":
                return {"message": "Only organizers can create events"}, 403

            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found"}, 404

            # Get form data and files
            data = request.form
            files = request.files

            # Validate required fields
            required_fields = ["name", "description", "date", "start_time", "location"]
            for field in required_fields:
                if field not in data:
                    return {"message": f"Missing field: {field}"}, 400

            # Handle file upload if provided
            image_url = None
            if 'file' in files:
                file = files['file']
                if file and file.filename != '':
                    if not allowed_file(file.filename):
                        return {"message": "Invalid file type. Allowed types: PNG, JPG, JPEG, GIF, WEBP"}, 400
                    
                    try:
                        upload_result = cloudinary.uploader.upload(
                            file,
                            folder="event_images",
                            resource_type="auto"
                        )
                        image_url = upload_result.get('secure_url')
                    except Exception as e:
                        logger.error(f"Error uploading event image: {str(e)}")
                        return {"message": "Failed to upload event image"}, 500

            # Parse date and time
            event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            start_time = datetime.strptime(data["start_time"], "%H:%M:%S").time()

            # Handle end_time (optional)
            end_time = None
            if "end_time" in data and data["end_time"]:
                end_time = datetime.strptime(data["end_time"], "%H:%M:%S").time()

            # Create Event instance
            event = Event(
                name=data["name"],
                description=data["description"],
                date=event_date,
                start_time=start_time,
                end_time=end_time,
                location=data["location"],
                image=image_url,
                organizer_id=organizer.id
            )

            # Validate time (handles overnight events and "Till Late")
            event.validate_datetime()

            db.session.add(event)
            db.session.commit()
            return {"message": "Event created successfully", "event": event.as_dict()}, 201

        except ValueError as e:  # Catch validation errors
            return {"error": str(e)}, 400
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500

    @jwt_required()
    def put(self, event_id):
        """Update an existing event. Only the event's creator (organizer) can update it."""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        event = Event.query.get(event_id)
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not user:
            return {"error": "User not found"}, 404

        if not event:
            return {"error": "Event not found"}, 404

        if user.role.value != "ORGANIZER" or event.organizer_id != organizer.id:
            return {"message": "Only the event creator (organizer) can update this event"}, 403

        data = request.get_json()
        if not data:
            return {"error": "No data provided"}, 400

        try:
            # Validate and update event date
            if "date" in data:
                try:
                    event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
                    if event_date < datetime.utcnow().date():
                        return {"error": "Event date cannot be in the past"}, 400
                    event.date = event_date
                except ValueError:
                    return {"error": "Invalid date format. Use-MM-DD"}, 400

            # Validate and update start_time
            if "start_time" in data:
                try:
                    event.start_time = datetime.strptime(data["start_time"], "%H:%M").time()
                except ValueError:
                    return {"error": "Invalid start_time format. Use HH:MM"}, 400

            # Validate and update end_time (optional)
            if "end_time" in data:
                try:
                    event.end_time = datetime.strptime(data["end_time"], "%H:%M").time()
                except ValueError:
                    return {"error": "Invalid end_time format. Use HH:MM"}, 400
            else:
                event.end_time = None  # No end_time means "Till Late"

            # Validate time logic (allowing overnight events)
            if event.start_time and event.end_time:
                start_datetime = datetime.combine(event.date, event.start_time)
                end_datetime = datetime.combine(event.date, event.end_time)

                if end_datetime <= start_datetime:  # Handles overnight cases
                    end_datetime += timedelta(days=1)

                if start_datetime >= end_datetime:
                    return {"error": "Start time must be before end time"}, 400

            # Update other event attributes
            event.name = data.get("name", event.name)
            event.description = data.get("description", event.description)
            event.location = data.get("location", event.location)
            event.image = data.get("image", event.image)

            db.session.commit()
            return {"message": "Update successful", "event": event.as_dict()}, 200

        except Exception as e:
            db.session.rollback()
            return {"error": f"An error occurred: {str(e)}"}, 500

    @jwt_required()
    def delete(self, event_id):
        """Delete an event (Only the event creator can delete it)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            event = Event.query.get(event_id)
            if not event:
                return {"error": "Event not found"}, 404

            if user.role.value != "ORGANIZER" or event.user_id != user.id:
                return {"message": "Only the event creator (organizer) can delete this event"}, 403

            db.session.delete(event)
            db.session.commit()
            return {"message": "Event deleted successfully"}, 200
        except Exception as e:
            return {"error": str(e)}, 500

    @jwt_required()
    def post(self, event_id):
        """Like an event."""
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        event = Event.query.get(event_id)

        if not event:
            return {"message": "Event not found"}, 404

        if user in event.likes:
            return {"message": "You have already liked this event"}, 400

        event.likes.append(user)
        db.session.commit()
        return {"message": "Event liked successfully", "likes_count": event.likes.count()}, 200

    @jwt_required()
    def delete(self, event_id):
        """Unlike an event."""
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        event = Event.query.get(event_id)

        if not event:
            return {"message": "Event not found"}, 404

        if user not in event.likes:
            return {"message": "You have not liked this event"}, 400

        event.likes.remove(user)
        db.session.commit()
        return {"message": "Event unliked successfully", "likes_count": event.likes.count()}, 200


class OrganizerEventsResource(Resource):
    @jwt_required()
    def get(self):
        """Retrieve events created by the logged-in organizer."""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can access their events"}, 403
        events = Event.query.filter_by(user_id=user.id).all()
        print(f"Fetched events: {events}")  # Add this line
        event_list = [event.as_dict() for event in events]
        print(f"Event list: {event_list}")  
        return event_list, 200


def register_event_resources(api):
    """Registers the EventResource routes with Flask-RESTful API."""
    api.add_resource(EventResource, "/events", "/events/<int:event_id>")
    api.add_resource(OrganizerEventsResource, "/api/organizer/events")
    api.add_resource(EventResource, "/events/<int:event_id>/like", endpoint="like_event")
    api.add_resource(EventResource, "/events/<int:event_id>/unlike", endpoint="unlike_event")
