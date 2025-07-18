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
import io
import tempfile
import os

# Your application-specific imports
from model import User, Event, Organizer, Report, db, Currency, ExchangeRate, Ticket, PaymentStatus
from pdf_utils import CSVExporter, PDFReportGenerator
from email_utils import send_email_with_attachment
from currency_routes import convert_ksh_to_target_currency

logger = logging.getLogger(__name__)

@dataclass
class AdminReportConfig:
    """Configuration for admin report generation"""
    include_charts: bool = True
    include_email: bool = False
    format_type: str = 'json'
    currency_conversion: bool = True
    target_currency_id: Optional[int] = None
    target_currency_code: Optional[str] = None
    group_by_organizer: bool = True
    use_latest_rates: bool = True

class AdminReportService:
    @staticmethod
    def get_default_currency() -> Dict[str, str]:
        """Get default currency (Kenyan Shilling) settings"""
        return {
            'code': 'KES',
            'symbol': 'KSh',
            'name': 'Kenyan Shilling'
        }

    @staticmethod
    def get_currency_settings(currency_id: Optional[int] = None, currency_code: Optional[str] = None) -> Dict[str, str]:
        """Get currency settings by ID or code, fallback to default"""
        try:
            if currency_id:
                currency = Currency.query.get(currency_id)
                if currency:
                    return {
                        'code': currency.code.value,
                        'symbol': currency.symbol,
                        'name': currency.name
                    }

            if currency_code:
                currency = Currency.query.filter_by(code=currency_code, is_active=True).first()
                if currency:
                    return {
                        'code': currency.code.value,
                        'symbol': currency.symbol,
                        'name': currency.name
                    }

            return AdminReportService.get_default_currency()

        except Exception as e:
            logger.error(f"Error getting currency settings: {e}")
            return AdminReportService.get_default_currency()

    @staticmethod
    def get_actual_event_metrics(event_id: int) -> Dict[str, Any]:
        """Get actual event metrics from database"""
        try:
            tickets_sold_count = Ticket.query.filter_by(
                event_id=event_id,
                payment_status=PaymentStatus.PAID
            ).count()

            paid_tickets = Ticket.query.filter_by(
                event_id=event_id,
                payment_status=PaymentStatus.PAID
            ).all()

            total_revenue = sum(ticket.total_price for ticket in paid_tickets)

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

            converted_amount, ksh_to_usd_rate, usd_to_target_rate = convert_ksh_to_target_currency(
                ksh_amount, target_currency_code
            )

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
            return {
                'converted_amount': ksh_amount,
                'currency_code': 'KES',
                'currency_symbol': 'KSh',
                'conversion_rate': 1.0
            }

    @staticmethod
    def format_report_data_for_frontend(report_data: Dict[str, Any], config: AdminReportConfig) -> Dict[str, Any]:
        """Format report data to ensure frontend compatibility and apply final currency conversion."""
        currency_settings = AdminReportService.get_currency_settings(
            config.target_currency_id,
            config.target_currency_code
        )

        target_currency_code = currency_settings['code']
        target_currency_symbol = currency_settings['symbol']
        target_currency_name = currency_settings['name']

        if 'event_info' in report_data:
            event_summary = report_data.get('event_summary', {})
            original_revenue = event_summary.get('revenue_ksh', event_summary.get('revenue', 0.0))
            if target_currency_code.upper() != 'KES':
                conversion_result = AdminReportService.convert_revenue_to_currency(
                    original_revenue, target_currency_code
                )
                event_summary.update({
                    'revenue': conversion_result['converted_amount'],
                    'currency': conversion_result['currency_code'],
                    'currency_symbol': conversion_result['currency_symbol'],
                    'conversion_rate': conversion_result['conversion_rate']
                })
            else:
                event_summary.update({
                    'revenue': original_revenue,
                    'currency': 'KES',
                    'currency_symbol': 'KSh',
                    'conversion_rate': 1.0
                })

            event_summary['revenue_ksh'] = original_revenue
            event_summary['currency_name'] = target_currency_name
            report_data['event_summary'] = event_summary

        elif 'organizer_info' in report_data:
            summary_data = report_data.get('summary', {})
            events_data = summary_data.get('events', [])
            formatted_events = []
            total_converted_revenue = 0.0
            for event_dict in events_data:
                original_event_revenue = event_dict.get('revenue_ksh', event_dict.get('revenue', 0.0))

                if target_currency_code.upper() != 'KES':
                    conversion_result = AdminReportService.convert_revenue_to_currency(
                        original_event_revenue, target_currency_code
                    )
                    event_dict.update({
                        'revenue': conversion_result['converted_amount'],
                        'currency': conversion_result['currency_code'],
                        'currency_symbol': conversion_result['currency_symbol'],
                        'conversion_rate': conversion_result['conversion_rate']
                    })
                else:
                    event_dict.update({
                        'revenue': original_event_revenue,
                        'currency': 'KES',
                        'currency_symbol': 'KSh',
                        'conversion_rate': 1.0
                    })

                event_dict['revenue_ksh'] = original_event_revenue
                event_dict['currency_name'] = target_currency_name
                total_converted_revenue += event_dict['revenue']
                formatted_events.append(event_dict)
            summary_data['events'] = formatted_events
            summary_data.update({
                'total_revenue': total_converted_revenue,
                'currency': target_currency_code,
                'currency_symbol': target_currency_symbol,
                'currency_name': target_currency_name
            })
            report_data['summary'] = summary_data

        report_data['currency_settings'] = {
            'target_currency_id': config.target_currency_id,
            'target_currency': target_currency_code,
            'target_currency_symbol': target_currency_symbol,
            'target_currency_name': target_currency_name,
            'use_latest_rates': config.use_latest_rates
        }
        return report_data

    @staticmethod
    def validate_admin_access(user: User) -> bool:
        """Validate that the user has admin access"""
        return user and user.role.value == "ADMIN"

    @staticmethod
    def get_organizer_by_id(organizer_user_id: int) -> Optional[User]:
        """Get organizer user by ID"""
        try:
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
            organizer_profile = Organizer.query.filter_by(user_id=organizer_user_id).first()
            if organizer_profile:
                return Event.query.filter_by(organizer_id=organizer_profile.id).all()
            return []
        except Exception as e:
            logger.error(f"Database error fetching events for organizer user ID {organizer_user_id}: {e}")
            return []

    @staticmethod
    def aggregate_organizer_reports(organizer_user_id: int) -> Dict[str, Any]:
        """Aggregate reports for an organizer using actual database metrics."""
        try:
            organizer_user = AdminReportService.get_organizer_by_id(organizer_user_id)
            if not organizer_user:
                return {"error": "Organizer not found"}

            events = AdminReportService.get_events_by_organizer(organizer_user_id)

            total_tickets_sold = 0
            total_revenue_ksh = 0.0
            total_attendees = 0
            event_details = []

            for event in events:
                metrics = AdminReportService.get_actual_event_metrics(event.id)

                total_tickets_sold += metrics['tickets_sold']
                total_revenue_ksh += metrics['total_revenue']
                total_attendees += metrics['attendees']

                event_details.append({
                    "event_id": event.id,
                    "event_name": event.name,
                    "event_date": event.date.isoformat() if event.date else None,
                    "location": event.location,
                    "tickets_sold": metrics['tickets_sold'],
                    "revenue_ksh": metrics['total_revenue'],
                    "attendees": metrics['attendees']
                })
            return {
                "total_tickets_sold": total_tickets_sold,
                "total_revenue_ksh": total_revenue_ksh,
                "total_attendees": total_attendees,
                "event_count": len(events),
                "events": event_details
            }

        except Exception as e:
            logger.error(f"Error aggregating organizer reports: {e}")
            return {"error": "Failed to aggregate reports for organizer", "status": 500}

    @staticmethod
    def aggregate_event_reports(event: Event) -> Dict[str, Any]:
        """Aggregate data for a single event using actual database metrics."""
        try:
            metrics = AdminReportService.get_actual_event_metrics(event.id)

            return {
                "event_id": event.id,
                "event_name": event.name,
                "event_date": event.date.isoformat() if event.date else None,
                "location": event.location,
                "tickets_sold": metrics['tickets_sold'],
                "attendees": metrics['attendees'],
                "revenue_ksh": metrics['total_revenue'],
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
            aggregated_data_ksh = AdminReportService.aggregate_organizer_reports(organizer_user_id)
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
                "summary": aggregated_data_ksh,
                "generation_timestamp": datetime.utcnow().isoformat()
            }

            return AdminReportService.format_report_data_for_frontend(summary_report, config)

        except Exception as e:
            logger.error(f"Error generating organizer summary report: {e}")
            return {"error": "Failed to generate report", "status": 500}

    @staticmethod
    def generate_event_admin_report(event_id: int, organizer_user_id: int, config: AdminReportConfig) -> Dict[str, Any]:
        """Generate an admin report for a specific event."""
        try:
            organizer_profile = Organizer.query.filter_by(user_id=organizer_user_id).first()
            if not organizer_profile:
                return {"error": "Organizer not found", "status": 404}
            event = Event.query.filter(
                Event.id == event_id,
                Event.organizer_id == organizer_profile.id
            ).first()

            if not event:
                return {"error": "Event not found or doesn't belong to the specified organizer", "status": 404}
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
                "event_summary": event_summary_ksh,
                "generation_timestamp": datetime.utcnow().isoformat()
            }

            return AdminReportService.format_report_data_for_frontend(admin_report, config)

        except Exception as e:
            logger.error(f"Error generating event admin report: {e}")
            return {"error": "Failed to generate event report", "status": 500}

    @staticmethod
    def generate_csv_report(report_data: Dict[str, Any]) -> str:
        """Generate CSV content from report data"""
        try:
            csv_content = io.StringIO()

            currency_symbol = report_data.get('currency_settings', {}).get('target_currency_symbol', 'KSh')
            currency_name = report_data.get('currency_settings', {}).get('target_currency_name', 'Kenyan Shilling')

            csv_content.write(f"Event Management System Report\n")
            csv_content.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            csv_content.write(f"Currency: {currency_name} ({currency_symbol})\n\n")

            if 'event_info' in report_data:
                event_info = report_data['event_info']
                event_summary = report_data['event_summary']

                csv_content.write("EVENT DETAILS\n")
                csv_content.write(f"Event Name,{event_info['event_name']}\n")
                csv_content.write(f"Event Date,{event_info['event_date']}\n")
                csv_content.write(f"Location,{event_info['location']}\n")
                csv_content.write(f"Organizer,{event_info['organizer_name']}\n\n")

                csv_content.write("PERFORMANCE METRICS\n")
                csv_content.write(f"Tickets Sold,{event_summary['tickets_sold']}\n")
                csv_content.write(f"Total Revenue,{currency_symbol}{event_summary['revenue']:,.2f}\n")
                csv_content.write(f"Attendees,{event_summary['attendees']}\n")
                if event_summary['tickets_sold'] > 0:
                    attendance_rate = (event_summary['attendees'] / event_summary['tickets_sold']) * 100
                    csv_content.write(f"Attendance Rate,{attendance_rate:.1f}%\n")

            elif 'organizer_info' in report_data:
                organizer_info = report_data['organizer_info']
                summary = report_data['summary']

                csv_content.write("ORGANIZER DETAILS\n")
                csv_content.write(f"Organizer Name,{organizer_info['organizer_name']}\n")
                csv_content.write(f"Email,{organizer_info['email']}\n")
                csv_content.write(f"Phone,{organizer_info['phone']}\n\n")

                csv_content.write("SUMMARY METRICS\n")
                csv_content.write(f"Total Events,{summary['event_count']}\n")
                csv_content.write(f"Total Tickets Sold,{summary['total_tickets_sold']}\n")
                csv_content.write(f"Total Revenue,{currency_symbol}{summary['total_revenue']:,.2f}\n")
                csv_content.write(f"Total Attendees,{summary['total_attendees']}\n\n")

                csv_content.write("EVENT BREAKDOWN\n")
                csv_content.write("Event Name,Event Date,Location,Tickets Sold,Revenue,Attendees\n")

                for event in summary['events']:
                    csv_content.write(f"{event['event_name']},{event['event_date']},{event['location']},{event['tickets_sold']},{currency_symbol}{event['revenue']:,.2f},{event['attendees']}\n")

            return csv_content.getvalue()

        except Exception as e:
            logger.error(f"Error generating CSV report: {e}")
            return "Error generating CSV report"

    @staticmethod
    def generate_pdf_report(report_data: Dict[str, Any]) -> bytes:
        """Generate PDF content from report data"""
        try:
            # Format the report data to match what your PDFReportGenerator expects
            formatted_data = {
                'event_id': report_data.get('event_id', 0),
                'event_name': report_data.get('event_name', 'Event Management System Report'),
                'event_date': report_data.get('event_date', datetime.now().strftime('%Y-%m-%d')),
                'event_location': report_data.get('event_location', 'Not specified'),
                'event_description': report_data.get('event_description', 'Generated admin report'),
                'total_tickets_sold': report_data.get('total_tickets_sold', 0),
                'total_revenue': report_data.get('total_revenue', 0.0),
                'number_of_attendees': report_data.get('number_of_attendees', 0),
                'revenue_by_ticket_type': report_data.get('revenue_by_ticket_type', {}),
                'ticket_sales_by_type': report_data.get('ticket_sales_by_type', {}),
                'filter_start_date': report_data.get('filter_start_date', ''),
                'filter_end_date': report_data.get('filter_end_date', ''),
                # Add currency info if available
                'currency_settings': report_data.get('currency_settings', {}),
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # Create temporary file for PDF generation
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                tmp_pdf_path = tmp_file.name

            try:
                # Use the correct method name from your PDFReportGenerator class
                pdf_path = PDFReportGenerator.generate_pdf_report(formatted_data)

                # If generation was successful and file exists
                if pdf_path and os.path.exists(pdf_path):
                    with open(pdf_path, 'rb') as pdf_file:
                        pdf_content = pdf_file.read()

                    # Clean up the generated file
                    try:
                        os.unlink(pdf_path)
                    except OSError:
                        pass

                    return pdf_content
                else:
                    logger.error("PDF generation failed - no file was created")
                    return b""

            finally:
                # Clean up temporary file
                try:
                    os.unlink(tmp_pdf_path)
                except OSError:
                    pass

        except Exception as e:
            logger.error(f"Error generating PDF report: {e}")
            return b""

    @staticmethod
    def send_report_email_with_download_guide(report_data: Dict[str, Any], recipient_email: str, organizer_id: int, event_id: Optional[int] = None) -> bool:
        """Send report email with download guide for admin dashboard instead of direct links"""
        try:
            is_event_report = 'event_info' in report_data
            currency_settings = report_data.get('currency_settings', {})

            if is_event_report:
                report_title = report_data['event_info'].get('event_name', 'Unknown Event')
                subject = f"Event Analytics Report - {report_title}"
                event_summary = report_data.get('event_summary', {})
                currency_symbol = currency_settings.get('target_currency_symbol', 'KSh')
                currency_code = currency_settings.get('target_currency', 'KES')
                currency_name = currency_settings.get('target_currency_name', 'Kenyan Shilling')
                total_tickets_sold = event_summary.get('tickets_sold', 0)
                total_revenue = event_summary.get('revenue', 0.0)
                number_of_attendees = event_summary.get('attendees', 0)
            else:
                report_title = report_data['organizer_info'].get('organizer_name', 'Unknown Organizer')
                subject = f"Organizer Summary Report - {report_title}"
                summary = report_data.get('summary', {})
                currency_symbol = currency_settings.get('target_currency_symbol', 'KSh')
                currency_code = currency_settings.get('target_currency', 'KES')
                currency_name = currency_settings.get('target_currency_name', 'Kenyan Shilling')
                total_tickets_sold = summary.get('total_tickets_sold', 0)
                total_revenue = summary.get('total_revenue', 0.0)
                number_of_attendees = summary.get('total_attendees', 0)

            attendance_rate = (number_of_attendees / total_tickets_sold * 100) if total_tickets_sold > 0 else 0

            # Create download guide section
            download_guide = f"""
            <div class="download-section">
                <h3>📥 How to Download Full Report</h3>
                <p>To download the complete report with detailed breakdowns and additional metrics:</p>
                <div class="guide-steps">
                    <div class="step">
                        <strong>Step 1:</strong> Log in to your Admin Dashboard
                    </div>
                    <div class="step">
                        <strong>Step 2:</strong> Navigate to the Reports section
                    </div>
                    <div class="step">
                        <strong>Step 3:</strong> Select the appropriate filters:
                        <ul>
                            <li>Organizer ID: {organizer_id}</li>
                            {f"<li>Event ID: {event_id}</li>" if event_id else ""}
                            <li>Currency: {currency_name} ({currency_code})</li>
                        </ul>
                    </div>
                    <div class="step">
                        <strong>Step 4:</strong> Choose your preferred format:
                        <ul>
                            <li>📄 CSV - For data analysis and spreadsheet import</li>
                            <li>📑 PDF - For professional presentation and printing</li>
                        </ul>
                    </div>
                    <div class="step">
                        <strong>Step 5:</strong> Click the Download button to get your report
                    </div>
                </div>
                <p style="font-size: 12px; color: #666; margin-top: 15px;">
                    <strong>Note:</strong> The downloaded report will include the same currency settings ({currency_code}) as shown in this email summary.
                    Both formats contain comprehensive data including detailed breakdowns and additional metrics not shown in this email.
                </p>
            </div>
            """

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
                    .download-section {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border: 2px solid #007bff; }}
                    .guide-steps {{ margin: 15px 0; }}
                    .step {{ background: white; padding: 12px; margin: 8px 0; border-radius: 6px; border-left: 4px solid #007bff; }}
                    .step strong {{ color: #007bff; }}
                    .step ul {{ margin: 8px 0; padding-left: 20px; }}
                    .step li {{ margin: 4px 0; }}
                    .footer {{ background: #333; color: white; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 8px 8px; }}
                    .currency-info {{ background: #f0f8ff; padding: 10px; border-radius: 4px; margin: 10px 0; font-size: 12px; }}
                    .dashboard-highlight {{ background: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; border: 1px solid #ffeaa7; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📊 Admin Report</h1>
                    <h2>{report_title}</h2>
                </div>
                <div class="content">
                    <div class="currency-info">
                        <strong>Currency:</strong> {currency_name} ({currency_code} - {currency_symbol}) |
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

                    {download_guide}

                    <div class="dashboard-highlight">
                        <strong>💡 Pro Tip:</strong> Use the admin dashboard for the most up-to-date reports with real-time data and additional filtering options.
                    </div>

                    <div class="insights">
                        <h3>💡 Key Insights</h3>
                        <ul>
                            <li><strong>Revenue Calculation:</strong> Based on sum of all PAID ticket prices</li>
                            <li><strong>Tickets Sold:</strong> Count of tickets with PAID status</li>
                            <li><strong>Attendees:</strong> Count of tickets with SCANNED status</li>
                            <li><strong>Currency:</strong> All amounts displayed in {currency_name} ({currency_code})</li>
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
                        <p><strong>Currency:</strong> {currency_name} ({currency_code} - {currency_symbol})</p>
                        <p><strong>Download Options:</strong> CSV and PDF reports available via Admin Dashboard</p>
                    </div>
                </div>
                <div class="footer">
                    <p>This report was automatically generated by the Event Management System</p>
                    <p>All figures are based on actual database records with PAID/SCANNED status</p>
                    <p>For detailed reports, please visit the Admin Dashboard</p>
                </div>
            </body>
            </html>
            """

            success = send_email_with_attachment(
                recipient=recipient_email,
                subject=subject,
                body=html_body,
                is_html=True,
                attachments=[]
            )
            return success

        except Exception as e:
            logger.error(f"Error sending report email with download guide: {e}")
            return False

class AdminReportResource(Resource):
    """Admin report API resource with enhanced AdminReportService integration"""

    @jwt_required()
    def get(self):
        """Get admin reports with various filtering options"""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        organizer_id = request.args.get('organizer_id', type=int)
        event_id = request.args.get('event_id', type=int)
        format_type = request.args.get('format', 'json')
        target_currency_id = request.args.get('currency_id', type=int)
        target_currency_code = request.args.get('currency_code', type=str)
        include_charts = request.args.get('include_charts', 'true').lower() == 'true'
        use_latest_rates = request.args.get('use_latest_rates', 'true').lower() == 'true'
        send_email = request.args.get('send_email', 'false').lower() == 'true'

        recipient_email = request.args.get('recipient_email')
        if not recipient_email:
            recipient_email = user.email

        group_by_organizer = request.args.get('group_by_organizer', 'true').lower() == 'true'

        config = AdminReportConfig(
            include_charts=include_charts,
            include_email=send_email,
            format_type=format_type,
            currency_conversion=target_currency_id is not None or target_currency_code is not None,
            target_currency_id=target_currency_id,
            target_currency_code=target_currency_code,
            group_by_organizer=group_by_organizer,
            use_latest_rates=use_latest_rates
        )

        try:
            if organizer_id and event_id:
                report_data = AdminReportService.generate_event_admin_report(
                    event_id, organizer_id, config
                )
            elif organizer_id:
                report_data = AdminReportService.generate_organizer_summary_report(
                    organizer_id, config
                )
            else:
                return {"message": "Please specify 'organizer_id' or both 'organizer_id' and 'event_id'"}, 400

            if "error" in report_data:
                return {"message": report_data["error"]}, report_data.get("status", 500)

            if send_email:
                email_success = AdminReportService.send_report_email_with_download_guide(
                    report_data, recipient_email, organizer_id, event_id
                )
                if not email_success:
                    logger.warning(f"Failed to send email to {recipient_email}")
                    if format_type.lower() == 'json':
                        report_data['email_status'] = 'failed'
                else:
                    if format_type.lower() == 'json':
                        report_data['email_status'] = 'sent'
                        report_data['email_recipient'] = recipient_email

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
                csv_content = AdminReportService.generate_csv_report(report_data)
                return Response(
                    csv_content,
                    mimetype='text/csv',
                    headers={
                        'Content-Disposition': f'attachment; filename={filename_prefix}_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
                    }
                )
            elif format_type.lower() == 'pdf':
                pdf_content = AdminReportService.generate_pdf_report(report_data)
                if pdf_content:
                    pdf_buffer = io.BytesIO(pdf_content)
                    return send_file(
                        pdf_buffer,
                        mimetype='application/pdf',
                        as_attachment=True,
                        download_name=f'{filename_prefix}_{datetime.now().strftime("%Y%m%d%H%M%S")}.pdf'
                    )
                else:
                    return {"message": "PDF generation failed"}, 500
            else:
                return jsonify(report_data)

        except Exception as e:
            logger.error(f"Response formatting failed for format {format_type}: {e}")
            raise

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
            target_currency_id = request.args.get('currency_id', type=int)
            target_currency_code = None
            target_currency_symbol = 'KSh'
            if target_currency_id:
                currency_obj = Currency.query.get(target_currency_id)
                if currency_obj:
                    target_currency_code = currency_obj.code.value
                    target_currency_symbol = currency_obj.symbol

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
                metrics_ksh = AdminReportService.aggregate_organizer_reports(org_user_record.id)

                if "error" in metrics_ksh:
                    logger.error(f"Error aggregating KSH metrics for organizer {org_user_record.id}: {metrics_ksh['error']}")
                    continue

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
                        "total_revenue": final_total_revenue,
                        "total_attendees": metrics_ksh.get('total_attendees', 0),
                        "currency": current_currency_code,
                        "currency_symbol": current_currency_symbol
                    }
                }
                organizer_list.append(organizer_data)
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
    def get(self, organizer_id):
        """Get list of events for a specific organizer with detailed metrics"""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403
        try:
            organizer_user = AdminReportService.get_organizer_by_id(organizer_id)
            if not organizer_user:
                return {"message": "Organizer not found"}, 404

            target_currency_id = request.args.get('currency_id', type=int)
            target_currency_code = None
            target_currency_symbol = 'KSh'
            if target_currency_id:
                currency_obj = Currency.query.get(target_currency_id)
                if currency_obj:
                    target_currency_code = currency_obj.code.value
                    target_currency_symbol = currency_obj.symbol

            events = AdminReportService.get_events_by_organizer(organizer_id)

            event_list = []
            for event in events:
                event_metrics_ksh = AdminReportService.aggregate_event_reports(event)

                if "error" in event_metrics_ksh:
                    logger.error(f"Error aggregating KSH metrics for event {event.id}: {event_metrics_ksh['error']}")
                    continue

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
                        "revenue": final_event_revenue,
                        "attendees": event_metrics_ksh.get('attendees', 0),
                        "currency": current_currency_code,
                        "currency_symbol": current_currency_symbol
                    }
                }
                event_list.append(event_data)

            event_list.sort(key=lambda x: x['event_date'] or '', reverse=True)

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