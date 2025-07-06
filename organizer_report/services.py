from typing import Dict, List, Any, Optional
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Any, Optional, Tuple
# ...existing code...
from model import db, Ticket, TicketType, Transaction, Scan, Event, User, Report, Organizer, Currency, ExchangeRate
# ...existing code...Organizer, Currency, ExchangeRate
from .utils import DateUtils, CurrencyConverter, FileManager
from  email_utils import send_email_with_attachment
from .report_generators import ChartGenerator
from .report_generators import PDFReportGenerator
from .report_generators import CSVReportGenerator
# ...existing code... 
from sqlalchemy import func, and_, or_

import logging
import os

logger = logging.getLogger(__name__)

class DatabaseQueryService:
    @staticmethod
    def get_tickets_sold_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        query = (db.session.query(TicketType.type_name, func.count(Ticket.id))
                .join(Ticket, Ticket.ticket_type_id == TicketType.id)
                .join(Transaction, Ticket.transaction_id == Transaction.id)
                .filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                )
                .group_by(TicketType.type_name)
                .all())
        return [(type_name, count) for type_name, count in query]

    @staticmethod
    def get_revenue_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, Decimal]]:
        query = (db.session.query(TicketType.type_name, func.sum(Transaction.amount_paid))
                .join(Ticket, Ticket.ticket_type_id == TicketType.id)
                .join(Transaction, Ticket.transaction_id == Transaction.id)
                .filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                )
                .group_by(TicketType.type_name)
                .all())
        return [(type_name, Decimal(str(revenue)) if revenue else Decimal('0')) for type_name, revenue in query]

    @staticmethod
    def get_attendees_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        query = (db.session.query(TicketType.type_name, func.count(func.distinct(Scan.ticket_id)))
                .join(Ticket, Scan.ticket_id == Ticket.id)
                .join(TicketType, Ticket.ticket_type_id == TicketType.id)
                .filter(
                    Ticket.event_id == event_id,
                    Scan.scanned_at >= start_date,
                    Scan.scanned_at <= end_date
                )
                .group_by(TicketType.type_name)
                .all())
        return [(type_name, count) for type_name, count in query]

    @staticmethod
    def get_payment_method_usage(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        query = (db.session.query(Transaction.payment_method, func.count(Transaction.id))
                .join(Ticket, Ticket.transaction_id == Transaction.id)
                .filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                )
                .group_by(Transaction.payment_method)
                .all())
        return [(method, count) for method, count in query]

    @staticmethod
    def get_total_revenue(event_id: int, start_date: datetime, end_date: datetime) -> Decimal:
        result = (db.session.query(func.sum(Transaction.amount_paid))
                 .join(Ticket, Ticket.transaction_id == Transaction.id)
                 .filter(
                     Ticket.event_id == event_id,
                     Transaction.payment_status == 'COMPLETED',
                     Transaction.timestamp >= start_date,
                     Transaction.timestamp <= end_date
                 )
                 .scalar())
        return Decimal(str(result)) if result else Decimal('0')

    @staticmethod
    def get_total_tickets_sold(event_id: int, start_date: datetime, end_date: datetime) -> int:
        result = (db.session.query(func.count(Ticket.id))
                 .join(Transaction, Ticket.transaction_id == Transaction.id)
                 .filter(
                     Ticket.event_id == event_id,
                     Transaction.payment_status == 'COMPLETED',
                     Transaction.timestamp >= start_date,
                     Transaction.timestamp <= end_date
                 )
                 .scalar())
        return result if result else 0

    @staticmethod
    def get_total_attendees(event_id: int, start_date: datetime, end_date: datetime) -> int:
        result = (db.session.query(func.count(func.distinct(Scan.ticket_id)))
                 .join(Ticket, Scan.ticket_id == Ticket.id)
                 .filter(
                     Ticket.event_id == event_id,
                     Scan.scanned_at >= start_date,
                     Scan.scanned_at <= end_date
                 )
                 .scalar())
        return result if result else 0

    @staticmethod
    def get_event_base_currency(event_id: int) -> int:
        event = Event.query.get(event_id)
        if event and hasattr(event, 'base_currency_id') and event.base_currency_id:
            return event.base_currency_id
        default_currency = Currency.query.filter_by(code='USD').first()
        return default_currency.id if default_currency else 1

class ReportService:
    def __init__(self, config):
        self.config = config
        self.chart_generator = ChartGenerator(self.config) if self.config.include_charts else None
        self.pdf_generator = PDFReportGenerator(self.config)
        self.db_service = DatabaseQueryService()
        self.currency_converter = CurrencyConverter()

    def create_report_data(self, event_id: int, start_date: datetime, end_date: datetime,
                          ticket_type_id: Optional[int] = None,
                          target_currency_id: Optional[int] = None) -> Dict[str, Any]:
        event = Event.query.get(event_id)
        if not event:
            raise ValueError(f"Event with ID {event_id} not found")
        base_currency_id = self.db_service.get_event_base_currency(event_id)
        display_currency_id = target_currency_id or base_currency_id
        base_currency_info = self.currency_converter.get_currency_info(base_currency_id)
        display_currency_info = self.currency_converter.get_currency_info(display_currency_id)
        tickets_sold_data = self.db_service.get_tickets_sold_by_type(event_id, start_date, end_date)
        revenue_data = self.db_service.get_revenue_by_type(event_id, start_date, end_date)
        attendees_data = self.db_service.get_attendees_by_type(event_id, start_date, end_date)
        payment_methods = self.db_service.get_payment_method_usage(event_id, start_date, end_date)
        tickets_sold_by_type = dict(tickets_sold_data)
        revenue_by_ticket_type = {}
        attendees_by_ticket_type = dict(attendees_data)
        payment_method_usage = dict(payment_methods)
        total_revenue_base = self.db_service.get_total_revenue(event_id, start_date, end_date)
        total_revenue_display = self.currency_converter.convert_amount(
            total_revenue_base, base_currency_id, display_currency_id
        )
        for ticket_type, revenue in revenue_data:
            converted_revenue = self.currency_converter.convert_amount(
                revenue, base_currency_id, display_currency_id
            )
            revenue_by_ticket_type[ticket_type] = converted_revenue
        total_tickets_sold = self.db_service.get_total_tickets_sold(event_id, start_date, end_date)
        total_attendees = self.db_service.get_total_attendees(event_id, start_date, end_date)
        report_data = {
            'event_id': event_id,
            'event_name': event.name,
            'event_date': event.event_date.isoformat() if hasattr(event, 'event_date') and event.event_date else 'N/A',
            'event_location': getattr(event, 'location', 'N/A'),
            'filter_start_date': start_date.strftime('%Y-%m-%d'),
            'filter_end_date': end_date.strftime('%Y-%m-%d'),
            'total_tickets_sold': total_tickets_sold,
            'total_revenue': float(total_revenue_display),
            'number_of_attendees': total_attendees,
            'tickets_sold_by_type': tickets_sold_by_type,
            'revenue_by_ticket_type': {k: float(v) for k, v in revenue_by_ticket_type.items()},
            'attendees_by_ticket_type': attendees_by_ticket_type,
            'payment_method_usage': payment_method_usage,
            'currency': display_currency_info['code'],
            'currency_symbol': display_currency_info['symbol'],
            'base_currency': base_currency_info['code'],
            'base_currency_symbol': base_currency_info['symbol'],
        }
        if base_currency_id != display_currency_id:
            report_data['original_revenue'] = float(total_revenue_base)
            report_data['original_currency'] = base_currency_info['code']
        if ticket_type_id:
            ticket_type = TicketType.query.get(ticket_type_id)
            if ticket_type:
                report_data['ticket_type_id'] = ticket_type_id
                report_data['ticket_type_name'] = ticket_type.type_name
                report_data['report_scope'] = 'ticket_type_summary'
            else:
                report_data['report_scope'] = 'event_summary'
        else:
            report_data['report_scope'] = 'event_summary'
        return report_data

    def save_report_to_database(self, report_data: Dict[str, Any], organizer_id: int) -> Optional[Report]:
        base_currency = Currency.query.filter_by(code=report_data.get('base_currency', 'USD')).first()
        base_currency_id = base_currency.id if base_currency else 1
        report = Report(
            organizer_id=organizer_id,
            event_id=report_data['event_id'],
            ticket_type_id=report_data.get('ticket_type_id'),
            base_currency_id=base_currency_id,
            report_scope=report_data.get('report_scope', 'event_summary'),
            total_tickets_sold=report_data.get('total_tickets_sold', 0),
            total_revenue=Decimal(str(report_data.get('total_revenue', 0))),
            number_of_attendees=report_data.get('number_of_attendees', 0),
            report_data=report_data,
            report_date=datetime.now().date()
        )
        db.session.add(report)
        db.session.commit()
        logger.info(f"Report saved to database with ID: {report.id}")
        return report

    def generate_complete_report(self, event_id: int, organizer_id: int, start_date: datetime,
                                end_date: datetime, ticket_type_id: Optional[int] = None,
                                target_currency_id: Optional[int] = None,
                                send_email: bool = False, recipient_email: str = None) -> Dict[str, Any]:
        chart_paths = []
        pdf_path = None
        csv_path = None
        try:
            report_data = self.create_report_data(event_id, start_date, end_date, ticket_type_id, target_currency_id)
            saved_report = self.save_report_to_database(report_data, organizer_id)
            if saved_report:
                report_data['database_id'] = saved_report.id
            pdf_path, csv_path = FileManager.generate_unique_paths(event_id)
            if self.config.include_charts and self.chart_generator:
                chart_paths = self.chart_generator.create_all_charts(report_data)
            pdf_path = self.pdf_generator.generate_pdf(report_data, chart_paths, pdf_path)
            csv_path = CSVReportGenerator.generate_csv(report_data, csv_path)
            email_sent = False
            if send_email and recipient_email and self.config.include_email:
                email_sent = self._send_report_email(
                    report_data, pdf_path, csv_path, recipient_email
                )
            return {
                'success': True,
                'report_data': report_data,
                'pdf_path': pdf_path,
                'csv_path': csv_path,
                'chart_paths': chart_paths,
                'email_sent': email_sent,
                'database_id': report_data.get('database_id')
            }
        except Exception as e:
            logger.error(f"Error generating complete report: {e}")
            return {
                'success': False,
                'error': str(e),
                'report_data': None,
                'pdf_path': None,
                'csv_path': None,
                'chart_paths': [],
                'email_sent': False
            }
        finally:
            if chart_paths:
                FileManager.cleanup_files(chart_paths)

    def _send_report_email(self, report_data: Dict[str, Any], pdf_path: str,
                          csv_path: str, recipient_email: str) -> bool:
        event_name = report_data.get('event_name', 'Unknown Event')
        currency_symbol = report_data.get('currency_symbol', '$')
        subject = f"Event Analytics Report - {event_name}"
        body = f"""
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
            body += f"""
                    <div class="metric">
                        <div class="metric-value">{attendance_rate:.1f}%</div>
                        <div class="metric-label">Attendance Rate</div>
                    </div>
            """
        body += """
                </div>
        """
        if report_data.get('tickets_sold_by_type'):
            body += """
                <div class="summary-box">
                    <h3>🎫 Ticket Sales Breakdown</h3>
                    <table>
                        <tr><th>Ticket Type</th><th>Quantity</th><th>Revenue</th></tr>
            """
            for ticket_type in report_data['tickets_sold_by_type'].keys():
                quantity = report_data['tickets_sold_by_type'].get(ticket_type, 0)
                revenue = report_data.get('revenue_by_ticket_type', {}).get(ticket_type, 0)
                body += f"<tr><td>{ticket_type}</td><td>{quantity}</td><td>{currency_symbol}{revenue:,.2f}</td></tr>"
            body += """
                    </table>
                </div>
            """
        body += f"""
                <div class="insights">
                    <h3>💡 Key Insights</h3>
                    <ul>
        """
        if report_data.get('total_tickets_sold', 0) > 0:
            attendance_rate = (report_data.get('number_of_attendees', 0) /
                             report_data.get('total_tickets_sold', 1) * 100)
            if attendance_rate > 90:
                body += "<li>Excellent attendance rate! Most ticket holders attended the event.</li>"
            elif attendance_rate > 70:
                body += "<li>Good attendance rate with room for improvement in no-show reduction.</li>"
            else:
                body += "<li>Low attendance rate suggests potential areas for improvement.</li>"
        if report_data.get('revenue_by_ticket_type'):
            max_revenue_type = max(report_data['revenue_by_ticket_type'].items(), key=lambda x: x[1])[0]
            body += f"<li>{max_revenue_type} tickets generated the highest revenue for this event.</li>"
        body += """
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
        attachments = []
        if pdf_path and os.path.exists(pdf_path):
            attachments.append({
                'filename': f'event_report_{event_name.replace(" ", "_")}.pdf',
                'content': open(pdf_path, 'rb').read(),
                'content_type': 'application/pdf'
            })
        if csv_path and os.path.exists(csv_path):
            attachments.append({
                'filename': f'event_data_{event_name.replace(" ", "_")}.csv',
                'content': open(csv_path, 'rb').read(),
                'content_type': 'text/csv'
            })
        success = send_email_with_attachment(
            recipient=recipient_email,
            subject=subject,
            body=body,
            attachments=attachments,
            is_html=True
        )
        return success
