import json
import os
import csv
from io import StringIO
from flask import Flask, request, jsonify, send_file, Response
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, time
from model import db, User, Event, UserRole, Ticket, Transaction, Scan, TicketType, Report, Organizer
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from flask import current_app
# from report import get_event_report, ReportConfig, PDFReportGenerator, ChartGenerator, FileManager, EmailService, CSVExporter
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DateUtils:
    @staticmethod
    def adjust_end_date(end_date):
        """Adjust end date to include the entire day"""
        if isinstance(end_date, datetime):
            return end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            # If it's a date object, combine it with time to make it a datetime
            return datetime.combine(end_date, time(23, 59, 59, 999999))

class AdminOperations:
    def __init__(self, db_session):
        self.db = db_session

    def get_events_by_organizer(self, organizer_id):
        """Retrieves all events created by a specific organizer."""
        try:
            events = Event.query.filter(Event.organizer_id == organizer_id).all()
            return [event.as_dict() for event in events]
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving events by organizer: {e}")
            return []

    def get_all_events(self):
        """Retrieves all events in the database."""
        try:
            events = Event.query.all()
            return [event.as_dict() for event in events]
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving all events: {e}")
            return []

    def get_event_by_id(self, event_id):
        """Retrieves a specific event by its ID."""
        try:
            event = Event.query.get(event_id)
            return event.as_dict() if event else None
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving event by ID: {e}")
            return None

    def get_non_attendee_users(self):
        """Retrieves all users who are not attendees."""
        try:
            users = User.query.filter(User.role != UserRole.ATTENDEE).all()
            return [user.as_dict() for user in users]
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving non-attendee users: {e}")
            return []

    def search_user_by_email(self, email):
        """Searches for a user by their email address."""
        try:
            user = User.query.filter(User.email.ilike(email)).first()
            return user.as_dict() if user else None
        except SQLAlchemyError as e:
            logger.error(f"Error searching user by email: {e}")
            return None

    # def get_reports_by_organizer(self, organizer_id, start_date=None, end_date=None):
    #     """Retrieves all reports for events created by a specific organizer with optional date filtering."""
    #     try:
    #         query = Report.query.join(Event).filter(Event.organizer_id == organizer_id)
    #         if start_date:
    #             query = query.filter(Report.timestamp >= start_date)
    #         if end_date:
    #             query = query.filter(Report.timestamp <= end_date)
    #         reports = query.all()
    #         return [self._enrich_report(report) for report in reports]
    #     except SQLAlchemyError as e:
    #         logger.error(f"Error retrieving reports by organizer: {e}")
    #         return []

    # def get_all_reports(self, start_date=None, end_date=None):
    #     """Retrieves all reports in the database with optional date filtering."""
    #     try:
    #         query = Report.query
    #         if start_date:
    #             query = query.filter(Report.timestamp >= start_date)
    #         if end_date:
    #             query = query.filter(Report.timestamp <= end_date)
    #         reports = query.all()
    #         return [self._enrich_report(report) for report in reports]
    #     except SQLAlchemyError as e:
    #         logger.error(f"Error retrieving all reports: {e}")
    #         return []

    # def _enrich_report(self, report):
    #     """Helper method to enrich report data with event and ticket type details."""
    #     event = Event.query.get(report.event_id)
    #     report_data = report.as_dict()
    #     report_data["event_name"] = event.name if event else "N/A"
    #     return report_data

    def get_organizers(self):
        """Get list of all organizers with their event counts."""
        try:
            organizers_models = User.query.filter_by(role=UserRole.ORGANIZER).all()
            result = []
            for organizer_model in organizers_models:
                organizer_data = organizer_model.as_dict()
                if organizer_model.organizer_profile:
                    profile_data = organizer_model.organizer_profile.as_dict()
                    profile_data.pop('user_id', None)
                    organizer_data['organizer'] = profile_data
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
            user = User.query.filter_by(id=organizer_id, role=UserRole.ORGANIZER).first()
            if not user:
                return {"message": "Organizer not found"}, 404
            if user.organizer_profile:
                self.db.session.delete(user.organizer_profile)
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
            users = User.query.all()
            result = []
            for user in users:
                user_data = user.as_dict()
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
        events = admin_ops.get_all_events()
        return events, 200

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
        users_list_of_dicts = admin_ops.get_non_attendee_users()
        separated_users = {"organizers": [], "security": [], "admins": []}
        for user_dict in users_list_of_dicts:
            role = user_dict.get('role')
            if role == UserRole.ORGANIZER.value:
                separated_users["organizers"].append(user_dict)
            elif role == UserRole.SECURITY.value:
                separated_users["security"].append(user_dict)
            elif role == UserRole.ADMIN.value:
                separated_users["admins"].append(user_dict)
        return separated_users, 200

class AdminGetUsers(Resource):
    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        users_list_of_dicts = admin_ops.get_users()
        categorized_users = {"admins": [], "organizers": [], "security": [], "attendees": []}
        for user_dict in users_list_of_dicts:
            role = user_dict.get("role")
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
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        email = request.args.get('email')
        if not email:
            return {"message": "Email parameter is required"}, 400
        admin_ops = AdminOperations(db)
        user_dict = admin_ops.search_user_by_email(email)
        if user_dict:
            return [user_dict], 200
        else:
            return [], 200

# class AdminReportResource(Resource):
#     @jwt_required()
#     def get(self):
#         current_user_id = get_jwt_identity()
#         user = User.query.get(current_user_id)
#         if not user:
#             return {"status": "error", "message": "User not found"}, 404
#         if user.role != UserRole.ADMIN:
#             return {"status": "error", "message": "Admin access required"}, 403
#
#         admin_ops = AdminOperations(db.session)
#
#         try:
#             organizer_id = request.args.get("organizer_id")
#             start_date_str = request.args.get("start_date")
#             end_date_str = request.args.get("end_date")
#
#             start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
#             end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
#
#             if organizer_id:
#                 organizer_id = int(organizer_id)
#                 summary = admin_ops.get_reports_by_organizer(organizer_id, start_date, end_date)
#                 message = f"Report summaries for organizer {organizer_id}"
#             else:
#                 summary = admin_ops.get_all_reports(start_date, end_date)
#                 message = "All report summaries grouped by event"
#
#             return {"status": "success", "message": message, "data": summary}, 200
#
#         except ValueError as ve:
#             return {"status": "error", "message": str(ve)}, 400
#         except Exception as e:
#             return {"status": "error", "message": f"An error occurred: {str(e)}"}, 500

# class AdminGenerateReportPDF(Resource):
#     @jwt_required()
#     def get(self, event_id):
#         current_user_id = get_jwt_identity()
#         user = User.query.get(current_user_id)
#         if not user:
#             return {"status": "error", "message": "User not found"}, 404
#         if user.role != UserRole.ADMIN:
#             return {"status": "error", "message": "Admin access required"}, 403
#
#         report_data = get_event_report(event_id)
#         if isinstance(report_data, tuple) and len(report_data) == 2 and isinstance(report_data[1], int):
#             return report_data
#
#         if not isinstance(report_data, dict):
#             return {"status": "error", "message": "Failed to generate report. Unexpected format returned from get_event_report.", "data_received": str(report_data)}, 500
#
#         config = ReportConfig()
#         pdf_generator = PDFReportGenerator(config)
#         chart_generator = ChartGenerator(config)
#         chart_paths = chart_generator.create_all_charts(report_data)
#
#         pdf_path = FileManager.generate_unique_paths(event_id)[1]
#         generated_pdf_path = pdf_generator.generate_pdf(report_data, chart_paths, pdf_path)
#
#         if not generated_pdf_path or not os.path.exists(generated_pdf_path):
#             logger.error(f"PDF file was not successfully generated for event {event_id}.")
#             return {"message": "Failed to generate PDF report"}, 500
#
#         try:
#             filename = f"event_report_{event_id}.pdf"
#             response = send_file(
#                 generated_pdf_path,
#                 as_attachment=True,
#                 download_name=filename
#             )
#             FileManager.cleanup_files(pdf_path)
#             return response
#         except Exception as e:
#             logger.error(f"Error sending PDF report for event {event_id}: {e}")
#             return {"message": "Failed to send PDF report"}, 500

# class AdminExportAllReportsResource(Resource):
#     @jwt_required()
#     def get(self):
#         current_user_id = get_jwt_identity()
#         user = User.query.get(current_user_id)
#         if not user:
#             return {"status": "error", "message": "User not found"}, 404
#         if user.role != UserRole.ADMIN:
#             return {"status": "error", "message": "Admin access required"}, 403
#
#         admin_ops = AdminOperations(db.session)
#
#         try:
#             organizer_id = request.args.get("organizer_id")
#             start_date_str = request.args.get("start_date")
#             end_date_str = request.args.get("end_date")
#
#             start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
#             end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
#
#             if organizer_id:
#                 organizer_id = int(organizer_id)
#                 reports = admin_ops.get_reports_by_organizer(organizer_id, start_date, end_date)
#             else:
#                 reports = admin_ops.get_all_reports(start_date, end_date)
#
#             csv_content = CSVExporter.generate_csv_report({"reports": reports})
#             filename = f"all_reports_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
#
#             return Response(
#                 csv_content,
#                 mimetype="text/csv",
#                 headers={"Content-disposition": f"attachment; filename={filename}"}
#             )
#
#         except ValueError as ve:
#             return {"status": "error", "message": str(ve)}, 400
#         except Exception as e:
#             return {"status": "error", "message": f"An error occurred: {str(e)}"}, 500

class AdminGetOrganizers(Resource):
    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        organizers = admin_ops.get_organizers()
        return organizers, 200

class AdminDeleteOrganizer(Resource):
    @jwt_required()
    def delete(self, organizer_id):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Admin access required"}, 403
        admin_ops = AdminOperations(db)
        return admin_ops.delete_organizer(organizer_id)

def register_admin_resources(api):
    api.add_resource(AdminGetUsers, "/admin/users")
    api.add_resource(AdminGetOrganizerEvents, "/admin/organizer/<int:organizer_id>/events")
    api.add_resource(AdminGetAllEvents, "/admin/events")
    api.add_resource(AdminGetEventById, "/admin/events/<int:event_id>")
    api.add_resource(AdminGetNonAttendees, "/admin/users/non-attendees")
    api.add_resource(AdminSearchUserByEmail, "/admin/users/search")
    # api.add_resource(AdminReportResource, "/admin/reports/summary")
    # api.add_resource(AdminGenerateReportPDF, "/admin/reports/<int:event_id>/pdf")
    # api.add_resource(AdminExportAllReportsResource, "/admin/reports/export-all")
