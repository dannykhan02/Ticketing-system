import json
import os
from flask import Flask, request, jsonify, send_file
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
# Import all related models and db instance
# Corrected: Import Organizer instead of OrganizerProfile
from model import db, User, Event, UserRole, Ticket, Transaction, Scan, TicketType, Report, Organizer
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import current_app  # Import current_app
from pdf_utils import generate_graph_image, generate_pdf_with_graph  # Import PDF generation utilities
from report import get_event_report  # Import the report generation function
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AdminOperations:
    def __init__(self, db_session):
        self.db = db_session

    def get_events_by_organizer(self, organizer_id):
        """Retrieves all events created by a specific organizer."""
        try:
            # Corrected: Use Event.organizer_id instead of Event.user_id
            events = Event.query.filter(Event.organizer_id == organizer_id).all()
            # Ensure Event model has an as_dict method
            return [event.as_dict() for event in events]
        except SQLAlchemyError as e:
            print(f"Error retrieving events: {e}")
            return []

    def get_all_events(self):
        """Retrieves all events in the database."""
        try:
            events = Event.query.all()
            # Ensure Event model has an as_dict method
            return [event.as_dict() for event in events]
        except SQLAlchemyError as e:
            print(f"Error retrieving events: {e}")
            return []

    def get_event_by_id(self, event_id):
        """Retrieves a specific event by its ID."""
        try:
            event = Event.query.get(event_id)
            # Ensure Event model has an as_dict method
            return event.as_dict() if event else None
        except SQLAlchemyError as e:
            print(f"Error retrieving event: {e}")
            return None

    def get_non_attendee_users(self):
        """Retrieves all users who are not attendees."""
        try:
            users = User.query.filter(User.role != UserRole.ATTENDEE).all()
            # Ensure User model has an as_dict method
            return [user.as_dict() for user in users]
        except SQLAlchemyError as e:
            print(f"Error retrieving users: {e}")
            return []

    def search_user_by_email(self, email):
        """Searches for a user by their email address."""
        try:
            user = User.query.filter_by(email=email).first()
            # Ensure User model has an as_dict method
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
                # Optionally handle related data if needed (e.g., delete organizer profile)
                # Corrected: Use user.organizer instead of user.organizer_profile
                if user_to_delete.organizer:
                    self.db.session.delete(user_to_delete.organizer)
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

    def get_reports_by_organizer(self, organizer_id):
        """Retrieves all reports for events created by a specific organizer."""
        try:
            # Corrected: Use Event.organizer_id in the join condition
            events = Event.query.filter(Event.organizer_id == organizer_id).all()
            event_ids = [event.id for event in events]
            reports = Report.query.filter(Report.event_id.in_(event_ids)).all()
            # Ensure Report model has an as_dict method
            return [report.as_dict() for report in reports]
        except SQLAlchemyError as e:
            print(f"Error retrieving reports: {e}")
            return []

    def get_all_reports(self):
        """Retrieves all reports in the database."""
        try:
            reports = Report.query.all()
            # Ensure Report model has an as_dict method
            return [report.as_dict() for report in reports]
        except SQLAlchemyError as e:
            print(f"Error retrieving reports: {e}")
            return []

    def get_organizers(self):
        """Get list of all organizers with their event counts."""
        try:
            organizers = User.query.filter_by(role=UserRole.ORGANIZER).all()
            result = []
            for organizer in organizers:
                # Get base user data
                # Ensure User model has an as_dict method
                organizer_data = organizer.as_dict()

                # Add organizer profile data if it exists
                # Corrected: Use organizer.organizer instead of organizer.organizer_profile
                if organizer.organizer:
                    # Ensure Organizer model has an as_dict method
                    profile_data = organizer.organizer.as_dict()
                    # Remove user_id from profile data to avoid redundancy
                    profile_data.pop('user_id', None)
                    # Add profile data under a nested key
                    # Corrected: Use 'organizer' key instead of 'organizer_profile'
                    organizer_data['organizer'] = profile_data
                else:
                    # Corrected: Use 'organizer' key instead of 'organizer_profile'
                    organizer_data['organizer'] = None

                result.append(organizer_data)
            return result
        except Exception as e:
            logger.error(f"Error fetching organizers: {str(e)}")
            return []

    def delete_organizer(self, organizer_id):
        """Delete an organizer."""
        try:
            # First fetch the user with role ORGANIZER
            user = User.query.filter_by(id=organizer_id, role=UserRole.ORGANIZER).first()
            if not user:
                return {"message": "Organizer not found"}, 404
            # Delete the organizer profile first
            # Corrected: Use user.organizer instead of user.organizer_profile
            if user.organizer:
                self.db.session.delete(user.organizer)
            # Then delete the user
            self.db.session.delete(user)
            self.db.session.commit()
            return {"message": "Organizer deleted successfully"}, 200
        except Exception as e:
            self.db.session.rollback()
            return {"message": "Failed to delete organizer", "error": str(e)}, 500

    def get_users(self):
        """Get list of all users with optional search."""
        try:
            search_query = request.args.get('search', '').lower()

            # Base query
            query = User.query

            # Apply search filter if provided
            if search_query:
                query = query.filter(
                    db.or_(
                        User.full_name.ilike(f'%{search_query}%'),
                        User.email.ilike(f'%{search_query}%'),
                        User.phone_number.ilike(f'%{search_query}%')
                    )
                )

            # Get all users
            users = query.all()

            # Format response
            result = []
            for user in users:
                # Ensure User model has an as_dict method
                user_data = user.as_dict()
                # Add additional fields if needed
                user_data['is_organizer'] = user.role == UserRole.ORGANIZER
                result.append(user_data)

            return result
        except Exception as e:
            logger.error(f"Error fetching users: {str(e)}")
            return []

class AdminGetOrganizerEvents(Resource):
    @jwt_required()
    def get(self, organizer_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # Corrected: admin_ops.get_events_by_organizer already returns a list of dicts
        events = admin_ops.get_events_by_organizer(organizer_id)
        return events, 200

class AdminGetAllEvents(Resource):
    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # Corrected: admin_ops.get_all_events already returns a list of dicts
        events = admin_ops.get_all_events()
        return events, 200

class AdminGetEventById(Resource):
    @jwt_required()
    def get(self, event_id):
        """Retrieves a specific event by its ID."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # admin_ops.get_event_by_id already returns a dict or None
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
        # Corrected: admin_ops.get_non_attendee_users already returns a list of dicts
        # Removed the redundant list comprehension calling .as_dict() again
        users = admin_ops.get_non_attendee_users()
        return users, 200

class AdminSearchUserByEmail(Resource):
    @jwt_required()
    def get(self):
        """Searches for a user by their email address."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        email = request.args.get('email')
        if not email:
            return {"message": "Email parameter is required"}, 400
        admin_ops = AdminOperations(db)
        # admin_ops.search_user_by_email already returns a dict or None
        user = admin_ops.search_user_by_email(email)
        if user:
            return user, 200
        return {"message": "User not found"}, 404

class AdminDeleteEvent(Resource):
    @jwt_required()
    def delete(self, event_id):
        """Delete an event and all related data."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # admin_ops.delete_event returns a tuple (message, status_code)
        return admin_ops.delete_event(event_id)

class AdminDeleteUser(Resource):
    @jwt_required()
    def delete(self, user_id):
        """Delete a user with ORGANIZER or SECURITY role (Only accessible by admin)."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # admin_ops.delete_user returns a tuple (message, status_code)
        return admin_ops.delete_user(current_user_id, user_id)

class AdminDeleteReport(Resource):
    @jwt_required()
    def delete(self, report_id):
        """Delete a report by its ID."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # admin_ops.delete_report returns a tuple (message, status_code)
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
            admin_ops = AdminOperations(db)
            if organizer_id:
                # Retrieve reports for a specific organizer
                # admin_ops.get_reports_by_organizer already returns a list of dicts
                reports = admin_ops.get_reports_by_organizer(organizer_id)
            else:
                # Retrieve all reports
                # admin_ops.get_all_reports already returns a list of dicts
                reports = admin_ops.get_all_reports()

            # Corrected: reports is already a list of dicts, no need for list comprehension with as_dict()
            return reports, 200
        else:
            return {"message": "You do not have permission to access reports"}, 403

class AdminGenerateReportPDF(Resource):
    @jwt_required()
    def get(self, event_id):
        """Generate and return a PDF report for a specific event."""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not user:
            return {"message": "User not found"}, 404

        if user.role.value != "ADMIN":
            return {"message": "Admin access required"}, 403

        # Generate the report data
        # get_event_report returns a dict or a tuple (message, status_code)
        report_data = get_event_report(event_id)
        if isinstance(report_data, tuple) and report_data[1] == 404:
            return report_data
        # If report_data is a dictionary, proceed

        # Generate the graph image
        graph_path = f"/tmp/event_report_{event_id}_graph.png"
        # Ensure generate_graph_image handles the dictionary format of report_data
        generate_graph_image(report_data, graph_path)

        # Generate the PDF file
        pdf_path = f"/tmp/event_report_{event_id}.pdf"
        # Ensure generate_pdf_with_graph handles the dictionary format of report_data
        generate_pdf_with_graph(report_data, event_id, pdf_path, graph_path)

        # Return the PDF file
        # Corrected: Use download_name instead of attachment_filename
        return send_file(pdf_path, as_attachment=True, download_name=f"event_report_{event_id}.pdf")

# The following classes are kept but their resources will be removed from registration
class AdminGetOrganizers(Resource):
    @jwt_required()
    def get(self):
        """Get list of all organizers with their event counts."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # admin_ops.get_organizers already returns a list of dicts
        organizers = admin_ops.get_organizers()
        return organizers, 200

class AdminDeleteOrganizer(Resource):
    @jwt_required()
    def delete(self, organizer_id):
        """Delete an organizer."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # admin_ops.delete_organizer returns a tuple (message, status_code)
        return admin_ops.delete_organizer(organizer_id)

class AdminGetUsers(Resource):
    @jwt_required()
    def get(self):
        """Get list of all users with optional search."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        # admin_ops.get_users already returns a list of dicts
        users = admin_ops.get_users()
        return users, 200


def register_admin_resources(api):
    """Registers admin-specific API resources with the Flask-RESTful API."""
    api.add_resource(AdminGetOrganizerEvents, "/admin/organizer/<int:organizer_id>/events")
    api.add_resource(AdminGetAllEvents, "/admin/events")  # Endpoint to get all events
    api.add_resource(AdminGetEventById, "/admin/events/<int:event_id>")  # Endpoint to get event by ID
    api.add_resource(AdminGetNonAttendees, "/admin/users/non-attendees")
    api.add_resource(AdminSearchUserByEmail, "/admin/users/search")
    api.add_resource(AdminDeleteEvent, "/admin/events/delete/<int:event_id>")  # Changed endpoint for clarity
    api.add_resource(AdminDeleteUser, "/admin/users/<int:user_id>")
    api.add_resource(AdminDeleteReport, "/admin/reports/<int:report_id>")  # New endpoint to delete a report
    api.add_resource(AdminReportResource, "/admin/reports")  # New endpoint to get all reports
    api.add_resource(AdminGenerateReportPDF, "/admin/reports/<int:event_id>/pdf")  # New endpoint to generate and get PDF report
    # Removed the following endpoints as requested:
    # api.add_resource(AdminGetOrganizers, "/admin/organizers")
    # api.add_resource(AdminDeleteOrganizer, "/admin/organizers/<int:organizer_id>")
    # api.add_resource(AdminGetUsers, "/admin/users")
    # api.add_resource(AdminLogout, "/admin/logout")

