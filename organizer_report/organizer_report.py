from flask import request, jsonify, send_file
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Event, User, Report, Organizer, Currency, UserRole, Ticket, Transaction

from .services import ReportService, DatabaseQueryService
from .utils import DateUtils, DateValidator, AuthorizationMixin
from .report_generators import ReportConfig
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import os
import tempfile

logger = logging.getLogger(__name__)

class GenerateReportResource(Resource, AuthorizationMixin):
    @jwt_required()
    def post(self):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                return {'error': 'User not found'}, 404
            data = request.get_json()
            event_id = data.get('event_id')
            start_date_str = data.get('start_date')
            end_date_str = data.get('end_date')
            ticket_type_id = data.get('ticket_type_id')
            target_currency_id = data.get('target_currency_id')
            send_email = data.get('send_email', False)
            recipient_email = data.get('recipient_email', current_user.email)
            if not event_id:
                return {'error': 'Event ID is required'}, 400
            event = Event.query.get(event_id)
            if not event:
                return {'error': 'Event not found'}, 404
            organizer = Organizer.query.filter_by(user_id=current_user_id).first()
            if not organizer or organizer.id != event.organizer_id:
                if not current_user.role == UserRole.ADMIN:
                    return {'error': 'Unauthorized to generate report for this event'}, 403
            start_date = DateUtils.parse_date_param(start_date_str, 'start_date') if start_date_str else None
            end_date = DateUtils.parse_date_param(end_date_str, 'end_date') if end_date_str else None
            if not start_date:
                start_date = event.timestamp if hasattr(event, 'timestamp') else datetime.now() - timedelta(days=30)
            if not end_date:
                end_date = datetime.now()
            end_date = DateUtils.adjust_end_date(end_date)
            target_currency = Currency.query.get(target_currency_id) if target_currency_id else None
            if not target_currency:
                return {'error': 'Target currency not found or invalid'}, 400
            target_currency_code = target_currency.code.value
            config = ReportConfig(
                include_charts=True,
                include_email=send_email,
                chart_dpi=300,
                chart_style='seaborn-v0_8'
            )
            report_service = ReportService(config)
            result = report_service.generate_complete_report(
                event_id=event_id,
                organizer_id=current_user_id,
                start_date=start_date,
                end_date=end_date,
                ticket_type_id=ticket_type_id,
                send_email=send_email,
                recipient_email=recipient_email
            )
            if result['success']:
                response_data = {
                    'message': 'Report generated successfully',
                    'report_id': result.get('database_id'),
                    'report_data': result['report_data'],
                    'email_sent': result['email_sent']
                }
                total_revenue = result['report_data'].get('total_revenue')
                base_currency = result['report_data'].get('currency', 'USD')
                from currency_routes import convert_currency
                converted_value, conversion_rate = convert_currency(
                    amount=total_revenue,
                    from_currency=base_currency,
                    to_currency=target_currency_code
                )
                response_data['currency_conversion'] = {
                    'original_amount': float(total_revenue),
                    'original_currency': base_currency,
                    'converted_amount': float(converted_value),
                    'converted_currency': target_currency_code,
                    'conversion_rate': float(conversion_rate)
                }
                if result.get('pdf_path'):
                    response_data['pdf_available'] = True
                if result.get('csv_path'):
                    response_data['csv_available'] = True
                return response_data, 200
            else:
                return {'error': result.get('error', 'Failed to generate report')}, 500
        except Exception as e:
            logger.error(f"Error in GenerateReportResource: {e}")
            return {'error': 'Internal server error'}, 500

class GetReportsResource(Resource, AuthorizationMixin):
    @jwt_required()
    def get(self):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                return {'error': 'User not found'}, 404
            event_id = request.args.get('event_id', type=int)
            scope = request.args.get('scope')
            limit = request.args.get('limit', 10, type=int)
            offset = request.args.get('offset', 0, type=int)
            target_currency_id = request.args.get('target_currency_id', type=int)
            query = Report.query.filter_by(organizer_id=current_user_id)
            if event_id:
                query = query.filter_by(event_id=event_id)
            if scope:
                query = query.filter_by(report_scope=scope)
            query = query.order_by(Report.timestamp.desc())
            total_count = query.count()
            reports = query.offset(offset).limit(limit).all()
            reports_data = []
            for report in reports:
                report_dict = report.as_dict(target_currency_id=target_currency_id)
                reports_data.append(report_dict)
            return {
                'reports': reports_data,
                'total_count': total_count,
                'limit': limit,
                'offset': offset
            }, 200
        except Exception as e:
            logger.error(f"Error in GetReportsResource: {e}")
            return {'error': 'Internal server error'}, 500

class GetReportResource(Resource, AuthorizationMixin):
    @jwt_required()
    def get(self, report_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                return {'error': 'User not found'}, 404
            report = Report.query.get(report_id)
            if not report:
                return {'error': 'Report not found'}, 404
            if not (report.organizer_id == current_user_id or current_user.role == UserRole.ADMIN):
                return {'error': 'Unauthorized to access this report'}, 403
            target_currency_id = request.args.get('target_currency_id', type=int)
            return {
                'report': report.as_dict(target_currency_id=target_currency_id)
            }, 200
        except Exception as e:
            logger.error(f"Error in GetReportResource: {e}")
            return {'error': 'Internal server error'}, 500

class ExportReportResource(Resource):
    @jwt_required()
    def get(self, report_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"User {current_user_id} not found")
                return {'error': 'User not found'}, 404
            report = Report.query.get(report_id)
            if not report:
                logger.warning(f"Report {report_id} not found")
                return {'error': 'Report not found'}, 404
            is_authorized = False
            if report.organizer_id == current_user_id:
                is_authorized = True
                logger.info(f"User {current_user_id} is the direct organizer of report {report_id}")
            elif hasattr(current_user, 'role') and current_user.role and current_user.role.value.upper() == 'ADMIN':
                is_authorized = True
                logger.info(f"User {current_user_id} is admin, allowing access to report {report_id}")
            elif hasattr(current_user, 'organizer_profile') and current_user.organizer_profile:
                if hasattr(report, 'event') and report.event:
                    if report.event.organizer_id == current_user.organizer_profile.id:
                        is_authorized = True
                        logger.info(f"User {current_user_id} owns the event associated with report {report_id}")
            if not is_authorized:
                logger.warning(f"User {current_user_id} not authorized to access report {report_id}")
                return {'error': 'Unauthorized to export this report'}, 403
            format_type = request.args.get('format', 'pdf').lower()
            if format_type == 'pdf':
                file_path = self._generate_pdf_report(report)
                mime_type = 'application/pdf'
                filename = f"report_{report.id}.pdf"
            elif format_type == 'csv':
                file_path = self._generate_csv_report(report)
                mime_type = 'text/csv'
                filename = f"report_{report.id}.csv"
                filename = f"report_{report.id}.csv"
            else:
                return {'error': 'Unsupported format. Use "pdf" or "csv".'}, 400
            if not file_path or not os.path.exists(file_path):
                logger.error(f"Failed to generate or find report file: {file_path}")
                return {'error': 'Failed to generate report file'}, 500
            logger.info(f"Successfully generated report file: {file_path}")
            return send_file(
                file_path,
                mimetype=mime_type,
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            logger.error(f"Error in ExportReportResource: {str(e)}", exc_info=True)
            return {'error': 'Internal server error'}, 500
    def _generate_pdf_report(self, report):
        try:
            temp_dir = tempfile.gettempdir()
            pdf_path = os.path.join(temp_dir, f"report_{report.id}.pdf")
            with open(pdf_path, 'w') as f:
                f.write("PDF Report Content - Replace with actual PDF generation")
            logger.info(f"PDF report generated at: {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"Error generating PDF report: {str(e)}", exc_info=True)
            return None

    def _generate_csv_report(self, report):
        try:
            temp_dir = tempfile.gettempdir()
            csv_path = os.path.join(temp_dir, f"report_{report.id}.csv")
            with open(csv_path, 'w') as f:
                f.write("CSV Report Content - Replace with actual CSV generation")
            logger.info(f"CSV report generated at: {csv_path}")
            return csv_path
        except Exception as e:
            logger.error(f"Error generating CSV report: {str(e)}", exc_info=True)
            return None
            return None

class OrganizerSummaryReportResource(Resource, AuthorizationMixin):
    @jwt_required()
    def get(self):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            return {"message": "Only organizers can access summary reports"}, 403
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found for this user"}, 404
        summary_data = self._calculate_organizer_summary(organizer)
        return summary_data, 200

    def _calculate_organizer_summary(self, organizer: Organizer) -> Dict[str, Any]:
        total_tickets_sold = 0
        total_revenue = 0.0
        events_summary = []
        organizer_events = Event.query.filter_by(organizer_id=organizer.id).all()
        for event in organizer_events:
            event_tickets = Ticket.query.filter_by(event_id=event.id).count()
            event_revenue_query = (db.session.query(db.func.sum(Transaction.amount_paid))
                                  .join(Ticket, Ticket.transaction_id == Transaction.id)
                                  .filter(Ticket.event_id == event.id,
                                           Transaction.payment_status == 'COMPLETED')
                                  .scalar())
            event_revenue = float(event_revenue_query) if event_revenue_query else 0.0
            total_tickets_sold += event_tickets
            total_revenue += event_revenue
            events_summary.append({
                "event_id": event.id,
                "event_name": event.name,
                "date": event.date.strftime('%Y-%m-%d') if event.date else "N/A",
                "location": event.location,
                "tickets_sold": event_tickets,
                "revenue": event_revenue
            })
        organizer_name = (organizer.user.full_name
                        if hasattr(organizer.user, 'full_name') and organizer.user.full_name
                        else organizer.user.email)
        return {
            "organizer_id": organizer.id,
            "organizer_name": organizer_name,
            "total_tickets_sold_across_all_events": total_tickets_sold,
            "total_revenue_across_all_events": f"{total_revenue:.2f}",
            "events_summary": events_summary
        }

class EventReportsResource(Resource):
    @jwt_required()
    def get(self, event_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"User {current_user_id} not found")
                return {'error': 'User not found'}, 404
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            start_date, end_date, error = DateValidator.validate_date_range(start_date_str, end_date_str)
            if error:
                logger.warning(f"Invalid date range: {error}")
                return error, error.get('status', 400)
            event = Event.query.get(event_id)
            if not event:
                logger.warning(f"Event {event_id} not found")
                return {'error': 'Event not found'}, 404
            if not AuthorizationMixin.check_event_ownership(event, current_user):
                logger.warning(f"User {current_user_id} not authorized for event {event_id}")
                return {'error': 'Unauthorized to access reports for this event'}, 403
            query = Report.query.filter_by(event_id=event_id)
            if start_date and end_date:
                query = query.filter(Report.report_date.between(start_date, end_date))
            reports = query.all()
            logger.info(f"Found {len(reports)} reports for event {event_id} from {start_date} to {end_date}")
            reports_data = [
                {
                    'report_id': r.id,
                    'event_id': r.event_id,
                    'total_tickets_sold': r.total_tickets_sold,
                    'total_revenue': float(r.total_revenue),
                    'number_of_attendees': r.number_of_attendees,
                    'report_date': r.report_date.isoformat()
                }
                for r in reports
            ]
            return {
                'event_id': event_id,
                'reports': reports_data
            }, 200
        except Exception as e:
            logger.exception(f"Error fetching event reports for event {event_id}: {e}")
            return {'error': 'Internal server error'}, 500


class ReportResourceRegistry:
    """Registry for report-related API resources"""
    @staticmethod
    def register_organizer_report_resources(api):
        """Register all report resources with the API"""
        api.add_resource(GenerateReportResource, '/reports/generate')
        api.add_resource(GetReportsResource, '/reports')
        api.add_resource(GetReportResource, '/reports/<int:report_id>')
        api.add_resource(ExportReportResource, '/reports/<int:report_id>/export')
        api.add_resource(OrganizerSummaryReportResource, '/reports/organizer/summary')
        api.add_resource(EventReportsResource, '/reports/events/<int:event_id>')
