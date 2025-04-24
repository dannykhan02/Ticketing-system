import json
import os
from flask import Flask, request, jsonify
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from model import db, User, Event, UserRole, Ticket, Transaction, Scan, TicketType, Report  # Import all related models
from flask_restful import Resource
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
            events = Event.query.options(
                db.joinedload(Event.organizer),
                db.joinedload(Event.tickets).joinedload(Ticket.ticket_type)
            ).all()
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
                # 1. Delete related tickets and their associated data
                for ticket in event.tickets:
                    # Delete transactions
                    if ticket.transaction is not None:
                        self.db.session.delete(ticket.transaction)
                    # Delete scans
                    for scan in ticket.scans:
                        self.db.session.delete(scan)
                    self.db.session.delete(ticket)
                self.db.session.commit()

                # 2. Delete associated reports
                reports = Report.query.filter_by(event_id=event_id).all()
                for report in reports:
                    self.db.session.delete(report)
                self.db.session.commit()

                # 3. Now delete the event itself
                self.db.session.delete(event)
                self.db.session.commit()

                return {"message": f"Event {event_id} and all related data deleted successfully."}, 200
            else:
                return {"message": f"Event {event_id} not found."}, 404
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

    def delete_report(self, report_id):
        """Delete a report by its ID."""
        try:
            report = Report.query.get(report_id)
            if report:
                self.db.session.delete(report)
                self.db.session.commit()
                return {"message": f"Report {report_id} deleted successfully."}, 200
            else:
                return {"message": f"Report {report_id} not found."}, 404
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

class AdminDeleteUser(Resource):
    @jwt_required()
    def delete(self, user_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        return admin_ops.delete_user(current_user_id, user_id)

class AdminDeleteReport(Resource):
    @jwt_required()
    def delete(self, report_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        return admin_ops.delete_report(report_id)

class AdminReportResource(Resource):
    @jwt_required()
    def get(self):
        """Retrieve all reports for admin or specific reports for organizers."""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not user:
            return {"message": "User not found"}, 404

        if user.role.value == "ADMIN":
            # Admin can see all reports or reports for a specific organizer
            organizer_id = request.args.get('organizer_id')
            if organizer_id:
                # Retrieve reports for a specific organizer
                events = Event.query.filter_by(user_id=organizer_id).all()
                event_ids = [event.id for event in events]
                reports = Report.query.filter(Report.event_id.in_(event_ids)).all()
            else:
                # Retrieve all reports
                reports = Report.query.all()

            report_data = [report.as_dict() for report in reports]
            return report_data, 200
        else:
            return {"message": "You do not have permission to access reports"}, 403

def register_admin_resources(api):
    api.add_resource(AdminGetOrganizerEvents, "/admin/organizer/<int:organizer_id>/events")
    api.add_resource(AdminGetAllEvents, "/admin/events")  # Endpoint to get all events
    api.add_resource(AdminGetEventById, "/admin/events/<int:event_id>")  # Endpoint to get event by ID
    api.add_resource(AdminGetNonAttendees, "/admin/users/non-attendees")
    api.add_resource(AdminSearchUserByEmail, "/admin/users/search")
    api.add_resource(AdminDeleteEvent, "/admin/events/delete/<int:event_id>")  # Changed endpoint for clarity
    api.add_resource(AdminDeleteUser, "/admin/users/<int:user_id>")
    api.add_resource(AdminDeleteReport, "/admin/reports/<int:report_id>")  # New endpoint to delete a report
    api.add_resource(AdminReportResource, "/admin/reports")  # New endpoint to get all reports
