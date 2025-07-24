from flask import request, jsonify, send_file, current_app, after_this_request, make_response
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Event, User, Report, Organizer, Currency, UserRole, Ticket, Transaction, CurrencyCode, TicketType
from .services import ReportService, DatabaseQueryService
from .utils import DateUtils, DateValidator, AuthorizationMixin
from .report_generators import ReportConfig, PDFReportGenerator, CSVReportGenerator, ChartGenerator # Import ChartGenerator
from currency_routes import convert_ksh_to_target_currency

from sqlalchemy import func, cast, String

from reportlab.lib.pagesizes import A4
import logging
from typing import Optional, Dict, Any, Union, List, Tuple
from datetime import datetime, timedelta
import os
import tempfile
import threading
from decimal import Decimal
import matplotlib.pyplot as plt # Import matplotlib
from contextlib import contextmanager # Import contextmanager

logger = logging.getLogger(__name__)


class GenerateReportResource(Resource):
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
                event_id=event_id,
                organizer_id=current_user_id,
                start_date=start_date,
                end_date=end_date,
                session=db.session,
                ticket_type_id=ticket_type_id,
                target_currency_code='KES',
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

            report_data = result.get('report_data', {})
            total_revenue_ksh = report_data.get('total_revenue', 0)
            total_tickets_sold = report_data.get('total_tickets_sold', 0)

            actual_attendee_count = report_data.get('attendee_count', 0)
            if actual_attendee_count == 0:
                actual_attendee_count = report_data.get('number_of_attendees', 0)
                if actual_attendee_count == 0:
                    actual_attendee_count = report_data.get('total_attendees', 0)

            logger.info(f"GenerateReportResource: Extracted attendee count from report data: {actual_attendee_count}")
            logger.info(f"GenerateReportResource: Available report data keys: {list(report_data.keys())}")

            base_currency = 'KES'
            converted_amount = Decimal(str(total_revenue_ksh))
            ksh_to_usd_rate = Decimal('1')
            usd_to_target_rate = Decimal('1')
            overall_conversion_rate = Decimal('1')

            try:
                if target_currency_code != 'KES' and total_revenue_ksh > 0:
                    logger.info(f"GenerateReportResource: Converting {total_revenue_ksh} KES to {target_currency_code}")
                    converted_amount, ksh_to_usd_rate, usd_to_target_rate = convert_ksh_to_target_currency(
                        total_revenue_ksh,
                        target_currency_code
                    )
                    overall_conversion_rate = ksh_to_usd_rate * usd_to_target_rate
                    logger.info(f"GenerateReportResource: Conversion successful - {total_revenue_ksh} KES = {converted_amount} {target_currency_code}")
                else:
                    converted_amount = Decimal(str(total_revenue_ksh))
                    logger.info(f"GenerateReportResource: No conversion needed - amount stays {total_revenue_ksh} KES")
            except Exception as e:
                logger.warning(f"GenerateReportResource: Currency conversion failed for {target_currency_code}: {str(e)}")
                converted_amount = Decimal(str(total_revenue_ksh))
                target_currency_code = 'KES'

            base_url = request.url_root.rstrip('/')
            pdf_download_url = f"{base_url}/reports/{report_id}/export?format=pdf&currency={target_currency_code}"
            csv_download_url = f"{base_url}/reports/{report_id}/export?format=csv&currency={target_currency_code}"

            response_data = {
                'message': 'Report generation initiated. You can download the report using the provided links.',
                'report_id': report_id,
                'report_data_summary': {
                    'total_tickets_sold': total_tickets_sold,
                    'total_revenue_original': float(total_revenue_ksh),
                    'total_revenue_converted': float(converted_amount.quantize(Decimal('0.01'))),
                    'number_of_attendees': actual_attendee_count,
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
                            email_report_data = report_data.copy()
                            email_report_data.update({
                                'event_name': event.name,
                                'currency_symbol': target_currency.symbol if target_currency else 'KSh',
                                'total_revenue': float(converted_amount.quantize(Decimal('0.01'))),
                                'currency': target_currency_code,
                                'target_currency': target_currency_code,
                                'report_period_start': start_date.strftime('%Y-%m-%d'),
                                'report_period_end': end_date.strftime('%Y-%m-%d'),
                                'conversion_rate': float(overall_conversion_rate) if overall_conversion_rate != 1 else None,
                                'base_currency': 'KES',
                                'base_currency_symbol': 'KSh',
                                'original_revenue': float(total_revenue_ksh) if target_currency_code != 'KES' else None,
                                'original_currency': 'KES' if target_currency_code != 'KES' else None,
                                'conversion_rate_used': float(overall_conversion_rate) if overall_conversion_rate != 1 else None,
                                'currency_conversion_source': 'currencyapi.com (with fallback)',
                                'attendee_count': actual_attendee_count,
                                'number_of_attendees': actual_attendee_count,
                            })

                            if target_currency_code != 'KES' and email_report_data.get('revenue_by_type'):
                                converted_revenue_by_type = {}
                                for ticket_type, original_revenue in email_report_data['revenue_by_type'].items():
                                    try:
                                        converted_revenue, _, _ = convert_ksh_to_target_currency(
                                            float(original_revenue), target_currency_code
                                        )
                                        converted_revenue_by_type[ticket_type] = float(converted_revenue.quantize(Decimal('0.01')))
                                    except Exception as e:
                                        logger.warning(f"Failed to convert revenue for {ticket_type}: {e}")
                                        converted_revenue_by_type[ticket_type] = float(original_revenue)
                                email_report_data['revenue_by_type'] = converted_revenue_by_type

                            email_sent = report_service.send_report_email(
                                report_data=email_report_data,
                                pdf_path='',
                                csv_path='',
                                recipient_email=recipient_email
                            )

                            if email_sent:
                                logger.info(f"GenerateReportResource: Background email sent to {recipient_email} for report {report_id}")
                            else:
                                logger.error(f"GenerateReportResource: Email sending failed for report {report_id}")
                    except Exception as e:
                        logger.error(f"GenerateReportResource: Email sending failed for report {report_id}: {e}", exc_info=True)

                threading.Thread(target=async_send_email).start()
                response_data['email_sent'] = True

            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"GenerateReportResource: Report generation request processed in {duration:.2f} seconds for report {report_id}")
            logger.info(f"GenerateReportResource: Final API response attendee count: {actual_attendee_count}")

            return response_data, 200
        except Exception as e:
            logger.error(f"GenerateReportResource: Unhandled error: {e}", exc_info=True)
            return {'error': 'Internal server error'}, 500


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

            # Enhanced authorization check with detailed logging
            is_authorized = False
            organizer = None
            
            # Admin users have access to all reports
            if current_user.role == UserRole.ADMIN:
                is_authorized = True
                logger.info(f"GetReportResource: Admin user {current_user_id} accessing report {report_id}.")
            else:
                # Get organizer record for current user
                organizer = Organizer.query.filter_by(user_id=current_user_id).first()
                
                if not organizer:
                    logger.warning(f"GetReportResource: No organizer record found for user {current_user_id}.")
                    return {'error': 'Organizer profile not found'}, 403
                
                # Log authorization details for debugging
                logger.info(f"GetReportResource: Checking authorization - User: {current_user_id}, "
                        f"Organizer ID: {organizer.id}, Report Organizer ID: {report.organizer_id}")
                
                # Check 1: Primary check - if organizer owns the report
                logger.info(f"GetReportResource: Check 1 - report.organizer_id ({report.organizer_id}) == organizer.id ({organizer.id}): {report.organizer_id == organizer.id}")
                if report.organizer_id == organizer.id:
                    is_authorized = True
                    logger.info(f"GetReportResource: Organizer {organizer.id} authorized to access report {report_id}.")
                
                # Check 2: If report's organizer_id matches the user_id (possible data inconsistency)
                else:
                    logger.info(f"GetReportResource: Check 2 - report.organizer_id ({report.organizer_id}) == current_user_id ({current_user_id}): {report.organizer_id == current_user_id}")
                    logger.info(f"GetReportResource: Check 2 types - report.organizer_id type: {type(report.organizer_id)}, current_user_id type: {type(current_user_id)}")
                    if str(report.organizer_id) == str(current_user_id):
                        is_authorized = True
                        logger.info(f"GetReportResource: User {current_user_id} authorized via user-report ownership for report {report_id}.")
                        logger.warning(f"GetReportResource: Data inconsistency detected - report {report_id} has organizer_id={report.organizer_id} but user's organizer.id={organizer.id}")
                    
                    # Check 3: If current organizer can access reports from the target organizer (same organization/team)
                    elif report.organizer_id:
                        logger.info(f"GetReportResource: Check 3 - Checking organization access for organizer_id {report.organizer_id}")
                        target_organizer = Organizer.query.get(report.organizer_id)
                        if target_organizer and hasattr(organizer, 'organization_id') and hasattr(target_organizer, 'organization_id'):
                            if organizer.organization_id == target_organizer.organization_id and organizer.organization_id is not None:
                                is_authorized = True
                                logger.info(f"GetReportResource: Organizer {organizer.id} authorized via same organization ({organizer.organization_id}) for report {report_id}.")
                
                # Check 4: If report has no organizer_id but was created by current user
                if not is_authorized and report.organizer_id is None and hasattr(report, 'created_by_user_id'):
                    if report.created_by_user_id == current_user_id:
                        is_authorized = True
                        logger.info(f"GetReportResource: User {current_user_id} authorized as creator of report {report_id}.")
                
                # Check 5: Check if the user has admin privileges for this specific organizer/organization
                if not is_authorized and hasattr(organizer, 'is_admin') and organizer.is_admin:
                    is_authorized = True
                    logger.info(f"GetReportResource: Organizer {organizer.id} authorized via admin privileges for report {report_id}.")
                
                # Additional diagnostic logging
                if not is_authorized:
                    logger.info(f"GetReportResource: Authorization failed - investigating report ownership:")
                    if report.organizer_id:
                        report_owner = Organizer.query.get(report.organizer_id)
                        if report_owner:
                            logger.info(f"GetReportResource: Report {report_id} is owned by organizer {report.organizer_id} (user_id: {report_owner.user_id})")
                        else:
                            # Check if organizer_id actually refers to a user_id
                            potential_user = User.query.get(report.organizer_id)
                            if potential_user:
                                logger.warning(f"GetReportResource: Report {report_id} has organizer_id {report.organizer_id} which appears to be a user_id, not organizer_id")
                            else:
                                logger.warning(f"GetReportResource: Report {report_id} has invalid organizer_id {report.organizer_id}")
                    else:
                        logger.info(f"GetReportResource: Report {report_id} has no organizer_id set")

            if not is_authorized:
                logger.warning(f"GetReportResource: User {current_user_id} (organizer: {organizer.id if organizer else 'None'}) "
                            f"unauthorized to access report {report_id} (owned by organizer: {report.organizer_id}).")
                return {'error': 'Unauthorized to access this report'}, 403

            # Get target currency for conversion
            target_currency_id = request.args.get('target_currency_id', type=int)
            
            # Build enhanced response
            report_dict = report.as_dict(target_currency_id=target_currency_id)
            
            # ==================== ATTENDEE COUNT CORRECTION ====================
            # Apply the same logic as GenerateReportResource to fix attendee count
            report_data = report_dict.get('report_data', {})
            
            # Extract attendee count using the same fallback approach
            actual_attendee_count = report_data.get('attendee_count', 0)
            if actual_attendee_count == 0:
                actual_attendee_count = report_data.get('number_of_attendees', 0)
                if actual_attendee_count == 0:
                    actual_attendee_count = report_data.get('total_attendees', 0)
            
            # Check debug_info for event_scans_count as fallback
            debug_info = report_data.get('debug_info', {})
            if actual_attendee_count == 0 and debug_info.get('event_scans_count'):
                actual_attendee_count = debug_info.get('event_scans_count', 0)
                logger.info(f"GetReportResource: Using event_scans_count as attendee count: {actual_attendee_count}")
            
            # Update the report data with corrected attendee count
            if actual_attendee_count > 0:
                logger.info(f"GetReportResource: Correcting attendee count from {report_dict.get('number_of_attendees', 0)} to {actual_attendee_count}")
                
                # Update main report fields
                report_dict['number_of_attendees'] = actual_attendee_count
                
                # Update report_data fields
                if 'report_data' in report_dict:
                    report_dict['report_data']['number_of_attendees'] = actual_attendee_count
                    report_dict['report_data']['attendee_count'] = actual_attendee_count
                
                # Recalculate attendance rate if we have ticket count
                total_tickets = report_dict.get('total_tickets_sold', 0)
                if total_tickets > 0:
                    attendance_rate = (actual_attendee_count / total_tickets) * 100
                    report_dict['attendance_rate'] = round(attendance_rate, 2)
                    if 'report_data' in report_dict:
                        report_dict['report_data']['attendance_rate'] = round(attendance_rate, 2)
                
                logger.info(f"GetReportResource: Attendee count corrected for report {report_id}: {actual_attendee_count} attendees")
            else:
                logger.warning(f"GetReportResource: Could not determine correct attendee count for report {report_id}")
            # ==================== END ATTENDEE COUNT CORRECTION ====================
            
            base_url = request.url_root.rstrip('/')
            report_dict['pdf_download_url'] = f"{base_url}/api/v1/reports/{report.id}/export?format=pdf"
            report_dict['csv_download_url'] = f"{base_url}/api/v1/reports/{report.id}/export?format=csv"

            # Add metadata about the request
            response_data = {
                'report': report_dict,
                'request_info': {
                    'requested_by_user_id': current_user_id,
                    'requested_by_role': current_user.role.value if current_user.role else None,
                    'requested_by_organizer_id': organizer.id if organizer else None,
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

            logger.info(f"GetReportResource: Successfully retrieved report {report_id} for user {current_user_id} "
                    f"(organizer: {organizer.id if organizer else 'None'}) with currency_id {target_currency_id}.")
            return response_data, 200

        except Exception as e:
            logger.error(f"GetReportResource: Error retrieving report {report_id} for user {current_user_id}: {e}", exc_info=True)
            return {'error': 'Internal server error'}, 500


class ExportReportResource(Resource):
    @jwt_required()
    def get(self, report_id):
        try:
            start_time = datetime.now()
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            
            if not current_user:
                logger.warning(f"ExportReportResource: User with ID {current_user_id} not found.")
                return {'error': 'User not found'}, 404

            # Get the report from database
            report = Report.query.get(report_id)
            if not report:
                logger.warning(f"ExportReportResource: Report with ID {report_id} not found.")
                return {'error': 'Report not found'}, 404

            # Get the event associated with this report
            event = Event.query.get(report.event_id)
            if not event:
                logger.warning(f"ExportReportResource: Event with ID {report.event_id} not found.")
                return {'error': 'Event not found'}, 404

            # Authorization check
            organizer = Organizer.query.filter_by(user_id=current_user_id).first()
            if not organizer or organizer.id != event.organizer_id:
                if current_user.role != UserRole.ADMIN:
                    logger.warning(f"ExportReportResource: User {current_user_id} unauthorized to export report {report_id}.")
                    return {'error': 'Unauthorized to export this report'}, 403

            # Get export format and currency from query parameters
            export_format = request.args.get('format', 'pdf').lower()
            target_currency = request.args.get('currency', 'KES')
            
            if export_format not in ['pdf', 'csv']:
                return {'error': 'Invalid format. Use "pdf" or "csv"'}, 400

            # Get report data (this should be stored in your report record or regenerated)
            report_data = report.report_data if hasattr(report, 'report_data') else {}
            
            # If report_data is empty, you might need to regenerate it
            if not report_data:
                logger.warning(f"ExportReportResource: No report data found for report {report_id}, regenerating...")
                config = ReportConfig()
                report_service = ReportService(config)
                
                result = report_service.generate_complete_report(
                    event_id=report.event_id,
                    organizer_id=current_user_id,
                    start_date=report.start_date,
                    end_date=report.end_date,
                    session=db.session,
                    target_currency_code=target_currency,
                    send_email=False
                )
                
                if not result['success']:
                    return {'error': 'Failed to regenerate report data'}, 500
                    
                report_data = result.get('report_data', {})

            if export_format == 'pdf':
                return self._export_pdf(report_data, report.event_id, target_currency)
            else:
                return self._export_csv(report_data, report.event_id, target_currency)
                
        except Exception as e:
            logger.error(f"ExportReportResource: Unhandled error: {e}", exc_info=True)
            return {'error': 'Internal server error'}, 500

    def _export_pdf(self, report_data, event_id, target_currency='KES'):
        """Export report as PDF"""
        try:
            # Create a temporary file for the PDF
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_pdf_file:
                
                # Generate charts if needed
                chart_paths = []
                try:
                    # ChartGenerator is already imported at the top
                    # Ensure matplotlib is imported for ChartGenerator
                    import matplotlib.pyplot as plt
                    from contextlib import contextmanager

                    config = ReportConfig(include_charts=True)
                    chart_generator = ChartGenerator(config)
                    
                    # Explicitly call the method that creates all charts
                    chart_paths = chart_generator.create_all_charts(report_data)
                    logger.info(f"ExportReportResource: Generated {len(chart_paths)} charts for PDF export")
                        
                except ImportError as import_error:
                    logger.warning(f"ExportReportResource: Failed to import ChartGenerator or matplotlib: {import_error}")
                    chart_paths = []
                except Exception as chart_error:
                    logger.warning(f"ExportReportResource: Chart generation failed: {chart_error}", exc_info=True)
                    chart_paths = []

                # Initialize PDF generator
                config = ReportConfig(include_charts=bool(chart_paths))
                pdf_generator = PDFReportGenerator(config)
                
                # Generate PDF with all required parameters
                file_path = pdf_generator.generate_pdf(
                    report_data=report_data,
                    chart_paths=chart_paths,
                    output_path=tmp_pdf_file.name,
                    session=db.session,
                    event_id=event_id,
                    target_currency=target_currency
                )
                
                if not file_path:
                    logger.error(f"ExportReportResource: PDF generation failed for report with event_id {event_id}")
                    return {'error': 'Failed to generate PDF'}, 500

                # Read the generated PDF file
                with open(file_path, 'rb') as pdf_file:
                    pdf_content = pdf_file.read()

                # Clean up temporary file
                try:
                    os.unlink(file_path)
                    # Clean up chart files
                    for chart_path in chart_paths:
                        if os.path.exists(chart_path):
                            os.unlink(chart_path)
                except Exception as cleanup_error:
                    logger.warning(f"ExportReportResource: Failed to cleanup files: {cleanup_error}")

                # Get event name for filename
                event = Event.query.get(event_id)
                event_name = event.name if event else f"Event_{event_id}"
                safe_event_name = "".join(c for c in event_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                
                # Create response
                response = make_response(pdf_content)
                response.headers['Content-Type'] = 'application/pdf'
                response.headers['Content-Disposition'] = f'attachment; filename="Report_{safe_event_name}_{datetime.now().strftime("%Y%m%d")}.pdf"'
                response.headers['Content-Length'] = len(pdf_content)
                
                logger.info(f"ExportReportResource: Successfully generated PDF for event {event_id}")
                return response
                
        except Exception as e:
            logger.error(f"ExportReportResource: Error generating PDF for event {event_id}: {e}", exc_info=True)
            return {'error': 'Failed to generate PDF report'}, 500

    def _export_csv(self, report_data, event_id, target_currency='KES'):
        """Export report as CSV"""
        try:
            # Create a temporary file for the CSV
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.csv', mode='w', encoding='utf-8') as tmp_csv_file:
                
                # Initialize CSV generator
                csv_generator = CSVReportGenerator()
                
                # Generate CSV with all required parameters
                file_path = csv_generator.generate_csv(
                    report_data=report_data,
                    output_path=tmp_csv_file.name,
                    session=db.session,
                    event_id=event_id
                )
                
                if not file_path:
                    logger.error(f"ExportReportResource: CSV generation failed for event {event_id}")
                    return {'error': 'Failed to generate CSV'}, 500

                # Read the generated CSV file
                with open(file_path, 'r', encoding='utf-8') as csv_file:
                    csv_content = csv_file.read()

                # Clean up temporary file
                try:
                    os.unlink(file_path)
                except Exception as cleanup_error:
                    logger.warning(f"ExportReportResource: Failed to cleanup CSV file: {cleanup_error}")

                # Get event name for filename
                event = Event.query.get(event_id)
                event_name = event.name if event else f"Event_{event_id}"
                safe_event_name = "".join(c for c in event_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                
                # Create response
                response = make_response(csv_content)
                response.headers['Content-Type'] = 'text/csv'
                response.headers['Content-Disposition'] = f'attachment; filename="Report_{safe_event_name}_{datetime.now().strftime("%Y%m%d")}.csv"'
                response.headers['Content-Length'] = len(csv_content.encode('utf-8'))
                
                logger.info(f"ExportReportResource: Successfully generated CSV for event {event_id}")
                return response
                
        except Exception as e:
            logger.error(f"ExportReportResource: Error generating CSV for event {event_id}: {e}", exc_info=True)
            return {'error': 'Failed to generate CSV report'}, 500


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
            # Count only PAID tickets (following DatabaseQueryService approach)
            event_tickets = (db.session.query(func.count(Ticket.id))
                           .filter(
                               Ticket.event_id == event.id,
                               cast(Ticket.payment_status, String).ilike("paid")
                           )
                           .scalar()) or 0

            # Calculate revenue using ticket price * quantity for PAID tickets only
            event_revenue_query = (db.session.query(func.sum(TicketType.price * Ticket.quantity))
                                  .select_from(Ticket)
                                  .join(TicketType, Ticket.ticket_type_id == TicketType.id)
                                  .filter(
                                      Ticket.event_id == event.id,
                                      cast(Ticket.payment_status, String).ilike("paid")
                                  )
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
from datetime import datetime, time

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

            # FIXED: Initialize ReportService to get correct attendee counts
            config = ReportConfig(include_email=False)
            report_service = ReportService(config)

            for r in reports:
                # FIXED: Get the correct attendee count using the same logic as GenerateReportResource
                actual_attendee_count = r.number_of_attendees

                # If the stored attendee count is 0, try to recalculate it from the report data
                if actual_attendee_count == 0 and hasattr(r, 'report_data') and r.report_data:
                    try:
                        # Parse the stored report data (assuming it's JSON)
                        import json
                        if isinstance(r.report_data, str):
                            report_data = json.loads(r.report_data)
                        else:
                            report_data = r.report_data

                        # Apply the same extraction logic as GenerateReportResource
                        actual_attendee_count = report_data.get('attendee_count', 0)
                        if actual_attendee_count == 0:
                            actual_attendee_count = report_data.get('number_of_attendees', 0)
                            if actual_attendee_count == 0:
                                actual_attendee_count = report_data.get('total_attendees', 0)

                        logger.info(f"EventReportsResource: Extracted attendee count from report data for report {r.id}: {actual_attendee_count}")

                    except Exception as e:
                        logger.warning(f"EventReportsResource: Failed to extract attendee count from report data for report {r.id}: {e}")
                        # Keep the original value if extraction fails
                        actual_attendee_count = r.number_of_attendees

                # Alternative approach: If report_data is not available or extraction failed,
                # and stored count is still 0, recalculate from the database
                if actual_attendee_count == 0:
                    try:
                        # Use the same date range that was used for this report
                        if r.report_date:
                            if isinstance(r.report_date, datetime):
                                report_start_date = r.report_date.replace(hour=0, minute=0, second=0, microsecond=0)
                                report_end_date = r.report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                            else:
                                # If it's a date object, convert to datetime first
                                report_start_date = datetime.combine(r.report_date, time.min)
                                report_end_date = datetime.combine(r.report_date, time.max)
                        else:
                            report_start_date = None
                            report_end_date = None

                        if report_start_date and report_end_date:
                            # Generate fresh report data to get the correct attendee count
                            fresh_result = report_service.generate_complete_report(
                                event_id=event_id,
                                organizer_id=current_user_id,
                                start_date=report_start_date,
                                end_date=report_end_date,
                                session=db.session,
                                ticket_type_id=None,
                                target_currency_code='KES',
                                send_email=False,
                                recipient_email=None
                            )

                            if fresh_result['success']:
                                fresh_report_data = fresh_result.get('report_data', {})
                                fresh_attendee_count = fresh_report_data.get('attendee_count', 0)
                                if fresh_attendee_count == 0:
                                    fresh_attendee_count = fresh_report_data.get('number_of_attendees', 0)
                                    if fresh_attendee_count == 0:
                                        fresh_attendee_count = fresh_report_data.get('total_attendees', 0)

                                if fresh_attendee_count > 0:
                                    actual_attendee_count = fresh_attendee_count
                                    logger.info(f"EventReportsResource: Recalculated attendee count for report {r.id}: {actual_attendee_count}")

                    except Exception as e:
                        logger.warning(f"EventReportsResource: Failed to recalculate attendee count for report {r.id}: {e}")

                report_dict = {
                    'report_id': r.id,
                    'event_id': r.event_id,
                    'total_tickets_sold': r.total_tickets_sold,
                    'total_revenue': float(r.total_revenue),
                    'number_of_attendees': actual_attendee_count,  # FIXED: Use the correctly extracted/calculated attendee count
                    'report_date': r.report_date.isoformat() if r.report_date else None
                }
                report_dict['pdf_download_url'] = f"{base_url}/reports/{r.id}/export?format=pdf"
                report_dict['csv_download_url'] = f"{base_url}/reports/{r.id}/export?format=csv"
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