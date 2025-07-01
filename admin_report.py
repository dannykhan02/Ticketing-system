from flask import jsonify, request, Response, send_file
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Report, Event, User, Organizer, Currency, ExchangeRate, TicketType
from pdf_utils import PDFReportGenerator, CSVExporter
from email_utils import send_email_with_attachment  # Import the email utility
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, and_, or_
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class AdminReportConfig:
    """Configuration for admin report generation"""
    include_charts: bool = True
    include_email: bool = False
    format_type: str = 'json'  # json, pdf, csv
    currency_conversion: bool = True
    target_currency_id: Optional[int] = None
    date_range_days: int = 30
    group_by_organizer: bool = True
    use_latest_rates: bool = True

class AdminReportService:
    """Service class for handling admin report operations"""

    @staticmethod
    def validate_admin_access(user: User) -> bool:
        """Validate that the user has admin access"""
        return user and user.role.value == "ADMIN"

    @staticmethod
    def get_organizer_by_id(organizer_id: int) -> Optional[User]:
        """Get organizer user by ID"""
        try:
            return User.query.filter_by(id=organizer_id, role='ORGANIZER').first()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching organizer {organizer_id}: {e}")
            return None

    @staticmethod
    def get_events_by_organizer(organizer_id: int, start_date: datetime = None, end_date: datetime = None) -> List[Event]:
        """Get all events for a specific organizer within date range"""
        try:
            query = Event.query.join(Organizer).filter(Organizer.user_id == organizer_id)

            if start_date:
                query = query.filter(Event.event_date >= start_date)
            if end_date:
                query = query.filter(Event.event_date <= end_date)

            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching events for organizer {organizer_id}: {e}")
            return []

    @staticmethod
    def get_reports_by_organizer(organizer_id: int, start_date: datetime = None, end_date: datetime = None) -> List[Report]:
        """Get all reports for a specific organizer within date range"""
        try:
            query = Report.query.filter_by(organizer_id=organizer_id)

            if start_date:
                query = query.filter(Report.timestamp >= start_date)
            if end_date:
                query = query.filter(Report.timestamp <= end_date)

            return query.order_by(Report.timestamp.desc()).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching reports for organizer {organizer_id}: {e}")
            return []

    @staticmethod
    def get_reports_by_event(event_id: int, start_date: datetime = None, end_date: datetime = None) -> List[Report]:
        """Get all reports for a specific event within date range"""
        try:
            query = Report.query.filter_by(event_id=event_id)

            if start_date:
                query = query.filter(Report.timestamp >= start_date)
            if end_date:
                query = query.filter(Report.timestamp <= end_date)

            return query.order_by(Report.timestamp.desc()).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching reports for event {event_id}: {e}")
            return []

    @staticmethod
    def aggregate_organizer_reports(reports: List[Report], target_currency_id: Optional[int] = None, use_latest_rates: bool = True) -> Dict[str, Any]:
        """Aggregate multiple reports for an organizer with currency conversion support"""
        if not reports:
            return {
                "total_tickets_sold": 0,
                "total_revenue": 0.0,
                "total_attendees": 0,
                "event_count": 0,
                "report_count": 0,
                "currency": None,
                "events": []
            }

        total_tickets = sum(report.total_tickets_sold for report in reports)
        total_attendees = sum(report.number_of_attendees or 0 for report in reports)

        # Calculate total revenue with currency conversion if needed
        total_revenue = 0.0
        currency_info = {}

        for report in reports:
            if target_currency_id:
                converted_revenue = report.get_revenue_in_currency(target_currency_id, use_latest_rates=use_latest_rates)
                total_revenue += float(converted_revenue)
            else:
                total_revenue += float(report.total_revenue)

        # Get currency information
        if target_currency_id:
            target_currency = Currency.query.get(target_currency_id)
            if target_currency:
                currency_info = {
                    "currency": target_currency.code.value,
                    "currency_symbol": target_currency.symbol
                }
        elif reports:
            base_currency = reports[0].base_currency
            if base_currency:
                currency_info = {
                    "currency": base_currency.code.value,
                    "currency_symbol": base_currency.symbol
                }

        # Get unique events
        unique_events = list(set(report.event_id for report in reports))
        event_details = []

        for event_id in unique_events:
            event_reports = [r for r in reports if r.event_id == event_id]
            event = Event.query.get(event_id)

            if event:
                event_revenue = sum(
                    float(r.get_revenue_in_currency(target_currency_id, use_latest_rates=use_latest_rates) if target_currency_id else r.total_revenue)
                    for r in event_reports
                )
                event_tickets = sum(r.total_tickets_sold for r in event_reports)
                event_attendees = sum(r.number_of_attendees or 0 for r in event_reports)

                event_details.append({
                    "event_id": event.id,
                    "event_name": event.name,
                    "event_date": event.event_date.isoformat() if event.event_date else None,
                    "location": event.location,
                    "tickets_sold": event_tickets,
                    "revenue": event_revenue,
                    "attendees": event_attendees,
                    "report_count": len(event_reports)
                })

        return {
            "total_tickets_sold": total_tickets,
            "total_revenue": total_revenue,
            "total_attendees": total_attendees,
            "event_count": len(unique_events),
            "report_count": len(reports),
            "events": event_details,
            **currency_info
        }

    @staticmethod
    def generate_organizer_summary_report(organizer_id: int, config: AdminReportConfig) -> Dict[str, Any]:
        """Generate a comprehensive summary report for an organizer"""
        try:
            # Get organizer information
            organizer = AdminReportService.get_organizer_by_id(organizer_id)
            if not organizer:
                return {"error": "Organizer not found", "status": 404}

            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=config.date_range_days)

            # Get reports for the organizer
            reports = AdminReportService.get_reports_by_organizer(
                organizer_id, start_date, end_date
            )

            # Get events for additional context
            events = AdminReportService.get_events_by_organizer(
                organizer_id, start_date, end_date
            )

            # Aggregate the reports with currency conversion settings
            aggregated_data = AdminReportService.aggregate_organizer_reports(
                reports, config.target_currency_id, config.use_latest_rates
            )

            # Prepare the summary report
            summary_report = {
                "organizer_info": {
                    "organizer_id": organizer.id,
                    "organizer_name": organizer.full_name,
                    "email": organizer.email,
                    "phone": organizer.phone_number
                },
                "report_period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days": config.date_range_days
                },
                "currency_settings": {
                    "target_currency_id": config.target_currency_id,
                    "use_latest_rates": config.use_latest_rates
                },
                "summary": aggregated_data,
                "detailed_reports": [
                    report.as_dict_with_currency(config.target_currency_id, config.use_latest_rates) for report in reports
                ],
                "generation_timestamp": datetime.utcnow().isoformat()
            }

            return summary_report

        except Exception as e:
            logger.error(f"Error generating organizer summary report: {e}")
            return {"error": "Failed to generate report", "status": 500}

    @staticmethod
    def generate_event_admin_report(event_id: int, organizer_id: int, config: AdminReportConfig) -> Dict[str, Any]:
        """Generate an admin report for a specific event"""
        try:
            # Validate event exists and belongs to organizer
            event = Event.query.join(Organizer).filter(
                Event.id == event_id,
                Organizer.user_id == organizer_id
            ).first()

            if not event:
                return {"error": "Event not found or doesn't belong to organizer", "status": 404}

            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=config.date_range_days)

            # Get existing reports for this event
            existing_reports = AdminReportService.get_reports_by_event(
                event_id, start_date, end_date
            )

            # Generate fresh report data with currency conversion
            fresh_report_data = None
            try:
                # Calculate fresh aggregated data from existing reports
                if existing_reports:
                    fresh_aggregated = AdminReportService.aggregate_organizer_reports(
                        existing_reports, config.target_currency_id, config.use_latest_rates
                    )

                    fresh_report_data = {
                        "event_summary": fresh_aggregated,
                        "report_timestamp": datetime.utcnow().isoformat(),
                        "currency_conversion": {
                            "target_currency_id": config.target_currency_id,
                            "use_latest_rates": config.use_latest_rates
                        }
                    }

                    # Get target currency info for display
                    if config.target_currency_id:
                        target_currency = Currency.query.get(config.target_currency_id)
                        if target_currency:
                            fresh_report_data["currency_info"] = {
                                "currency": target_currency.code.value,
                                "currency_symbol": target_currency.symbol
                            }

            except Exception as e:
                logger.warning(f"Could not generate fresh report data: {e}")
                fresh_report_data = {"error": "Fresh report generation failed", "details": str(e)}

            # Prepare the admin report
            admin_report = {
                "event_info": {
                    "event_id": event.id,
                    "event_name": event.name,
                    "event_date": event.event_date.isoformat() if event.event_date else None,
                    "location": event.location,
                    "organizer_id": organizer_id,
                    "organizer_name": event.organizer.user.full_name if event.organizer and event.organizer.user else "N/A"
                },
                "report_period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days": config.date_range_days
                },
                "currency_settings": {
                    "target_currency_id": config.target_currency_id,
                    "use_latest_rates": config.use_latest_rates
                },
                "existing_reports": [
                    report.as_dict_with_currency(config.target_currency_id, config.use_latest_rates) for report in existing_reports
                ],
                "fresh_report_data": fresh_report_data,
                "summary": {
                    "total_stored_reports": len(existing_reports),
                    "latest_report_date": existing_reports[0].timestamp.isoformat() if existing_reports else None
                },
                "generation_timestamp": datetime.utcnow().isoformat()
            }

            return admin_report

        except Exception as e:
            logger.error(f"Error generating event admin report: {e}")
            return {"error": "Failed to generate event report", "status": 500}

    @staticmethod
    def send_report_email(report_data: Dict[str, Any], recipient_email: str) -> bool:
        """Send report via email with enhanced formatting"""
        try:
            event_name = report_data.get('event_name', 'Unknown Event')
            currency_symbol = report_data.get('currency_symbol', '$')

            subject = f"Event Analytics Report - {event_name}"

            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .header {{ background: linear-gradient(135deg, #2E86AB, #A23B72); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 30px; background: #f9f9f9; }}
                    .summary-box {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .metric {{ display: inline-block; margin: 10px 20px; text-align: center; }}
                    .metric-value {{ font-size: 24px; font-weight: bold; color: #2E86AB; }}
                    .metric-label {{ font-size: 14px; color: #666; }}
                    .insights {{ background: #e8f4fd; padding: 15px; border-left: 4px solid #2E86AB; margin: 20px 0; }}
                    .footer {{ background: #333; color: white; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 8px 8px; }}
                    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                    th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                    th {{ background-color: #2E86AB; color: white; }}
                    .attachment-note {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 4px; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📊 Event Report</h1>
                    <h2>{event_name}</h2>
                    <p>Report Period: {report_data.get('filter_start_date', 'N/A')} to {report_data.get('filter_end_date', 'N/A')}</p>
                </div>

                <div class="content">
                    <div class="summary-box">
                        <h3>📈 Executive Summary</h3>
                        <div class="metric">
                            <div class="metric-value">{report_data.get('total_tickets_sold', 0)}</div>
                            <div class="metric-label">Tickets Sold</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{currency_symbol}{report_data.get('total_revenue', 0):,.2f}</div>
                            <div class="metric-label">Total Revenue</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{report_data.get('number_of_attendees', 0)}</div>
                            <div class="metric-label">Attendees</div>
                        </div>
            """

            if report_data.get('total_tickets_sold', 0) > 0:
                attendance_rate = (report_data.get('number_of_attendees', 0) /
                                 report_data.get('total_tickets_sold', 1) * 100)
                html_body += f"""
                        <div class="metric">
                            <div class="metric-value">{attendance_rate:.1f}%</div>
                            <div class="metric-label">Attendance Rate</div>
                        </div>
                """

            html_body += """
                    </div>
            """

            if report_data.get('tickets_sold_by_type'):
                html_body += """
                    <div class="summary-box">
                        <h3>🎫 Ticket Sales Breakdown</h3>
                        <table>
                            <tr><th>Ticket Type</th><th>Quantity</th><th>Revenue</th></tr>
                """
                for ticket_type in report_data['tickets_sold_by_type'].keys():
                    quantity = report_data['tickets_sold_by_type'].get(ticket_type, 0)
                    revenue = report_data.get('revenue_by_ticket_type', {}).get(ticket_type, 0)
                    html_body += f"<tr><td>{ticket_type}</td><td>{quantity}</td><td>{currency_symbol}{revenue:,.2f}</td></tr>"

                html_body += """
                        </table>
                    </div>
                """

            html_body += f"""
                    <div class="insights">
                        <h3>💡 Key Insights</h3>
                        <ul>
            """

            if report_data.get('total_tickets_sold', 0) > 0:
                attendance_rate = (report_data.get('number_of_attendees', 0) /
                                 report_data.get('total_tickets_sold', 1) * 100)
                if attendance_rate > 90:
                    html_body += "<li>Excellent attendance rate! Most ticket holders attended the event.</li>"
                elif attendance_rate > 70:
                    html_body += "<li>Good attendance rate with room for improvement in no-show reduction.</li>"
                else:
                    html_body += "<li>Low attendance rate suggests potential areas for improvement.</li>"

            if report_data.get('revenue_by_ticket_type'):
                max_revenue_type = max(report_data['revenue_by_ticket_type'].items(), key=lambda x: x[1])[0]
                html_body += f"<li>{max_revenue_type} tickets generated the highest revenue for this event.</li>"

            html_body += """
                        </ul>
                    </div>

                    <div class="attachment-note">
                        <h3>📎 Attachments</h3>
                        <p><strong>Detailed PDF Report:</strong> Complete analytics with charts and visualizations</p>
                        <p><strong>CSV Data Export:</strong> Raw data for further analysis and processing</p>
                    </div>
                </div>

                <div class="footer">
                    <p>This report was automatically generated by the Event Management System</p>
                    <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            </body>
            </html>
            """

            success = send_email_with_attachment(
                to_email=recipient_email,
                subject=subject,
                html_body=html_body,
                attachments=[]  # Add attachments if needed
            )
            return success
        except Exception as e:
            logger.error(f"Error sending report email: {e}")
            return False

class AdminReportResource(Resource):
    """Admin report API resource"""

    @jwt_required()
    def get(self):
        """Get admin reports with various filtering options"""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        # Parse query parameters
        organizer_id = request.args.get('organizer_id', type=int)
        event_id = request.args.get('event_id', type=int)
        format_type = request.args.get('format', 'json')
        days = request.args.get('days', 30, type=int)
        target_currency_id = request.args.get('currency_id', type=int)
        include_charts = request.args.get('include_charts', 'true').lower() == 'true'
        use_latest_rates = request.args.get('use_latest_rates', 'true').lower() == 'true'
        send_email = request.args.get('send_email', 'false').lower() == 'true'
        recipient_email = request.args.get('recipient_email', user.email)

        # Create configuration
        config = AdminReportConfig(
            include_charts=include_charts,
            include_email=send_email,
            format_type=format_type,
            target_currency_id=target_currency_id,
            date_range_days=days,
            use_latest_rates=use_latest_rates
        )

        try:
            if organizer_id and event_id:
                # Get specific event report for organizer
                report_data = AdminReportService.generate_event_admin_report(
                    event_id, organizer_id, config
                )
            elif organizer_id:
                # Get organizer summary report
                report_data = AdminReportService.generate_organizer_summary_report(
                    organizer_id, config
                )
            else:
                return {"message": "Please specify organizer_id or both organizer_id and event_id"}, 400

            # Handle errors
            if "error" in report_data:
                return {"message": report_data["error"]}, report_data.get("status", 500)

            # Handle different format types
            if format_type.lower() == 'csv':
                csv_content = CSVExporter.generate_csv_report(report_data)
                response = Response(
                    csv_content,
                    mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=admin_report_{organizer_id}_{datetime.now().strftime("%Y%m%d")}.csv'}
                )
            elif format_type.lower() == 'pdf':
                # Generate PDF using existing PDF generator
                try:
                    pdf_buffer = PDFReportGenerator.generate_pdf_report(report_data, config)
                    response = send_file(
                        pdf_buffer,
                        mimetype='application/pdf',
                        as_attachment=True,
                        download_name=f'admin_report_{organizer_id}_{datetime.now().strftime("%Y%m%d")}.pdf'
                    )
                except Exception as e:
                    logger.error(f"PDF generation failed: {e}")
                    return {"message": "PDF generation failed", "error": str(e)}, 500
            else:
                # Return JSON by default
                response = jsonify(report_data)

            # Send email if requested
            if send_email:
                email_success = AdminReportService.send_report_email(report_data, recipient_email)
                if not email_success:
                    logger.error("Failed to send email")

            return response

        except Exception as e:
            logger.error(f"Admin report generation failed: {e}")
            return {"message": "Report generation failed", "error": str(e)}, 500

class AdminOrganizerListResource(Resource):
    """Resource for listing all organizers for admin"""

    @jwt_required()
    def get(self):
        """Get list of all organizers with basic info"""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        try:
            # Get all organizers with their basic info and event counts
            organizers = db.session.query(
                User.id,
                User.full_name,
                User.email,
                User.phone_number,
                func.count(Event.id).label('event_count'),
                func.count(Report.id).label('report_count')
            ).select_from(User)\
            .outerjoin(Organizer, User.id == Organizer.user_id)\
            .outerjoin(Event, Organizer.id == Event.organizer_id)\
            .outerjoin(Report, User.id == Report.organizer_id)\
            .filter(User.role == 'ORGANIZER')\
            .group_by(User.id, User.full_name, User.email, User.phone_number)\
            .all()

            organizer_list = []
            for org in organizers:
                organizer_list.append({
                    "organizer_id": org.id,
                    "name": org.full_name,
                    "email": org.email,
                    "phone": org.phone_number,
                    "event_count": org.event_count,
                    "report_count": org.report_count
                })

            return {
                "organizers": organizer_list,
                "total_count": len(organizer_list)
            }

        except Exception as e:
            logger.error(f"Error fetching organizer list: {e}")
            return {"message": "Failed to fetch organizer list", "error": str(e)}, 500

class AdminEventListResource(Resource):
    """Resource for listing events by organizer for admin"""

    @jwt_required()
    def get(self, organizer_id):
        """Get list of events for a specific organizer"""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        try:
            # Get events for the organizer with report counts
            events = db.session.query(
                Event.id,
                Event.name,
                Event.event_date,
                Event.location,
                Event.status,
                func.count(Report.id).label('report_count')
            ).select_from(Event)\
            .join(Organizer, Event.organizer_id == Organizer.id)\
            .outerjoin(Report, Event.id == Report.event_id)\
            .filter(Organizer.user_id == organizer_id)\
            .group_by(Event.id, Event.name, Event.event_date, Event.location, Event.status)\
            .order_by(Event.event_date.desc())\
            .all()

            event_list = []
            for event in events:
                event_list.append({
                    "event_id": event.id,
                    "name": event.name,
                    "event_date": event.event_date.isoformat() if event.event_date else None,
                    "location": event.location,
                    "status": event.status.value if event.status else None,
                    "report_count": event.report_count
                })

            return {
                "organizer_id": organizer_id,
                "events": event_list,
                "total_count": len(event_list)
            }

        except Exception as e:
            logger.error(f"Error fetching event list for organizer {organizer_id}: {e}")
            return {"message": "Failed to fetch event list", "error": str(e)}, 500

def register_admin_report_resources(api):
    """Register admin report resources with the Flask-RESTful API"""
    api.add_resource(AdminReportResource, '/admin/reports')
    api.add_resource(AdminOrganizerListResource, '/admin/organizers')
    api.add_resource(AdminEventListResource, '/admin/organizers/<int:organizer_id>/events')
