from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from decimal import Decimal
from model import db, Ticket, TicketType, Transaction, Scan, Event, User, Report, Organizer, Currency, ExchangeRate, PaymentStatus
from .utils import DateUtils, FileManager
from email_utils import send_email_with_attachment
from .report_generators import ChartGenerator, PDFReportGenerator, CSVReportGenerator
from sqlalchemy import func
import logging
import os

from currency_routes import get_exchange_rate, convert_ksh_to_target_currency, rate_cache

logger = logging.getLogger(__name__)

class DatabaseQueryService:
    @staticmethod
    def _convert_enum_to_string(value):
        """Convert enum values to strings for database storage"""
        if hasattr(value, 'value'):
            return str(value.value)
        return str(value)

    @staticmethod
    def get_tickets_sold_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get tickets sold by type for PAID tickets only"""
        try:
            query = (db.session.query(TicketType.type_name, func.count(Ticket.id))
                    .select_from(Ticket)
                    .join(TicketType, Ticket.ticket_type_id == TicketType.id)
                    .filter(
                        Ticket.event_id == event_id,
                        Ticket.payment_status == PaymentStatus.PAID,
                        Ticket.purchase_date >= start_date,
                        Ticket.purchase_date <= end_date
                    )
                    .group_by(TicketType.type_name)
                    .all())
            return [(DatabaseQueryService._convert_enum_to_string(type_name), count) for type_name, count in query]
        except Exception as e:
            logger.error(f"Error in get_tickets_sold_by_type: {e}")
            return []

    @staticmethod
    def get_revenue_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, Decimal]]:
        """Get revenue by type for PAID tickets only - sum of ticket prices"""
        try:
            query = (db.session.query(TicketType.type_name, func.sum(TicketType.price * Ticket.quantity))
                    .select_from(Ticket)
                    .join(TicketType, Ticket.ticket_type_id == TicketType.id)
                    .filter(
                        Ticket.event_id == event_id,
                        Ticket.payment_status == PaymentStatus.PAID,
                        Ticket.purchase_date >= start_date,
                        Ticket.purchase_date <= end_date
                    )
                    .group_by(TicketType.type_name)
                    .all())
            return [(DatabaseQueryService._convert_enum_to_string(type_name),
                    Decimal(str(revenue)) if revenue else Decimal('0')) for type_name, revenue in query]
        except Exception as e:
            logger.error(f"Error in get_revenue_by_type: {e}")
            return []

    @staticmethod
    def get_attendees_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get attendees by type - tickets that have been scanned"""
        try:
            query = (db.session.query(TicketType.type_name, func.count(func.distinct(Scan.ticket_id)))
                    .select_from(Scan)
                    .join(Ticket, Scan.ticket_id == Ticket.id)
                    .join(TicketType, Ticket.ticket_type_id == TicketType.id)
                    .filter(
                        Ticket.event_id == event_id,
                        Scan.scanned_at >= start_date,
                        Scan.scanned_at <= end_date
                    )
                    .group_by(TicketType.type_name)
                    .all())
            return [(DatabaseQueryService._convert_enum_to_string(type_name), count) for type_name, count in query]
        except Exception as e:
            logger.error(f"Error in get_attendees_by_type: {e}")
            return []

    @staticmethod
    def get_payment_method_usage(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get payment method usage for PAID tickets only"""
        try:
            query = (db.session.query(Transaction.payment_method, func.count(Transaction.id))
                    .select_from(Ticket)
                    .join(Transaction, Ticket.transaction_id == Transaction.id)
                    .filter(
                        Ticket.event_id == event_id,
                        Ticket.payment_status == PaymentStatus.PAID,
                        Ticket.purchase_date >= start_date,
                        Ticket.purchase_date <= end_date
                    )
                    .group_by(Transaction.payment_method)
                    .all())
            return [(DatabaseQueryService._convert_enum_to_string(method), count) for method, count in query]
        except Exception as e:
            logger.error(f"Error in get_payment_method_usage: {e}")
            return []

    @staticmethod
    def get_total_revenue(event_id: int, start_date: datetime, end_date: datetime) -> Decimal:
        """Get total revenue for PAID tickets only - sum of ticket prices"""
        try:
            result = (db.session.query(func.sum(TicketType.price * Ticket.quantity))
                     .select_from(Ticket)
                     .join(TicketType, Ticket.ticket_type_id == TicketType.id)
                     .filter(
                         Ticket.event_id == event_id,
                         Ticket.payment_status == PaymentStatus.PAID,
                         Ticket.purchase_date >= start_date,
                         Ticket.purchase_date <= end_date
                     )
                     .scalar())
            return Decimal(str(result)) if result else Decimal('0')
        except Exception as e:
            logger.error(f"Error in get_total_revenue: {e}")
            return Decimal('0')

    @staticmethod
    def get_total_tickets_sold(event_id: int, start_date: datetime, end_date: datetime) -> int:
        """Calculate total_ticket_sold: Sum of tickets that have payment status marked as PAID"""
        try:
            result = (db.session.query(func.sum(Ticket.quantity))
                    .filter(
                        Ticket.event_id == event_id,
                        Ticket.payment_status == PaymentStatus.PAID,
                        Ticket.purchase_date >= start_date,
                        Ticket.purchase_date <= end_date
                    )
                    .scalar())
            return result if result else 0
        except Exception as e:
            logger.error(f"Error in get_total_tickets_sold: {e}")
            return 0

    @staticmethod
    def get_total_attendees(event_id: int, start_date: datetime, end_date: datetime) -> int:
        """Calculate attendees: Number of tickets that have been scanned for the event"""
        try:
            result = (db.session.query(func.count(func.distinct(Scan.ticket_id)))
                    .select_from(Scan)
                    .join(Ticket, Scan.ticket_id == Ticket.id)
                    .filter(
                        Ticket.event_id == event_id,
                        Scan.scanned_at >= start_date,
                        Scan.scanned_at <= end_date
                    )
                    .scalar())
            return result if result else 0
        except Exception as e:
            logger.error(f"Error in get_total_attendees: {e}")
            return 0

    @staticmethod
    def get_event_base_currency(event_id: int) -> str:
        """Get event's base currency code, defaulting to KES"""
        try:
            event = Event.query.get(event_id)
            if event and hasattr(event, 'base_currency_id') and event.base_currency_id:
                currency = Currency.query.get(event.base_currency_id)
                return currency.code if currency else 'KES'
            return 'KES'
        except Exception as e:
            logger.error(f"Error in get_event_base_currency: {e}")
            return 'KES'

class EnhancedCurrencyConverter:
    """Enhanced currency converter that uses the currency exchange rate service"""
    
    @staticmethod
    def get_currency_info(currency_code: str) -> Dict[str, str]:
        """Get currency information from database or return defaults"""
        try:
            currency = Currency.query.filter_by(code=currency_code).first()
            if currency:
                return {
                    'code': currency.code,
                    'symbol': getattr(currency, 'symbol', currency_code),
                    'name': getattr(currency, 'name', currency_code)
                }
        except Exception as e:
            logger.warning(f"Error fetching currency info for {currency_code}: {e}")
        
        # Fallback currency info
        currency_symbols = {
            'KES': '₹', 'USD': '$', 'EUR': '€', 'GBP': '£', 'UGX': 'USh',
            'TZS': 'TSh', 'NGN': '₦', 'GHS': '₵', 'ZAR': 'R', 'JPY': '¥',
            'CAD': 'C$', 'AUD': 'A$'
        }
        
        return {
            'code': currency_code,
            'symbol': currency_symbols.get(currency_code, currency_code),
            'name': currency_code
        }

    @staticmethod
    def convert_amount(amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
        """Convert amount using the integrated currency exchange service"""
        if from_currency == to_currency:
            return amount
        
        try:
            amount = Decimal(str(amount))
            
            # Handle KES conversions directly
            if from_currency == 'KES':
                if to_currency == 'KES':
                    return amount
                
                # Use the convert_ksh_to_target_currency function
                converted_amount, _, _ = convert_ksh_to_target_currency(amount, to_currency)
                return converted_amount
            
            # For non-KES base currencies, convert to KES first, then to target
            elif to_currency == 'KES':
                # Get rate from source currency to KES (reverse of KES to source)
                rate = get_exchange_rate('KES', from_currency)
                kes_amount = amount / rate  # Reverse conversion
                return kes_amount
            
            else:
                # Convert: source -> KES -> target
                # Step 1: Convert from source currency to KES
                source_to_kes_rate = get_exchange_rate('KES', from_currency)
                kes_amount = amount / source_to_kes_rate
                
                # Step 2: Convert from KES to target currency
                converted_amount, _, _ = convert_ksh_to_target_currency(kes_amount, to_currency)
                return converted_amount
                
        except Exception as e:
            logger.error(f"Currency conversion error from {from_currency} to {to_currency}: {e}")
            # Return original amount if conversion fails
            return amount

            
class ReportDataProcessor:
    @staticmethod
    def process_report_data(report_data: Dict[str, Any], event_id: int, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Process comprehensive report data using all available DatabaseQueryService methods."""
        total_tickets_sold = DatabaseQueryService.get_total_tickets_sold(event_id, start_date, end_date)
        total_attendees = DatabaseQueryService.get_total_attendees(event_id, start_date, end_date)
        total_revenue = DatabaseQueryService.get_total_revenue(event_id, start_date, end_date)
        tickets_by_type = DatabaseQueryService.get_tickets_sold_by_type(event_id, start_date, end_date)
        revenue_by_type = DatabaseQueryService.get_revenue_by_type(event_id, start_date, end_date)
        attendees_by_type = DatabaseQueryService.get_attendees_by_type(event_id, start_date, end_date)
        payment_methods = DatabaseQueryService.get_payment_method_usage(event_id, start_date, end_date)
        base_currency_code = DatabaseQueryService.get_event_base_currency(event_id)
        attendance_rate = (total_attendees / total_tickets_sold * 100) if total_tickets_sold > 0 else 0

        processed_data = {
            'total_tickets_sold': total_tickets_sold,
            'number_of_attendees': total_attendees,
            'total_revenue': total_revenue,
            'attendance_rate': round(attendance_rate, 2),
            'tickets_by_type': dict(tickets_by_type),
            'revenue_by_type': {k: float(v) for k, v in revenue_by_type},
            'attendees_by_type': dict(attendees_by_type),
            'payment_method_usage': dict(payment_methods),
            'base_currency_code': base_currency_code,
            'report_start_date': start_date.isoformat(),
            'report_end_date': end_date.isoformat(),
            'currency_conversion_source': 'currencyapi.com',
            'conversion_cache_status': f"{len(rate_cache.cache)} rates cached"
        }

        report_data.update(processed_data)
        return report_data

class ReportService:
    def __init__(self, config):
        self.config = config
        self.chart_generator = ChartGenerator(self.config) if self.config.include_charts else None
        self.pdf_generator = PDFReportGenerator(self.config)
        self.db_service = DatabaseQueryService()
        self.currency_converter = EnhancedCurrencyConverter()

    def _sanitize_report_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize data to ensure all keys and values are database-compatible"""
        sanitized = {}
        for key, value in data.items():
            str_key = str(key.value) if hasattr(key, 'value') else str(key)
            if isinstance(value, dict):
                sanitized_dict = {}
                for k, v in value.items():
                    str_k = str(k.value) if hasattr(k, 'value') else str(k)
                    if hasattr(v, 'value'):
                        sanitized_dict[str_k] = str(v.value)
                    elif isinstance(v, (int, float, str, bool)) or v is None:
                        sanitized_dict[str_k] = v
                    else:
                        sanitized_dict[str_k] = str(v)
                sanitized[str_key] = sanitized_dict
            elif isinstance(value, list):
                sanitized_list = []
                for item in value:
                    if hasattr(item, 'value'):
                        sanitized_list.append(str(item.value))
                    elif isinstance(item, (int, float, str, bool)) or item is None:
                        sanitized_list.append(item)
                    else:
                        sanitized_list.append(str(item))
                sanitized[str_key] = sanitized_list
            elif hasattr(value, 'value'):
                sanitized[str_key] = str(value.value)
            elif isinstance(value, (int, float, str, bool)) or value is None:
                sanitized[str_key] = value
            else:
                sanitized[str_key] = str(value)
        return sanitized

    def _generate_charts(self, report_data: Dict[str, Any]) -> List[str]:
        """Generate charts based on report data and return list of chart file paths"""
        if not self.chart_generator:
            return []
        chart_paths = []
        try:
            # Use consistent field name 'tickets_by_type' (matches PDFReportGenerator)
            if report_data.get('tickets_by_type'):
                tickets_chart = self.chart_generator.create_pie_chart(
                    data=report_data['tickets_by_type'],
                    title="Tickets Sold by Type"
                )
                if tickets_chart:
                    chart_paths.append(tickets_chart)
            
            # Use consistent field name 'revenue_by_ticket_type' (matches PDFReportGenerator)
            if report_data.get('revenue_by_ticket_type'):
                revenue_chart = self.chart_generator.create_bar_chart(
                    data=report_data['revenue_by_ticket_type'],
                    title="Revenue by Ticket Type",
                    xlabel="Ticket Type",
                    ylabel=f"Revenue ({report_data.get('currency_symbol', '$')})"
                )
                if revenue_chart:
                    chart_paths.append(revenue_chart)
            
            if report_data.get('payment_method_usage'):
                payment_chart = self.chart_generator.create_pie_chart(
                    data=report_data['payment_method_usage'],
                    title="Payment Method Usage"
                )
                if payment_chart:
                    chart_paths.append(payment_chart)
            
            if report_data.get('attendees_by_type'):
                attendees_chart = self.chart_generator.create_bar_chart(
                    data=report_data['attendees_by_type'],
                    title="Attendees by Ticket Type",
                    xlabel="Ticket Type",
                    ylabel="Number of Attendees"
                )
                if attendees_chart:
                    chart_paths.append(attendees_chart)
            
            logger.info(f"Generated {len(chart_paths)} charts for event {report_data['event_id']}")
            return chart_paths
        except Exception as e:
            logger.error(f"Error generating charts: {e}")
            return []

    def create_report_data(self, session, event_id: int, start_date: datetime, end_date: datetime,
                            ticket_type_id: Optional[int] = None, target_currency_code: Optional[str] = None) -> Dict[str, Any]:
        """Create report data using the provided session"""
        event = session.query(Event).get(event_id)
        if not event:
            raise ValueError(f"Event with ID {event_id} not found")

        base_currency_code = self.db_service.get_event_base_currency(event_id)
        display_currency_code = target_currency_code or base_currency_code

        base_currency_info = self.currency_converter.get_currency_info(base_currency_code)
        display_currency_info = self.currency_converter.get_currency_info(display_currency_code)

        initial_report_data = {
            'event_id': event_id,
            'event_name': event.name,
            'event_date': event.event_date.isoformat() if hasattr(event, 'event_date') and event.event_date else 'N/A',
            'event_location': getattr(event, 'location', 'N/A'),
            'filter_start_date': start_date.strftime('%Y-%m-%d'),
            'filter_end_date': end_date.strftime('%Y-%m-%d'),
        }

        processed_data = ReportDataProcessor.process_report_data(
            initial_report_data, event_id, start_date, end_date
        )

        # Currency conversion for total revenue
        if base_currency_code != display_currency_code:
            if 'total_revenue' in processed_data:
                original_revenue = processed_data['total_revenue']
                converted_revenue = self.currency_converter.convert_amount(
                    original_revenue, base_currency_code, display_currency_code
                )
                processed_data['original_revenue'] = float(original_revenue)
                processed_data['total_revenue'] = float(converted_revenue)
                processed_data['conversion_rate_used'] = float(
                    self.currency_converter.convert_amount(Decimal('1'), base_currency_code, display_currency_code)
                )

            # Convert revenue_by_ticket_type (consistent with PDFReportGenerator)
            if 'revenue_by_ticket_type' in processed_data:
                converted_revenue_by_type = {}
                for ticket_type, revenue in processed_data['revenue_by_ticket_type'].items():
                    converted_amount = self.currency_converter.convert_amount(
                        Decimal(str(revenue)), base_currency_code, display_currency_code
                    )
                    converted_revenue_by_type[ticket_type] = float(converted_amount)
                processed_data['revenue_by_ticket_type'] = converted_revenue_by_type

        processed_data.update({
            'currency': display_currency_info['code'],
            'currency_symbol': display_currency_info['symbol'],
            'base_currency': base_currency_info['code'],
            'base_currency_symbol': base_currency_info['symbol'],
            'original_currency': base_currency_info['code'],
        })

        if ticket_type_id:
            ticket_type = session.query(TicketType).get(ticket_type_id)
            if ticket_type:
                processed_data['ticket_type_id'] = ticket_type_id
                processed_data['ticket_type_name'] = ticket_type.type_name
                processed_data['report_scope'] = 'ticket_type_summary'
            else:
                processed_data['report_scope'] = 'event_summary'
        else:
            processed_data['report_scope'] = 'event_summary'

        return self._sanitize_report_data(processed_data)

    def save_report_to_database(self, report_data: Dict[str, Any], organizer_id: int, session) -> Optional[Report]:
        """Save report to database using the provided session"""
        base_currency = session.query(Currency).filter_by(code=report_data.get('base_currency', 'KES')).first()
        base_currency_id = base_currency.id if base_currency else None

        if not base_currency_id:
            logger.warning(f"Base currency {report_data.get('base_currency')} not found, using default")
            base_currency = session.query(Currency).filter_by(code='KES').first()
            base_currency_id = base_currency.id if base_currency else 1

        sanitized_report_data = self._sanitize_report_data(report_data)
        report = Report(
            organizer_id=organizer_id,
            event_id=report_data['event_id'],
            ticket_type_id=report_data.get('ticket_type_id'),
            base_currency_id=base_currency_id,
            report_scope=report_data.get('report_scope', 'event_summary'),
            total_tickets_sold=report_data.get('total_tickets_sold', 0),
            total_revenue=Decimal(str(report_data.get('total_revenue', 0))),
            number_of_attendees=report_data.get('number_of_attendees', 0),
            report_data=sanitized_report_data,
            report_date=datetime.now().date()
        )

        session.add(report)
        session.commit()
        logger.info(f"Report saved to database with ID: {report.id}")
        return report

    def generate_complete_report(self, session, event_id: int, organizer_id: int, start_date: datetime,
                                end_date: datetime, ticket_type_id: Optional[int] = None,
                                target_currency_code: Optional[str] = None,
                                send_email: bool = False, recipient_email: str = None) -> Dict[str, Any]:
        """
        Generate a complete report with enhanced currency conversion capabilities
        """
        chart_paths = []
        pdf_path = None
        csv_path = None
        try:
            report_data = self.create_report_data(
                session, event_id, start_date, end_date, ticket_type_id, target_currency_code
            )

            saved_report = self.save_report_to_database(report_data, organizer_id, session)
            if saved_report:
                report_data['database_id'] = saved_report.id

            pdf_path, csv_path = FileManager.generate_unique_paths(event_id)

            if self.config.include_charts and self.chart_generator:
                chart_paths = self._generate_charts(report_data)

            # Updated method signature to match PDFReportGenerator.generate_pdf
            pdf_path = self.pdf_generator.generate_pdf(
                report_data, chart_paths, pdf_path
            )

            csv_path = CSVReportGenerator.generate_csv(report_data, csv_path)

            email_sent = False
            if send_email and recipient_email and self.config.include_email:
                email_sent = self.send_report_email(
                    report_data, pdf_path, csv_path, recipient_email
                )

            return {
                'success': True,
                'report_data': report_data,
                'pdf_path': pdf_path,
                'csv_path': csv_path,
                'chart_paths': chart_paths,
                'email_sent': email_sent,
                'database_id': report_data.get('database_id'),
                'currency_info': {
                    'base_currency': report_data.get('base_currency'),
                    'display_currency': report_data.get('currency'),
                    'conversion_performed': report_data.get('base_currency') != report_data.get('currency'),
                    'cache_entries': report_data.get('conversion_cache_entries', 0)
                }
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

    def send_report_email(self, report_data: Dict[str, Any], pdf_path: str,
                          csv_path: str, recipient_email: str) -> bool:
        """Public method to send report email - delegates to private implementation"""
        try:
            return self._send_report_email(report_data, pdf_path, csv_path, recipient_email)
        except Exception as e:
            logger.error(f"Error sending report email: {e}")
            return False

    def _send_report_email(self, report_data: Dict[str, Any], pdf_path: str,
                           csv_path: str, recipient_email: str) -> bool:
        """Private method that handles the actual email sending logic"""
        event_name = report_data.get('event_name', 'Unknown Event')
        currency_symbol = report_data.get('currency_symbol', '$')
        subject = f"Event Analytics Report - {event_name}"
        start_date = report_data.get('filter_start_date', 'N/A')
        end_date = report_data.get('filter_end_date', 'N/A')

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
                .download-instructions {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .download-instructions h3 {{ color: #856404; margin-top: 0; }}
                .download-instructions p {{ margin-bottom: 10px; }}
                .download-step {{ background: #f8f9fa; padding: 12px; border-left: 3px solid #007bff; margin: 10px 0; }}
                .important-note {{ background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 4px; margin: 20px 0; color: #155724; }}
                .currency-info {{ background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #1976d2; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📊 Event Report</h1>
                <h2>{event_name}</h2>
                <p>Report Period: {start_date} to {end_date}</p>
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
                    <div class="metric">
                        <div class="metric-value">{self._calculate_attendance_rate(report_data):.1f}%</div>
                        <div class="metric-label">Attendance Rate</div>
                    </div>
                </div>
        """

        if report_data.get('base_currency') != report_data.get('currency'):
            base_currency_symbol = report_data.get('base_currency_symbol', report_data.get('base_currency', ''))
            original_revenue = report_data.get('original_revenue', 0)
            conversion_rate = report_data.get('conversion_rate_used', 1)
            body += f"""
                <div class="currency-info">
                    <h4>💱 Currency Conversion Information</h4>
                    <p><strong>Original Amount:</strong> {base_currency_symbol}{original_revenue:,.2f} {report_data.get('base_currency', '')}</p>
                    <p><strong>Converted Amount:</strong> {currency_symbol}{report_data.get('total_revenue', 0):,.2f} {report_data.get('currency', '')}</p>
                    <p><strong>Exchange Rate Used:</strong> 1 {report_data.get('base_currency', '')} = {conversion_rate:.4f} {report_data.get('currency', '')}</p>
                    <p><small>Exchange rates provided by {report_data.get('currency_conversion_source', 'external service')}</small></p>
                </div>
            """

        # Use consistent field names for email content
        if report_data.get('tickets_by_type'):
            body += """
                <div class="summary-box">
                    <h3>🎫 Ticket Sales Breakdown</h3>
                    <table>
                        <tr><th>Ticket Type</th><th>Tickets Sold</th><th>Revenue</th><th>Attendees</th></tr>
            """
            tickets_by_type = report_data.get('tickets_by_type', {})
            revenue_by_type = report_data.get('revenue_by_ticket_type', {})  # Updated to match PDFReportGenerator
            attendees_by_type = report_data.get('attendees_by_type', {})
            for ticket_type in tickets_by_type.keys():
                tickets = tickets_by_type.get(ticket_type, 0)
                revenue = revenue_by_type.get(ticket_type, 0)
                attendees = attendees_by_type.get(ticket_type, 0)
                body += f"<tr><td>{ticket_type}</td><td>{tickets}</td><td>{currency_symbol}{revenue:,.2f}</td><td>{attendees}</td></tr>"
            body += """
                    </table>
                </div>
            """

        if report_data.get('payment_method_usage'):
            body += """
                <div class="summary-box">
                    <h3>💳 Payment Methods</h3>
                    <table>
                        <tr><th>Payment Method</th><th>Transactions</th></tr>
            """
            for method, count in report_data['payment_method_usage'].items():
                body += f"<tr><td>{method}</td><td>{count}</td></tr>"
            body += """
                    </table>
                </div>
            """

        # Add insights section
        body += '<div class="insights"><h3>💡 Key Insights</h3><ul>'
        
        attendance_rate = self._calculate_attendance_rate(report_data)
        if attendance_rate > 90:
            body += "<li>🎉 Excellent attendance rate! Most ticket holders attended the event.</li>"
        elif attendance_rate > 70:
            body += "<li>✅ Good attendance rate with room for improvement in no-show reduction.</li>"
        elif attendance_rate > 0:
            body += "<li>⚠️ Low attendance rate suggests potential areas for improvement in engagement.</li>"

        # Use consistent field name 'revenue_by_ticket_type'
        revenue_by_type = report_data.get('revenue_by_ticket_type', {})
        if revenue_by_type:
            max_revenue_type = max(revenue_by_type.items(), key=lambda x: x[1])[0]
            body += f"<li>💰 {max_revenue_type} tickets generated the highest revenue for this event.</li>"

        tickets_by_type = report_data.get('tickets_by_type', {})
        if tickets_by_type:
            max_sold_type = max(tickets_by_type.items(), key=lambda x: x[1])[0]
            body += f"<li>🎫 {max_sold_type} was the most popular ticket type with {tickets_by_type[max_sold_type]} tickets sold.</li>"

        payment_methods = report_data.get('payment_method_usage', {})
        if payment_methods:
            preferred_method = max(payment_methods.items(), key=lambda x: x[1])[0]
            body += f"<li>💳 {preferred_method} was the preferred payment method for this event.</li>"

        total_tickets = report_data.get('total_tickets_sold', 0)
        total_attendees = report_data.get('number_of_attendees', 0)
        if total_tickets > 0:
            body += f"<li>📊 Out of {total_tickets} tickets sold, {total_attendees} attendees showed up to the event.</li>"

        if report_data.get('base_currency') != report_data.get('currency'):
            cache_entries = report_data.get('conversion_cache_entries', 0)
            body += f"<li>💱 Revenue converted from {report_data.get('base_currency')} to {report_data.get('currency')} using live exchange rates.</li>"
            if cache_entries > 0:
                body += f"<li>⚡ Exchange rate data cached ({cache_entries} rates) for improved performance.</li>"

        body += """
                    </ul>
                </div>
                <div class="download-instructions">
                    <h3>📥 Download Your Complete Report Files</h3>
                    <p><strong>Your detailed report files are ready for download!</strong></p>
                    <p>To access your complete PDF report and CSV data export, please follow these steps:</p>
                    <div class="download-step">
                        <strong>Step 1:</strong> Log in to your Event Management Dashboard in your web browser
                    </div>
                    <div class="download-step">
                        <strong>Step 2:</strong> Navigate to the "Reports" section
                    </div>
                    <div class="download-step">
                        <strong>Step 3:</strong> Find your report for "{event_name}" generated on {datetime.now().strftime('%Y-%m-%d at %H:%M')}
                    </div>
                    <div class="download-step">
                        <strong>Step 4:</strong> Click the download buttons for:
                        <ul>
                            <li><strong>PDF Report:</strong> Complete analytics with charts and visualizations</li>
                            <li><strong>CSV Data:</strong> Raw data for further analysis and processing</li>
                        </ul>
                    </div>
                    <div class="important-note">
                        <strong>📌 Important:</strong> Report files are available for download for 30 days from the generation date.
                        Please download them soon to ensure access to your data.
                    </div>
                </div>
            </div>
            <div class="footer">
                <p>This report was automatically generated by the Event Management System</p>
                <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>Report ID: {report_data.get('database_id', 'N/A')}</p>
                <p>For technical support, please contact our support team.</p>
            </div>
        </body>
        </html>
        """

        try:
            success = send_email_with_attachment(
                recipient=recipient_email,
                subject=subject,
                body=body,
                attachments=[],
                is_html=True
            )
            if success:
                logger.info(f"Report email sent successfully to {recipient_email} for event {event_name}")
            else:
                logger.error(f"Failed to send report email to {recipient_email} for event {event_name}")
            return success
        except Exception as e:
            logger.error(f"Exception while sending report email: {e}")
            return False

    def _calculate_attendance_rate(self, report_data: Dict[str, Any]) -> float:
        """Helper method to calculate attendance rate consistently"""
        total_tickets_sold = report_data.get('total_tickets_sold', 0)
        number_of_attendees = report_data.get('number_of_attendees', 0)
        if total_tickets_sold > 0:
            return (float(number_of_attendees) / total_tickets_sold) * 100
        return 0.0