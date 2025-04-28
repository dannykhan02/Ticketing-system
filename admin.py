import json
import os
from flask import Flask, request, jsonify, send_file
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
# Assuming model.py contains db, User, Event, UserRole, Ticket, Transaction, Scan, TicketType, Report, Organizer
from model import db, User, Event, UserRole, Ticket, Transaction, Scan, TicketType, Report, Organizer
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import current_app
# Assuming these utility functions exist and work with dictionary data
from pdf_utils import generate_graph_image, generate_pdf_with_graph
from report import get_event_report
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
            events = Event.query.filter(Event.organizer_id == organizer_id).all()
            # Ensure Event model has an as_dict method
            return [event.as_dict() for event in events]
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving events by organizer: {e}")
            return []

    def get_all_events(self):
        """Retrieves all events in the database."""
        try:
            events = Event.query.options(
                db.joinedload(Event.organizer),
                db.joinedload(Event.tickets).joinedload(Ticket.ticket_type)
            ).all()
            # Ensure Event model has an as_dict method
            return [event.as_dict() for event in events]
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving all events: {e}")
            return []

    def get_event_by_id(self, event_id):
        """Retrieves a specific event by its ID."""
        try:
            event = Event.query.get(event_id)
            # Ensure Event model has an as_dict method
            return event.as_dict() if event else None
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving event by ID: {e}")
            return None

    def get_non_attendee_users(self):
        """Retrieves all users who are not attendees."""
        try:
            users = User.query.filter(User.role != UserRole.ATTENDEE).all()
            # Ensure User model has an as_dict method that returns the role value (string)
            return [user.as_dict() for user in users]
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving non-attendee users: {e}")
            return []

    def search_user_by_email(self, email):
        """Searches for a user by their email address."""
        try:
            # Using ilike for case-insensitive search
            user = User.query.filter(User.email.ilike(email)).first()
            # Ensure User model has an as_dict method that returns the role value (string)
            return user.as_dict() if user else None
        except SQLAlchemyError as e:
            logger.error(f"Error searching user by email: {e}")
            return None

    def get_reports_by_organizer(self, organizer_id):
        """Retrieves all reports for events created by a specific organizer."""
        try:
            # Corrected: Use Event.organizer_id in the join condition
            events = Event.query.filter(Event.organizer_id == organizer_id).all()
            event_ids = [event.id for event in events]
            # Corrected: Filter reports where event_id is in the list of event_ids
            reports = Report.query.filter(Report.event_id.in_(event_ids)).all()
            # Ensure Report model has an as_dict method
            return [report.as_dict() for report in reports]
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving reports by organizer: {e}")
            return []

    def get_all_reports(self):
        """Retrieves all reports in the database."""
        try:
            reports = Report.query.all()
            # Ensure Report model has an as_dict method
            return [report.as_dict() for report in reports]
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving all reports: {e}")
            return []

    def get_organizers(self):
        """Get list of all organizers with their event counts."""
        try:
            organizers_models = User.query.filter_by(role=UserRole.ORGANIZER).all()
            result = []
            for organizer_model in organizers_models: # Iterate over models
                # Get base user data (as dictionary)
                organizer_data = organizer_model.as_dict()

                # Add organizer profile data if it exists
                # Access the relationship on the model instance
                if organizer_model.organizer_profile: # Access the backref from User to Organizer
                    # Ensure Organizer model has an as_dict method
                    profile_data = organizer_model.organizer_profile.as_dict()
                    # Remove user_id from profile data to avoid redundancy
                    profile_data.pop('user_id', None)
                    # Add profile data under a nested key
                    organizer_data['organizer'] = profile_data # Use 'organizer' key as intended
                else:
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
            # Delete the organizer profile first (access relationship on model instance)
            if user.organizer_profile: # Access the backref from User to Organizer
                self.db.session.delete(user.organizer_profile)
            # Then delete the user
            self.db.session.delete(user)
            self.db.session.commit()
            return {"message": "Organizer deleted successfully"}, 200
        except Exception as e:
            self.db.session.rollback()
            logger.error(f"Error deleting organizer: {str(e)}")
            return {"message": "Failed to delete organizer", "error": str(e)}, 500

    def get_users(self):
        """Get list of all users."""
        try:
            query = User.query
            users = query.all()

            # Format response
            result = []
            for user in users: # Iterate over models
                # Ensure User model has an as_dict method
                user_data = user.as_dict()
                # Add additional fields if needed
                # The as_dict method already includes 'role' as a string value
                user_data['is_organizer'] = user.role == UserRole.ORGANIZER # Compare model enum with enum member
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
        # admin_ops.get_events_by_organizer already returns a list of dicts
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
        # admin_ops.get_all_events already returns a list of dicts
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
        """Retrieves all users who are not attendees."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)

        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        admin_ops = AdminOperations(db)
        # This returns a list of dictionaries [{id:..., email:..., role:'ADMIN'}, {...}, ...]
        users_list_of_dicts = admin_ops.get_non_attendee_users()

        separated_users = {
            "organizers": [],
            "security": [],
            "admins": []
        }

        for user_dict in users_list_of_dicts: # 'user_dict' here is a dictionary
            # Corrected: Access role using dictionary key access and compare with enum value
            role = user_dict.get('role') # Use .get() for safety
            if role == UserRole.ORGANIZER.value:
                separated_users["organizers"].append(user_dict) # Append the user dictionary
            elif role == UserRole.SECURITY.value:
                separated_users["security"].append(user_dict) # Append the user dictionary
            elif role == UserRole.ADMIN.value:
                separated_users["admins"].append(user_dict) # Append the user dictionary
            # You might want to handle other roles or roles that don't match

        # Return the structured dictionary
        return separated_users, 200


class AdminGetUsers(Resource):
    @jwt_required()
    def get(self):
        """Get list of all users categorized by role."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)

        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        admin_ops = AdminOperations(db)

        # Get all users (as dictionaries from admin_ops.get_users)
        users_list_of_dicts = admin_ops.get_users()

        # Initialize empty lists for each role
        categorized_users = {
            "admins": [],
            "organizers": [],
            "security": [],
            "attendees": [] # Also include attendees if get_users gets all roles
        }

        # Sort users into categories
        for user_dict in users_list_of_dicts: # 'user_dict' here is a dictionary
            role = user_dict.get("role") # Use .get() for safety
            if role == UserRole.ADMIN.value:
                categorized_users["admins"].append(user_dict)
            elif role == UserRole.ORGANIZER.value:
                categorized_users["organizers"].append(user_dict)
            elif role == UserRole.SECURITY.value:
                categorized_users["security"].append(user_dict)
            elif role == UserRole.ATTENDEE.value:
                categorized_users["attendees"].append(user_dict)


        return categorized_users, 200


class AdminSearchUserByEmail(Resource):
    @jwt_required()
    def get(self):
        """Searches for a user by their email address (case-insensitive)."""
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403

        email = request.args.get('email')
        if not email:
            return {"message": "Email parameter is required"}, 400

        admin_ops = AdminOperations(db)
        # admin_ops.search_user_by_email returns a dict or None
        user_dict = admin_ops.search_user_by_email(email)

        if user_dict:
            # Return the user dictionary in a list, to match the expected array format on the frontend
            # The frontend AdminDashboard/UserManagement expects an array of users.
            return [user_dict], 200
        else:
             # Return an empty list if no user is found, matching the expected array format
            return [], 200


class AdminReportResource(Resource):
    @jwt_required()
    def get(self):
        """Retrieve all reports for admin or specific reports for organizers."""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not user:
            return {"message": "User not found"}, 404

        # Corrected: Compare role value with string value
        if user.role.value == UserRole.ADMIN.value:
            # Admin can see all reports or reports for a specific organizer
            organizer_id = request.args.get('organizer_id')
            admin_ops = AdminOperations(db)
            if organizer_id:
                # Retrieve reports for a specific organizer (returns list of dicts)
                reports = admin_ops.get_reports_by_organizer(organizer_id)
            else:
                # Retrieve all reports (returns list of dicts)
                reports = admin_ops.get_all_reports()

            # Corrected: reports is already a list of dicts, return directly
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

        # Corrected: Compare role value with string value
        if user.role.value != UserRole.ADMIN.value:
            return {"message": "Admin access required"}, 403

        # Generate the report data (expected to return a dictionary or tuple)
        report_data = get_event_report(event_id)
        # Check if get_event_report returned an error tuple
        if isinstance(report_data, tuple) and len(report_data) == 2 and isinstance(report_data[1], int):
             # Assuming tuple is (message, status_code)
             return report_data

        # If report_data is a dictionary, proceed
        if not isinstance(report_data, dict):
             return {"message": "Failed to generate report data: unexpected format"}, 500


        # Generate the graph image
        # Use current_app.root_path to get the base directory of the Flask app
        graph_dir = os.path.join(current_app.root_path, 'tmp')
        os.makedirs(graph_dir, exist_ok=True) # Create tmp directory if it doesn't exist
        graph_path = os.path.join(graph_dir, f"event_report_{event_id}_graph.png")

        try:
            generate_graph_image(report_data, graph_path)
        except Exception as e:
            logger.error(f"Error generating graph image: {e}")
            return {"message": "Failed to generate report graph", "error": str(e)}, 500


        # Generate the PDF file
        pdf_dir = os.path.join(current_app.root_path, 'tmp')
        os.makedirs(pdf_dir, exist_ok=True) # Create tmp directory if it doesn't exist
        pdf_path = os.path.join(pdf_dir, f"event_report_{event_id}.pdf")

        try:
            # Ensure generate_pdf_with_graph handles the dictionary format of report_data
            generate_pdf_with_graph(report_data, event_id, pdf_path, graph_path)
        except Exception as e:
             logger.error(f"Error generating PDF: {e}")
             # Clean up the generated graph file if PDF generation fails
             if os.path.exists(graph_path):
                 os.remove(graph_path)
             return {"message": "Failed to generate PDF report", "error": str(e)}, 500
        finally:
            # Clean up the graph image file after PDF is generated
            if os.path.exists(graph_path):
                os.remove(graph_path)


        # Return the PDF file
        try:
            # Corrected: Use download_name instead of attachment_filename
            response = send_file(pdf_path, as_attachment=True, download_name=f"event_report_{event_id}.pdf")
            # Clean up the generated PDF file after sending
            @response.after_request
            def remove_file(response):
                try:
                    # Add a small delay to ensure file is closed before deletion on some systems
                    import time
                    time.sleep(0.1)
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                except Exception as e:
                    logger.error(f"Error removing generated PDF file: {e}")
                return response
            return response
        except Exception as e:
            logger.error(f"Error sending PDF file: {e}")
            return {"message": "Failed to send PDF report", "error": str(e)}, 500


# The following classes are kept but their resources will be removed from registration (based on original comment)
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


def register_admin_resources(api):
    """Registers admin-specific API resources with the Flask-RESTful API."""
    # This endpoint now returns ALL users and relies on frontend filtering or the search endpoint
    api.add_resource(AdminGetUsers, "/admin/users")
    api.add_resource(AdminGetOrganizerEvents, "/admin/organizer/<int:organizer_id>/events")
    api.add_resource(AdminGetAllEvents, "/admin/events")
    api.add_resource(AdminGetEventById, "/admin/events/<int:event_id>")
    # This endpoint returns only non-attendee users
    api.add_resource(AdminGetNonAttendees, "/admin/users/non-attendees")
    # This endpoint is specifically for searching users by email
    api.add_resource(AdminSearchUserByEmail, "/admin/users/search")
    api.add_resource(AdminReportResource, "/admin/reports")
    api.add_resource(AdminGenerateReportPDF, "/admin/reports/<int:event_id>/pdf")

    # Based on the comment "The following classes are kept but their resources will be removed from registration"
    # I will keep these resources unregistered as per that instruction.
    # If you still need these endpoints registered, uncomment them below.
    # api.add_resource(AdminGetOrganizers, "/admin/organizers")
    # api.add_resource(AdminDeleteOrganizer, "/admin/organizers/<int:organizer_id>")