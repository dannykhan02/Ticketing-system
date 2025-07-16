from flask import jsonify, request, Response, send_file
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func
from datetime import datetime
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from decimal import Decimal
import requests

# Your application-specific imports
# Ensure these imports correctly point to your model and utility files
from model import User, Event, Organizer, Report, db, Currency, ExchangeRate, Ticket, PaymentStatus
from pdf_utils import CSVExporter
from pdf_utils import PDFReportGenerator
from email_utils import send_email_with_attachment
from currency_routes import convert_ksh_to_target_currency # Assuming this is correctly implemented

logger = logging.getLogger(__name__)

@dataclass
class AdminReportConfig:
    """Configuration for admin report generation"""
    include_charts: bool = True
    include_email: bool = False
    format_type: str = 'json'
    currency_conversion: bool = True
    target_currency_id: Optional[int] = None
    group_by_organizer: bool = True
    use_latest_rates: bool = True

class AdminReportService:
    @staticmethod
    def get_actual_event_metrics(event_id: int) -> Dict[str, Any]:
        """Get actual event metrics from database"""
        try:
            # Get tickets sold (PAID status only)
            tickets_sold_count = Ticket.query.filter_by(
                event_id=event_id,
                payment_status=PaymentStatus.PAID
            ).count()
            
            # Get total revenue (sum of paid tickets)
            paid_tickets = Ticket.query.filter_by(
                event_id=event_id,
                payment_status=PaymentStatus.PAID
            ).all()
            
            # Sum the total_price from each paid ticket
            total_revenue = sum(ticket.total_price for ticket in paid_tickets)
            
            # Get attendees (scanned tickets) - Use the 'scanned' boolean field
            attendees_count = Ticket.query.filter_by(
                event_id=event_id,
                scanned=True
            ).count()
            
            return {
                'tickets_sold': tickets_sold_count,
                'total_revenue': float(total_revenue),
                'attendees': attendees_count,
                'paid_tickets': paid_tickets
            }
        except Exception as e:
            logger.error(f"Error getting actual event metrics for event {event_id}: {e}")
            return {
                'tickets_sold': 0,
                'total_revenue': 0.0,
                'attendees': 0,
                'paid_tickets': []
            }

    @staticmethod
    def convert_revenue_to_currency(ksh_amount: float, target_currency_code: str) -> Dict[str, Any]:
        """Convert KSH amount to target currency using the currency conversion API"""
        try:
            if target_currency_code.upper() in ["KES", "KSH"]:
                return {
                    'converted_amount': ksh_amount,
                    'currency_code': 'KES',
                    'currency_symbol': 'KSh',
                    'conversion_rate': 1.0
                }
            
            # Use the existing conversion function
            converted_amount, ksh_to_usd_rate, usd_to_target_rate = convert_ksh_to_target_currency(
                ksh_amount, target_currency_code
            )
            
            # Get currency symbol
            target_currency_obj = Currency.query.filter_by(
                code=target_currency_code, 
                is_active=True
            ).first()
            
            currency_symbol = target_currency_obj.symbol if target_currency_obj else target_currency_code
            overall_rate = ksh_to_usd_rate * usd_to_target_rate
            
            return {
                'converted_amount': float(converted_amount.quantize(Decimal('0.01'))),
                'currency_code': target_currency_code,
                'currency_symbol': currency_symbol,
                'conversion_rate': float(overall_rate)
            }
            
        except Exception as e:
            logger.error(f"Error converting {ksh_amount} KSH to {target_currency_code}: {e}")
            # Return original amount if conversion fails
            return {
                'converted_amount': ksh_amount,
                'currency_code': 'KES',
                'currency_symbol': 'KSh',
                'conversion_rate': 1.0
            }

    @staticmethod
    def format_report_data_for_frontend(report_data: Dict[str, Any], config: AdminReportConfig) -> Dict[str, Any]:
        """Format report data to ensure frontend compatibility and apply final currency conversion."""
        
        # Determine the target currency code based on config
        target_currency_code = None
        target_currency_symbol = 'KSh' # Default
        if config.target_currency_id:
            currency_obj = Currency.query.get(config.target_currency_id)
            if currency_obj:
                target_currency_code = currency_obj.code.value
                target_currency_symbol = currency_obj.symbol

        # This function processes two main types of reports: single event and organizer summary.
        # It needs to ensure that the 'revenue' and 'total_revenue' fields are consistently converted.

        if 'event_info' in report_data: # This is a single event report
            event_summary = report_data.get('event_summary', {})
            original_revenue = event_summary.get('revenue_ksh', event_summary.get('revenue', 0.0)) # Get original KSH revenue

            if target_currency_code and target_currency_code.upper() != 'KES':
                conversion_result = AdminReportService.convert_revenue_to_currency(
                    original_revenue, target_currency_code
                )
                event_summary['revenue'] = conversion_result['converted_amount']
                event_summary['currency'] = conversion_result['currency_code']
                event_summary['currency_symbol'] = conversion_result['currency_symbol']
            else: # If no specific target currency or target is KES, use KSH values directly
                event_summary['revenue'] = original_revenue
                event_summary['currency'] = 'KES'
                event_summary['currency_symbol'] = 'KSh'
            
            report_data['event_summary'] = event_summary
            
            # Update currency settings for the report
            report_data['currency_settings']['target_currency'] = event_summary['currency']
            report_data['currency_settings']['target_currency_symbol'] = event_summary['currency_symbol']


        elif 'organizer_info' in report_data: # This is an organizer summary report
            summary_data = report_data.get('summary', {})
            events_data = summary_data.get('events', []) # This will be the list of event dicts

            formatted_events = []
            total_converted_revenue = 0.0

            for event_dict in events_data:
                original_event_revenue = event_dict.get('revenue_ksh', event_dict.get('revenue', 0.0))
                
                converted_event_revenue = original_event_revenue
                event_currency_code = 'KES'
                event_currency_symbol = 'KSh'

                if target_currency_code and target_currency_code.upper() != 'KES':
                    conversion_result = AdminReportService.convert_revenue_to_currency(
                        original_event_revenue, target_currency_code
                    )
                    converted_event_revenue = conversion_result['converted_amount']
                    event_currency_code = conversion_result['currency_code']
                    event_currency_symbol = conversion_result['currency_symbol']
                
                event_dict['revenue'] = converted_event_revenue
                event_dict['currency'] = event_currency_code
                event_dict['currency_symbol'] = event_currency_symbol
                
                total_converted_revenue += converted_event_revenue
                formatted_events.append(event_dict)

            summary_data['events'] = formatted_events
            summary_data['total_revenue'] = total_converted_revenue
            summary_data['currency'] = target_currency_code if target_currency_code else 'KES'
            summary_data['currency_symbol'] = target_currency_symbol if target_currency_symbol else 'KSh'
            
            report_data['summary'] = summary_data

            # Update currency settings for the report
            report_data['currency_settings']['target_currency'] = summary_data['currency']
            report_data['currency_settings']['target_currency_symbol'] = summary_data['currency_symbol']

        return report_data


    @staticmethod
    def validate_admin_access(user: User) -> bool:
        """Validate that the user has admin access"""
        return user and user.role.value == "ADMIN"

    @staticmethod
    def get_organizer_by_id(organizer_user_id: int) -> Optional[User]:
        """Get organizer user by ID"""
        try:
            # Query the User table directly for ADMIN or ORGANIZER role
            user = User.query.filter_by(id=organizer_user_id).first()
            if user and user.role.value == "ORGANIZER":
                return user
            return None
        except Exception as e:
            logger.error(f"Database error fetching organizer {organizer_user_id}: {e}")
            return None

    @staticmethod
    def get_events_by_organizer(organizer_user_id: int) -> List[Event]:
        """Get all events for a specific organizer"""
        try:
            # First get the Organizer profile linked to the user_id
            organizer_profile = Organizer.query.filter_by(user_id=organizer_user_id).first()
            if organizer_profile:
                return Event.query.filter_by(organizer_id=organizer_profile.id).all()
            return []
        except Exception as e:
            logger.error(f"Database error fetching events for organizer user ID {organizer_user_id}: {e}")
            return []

    @staticmethod
    def aggregate_organizer_reports(organizer_user_id: int, target_currency_code: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate reports for an organizer using actual database metrics.
           Returns revenue in KSH, and let format_report_data_for_frontend handle conversion."""
        try:
            organizer_user = AdminReportService.get_organizer_by_id(organizer_user_id)
            if not organizer_user:
                return {"error": "Organizer not found"}
            
            events = AdminReportService.get_events_by_organizer(organizer_user_id)
            
            total_tickets_sold = 0
            total_revenue_ksh = 0.0 # Store revenue in KSH initially
            total_attendees = 0
            event_details = []
            
            for event in events:
                metrics = AdminReportService.get_actual_event_metrics(event.id)
                
                total_tickets_sold += metrics['tickets_sold']
                total_revenue_ksh += metrics['total_revenue'] # Sum KSH revenue
                total_attendees += metrics['attendees']
                
                event_details.append({
                    "event_id": event.id,
                    "event_name": event.name,
                    "event_date": event.date.isoformat() if event.date else None,
                    "location": event.location,
                    "tickets_sold": metrics['tickets_sold'],
                    "revenue_ksh": metrics['total_revenue'], # Store KSH revenue
                    "attendees": metrics['attendees']
                })

            return {
                "total_tickets_sold": total_tickets_sold,
                "total_revenue_ksh": total_revenue_ksh, # Return KSH total
                "total_attendees": total_attendees,
                "event_count": len(events),
                "events": event_details # Pass detailed event data with KSH revenue
            }
            
        except Exception as e:
            logger.error(f"Error aggregating organizer reports: {e}")
            return {"error": "Failed to aggregate reports for organizer", "status": 500}

    @staticmethod
    def aggregate_event_reports(event: Event, target_currency_code: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate data for a single event using actual database metrics.
           Returns revenue in KSH, and let format_report_data_for_frontend handle conversion."""
        try:
            metrics = AdminReportService.get_actual_event_metrics(event.id)
            
            return {
                "event_id": event.id,
                "event_name": event.name,
                "event_date": event.date.isoformat() if event.date else None,
                "location": event.location,
                "tickets_sold": metrics['tickets_sold'],
                "attendees": metrics['attendees'],
                "revenue_ksh": metrics['total_revenue'], # Store revenue in KSH
            }
            
        except Exception as e:
            logger.error(f"Error aggregating event reports: {e}")
            return {"error": "Failed to aggregate event data", "status": 500}

    @staticmethod
    def generate_organizer_summary_report(organizer_user_id: int, config: AdminReportConfig) -> Dict[str, Any]:
        """Generate a comprehensive summary report for an organizer."""
        try:
            organizer_user = AdminReportService.get_organizer_by_id(organizer_user_id)
            if not organizer_user:
                return {"error": "Organizer not found", "status": 404}

            # Get aggregated data in KSH
            aggregated_data_ksh = AdminReportService.aggregate_organizer_reports(
                organizer_user_id
            )

            if "error" in aggregated_data_ksh:
                return {"error": aggregated_data_ksh["error"], "status": aggregated_data_ksh.get("status", 500)}

            summary_report = {
                "organizer_info": {
                    "organizer_id": organizer_user.id,
                    "organizer_name": organizer_user.full_name,
                    "email": organizer_user.email,
                    "phone": organizer_user.phone_number
                },
                "report_period": {
                    "days": "All available data"
                },
                "currency_settings": {
                    "target_currency_id": config.target_currency_id,
                    "use_latest_rates": config.use_latest_rates
                },
                "summary": aggregated_data_ksh, # This initially contains KSH values and event details
                "generation_timestamp": datetime.utcnow().isoformat()
            }
            
            # Now, apply the formatting and currency conversion
            return AdminReportService.format_report_data_for_frontend(summary_report, config)
            
        except Exception as e:
            logger.error(f"Error generating organizer summary report: {e}")
            return {"error": "Failed to generate report", "status": 500}

    @staticmethod
    def generate_event_admin_report(event_id: int, organizer_user_id: int, config: AdminReportConfig) -> Dict[str, Any]:
        """Generate an admin report for a specific event."""
        try:
            # Ensure the event belongs to the specified organizer
            organizer_profile = Organizer.query.filter_by(user_id=organizer_user_id).first()
            if not organizer_profile:
                return {"error": "Organizer not found", "status": 404}

            event = Event.query.filter(
                Event.id == event_id,
                Event.organizer_id == organizer_profile.id
            ).first()
            
            if not event:
                return {"error": "Event not found or doesn't belong to the specified organizer", "status": 404}

            # Get event summary in KSH
            event_summary_ksh = AdminReportService.aggregate_event_reports(event)
            
            if "error" in event_summary_ksh:
                return {"error": event_summary_ksh["error"], "status": event_summary_ksh.get("status", 500)}

            admin_report = {
                "event_info": {
                    "event_id": event.id,
                    "event_name": event.name,
                    "event_date": event.date.isoformat() if event.date else None,
                    "location": event.location,
                    "organizer_id": organizer_user_id,
                    "organizer_name": organizer_profile.user.full_name if organizer_profile.user else "N/A"
                },
                "report_period": {
                    "days": "All available data"
                },
                "currency_settings": {
                    "target_currency_id": config.target_currency_id,
                    "use_latest_rates": config.use_latest_rates
                },
                "event_summary": event_summary_ksh, # This initially contains KSH values
                "generation_timestamp": datetime.utcnow().isoformat()
            }
            
            # Now, apply the formatting and currency conversion
            return AdminReportService.format_report_data_for_frontend(admin_report, config)
            
        except Exception as e:
            logger.error(f"Error generating event admin report: {e}")
            return {"error": "Failed to generate event report", "status": 500}

    @staticmethod
    def send_report_email(report_data: Dict[str, Any], recipient_email: str) -> bool:
        """Send report via email with enhanced formatting and proper currency display"""
        try:
            is_event_report = 'event_info' in report_data
            
            if is_event_report:
                report_title = report_data['event_info'].get('event_name', 'Unknown Event')
                subject = f"Event Analytics Report - {report_title}"
                event_summary = report_data.get('event_summary', {})
                currency_symbol = event_summary.get('currency_symbol', 'KSh')
                currency_code = event_summary.get('currency', 'KES')
                total_tickets_sold = event_summary.get('tickets_sold', 0)
                total_revenue = event_summary.get('revenue', 0.0)
                number_of_attendees = event_summary.get('attendees', 0)
            else:
                report_title = report_data['organizer_info'].get('organizer_name', 'Unknown Organizer')
                subject = f"Organizer Summary Report - {report_title}"
                summary = report_data.get('summary', {})
                currency_symbol = summary.get('currency_symbol', 'KSh')
                currency_code = summary.get('currency', 'KES')
                total_tickets_sold = summary.get('total_tickets_sold', 0)
                total_revenue = summary.get('total_revenue', 0.0)
                number_of_attendees = summary.get('total_attendees', 0)

            # Calculate attendance rate
            attendance_rate = (number_of_attendees / total_tickets_sold * 100) if total_tickets_sold > 0 else 0

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
                    .currency-info {{ background: #f0f8ff; padding: 10px; border-radius: 4px; margin: 10px 0; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📊 Admin Report</h1>
                    <h2>{report_title}</h2>
                </div>
                <div class="content">
                    <div class="currency-info">
                        <strong>Currency:</strong> {currency_code} ({currency_symbol}) | 
                        <strong>Data Source:</strong> Live database metrics
                    </div>
                    <div class="summary-box">
                        <h3>📈 Executive Summary</h3>
                        <div class="metric">
                            <div class="metric-value">{total_tickets_sold}</div>
                            <div class="metric-label">Tickets Sold (PAID)</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{currency_symbol}{total_revenue:,.2f}</div>
                            <div class="metric-label">Total Revenue</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{number_of_attendees}</div>
                            <div class="metric-label">Attendees (SCANNED)</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{attendance_rate:.1f}%</div>
                            <div class="metric-label">Attendance Rate</div>
                        </div>
                    </div>
                    
                    <div class="insights">
                        <h3>💡 Key Insights</h3>
                        <ul>
                            <li><strong>Revenue Calculation:</strong> Based on sum of all PAID ticket prices</li>
                            <li><strong>Tickets Sold:</strong> Count of tickets with PAID status</li>
                            <li><strong>Attendees:</strong> Count of tickets with SCANNED status</li>
            """
            
            if attendance_rate > 90:
                html_body += "<li><strong>Excellent attendance rate!</strong> Most ticket holders attended the event.</li>"
            elif attendance_rate > 70:
                html_body += "<li><strong>Good attendance rate</strong> with room for improvement in no-show reduction.</li>"
            elif attendance_rate > 0:
                html_body += "<li><strong>Low attendance rate</strong> suggests potential areas for improvement.</li>"
            else:
                html_body += "<li><strong>No attendance recorded</strong> - check scanning process.</li>"
            
            html_body += f"""
                        </ul>
                    </div>
                    
                    <div class="summary-box">
                        <h3>📋 Report Details</h3>
                        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p><strong>Data Source:</strong> Live database with real-time metrics</p>
                        <p><strong>Currency:</strong> {currency_code} ({currency_symbol})</p>
                    </div>
                </div>
                <div class="footer">
                    <p>This report was automatically generated by the Event Management System</p>
                    <p>All figures are based on actual database records with PAID/SCANNED status</p>
                </div>
            </body>
            </html>
            """

            success = send_email_with_attachment(
                recipient=recipient_email,
                subject=subject,
                body=html_body,
                is_html=True
            )
            return success
            
        except Exception as e:
            logger.error(f"Error sending report email: {e}")
            return False

class AdminReportResource(Resource):
    """Admin report API resource with enhanced AdminReportService integration"""
    
    @jwt_required()
    def get(self):
        """Get admin reports with various filtering options"""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        # Use AdminReportService for validation
        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        # Parse query parameters
        organizer_id = request.args.get('organizer_id', type=int)
        event_id = request.args.get('event_id', type=int)
        format_type = request.args.get('format', 'json')
        target_currency_id = request.args.get('currency_id', type=int)
        include_charts = request.args.get('include_charts', 'true').lower() == 'true'
        use_latest_rates = request.args.get('use_latest_rates', 'true').lower() == 'true'
        send_email = request.args.get('send_email', 'false').lower() == 'true'
        
        # Use user's registered email if no recipient email is specified
        recipient_email = request.args.get('recipient_email')
        if not recipient_email:
            recipient_email = user.email
            
        group_by_organizer = request.args.get('group_by_organizer', 'true').lower() == 'true' # Not directly used in AdminReportResource logic, but for config consistency

        # Create config using AdminReportConfig
        config = AdminReportConfig(
            include_charts=include_charts,
            include_email=send_email,
            format_type=format_type,
            currency_conversion=target_currency_id is not None,
            target_currency_id=target_currency_id,
            group_by_organizer=group_by_organizer,
            use_latest_rates=use_latest_rates
        )

        try:
            # Generate report using AdminReportService
            if organizer_id and event_id:
                # Single event report
                report_data = AdminReportService.generate_event_admin_report(
                    event_id, organizer_id, config
                )
            elif organizer_id:
                # Organizer summary report
                report_data = AdminReportService.generate_organizer_summary_report(
                    organizer_id, config
                )
            else:
                return {"message": "Please specify 'organizer_id' or both 'organizer_id' and 'event_id'"}, 400

            # Handle service errors
            if "error" in report_data:
                return {"message": report_data["error"]}, report_data.get("status", 500)

            # Send email if requested, *before* formatting the response for file downloads
            # This ensures the email gets the fully formatted report_data with correct currency
            if send_email:
                email_success = AdminReportService.send_report_email(report_data, recipient_email)
                if not email_success:
                    logger.warning(f"Failed to send email to {recipient_email}")
                    # If it's a JSON response, add a failure status
                    if format_type.lower() == 'json':
                        report_data['email_status'] = 'failed'
                else:
                    # Add success status for JSON responses
                    if format_type.lower() == 'json':
                        report_data['email_status'] = 'sent'
                        report_data['email_recipient'] = recipient_email
            
            # Format response based on requested format
            response = self._format_response(report_data, format_type, organizer_id, event_id)
            
            return response

        except Exception as e:
            logger.error(f"Admin report generation failed: {e}")
            return {"message": "Report generation failed", "error": str(e)}, 500

    def _format_response(self, report_data: Dict[str, Any], format_type: str, organizer_id: int, event_id: Optional[int] = None) -> Response:
        """Format the response based on the requested format type"""
        try:
            filename_prefix = f"admin_report_org{organizer_id}"
            if event_id:
                filename_prefix += f"_event{event_id}"

            if format_type.lower() == 'csv':
                csv_content = CSVExporter.generate_csv_report(report_data)
                return Response(
                    csv_content,
                    mimetype='text/csv',
                    headers={
                        'Content-Disposition': f'attachment; filename={filename_prefix}_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
                    }
                )
            elif format_type.lower() == 'pdf':
                # Re-create a config for PDF to ensure it has the necessary currency info
                # This ensures PDF generation uses the already converted data in report_data
                config_for_pdf = AdminReportConfig(
                    format_type=format_type,
                    target_currency_id=report_data['currency_settings'].get('target_currency_id'),
                    currency_conversion=True # Already converted
                )
                pdf_buffer = PDFReportGenerator.generate_pdf_report(report_data, config_for_pdf)
                return send_file(
                    pdf_buffer,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=f'{filename_prefix}_{datetime.now().strftime("%Y%m%d%H%M%S")}.pdf'
                )
            else:
                # JSON response (default)
                return jsonify(report_data)
        except Exception as e:
            logger.error(f"Response formatting failed for format {format_type}: {e}")
            raise # Re-raise to be caught by the outer try-except

class AdminOrganizerListResource(Resource):
    """Resource for listing all organizers for admin with enhanced metrics"""
    
    @jwt_required()
    def get(self):
        """Get list of all organizers with comprehensive metrics"""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        try:
            # Get currency parameter for revenue calculation
            target_currency_id = request.args.get('currency_id', type=int)
            target_currency_code = None
            target_currency_symbol = 'KSh'
            if target_currency_id:
                currency_obj = Currency.query.get(target_currency_id)
                if currency_obj:
                    target_currency_code = currency_obj.code.value
                    target_currency_symbol = currency_obj.symbol

            # Get basic organizer info with event counts
            organizers_query = db.session.query(
                User.id,
                User.full_name,
                User.email,
                User.phone_number,
                func.count(Event.id).label('event_count')
            ).select_from(User)\
            .outerjoin(Organizer, User.id == Organizer.user_id)\
            .outerjoin(Event, Organizer.id == Event.organizer_id)\
            .filter(User.role == 'ORGANIZER')\
            .group_by(User.id, User.full_name, User.email, User.phone_number)\
            .all()

            organizer_list = []
            for org_user_record in organizers_query:
                # Get metrics in KSH first
                metrics_ksh = AdminReportService.aggregate_organizer_reports(org_user_record.id)
                
                if "error" in metrics_ksh:
                    logger.error(f"Error aggregating KSH metrics for organizer {org_user_record.id}: {metrics_ksh['error']}")
                    continue 

                # Perform final conversion for the aggregated total revenue
                final_total_revenue = metrics_ksh.get('total_revenue_ksh', 0.0)
                current_currency_code = 'KES'
                current_currency_symbol = 'KSh'

                if target_currency_code and target_currency_code.upper() != 'KES':
                    conversion_result = AdminReportService.convert_revenue_to_currency(
                        final_total_revenue, target_currency_code
                    )
                    final_total_revenue = conversion_result['converted_amount']
                    current_currency_code = conversion_result['currency_code']
                    current_currency_symbol = conversion_result['currency_symbol']

                organizer_data = {
                    "organizer_id": org_user_record.id,
                    "name": org_user_record.full_name,
                    "email": org_user_record.email,
                    "phone": org_user_record.phone_number,
                    "event_count": org_user_record.event_count,
                    "metrics": {
                        "total_tickets_sold": metrics_ksh.get('total_tickets_sold', 0),
                        "total_revenue": final_total_revenue, # Use the converted revenue
                        "total_attendees": metrics_ksh.get('total_attendees', 0),
                        "currency": current_currency_code,
                        "currency_symbol": current_currency_symbol
                    }
                }
                organizer_list.append(organizer_data)

            # Sort by total revenue (descending) for better insights
            organizer_list.sort(key=lambda x: x['metrics']['total_revenue'], reverse=True)

            return {
                "organizers": organizer_list,
                "total_count": len(organizer_list),
                "currency_info": {
                    "target_currency_id": target_currency_id,
                    "target_currency": target_currency_code or 'KES',
                    "target_currency_symbol": target_currency_symbol or 'KSh'
                }
            }

        except Exception as e:
            logger.error(f"Error fetching organizer list: {e}")
            return {"message": "Failed to fetch organizer list", "error": str(e)}, 500

class AdminEventListResource(Resource):
    """Resource for listing events by organizer with enhanced metrics"""
    
    @jwt_required()
    def get(self, organizer_id): # This organizer_id refers to User.id for the organizer
        """Get list of events for a specific organizer with detailed metrics"""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        try:
            # Validate organizer exists (using the user ID passed in the URL)
            organizer_user = AdminReportService.get_organizer_by_id(organizer_id)
            if not organizer_user:
                return {"message": "Organizer not found"}, 404

            # Get currency parameter
            target_currency_id = request.args.get('currency_id', type=int)
            target_currency_code = None
            target_currency_symbol = 'KSh'
            if target_currency_id:
                currency_obj = Currency.query.get(target_currency_id)
                if currency_obj:
                    target_currency_code = currency_obj.code.value
                    target_currency_symbol = currency_obj.symbol

            # Get events using AdminReportService (passing the organizer's user ID)
            events = AdminReportService.get_events_by_organizer(organizer_id)
            
            event_list = []
            for event in events:
                # Get detailed metrics for each event in KSH first
                event_metrics_ksh = AdminReportService.aggregate_event_reports(event)
                
                if "error" in event_metrics_ksh:
                    logger.error(f"Error aggregating KSH metrics for event {event.id}: {event_metrics_ksh['error']}")
                    continue

                # Perform final conversion for each event's revenue
                final_event_revenue = event_metrics_ksh.get('revenue_ksh', 0.0)
                current_currency_code = 'KES'
                current_currency_symbol = 'KSh'

                if target_currency_code and target_currency_code.upper() != 'KES':
                    conversion_result = AdminReportService.convert_revenue_to_currency(
                        final_event_revenue, target_currency_code
                    )
                    final_event_revenue = conversion_result['converted_amount']
                    current_currency_code = conversion_result['currency_code']
                    current_currency_symbol = conversion_result['currency_symbol']
                
                event_data = {
                    "event_id": event.id,
                    "name": event.name,
                    "event_date": event.date.isoformat() if event.date else None,
                    "location": event.location,
                    "status": event.status.value if hasattr(event, 'status') else 'ACTIVE',
                    "metrics": {
                        "tickets_sold": event_metrics_ksh.get('tickets_sold', 0),
                        "revenue": final_event_revenue, # Use the converted revenue
                        "attendees": event_metrics_ksh.get('attendees', 0),
                        "currency": current_currency_code,
                        "currency_symbol": current_currency_symbol
                    }
                }
                event_list.append(event_data)

            # Sort by event date (most recent first)
            event_list.sort(key=lambda x: x['event_date'] or '', reverse=True)

            # Calculate totals based on the converted revenues
            total_tickets_sold = sum(event['metrics']['tickets_sold'] for event in event_list)
            total_revenue = sum(event['metrics']['revenue'] for event in event_list)
            total_attendees = sum(event['metrics']['attendees'] for event in event_list)

            return {
                "organizer_id": organizer_id,
                "organizer_name": organizer_user.full_name,
                "events": event_list,
                "total_count": len(event_list),
                "summary": {
                    "total_tickets_sold": total_tickets_sold,
                    "total_revenue": total_revenue,
                    "total_attendees": total_attendees,
                    "currency": target_currency_code or 'KES',
                    "currency_symbol": target_currency_symbol or 'KSh'
                },
                "currency_info": {
                    "target_currency_id": target_currency_id,
                    "target_currency": target_currency_code or 'KES',
                    "target_currency_symbol": target_currency_symbol or 'KSh'
                }
            }

        except Exception as e:
            logger.error(f"Error fetching event list for organizer {organizer_id}: {e}")
            return {"message": "Failed to fetch event list", "error": str(e)}, 500


def register_admin_report_resources(api):
    """Register admin report resources with the Flask-RESTful API"""
    api.add_resource(AdminReportResource, '/admin/reports')
    api.add_resource(AdminOrganizerListResource, '/admin/organizers')
    api.add_resource(AdminEventListResource, '/admin/organizers/<int:organizer_id>/events')