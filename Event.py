from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime
from model import db, Event, User, UserRole
from flask_jwt_extended import jwt_required, get_jwt_identity

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
        """Create a new event. Only organizers can create events."""
        current_user = get_jwt_identity()

        # Ensure the JWT contains the correct structure
        if not isinstance(current_user, dict) or "id" not in current_user:
            return {"error": "Invalid JWT identity format"}, 400

        current_user_id = current_user["id"]
        user = User.query.get(current_user_id)

        if not user:
            return {"error": "User not found"}, 404

        if user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can create events"}, 403

        data = request.get_json()
        required_fields = ["name", "description", "date", "start_time", "end_time", "location"]

        for field in required_fields:
            if field not in data:
                return {"message": f"Missing field: {field}"}, 400

        try:
            event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            end_time = datetime.strptime(data["end_time"], "%H:%M").time()

            if start_time >= end_time:
                return {"error": "Start time must be before end time"}, 400

            if event_date < datetime.utcnow().date():
                return {"error": "Event date cannot be in the past"}, 400

            event = Event(
                name=data["name"],
                description=data["description"],
                date=event_date,
                start_time=start_time,
                end_time=end_time,
                location=data["location"],
                image=data.get("image", None),
                user_id=user.id
            )

            db.session.add(event)
            db.session.commit()
            return event.as_dict(), 201

        except ValueError as e:
            return {"error": str(e)}, 400


    @jwt_required()
    def put(self, event_id):
        """Update an existing event. Only the event's creator (organizer) can update it."""
        current_user = get_jwt_identity()

        # Ensure JWT identity is structured correctly
        if not isinstance(current_user, dict) or "id" not in current_user:
            return {"error": "Invalid JWT identity format"}, 400

        current_user_id = current_user["id"]
        user = User.query.get(current_user_id)

        if not user:
            return {"error": "User not found"}, 404

        event = Event.query.get(event_id)
        if not event:
            return {"error": "Event not found"}, 404

        if user.role != UserRole.ORGANIZER or event.user_id != user.id:
            return {"message": "Only organizers can update this event"}, 403

        data = request.get_json()
        if not data:
            return {"error": "No data provided"}, 400

        try:
            if "date" in data:
                event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
                if event_date < datetime.utcnow().date():
                    return {"error": "Event date cannot be in the past"}, 400
                event.date = event_date

            if "start_time" in data:
                time_str = data["start_time"]
                event.start_time = datetime.strptime(time_str, "%H:%M" if len(time_str) == 5 else "%H:%M:%S").time()

            if "end_time" in data:
                time_str = data["end_time"]
                event.end_time = datetime.strptime(time_str, "%H:%M" if len(time_str) == 5 else "%H:%M:%S").time()

            if event.start_time and event.end_time and event.start_time >= event.end_time:
                return {"error": "Start time must be before end time"}, 400

            event.name = data.get("name", event.name)
            event.description = data.get("description", event.description)
            event.location = data.get("location", event.location)
            event.image = data.get("image", event.image)

            db.session.commit()
            return {"message": "Update Done Successfully", "event": event.as_dict()}, 200

        except ValueError as e:
            return {"error": str(e)}, 400

    

    @jwt_required()
    def delete(self, event_id):
        """Delete an event. Only the event's creator (organizer) can delete it."""
        current_user = get_jwt_identity()

        # Ensure JWT identity is structured correctly
        if not isinstance(current_user, dict) or "id" not in current_user:
            return {"error": "Invalid JWT identity format"}, 400

        current_user_id = current_user["id"]
        user = User.query.get(current_user_id)

        if not user:
            return {"error": "User not found"}, 404

        event = Event.query.get(event_id)
        if not event:
            return {"error": "Event not found"}, 404

        if user.role != UserRole.ORGANIZER or event.user_id != user.id:
            return {"message": "Only organizers can delete this event"}, 403

        db.session.delete(event)
        db.session.commit()

        return {"message": "Event Deleted Successfully"}, 200


def register_event_resources(api):
    """Registers the EventResource routes with Flask-RESTful API."""
    api.add_resource(EventResource, "/events", "/events/<int:event_id>")
