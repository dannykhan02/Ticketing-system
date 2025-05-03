import json
from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime, timedelta
from model import db, Event, User, UserRole, Organizer, Category
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
        
        # Get pagination parameters from query string
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 7, type=int)
        
        try:
            # Get all events with pagination
            events = Event.query.paginate(page=page, per_page=per_page, error_out=False)
            
            if not events.items:
                return {
                    'events': [],
                    'total': 0,
                    'pages': 0,
                    'current_page': page
                }
            
            return {
                'events': [{
                    'id': event.id,
                    'name': event.name,
                    'description': event.description,
                    'date': event.date.isoformat(),
                    'start_time': event.start_time.isoformat(),
                    'end_time': event.end_time.isoformat() if event.end_time else None,
                    'location': event.location,
                    'image': event.image,
                    'category': event.event_category.name if event.event_category else None,
                    'category_id': event.category_id,
                    'organizer': {
                        'id': event.organizer.id,
                        'company_name': event.organizer.company_name
                    },
                    'likes_count': event.likes.count()
                } for event in events.items],
                'total': events.total,
                'pages': events.pages,
                'current_page': events.page
            }, 200
        except Exception as e:
            logger.error(f"Error fetching events: {str(e)}")
            return {"message": "Error fetching events"}, 500

    @jwt_required()
    def post(self):
        """Create a new event (Only organizers can create events)."""
        try:
            identity = get_jwt_identity()  # Get current user
            user = User.query.get(identity)
            
            if not user or user.role != UserRole.ORGANIZER:
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

            # Parse dates and times
            event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            
            end_time = None
            if "end_time" in data and data["end_time"]:
                end_time = datetime.strptime(data["end_time"], "%H:%M").time()

            # Get category_id if provided
            category_id = data.get('category_id')
            if category_id:
                category = Category.query.get(category_id)
                if not category:
                    return {"message": "Invalid category ID"}, 400

            # Create Event instance
            event = Event(
                name=data["name"],
                description=data["description"],
                date=event_date,
                start_time=start_time,
                end_time=end_time,
                location=data["location"],
                image=image_url,
                organizer_id=organizer.id,
                category_id=category_id
            )

            # Validate time (handles overnight events and "Till Late")
            event.validate_datetime()

            db.session.add(event)
            db.session.commit()
            return {"message": "Event created successfully", "event": event.as_dict(), "id": event.id}, 201

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

        if user.role != "ORGANIZER" or event.organizer_id != organizer.id:
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
            # Find the organizer profile for the current user (if they are an organizer)
            organizer = Organizer.query.filter_by(user_id=user.id).first()

            # Check if the user is the event's organizer OR an Admin
            is_organizer = organizer and event.organizer_id == organizer.id
            is_admin = user.role.value == UserRole.ADMIN.value  # Use Enum

            if not (is_organizer or is_admin):
                return {"message": "Only the event creator (organizer) or Admin can delete this event"}, 403

            db.session.delete(event)
            db.session.commit()
            return {"message": "Event deleted successfully"}, 200
        except Exception as e:
             db.session.rollback() # Rollback in case of unexpected error before commit
             logger.error(f"Error deleting event id {event_id}: {str(e)}", exc_info=True) # Log traceback
             return {"error": "An unexpected error occurred during event deletion."}, 500


class EventLikeResource(Resource):
    """Resource for handling event likes."""


class EventLikeResource(Resource):
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
        current_user_id = get_jwt_identity()  # Get current user ID
        user = User.query.get(current_user_id)  # Get current user object

        # Check if the user exists and has the ORGANIZER role
        if not user or user.role.value != UserRole.ORGANIZER.value:  # Use Enum
            return {"message": "Only organizers can access their events"}, 403

        # Find the Organizer profile linked to this user
        organizer = Organizer.query.filter_by(user_id=user.id).first()

        # If an organizer profile exists, filter events by organizer_id
        if organizer:
            events = Event.query.filter_by(organizer_id=organizer.id).all()
            logger.info(f"Fetched events for organizer_id {organizer.id}: {len(events)} events")
            event_list = [event.as_dict() for event in events]
            return event_list, 200
        else:
            logger.warning(f"User {current_user_id} has ORGANIZER role but no Organizer profile found.")
            return {"message": "Organizer profile not found for this user."}, 404


class CategoryResource(Resource):
    def get(self):
        """Get all categories"""
        categories = Category.query.all()
        return {
            'categories': [category.as_dict() for category in categories]
        }, 200

    @jwt_required()
    def post(self):
        """Create a new category (Admin only)"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can create categories"}, 403

        data = request.get_json()
        if not data or 'name' not in data:
            return {"message": "Category name is required"}, 400

        try:
            category = Category(
                name=data['name'],
                description=data.get('description')
            )
            db.session.add(category)
            db.session.commit()
            return category.as_dict(), 201
        except Exception as e:
            db.session.rollback()
            return {"message": str(e)}, 400


def register_event_resources(api):
    """Registers the EventResource routes with Flask-RESTful API."""
    api.add_resource(EventResource, "/events", "/events/<int:event_id>")
    api.add_resource(OrganizerEventsResource, "/api/organizer/events")
    api.add_resource(CategoryResource, "/categories")
    # Resource for liking/unliking events
    api.add_resource(EventLikeResource, "/events/<int:event_id>/like", endpoint="like_event")
    api.add_resource(EventLikeResource, "/events/<int:event_id>/unlike", endpoint="unlike_event")