import json
import os
from flask import Flask, request, jsonify
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from model import db, User, Event, UserRole, Ticket, Transaction, Scan, TicketType  # Import all related models
from flask_restful import Resource, Api
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import current_app  # Import current_app

class AdminOperations:
    def __init__(self, db_session):
        self.db = db_session

    def get_events_by_organizer(self, organizer_id):
        """Retrieves all events created by a specific organizer."""
        try:
            events = Event.query.filter(Event.user_id == organizer_id).all()
            return [event.as_dict() for event in events]
        except SQLAlchemyError as e:
            print(f"Error retrieving events: {e}")
            return []

    def get_all_events(self):
        """Retrieves all events in the database."""
        try:
            events = Event.query.all()
            return [event.as_dict() for event in events]
        except SQLAlchemyError as e:
            print(f"Error retrieving events: {e}")
            return []

    def get_event_by_id(self, event_id):
        """Retrieves a specific event by its ID."""
        try:
            event = Event.query.get(event_id)
            return event.as_dict() if event else None
        except SQLAlchemyError as e:
            print(f"Error retrieving event: {e}")
            return None

    def get_non_attendee_users(self):
        """Retrieves all users who are not attendees."""
        try:
            users = User.query.filter(User.role != UserRole.ATTENDEE).all()
            return [user.as_dict() for user in users]
        except SQLAlchemyError as e:
            print(f"Error retrieving users: {e}")
            return []

    def search_user_by_email(self, email):
        """Searches for a user by their email address."""
        try:
            user = User.query.filter_by(email=email).first()
            return user.as_dict() if user else None
        except SQLAlchemyError as e:
            print(f"Error searching user: {e}")
            return None

    def delete_event(self, event_id):
        """Delete an event and all related data."""
        try:
            event = Event.query.get(event_id)
            if event:
                # 1. Delete related Tickets and their associated data
                for ticket in event.tickets:
                    # Delete Transactions
                    if ticket.transaction is not None:
                        self.db.session.delete(ticket.transaction)
                    # Delete Scans
                    for scan in ticket.scans:
                        self.db.session.delete(scan)
                    # Delete QR code files
                    qr_code_filename = f'ticket_{ticket.id}.png'  # Corrected filename
                    qrcode_path = os.path.join('static', 'qrcode', qr_code_filename)
                    qrcodes_path = os.path.join('static', 'qrcodes', qr_code_filename)
                    if os.path.exists(qrcode_path):
                        os.remove(qrcode_path)
                    if os.path.exists(qrcodes_path):
                        os.remove(qrcodes_path)
                    self.db.session.delete(ticket)
                self.db.session.commit()

                # 2. Now delete the Event itself
                self.db.session.delete(event)
                self.db.session.commit()

                return {"message": f"Event {event_id} and all related data deleted successfully."}, 200
            else:
                return {"message": f"Event {event_id} not found."}, 404
        except SQLAlchemyError as e:
            self.db.session.rollback()
            return {"error": str(e)}, 500

    def auto_delete_old_events(self):
        """Automatically delete events and all related data older than a configurable number of days."""
        try:
            deletion_period_days_str = current_app.config.get('AUTO_DELETE_EVENT_DAYS', '30')
            try:
                days = int(deletion_period_days_str)
            except ValueError:
                print(f"Invalid value for AUTO_DELETE_EVENT_DAYS in config: {deletion_period_days_str}. Using default of 30 days.")
                days = 30

            thirty_days_ago = datetime.utcnow().date() - timedelta(days=days)
            old_events = Event.query.filter(Event.date < thirty_days_ago).all()
            deleted_count = 0
            for event in old_events:
                # 1. Delete related Tickets and their associated data
                for ticket in event.tickets:
                    # Delete Transactions
                    if ticket.transaction is not None:
                        self.db.session.delete(ticket.transaction)
                    # Delete Scans
                    for scan in ticket.scans:
                        self.db.session.delete(scan)
                    # Delete QR code files
                    qr_code_filename = f'ticket_{ticket.id}.png'  # Corrected filename
                    qrcode_path = os.path.join('static', 'qrcode', qr_code_filename)
                    qrcodes_path = os.path.join('static', 'qrcodes', qr_code_filename)
                    if os.path.exists(qrcode_path):
                        os.remove(qrcode_path)
                    if os.path.exists(qrcodes_path):
                        os.remove(qrcodes_path)
                    self.db.session.delete(ticket)
                self.db.session.commit() # Commit the deletion of tickets before proceeding

                # 2. Now delete the Event itself. This should trigger the cascade to delete TicketTypes.
                self.db.session.delete(event)
                self.db.session.commit() # Commit the deletion of the event and ticket types

                deleted_count += 1

            return {"message": f"Deleted {deleted_count} old events and all related data."}, 200
        except SQLAlchemyError as e:
            self.db.session.rollback()
            return {"error": str(e)}, 500

    def delete_user(self, admin_user_id, user_id_to_delete):
        """Delete a user with ORGANIZER or SECURITY role (Only accessible by admin)."""
        try:
            admin_user = User.query.get(admin_user_id)
            if not admin_user or admin_user.role != UserRole.ADMIN:
                return {"message": "Only admins can delete users"}, 403

            user_to_delete = User.query.get(user_id_to_delete)
            if not user_to_delete:
                return {"message": f"User with ID {user_id_to_delete} not found"}, 404

            if user_to_delete.role in [UserRole.ORGANIZER, UserRole.SECURITY]:
                # Optionally handle related data if needed
                self.db.session.delete(user_to_delete)
                self.db.session.commit()
                return {"message": f"User with ID {user_id_to_delete} and role {user_to_delete.role} deleted successfully"}, 200
            else:
                return {"message": f"Cannot delete user with ID {user_id_to_delete} as their role is {user_to_delete.role}"}, 403
        except SQLAlchemyError as e:
            self.db.session.rollback()
            return {"error": str(e)}, 500

class AdminGetOrganizerEvents(Resource):
    @jwt_required()
    def get(self, organizer_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        events = admin_ops.get_events_by_organizer(organizer_id)
        return [event.as_dict() for event in events], 200

class AdminGetAllEvents(Resource):
    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        events = admin_ops.get_all_events()
        return [event.as_dict() for event in events], 200

class AdminGetEventById(Resource):
    @jwt_required()
    def get(self, event_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        event = admin_ops.get_event_by_id(event_id)
        if event:
            return event, 200
        return {"message": "Event not found"}, 404

class AdminGetNonAttendees(Resource):
    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        users = admin_ops.get_non_attendee_users()
        return [user.as_dict() for user in users], 200

class AdminSearchUserByEmail(Resource):
    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        email = request.args.get('email')
        if not email:
            return {"message": "Email parameter is required"}, 400
        admin_ops = AdminOperations(db)
        user = admin_ops.search_user_by_email(email)
        if user:
            return user, 200
        return {"message": "User not found"}, 404

class AdminDeleteEvent(Resource):
    @jwt_required()
    def delete(self, event_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        return admin_ops.delete_event(event_id)

class AdminAutoDeleteOldEvents(Resource):
    @jwt_required()
    def post(self): # Using POST as it's an action
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        return admin_ops.auto_delete_old_events()

class AdminDeleteUser(Resource):
    @jwt_required()
    def delete(self, user_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        return admin_ops.delete_user(current_user_id, user_id)

def register_admin_resources(api):
    api.add_resource(AdminGetOrganizerEvents, "/admin/organizer/<int:organizer_id>/events")
    api.add_resource(AdminGetAllEvents, "/admin/events") # Endpoint to get all events
    api.add_resource(AdminGetEventById, "/admin/events/<int:event_id>") # Endpoint to get event by ID
    api.add_resource(AdminGetNonAttendees, "/admin/users/non-attendees")
    api.add_resource(AdminSearchUserByEmail, "/admin/users/search")
    api.add_resource(AdminDeleteEvent, "/admin/events/delete/<int:event_id>") # Changed endpoint for clarity
    api.add_resource(AdminAutoDeleteOldEvents, "/admin/events/auto-delete-old")
    api.add_resource(AdminDeleteUser, "/admin/users/<int:user_id>")