from flask import request, jsonify, send_file, current_app, after_this_request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Event, User, Report, Organizer, Currency, UserRole, Ticket, Transaction
from .services import ReportService, DatabaseQueryService
from .utils import DateUtils, DateValidator, AuthorizationMixin
from .report_generators import ReportConfig, PDFReportGenerator, CSVReportGenerator, ChartGenerator
from currency_routes import convert_ksh_to_target_currency

from reportlab.lib.pagesizes import A4
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import os
import tempfile
import threading
from decimal import Decimal

logger = logging.getLogger(__name__)

class GenerateReportResource(Resource):
    """
    API resource for generating event reports.
    Handles report configuration, data retrieval, currency conversion,
    and triggers background email sending without attachments, providing download links.
    """
    @jwt_required()
    def post(self):
        try:
            start_time = datetime.now()
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"GenerateReportResource: User with ID {current_user_id} not found.")
                return {'error': 'User not found'}, 404

            data = request.get_json()
            event_id = data.get('event_id')
            start_date_str = data.get('start_date')
            end_date_str = data.get('end_date')
            specific_date_str = data.get('specific_date')
            ticket_type_id = data.get('ticket_type_id')
            target_currency_code = data.get('target_currency')
            send_email = data.get('send_email', False)
            recipient_email = data.get('recipient_email', current_user.email)

            if not event_id:
                logger.warning("GenerateReportResource: Event ID is required but missing.")
                return {'error': 'Event ID is required'}, 400

            event = Event.query.get(event_id)
            if not event:
                logger.warning(f"GenerateReportResource: Event with ID {event_id} not found.")
                return {'error': 'Event not found'}, 404

            organizer = Organizer.query.filter_by(user_id=current_user_id).first()
            if not organizer or organizer.id != event.organizer_id:
                if current_user.role != UserRole.ADMIN:
                    logger.warning(f"GenerateReportResource: User {current_user_id} unauthorized to generate report for event {event_id}.")
                    return {'error': 'Unauthorized to generate report for this event'}, 403

            if specific_date_str:
                try:
                    specific_date = DateUtils.parse_date_param(specific_date_str, 'specific_date')
                    start_date = specific_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = specific_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                except Exception as e:
                    logger.error(f"GenerateReportResource: Error parsing specific_date '{specific_date_str}': {e}")
                    return {'error': 'Invalid specific date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS'}, 400
            else:
                start_date = DateUtils.parse_date_param(start_date_str, 'start_date') if start_date_str else None
                end_date = DateUtils.parse_date_param(end_date_str, 'end_date') if end_date_str else None
                if not start_date:
                    start_date = event.timestamp if hasattr(event, 'timestamp') and event.timestamp else datetime.now() - timedelta(days=30)
                if not end_date:
                    end_date = datetime.now()
                end_date = DateUtils.adjust_end_date(end_date)

            if target_currency_code:
                try:
                    from model import CurrencyCode
                    target_currency = Currency.query.filter_by(
                        code=CurrencyCode(target_currency_code),
                        is_active=True
                    ).first()

                    if not target_currency:
                        logger.warning(f"GenerateReportResource: Target currency '{target_currency_code}' not found or not active.")
                        return {'error': f'Target currency "{target_currency_code}" not found or not active'}, 400
                except ValueError:
                    logger.warning(f"GenerateReportResource: Invalid target currency code '{target_currency_code}'.")
                    return {'error': f'Invalid target currency code "{target_currency_code}"'}, 400
            else:
                target_currency_code = 'KES'
                target_currency = Currency.query.filter_by(
                    code=CurrencyCode('KES'),
                    is_active=True
                ).first()

            config = ReportConfig(include_email=send_email)
            report_service = ReportService(config)

            result = report_service.generate_complete_report(
                session=db.session,
                event_id=event_id,
                organizer_id=current_user_id,
                start_date=start_date,
                end_date=end_date,
                ticket_type_id=ticket_type_id,
                target_currency_code=target_currency_code,
                send_email=False,
                recipient_email=recipient_email
            )

            if not result['success']:
                logger.error(f"GenerateReportResource: Failed to generate report data for event {event_id}: {result.get('error')}")
                return {'error': result.get('error', 'Failed to generate report')}, 500

            report_id = result.get('database_id')
            if not report_id:
                logger.error(f"GenerateReportResource: Report data generated successfully but no database_id returned for event {event_id}.")
                return {'error': 'Report generated but could not retrieve ID'}, 500

            total_revenue_ksh = result['report_data'].get('total_revenue', 0)
            base_currency = result['report_data'].get('currency', 'KES')

            converted_amount = total_revenue_ksh
            ksh_to_usd_rate = Decimal('1')
            usd_to_target_rate = Decimal('1')
            overall_conversion_rate = Decimal('1')

            try:
                if target_currency_code != 'KES' and total_revenue_ksh > 0:
                    logger.info(f"GenerateReportResource: Converting {total_revenue_ksh} KSH to {target_currency_code}")
                    converted_amount, ksh_to_usd_rate, usd_to_target_rate = convert_ksh_to_target_currency(
                        total_revenue_ksh,
                        target_currency_code
                    )
                    overall_conversion_rate = ksh_to_usd_rate * usd_to_target_rate
                    logger.info(f"GenerateReportResource: Conversion successful - {total_revenue_ksh} KSH = {converted_amount} {target_currency_code}")
                else:
                    converted_amount = Decimal(str(total_revenue_ksh))
            except Exception as e:
                logger.warning(f"GenerateReportResource: Currency conversion failed for {target_currency_code}: {str(e)}")
                converted_amount = Decimal(str(total_revenue_ksh))
                target_currency_code = 'KES'

            base_url = request.url_root.rstrip('/')
            pdf_download_url = f"{base_url}/api/v1/reports/{report_id}/export?format=pdf&currency={target_currency_code}"
            csv_download_url = f"{base_url}/api/v1/reports/{report_id}/export?format=csv&currency={target_currency_code}"

            response_data = {
                'message': 'Report generation initiated. You can download the report using the provided links.',
                'report_id': report_id,
                'report_data_summary': {
                    'total_tickets_sold': result['report_data'].get('total_tickets_sold'),
                    'total_revenue_original': float(total_revenue_ksh),
                    'total_revenue_converted': float(converted_amount.quantize(Decimal('0.01'))),
                    'number_of_attendees': result['report_data'].get('number_of_attendees'),
                    'original_currency': 'KES',
                    'target_currency': target_currency_code,
                    'currency_symbol': target_currency.symbol if target_currency else 'KSh'
                },
                'report_period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'is_single_day': bool(specific_date_str)
                },
                'currency_conversion': {
                    'original_amount': float(total_revenue_ksh),
                    'original_currency': 'KES',
                    'converted_amount': float(converted_amount.quantize(Decimal('0.01'))),
                    'converted_currency': target_currency_code,
                    'conversion_steps': {
                        'ksh_to_usd_rate': float(ksh_to_usd_rate),
                        'usd_to_target_rate': float(usd_to_target_rate),
                        'overall_conversion_rate': float(overall_conversion_rate)
                    },
                    'conversion_successful': target_currency_code != 'KES' or total_revenue_ksh == 0
                },
                'download_links': {
                    'pdf_url': pdf_download_url,
                    'csv_url': csv_download_url
                },
                'email_sent': False
            }

            if send_email:
                def async_send_email():
                    try:
                        from app import app
                        with app.app_context():
                            report_data = {
                                'event_name': event.name,
                                'currency_symbol': target_currency.symbol if target_currency else 'KSh',
                                'total_revenue': float(converted_amount.quantize(Decimal('0.01'))),
                                'target_currency': target_currency_code,
                                'report_period_start': start_date.strftime('%Y-%m-%d'),
                                'report_period_end': end_date.strftime('%Y-%m-%d'),
                                'conversion_rate': float(overall_conversion_rate) if overall_conversion_rate != 1 else None
                            }
                            report_service.send_report_email(
                                report_data=report_data,
                                pdf_path='',
                                csv_path='',
                                recipient_email=recipient_email
                            )
                            logger.info(f"GenerateReportResource: Background email sent to {recipient_email} for report {report_id}")
                    except Exception as e:
                        logger.error(f"GenerateReportResource: Email sending failed for report {report_id}: {e}", exc_info=True)

                threading.Thread(target=async_send_email).start()
                response_data['email_sent'] = True

            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"GenerateReportResource: Report generation request processed in {duration:.2f} seconds for report {report_id}")
            return response_data, 200
        except Exception as e:
            logger.error(f"GenerateReportResource: Unhandled error: {e}", exc_info=True)
            return {'error': 'Internal server error'}, 500

# The rest of your code remains unchanged...


class GetReportsResource(Resource, AuthorizationMixin):
    """
    API resource for retrieving a list of generated reports.
    Includes download URLs for PDF and CSV for each report.
    Supports date filtering, specific date queries, and flexible limiting.
    """
    @jwt_required()
    def get(self):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"GetReportsResource: User with ID {current_user_id} not found.")
                return {'error': 'User not found'}, 404

            # Extract query parameters
            event_id = request.args.get('event_id', type=int)
            scope = request.args.get('scope')
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            specific_date_str = request.args.get('specific_date')
            limit_str = request.args.get('limit')
            get_all = request.args.get('get_all', 'false').lower() == 'true'
            offset = request.args.get('offset', 0, type=int)
            target_currency_id = request.args.get('target_currency_id', type=int)

            # Handle date filtering
            start_date = None
            end_date = None
            if specific_date_str:
                try:
                    specific_date = DateUtils.parse_date_param(specific_date_str, 'specific_date')
                    start_date = specific_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = specific_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                except Exception as e:
                    logger.error(f"GetReportsResource: Error parsing specific_date '{specific_date_str}': {e}")
                    return {'error': 'Invalid specific date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS'}, 400
            elif start_date_str or end_date_str:
                start_date, end_date, error = DateValidator.validate_date_range(start_date_str, end_date_str)
                if error:
                    logger.warning(f"GetReportsResource: Invalid date range provided: {error}")
                    return error, error.get('status', 400)

            # Handle limit parameter
            limit = None
            if not get_all:
                if limit_str:
                    try:
                        limit = int(limit_str)
                        if limit <= 0:
                            logger.warning(f"GetReportsResource: Invalid limit value: {limit_str}")
                            return {'error': 'Limit must be a positive integer'}, 400
                    except ValueError:
                        logger.warning(f"GetReportsResource: Invalid limit format: {limit_str}")
                        return {'error': 'Limit must be a valid integer'}, 400
                else:
                    limit = 10  # Default to 10 most recent reports

            # Build base query based on user role
            if current_user.role == UserRole.ADMIN:
                query = Report.query
            else:
                organizer = Organizer.query.filter_by(user_id=current_user_id).first()
                if not organizer:
                    logger.warning(f"GetReportsResource: Organizer profile not found for user {current_user_id}.")
                    return {'error': 'Organizer profile not found for this user'}, 403
                query = Report.query.filter_by(organizer_id=organizer.id)

            # Apply event filter
            if event_id:
                event = Event.query.get(event_id)
                if not event:
                    logger.warning(f"GetReportsResource: Event with ID {event_id} not found for filtering reports.")
                    return {'error': 'Event not found'}, 404
                if not (event.organizer_id == (organizer.id if organizer else None) or current_user.role == UserRole.ADMIN):
                    logger.warning(f"GetReportsResource: User {current_user_id} unauthorized to access reports for event {event_id}.")
                    return {'error': 'Unauthorized to access reports for this event'}, 403
                query = query.filter_by(event_id=event_id)

            # Apply scope filter
            if scope:
                query = query.filter_by(report_scope=scope)

            # Apply date filters
            if start_date and end_date:
                query = query.filter(Report.timestamp.between(start_date, end_date))

            # Order by timestamp descending (most recent first)
            query = query.order_by(Report.timestamp.desc())

            # Get total count before applying limit/offset
            total_count = query.count()

            # Apply offset and limit
            if offset:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            reports = query.all()

            # Build response data
            reports_data = []
            base_url = request.url_root.rstrip('/')
            for report in reports:
                report_dict = report.as_dict(target_currency_id=target_currency_id)
                report_dict['pdf_download_url'] = f"{base_url}/api/v1/reports/{report.id}/export?format=pdf"
                report_dict['csv_download_url'] = f"{base_url}/api/v1/reports/{report.id}/export?format=csv"
                reports_data.append(report_dict)

            # Enhanced logging with filter information
            filter_info = []
            if event_id:
                filter_info.append(f"event_id={event_id}")
            if scope:
                filter_info.append(f"scope={scope}")
            if specific_date_str:
                filter_info.append(f"specific_date={specific_date_str}")
            elif start_date_str or end_date_str:
                filter_info.append(f"date_range={start_date_str} to {end_date_str}")
            if limit:
                filter_info.append(f"limit={limit}")
            if offset:
                filter_info.append(f"offset={offset}")

            filters_applied = ", ".join(filter_info) if filter_info else "no filters"
            logger.info(f"GetReportsResource: Retrieved {len(reports_data)} reports for user {current_user_id} with {filters_applied}.")

            response_data = {
                'reports': reports_data,
                'total_count': total_count,
                'total_reports_returned': len(reports_data),
                'limit': limit,
                'offset': offset,
                'is_limited': bool(limit),
                'limit_applied': limit
            }

            # Add query parameters info to response
            query_info = {
                'event_id': event_id,
                'scope': scope,
                'limit': limit,
                'offset': offset,
                'get_all': get_all,
                'target_currency_id': target_currency_id
            }

            if specific_date_str:
                query_info.update({
                    'specific_date': specific_date_str,
                    'is_single_day': True
                })
            elif start_date_str or end_date_str:
                query_info.update({
                    'start_date': start_date_str,
                    'end_date': end_date_str,
                    'is_single_day': False
                })

            response_data['query_info'] = query_info

            return response_data, 200

        except Exception as e:
            logger.error(f"GetReportsResource: Error: {e}", exc_info=True)
            return {'error': 'Internal server error'}, 500


class GetReportResource(Resource, AuthorizationMixin):
    """
    API resource for retrieving a single report by its ID.
    Includes download URLs for PDF and CSV with enhanced response format.
    """
    @jwt_required()
    def get(self, report_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"GetReportResource: User with ID {current_user_id} not found.")
                return {'error': 'User not found'}, 404

            report = Report.query.get(report_id)
            if not report:
                logger.warning(f"GetReportResource: Report with ID {report_id} not found.")
                return {'error': 'Report not found'}, 404

            # Enhanced authorization check
            is_authorized = False
            organizer = None
            if current_user.role == UserRole.ADMIN:
                is_authorized = True
            else:
                organizer = Organizer.query.filter_by(user_id=current_user_id).first()
                if organizer and report.organizer_id == organizer.id:
                    is_authorized = True

            if not is_authorized:
                logger.warning(f"GetReportResource: User {current_user_id} unauthorized to access report {report_id}.")
                return {'error': 'Unauthorized to access this report'}, 403

            # Get target currency for conversion
            target_currency_id = request.args.get('target_currency_id', type=int)
            
            # Build enhanced response
            report_dict = report.as_dict(target_currency_id=target_currency_id)
            base_url = request.url_root.rstrip('/')
            report_dict['pdf_download_url'] = f"{base_url}/api/v1/reports/{report.id}/export?format=pdf"
            report_dict['csv_download_url'] = f"{base_url}/api/v1/reports/{report.id}/export?format=csv"

            # Add metadata about the request
            response_data = {
                'report': report_dict,
                'request_info': {
                    'requested_by_user_id': current_user_id,
                    'requested_by_role': current_user.role.value if current_user.role else None,
                    'target_currency_id': target_currency_id,
                    'request_timestamp': datetime.now().isoformat()
                }
            }

            # Add currency conversion info if applicable
            if target_currency_id and hasattr(report, 'total_revenue'):
                target_currency = Currency.query.get(target_currency_id)
                if target_currency:
                    response_data['currency_conversion'] = {
                        'target_currency_id': target_currency_id,
                        'target_currency_code': target_currency.code.value,
                        'conversion_applied': True
                    }

            logger.info(f"GetReportResource: Retrieved report {report_id} for user {current_user_id} with currency_id {target_currency_id}.")
            return response_data, 200

        except Exception as e:
            logger.error(f"GetReportResource: Error retrieving report {report_id}: {e}", exc_info=True)
            return {'error': 'Internal server error'}, 500

class ExportReportResource(Resource):
    """
    API resource for downloading generated reports (PDF or CSV).
    Generates the report file on demand using the data stored in the Report model.
    """

    @jwt_required()
    def get(self, report_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"ExportReportResource: User {current_user_id} not found.")
                return {'error': 'User not found'}, 404

            report = Report.query.get(report_id)
            if not report:
                logger.warning(f"ExportReportResource: Report {report_id} not found.")
                return {'error': 'Report not found'}, 404

            # Authorization check
            is_authorized = (
                report.organizer_id == current_user_id or
                (hasattr(current_user, 'role') and current_user.role and current_user.role.value.upper() == 'ADMIN') or
                (hasattr(current_user, 'organizer_profile') and report.event and report.event.organizer_id == current_user.organizer_profile.id)
            )

            if not is_authorized:
                logger.warning(f"ExportReportResource: User {current_user_id} not authorized to access report {report_id}.")
                return {'error': 'Unauthorized to export this report'}, 403

            format_type = request.args.get('format', 'pdf').lower()
            report_data = report.report_data
            if not report_data:
                logger.error(f"ExportReportResource: No report_data found for report ID {report_id}.")
                return {'error': 'Report data is missing, cannot generate file.'}, 500

            config = ReportConfig(
                include_charts=True,
                chart_dpi=72,
                chart_style='default',
                pdf_pagesize=A4,
                limit_charts=False
            )

            file_path = None
            mime_type = None
            filename = None

            if format_type == 'pdf':
                chart_paths = []
                try:
                    if config.include_charts and not config.limit_charts:
                        chart_generator = ChartGenerator(config)
                        chart_paths = chart_generator.create_all_charts(report_data)

                    pdf_generator = PDFReportGenerator(config)
                    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf_file:
                        file_path = pdf_generator.generate_pdf(report_data, chart_paths, tmp_pdf_file.name)

                    mime_type = 'application/pdf'
                    filename = f"event_report_{report.id}.pdf"
                    logger.info(f"ExportReportResource: Generated PDF for report {report.id} at {file_path}")
                except Exception as e:
                    logger.error(f"ExportReportResource: Error generating PDF for report {report.id}: {e}", exc_info=True)
                    return {'error': 'Failed to generate PDF report'}, 500
                finally:
                    for c_path in chart_paths:
                        if os.path.exists(c_path):
                            try:
                                os.remove(c_path)
                                logger.debug(f"ExportReportResource: Cleaned up chart file: {c_path}")
                            except Exception as cleanup_error:
                                logger.warning(f"ExportReportResource: Failed to cleanup chart file {c_path}: {cleanup_error}")

            elif format_type == 'csv':
                try:
                    csv_generator = CSVReportGenerator()
                    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp_csv_file:
                        file_path = csv_generator.generate_csv(report_data, tmp_csv_file.name)

                    mime_type = 'text/csv'
                    filename = f"event_report_{report.id}.csv"
                    logger.info(f"ExportReportResource: Generated CSV for report {report.id} at {file_path}")
                except Exception as e:
                    logger.error(f"ExportReportResource: Error generating CSV for report {report.id}: {e}", exc_info=True)
                    return {'error': 'Failed to generate CSV report'}, 500

            else:
                logger.warning(f"ExportReportResource: Unsupported format '{format_type}' requested for report {report_id}.")
                return {'error': 'Unsupported format. Use \"pdf\" or \"csv\".'}, 400

            if not file_path or not os.path.exists(file_path):
                logger.error(f"ExportReportResource: Generated file path is invalid or file does not exist: {file_path}")
                return {'error': 'Failed to generate report file. Please try again.'}, 500

            file_size = os.path.getsize(file_path)
            logger.info(f"ExportReportResource: File size to be sent: {file_size} bytes")

            if file_size == 0:
                logger.error(f"ExportReportResource: Generated file is empty: {file_path}")
                return {'error': 'Report file is empty.'}, 500

            @after_this_request
            def delete_temp_file(response):
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"ExportReportResource: Cleaned up temporary file: {file_path}")
                except Exception as e:
                    logger.error(f"ExportReportResource: Error cleaning up temporary file {file_path}: {e}")
                return response

            response = send_file(
                file_path,
                mimetype=mime_type,
                as_attachment=True,
                download_name=filename
            )
            return response

        except Exception as e:
            logger.error(f"ExportReportResource: Unhandled error: {str(e)}", exc_info=True)
            return {'error': 'Internal server error'}, 500
class OrganizerSummaryReportResource(Resource, AuthorizationMixin):
    """
    API resource for retrieving a summary report for an organizer.
    """
    @jwt_required()
    def get(self):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            logger.warning(f"OrganizerSummaryReportResource: User {user.id} attempted to access summary without organizer access.")
            return {"message": "Only organizers can access summary reports"}, 403

        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            logger.warning(f"OrganizerSummaryReportResource: Organizer profile not found for user {user.id}.")
            return {"message": "Organizer profile not found for this user"}, 404

        summary_data = self._calculate_organizer_summary(organizer)
        logger.info(f"OrganizerSummaryReportResource: Generated summary for organizer {organizer.id}.")
        return summary_data, 200

    def _calculate_organizer_summary(self, organizer: Organizer) -> Dict[str, Any]:
        """
        Calculates the summary data for a given organizer, including total tickets sold,
        total revenue, and a summary of each event.
        """
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
    """
    API resource for retrieving reports specific to a single event.
    """
    @jwt_required()
    def get(self, event_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"EventReportsResource: User {current_user_id} not found.")
                return {'error': 'User not found'}, 404

            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            specific_date_str = request.args.get('specific_date')
            limit_str = request.args.get('limit')
            get_all = request.args.get('get_all', 'false').lower() == 'true'

            # Handle specific date logic similar to GenerateReportResource
            if specific_date_str:
                try:
                    specific_date = DateUtils.parse_date_param(specific_date_str, 'specific_date')
                    start_date = specific_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = specific_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                except Exception as e:
                    logger.error(f"EventReportsResource: Error parsing specific_date '{specific_date_str}': {e}")
                    return {'error': 'Invalid specific date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS'}, 400
            else:
                start_date, end_date, error = DateValidator.validate_date_range(start_date_str, end_date_str)
                if error:
                    logger.warning(f"EventReportsResource: Invalid date range provided: {error}")
                    return error, error.get('status', 400)

            # Handle limit parameter
            limit = None
            if not get_all:
                if limit_str:
                    try:
                        limit = int(limit_str)
                        if limit <= 0:
                            logger.warning(f"EventReportsResource: Invalid limit value: {limit_str}")
                            return {'error': 'Limit must be a positive integer'}, 400
                    except ValueError:
                        logger.warning(f"EventReportsResource: Invalid limit format: {limit_str}")
                        return {'error': 'Limit must be a valid integer'}, 400
                else:
                    limit = 5  # Default to 5 most recent reports

            event = Event.query.get(event_id)
            if not event:
                logger.warning(f"EventReportsResource: Event {event_id} not found.")
                return {'error': 'Event not found'}, 404

            if not AuthorizationMixin.check_event_ownership(event, current_user):
                logger.warning(f"EventReportsResource: User {current_user_id} not authorized for event {event_id}.")
                return {'error': 'Unauthorized to access reports for this event'}, 403

            query = Report.query.filter_by(event_id=event_id)
            if start_date and end_date:
                query = query.filter(Report.report_date.between(start_date, end_date))

            # Order by report_date descending to get most recent first
            query = query.order_by(Report.report_date.desc())

            # Apply limit if specified
            if limit:
                query = query.limit(limit)

            reports = query.all()
            
            # Enhanced logging to include limit information
            date_info = f"specific date {specific_date_str}" if specific_date_str else f"from {start_date} to {end_date}"
            limit_info = f"(limited to {limit})" if limit else "(all reports)"
            logger.info(f"EventReportsResource: Found {len(reports)} reports for event {event_id} {date_info} {limit_info}.")

            reports_data = []
            base_url = request.url_root.rstrip('/')
            for r in reports:
                report_dict = {
                    'report_id': r.id,
                    'event_id': r.event_id,
                    'total_tickets_sold': r.total_tickets_sold,
                    'total_revenue': float(r.total_revenue),
                    'number_of_attendees': r.number_of_attendees,
                    'report_date': r.report_date.isoformat() if r.report_date else None
                }
                report_dict['pdf_download_url'] = f"{base_url}/api/v1/reports/{r.id}/export?format=pdf"
                report_dict['csv_download_url'] = f"{base_url}/api/v1/reports/{r.id}/export?format=csv"
                reports_data.append(report_dict)

            response_data = {
                'event_id': event_id,
                'reports': reports_data,
                'total_reports_returned': len(reports_data),
                'is_limited': bool(limit),
                'limit_applied': limit
            }

            # Add query parameters info to response for clarity
            if specific_date_str:
                response_data['query_info'] = {
                    'specific_date': specific_date_str,
                    'is_single_day': True,
                    'limit': limit,
                    'get_all': get_all
                }
            elif start_date_str or end_date_str:
                response_data['query_info'] = {
                    'start_date': start_date_str,
                    'end_date': end_date_str,
                    'is_single_day': False,
                    'limit': limit,
                    'get_all': get_all
                }
            else:
                response_data['query_info'] = {
                    'limit': limit,
                    'get_all': get_all
                }

            return response_data, 200

        except Exception as e:
            logger.exception(f"EventReportsResource: Error fetching event reports for event {event_id}: {e}")
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
