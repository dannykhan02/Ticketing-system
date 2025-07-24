from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from decimal import Decimal
from model import db, Ticket, TicketType, Transaction, Scan, Event, User, Report, Organizer, Currency, ExchangeRate, PaymentStatus
from .utils import DateUtils, FileManager
from email_utils import send_email_with_attachment
from .report_generators import ChartGenerator
from .report_generators import PDFReportGenerator
from .report_generators import CSVReportGenerator
from sqlalchemy import func, cast, String
import logging
import os
import json
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
                         cast(Ticket.payment_status, String).ilike("paid"),
                         Ticket.purchase_date >= start_date,
                         Ticket.purchase_date <= end_date
                     )
                     .group_by(TicketType.type_name)
                     .all())
            result = [(DatabaseQueryService._convert_enum_to_string(type_name), count) for type_name, count in query]
            logger.debug(f"get_tickets_sold_by_type for event {event_id}: {result}")
            return result
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
                         cast(Ticket.payment_status, String).ilike("paid"),
                         Ticket.purchase_date >= start_date,
                         Ticket.purchase_date <= end_date
                     )
                     .group_by(TicketType.type_name)
                     .all())
            result = [(DatabaseQueryService._convert_enum_to_string(type_name),
                       Decimal(str(revenue)) if revenue else Decimal('0')) for type_name, revenue in query]
            logger.debug(f"get_revenue_by_type for event {event_id}: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in get_revenue_by_type: {e}")
            return []

    @staticmethod
    def get_attendees_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get attendees by type - based on scanned tickets with enhanced debugging"""
        try:
            logger.debug(f"=== DEBUGGING get_attendees_by_type ===")
            logger.debug(f"Event ID: {event_id}, Date range: {start_date} to {end_date}")

            # Check if Scan table has any data
            scan_count = db.session.query(func.count(Scan.id)).scalar()
            logger.debug(f"Total records in Scan table: {scan_count}")

            # Check scans for this specific event (without date filter first)
            event_scans = (db.session.query(func.count(Scan.id))
                          .join(Ticket, Scan.ticket_id == Ticket.id)
                          .filter(Ticket.event_id == event_id)
                          .scalar())
            logger.debug(f"Total scans for event {event_id}: {event_scans}")

            # Original query with debug
            query = (db.session.query(TicketType.type_name, func.count(Scan.ticket_id.distinct()))
                     .join(Ticket, Ticket.id == Scan.ticket_id)
                     .join(TicketType, Ticket.ticket_type_id == TicketType.id)
                     .filter(
                         Ticket.event_id == event_id,
                         Scan.scanned_at >= start_date,
                         Scan.scanned_at <= end_date
                     )
                     .group_by(TicketType.type_name)
                     .all())

            result = [(DatabaseQueryService._convert_enum_to_string(type_name), count) for type_name, count in query]
            logger.debug(f"get_attendees_by_type result: {result}")
            logger.debug(f"=== END DEBUGGING get_attendees_by_type ===")
            return result
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
                         cast(Ticket.payment_status, String).ilike("paid"),
                         Ticket.purchase_date >= start_date,
                         Ticket.purchase_date <= end_date
                     )
                     .group_by(Transaction.payment_method)
                     .all())
            result = [(DatabaseQueryService._convert_enum_to_string(method), count) for method, count in query]
            logger.debug(f"get_payment_method_usage for event {event_id}: {result}")
            return result
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
                          cast(Ticket.payment_status, String).ilike("paid"),
                          Ticket.purchase_date >= start_date,
                          Ticket.purchase_date <= end_date
                      )
                      .scalar())
            total_revenue = Decimal(str(result)) if result else Decimal('0')
            logger.debug(f"get_total_revenue for event {event_id}: {total_revenue}")
            return total_revenue
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
                          cast(Ticket.payment_status, String).ilike("paid"),
                          Ticket.purchase_date >= start_date,
                          Ticket.purchase_date <= end_date
                      )
                      .scalar())
            total_tickets = result if result else 0
            logger.debug(f"get_total_tickets_sold for event {event_id}: {total_tickets}")
            return total_tickets
        except Exception as e:
            logger.error(f"Error in get_total_tickets_sold: {e}")
            return 0

    @staticmethod
    def get_total_attendees(event_id: int, start_date: datetime, end_date: datetime) -> int:
        """Calculate attendees: Count distinct scanned tickets within the date range."""
        try:
            # Add debug logging to understand what's happening
            logger.debug(f"=== DEBUGGING get_total_attendees ===")
            logger.debug(f"Event ID: {event_id}")
            logger.debug(f"Date range: {start_date} to {end_date}")

            # First, check if there are any scans at all for this event
            total_scans_query = (db.session.query(func.count(Scan.id))
                               .join(Ticket, Scan.ticket_id == Ticket.id)
                               .filter(Ticket.event_id == event_id))
            total_scans = total_scans_query.scalar()
            logger.debug(f"Total scans for event {event_id}: {total_scans}")

            # Check scans within date range
            scans_in_range_query = (db.session.query(func.count(Scan.id))
                                  .join(Ticket, Scan.ticket_id == Ticket.id)
                                  .filter(
                                      Ticket.event_id == event_id,
                                      Scan.scanned_at >= start_date,
                                      Scan.scanned_at <= end_date
                                  ))
            scans_in_range = scans_in_range_query.scalar()
            logger.debug(f"Scans in date range: {scans_in_range}")

            # Check if there are any tickets for this event
            total_tickets_query = (db.session.query(func.count(Ticket.id))
                                 .filter(Ticket.event_id == event_id))
            total_tickets = total_tickets_query.scalar()
            logger.debug(f"Total tickets for event {event_id}: {total_tickets}")

            # Original query with enhanced logging
            result = (db.session.query(func.count(Scan.ticket_id.distinct()))
                     .join(Ticket, Scan.ticket_id == Ticket.id)
                     .filter(
                         Ticket.event_id == event_id,
                         Scan.scanned_at >= start_date,
                         Scan.scanned_at <= end_date
                     )
                     .scalar())

            total_attendees = result if result else 0
            logger.debug(f"Final attendees count: {total_attendees}")
            logger.debug(f"=== END DEBUGGING get_total_attendees ===")

            return total_attendees
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
                return currency.code.value if currency and currency.code else 'KES'
            return 'KES'
        except Exception as e:
            logger.error(f"Error in get_event_base_currency: {e}")
            return 'KES'

    @staticmethod
    def get_attendance_rate(event_id: int, start_date: datetime, end_date: datetime) -> float:
        """Calculate attendance rate: (attendees / tickets_sold) * 100"""
        try:
            total_tickets = DatabaseQueryService.get_total_tickets_sold(event_id, start_date, end_date)
            total_attendees = DatabaseQueryService.get_total_attendees(event_id, start_date, end_date)
            if total_tickets == 0:
                return 0.0
            rate = (total_attendees / total_tickets) * 100
            return round(rate, 2)
        except Exception as e:
            logger.error(f"Error calculating attendance rate: {e}")
            return 0.0

class EnhancedCurrencyConverter:
    """Enhanced currency converter that uses the currency exchange rate service"""
    @staticmethod
    def get_currency_info(currency_code: str) -> Dict[str, str]:
        """Get currency information from database or return defaults"""
        try:
            currency = Currency.query.filter_by(code=currency_code).first()
            if currency:
                return {
                    'code': currency.code.value,
                    'symbol': getattr(currency, 'symbol', currency_code),
                    'name': getattr(currency, 'name', currency_code)
                }
        except Exception as e:
            logger.warning(f"Error fetching currency info for {currency_code}: {e}")
        currency_symbols = {
            'KES': 'KSh', 'USD': '$', 'EUR': '€', 'GBP': '£', 'UGX': 'USh',
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
            if from_currency.upper() == 'KES':
                if to_currency.upper() == 'KES':
                    return amount
                converted_amount, _, _ = convert_ksh_to_target_currency(amount, to_currency)
                return converted_amount.quantize(Decimal('0.01'))
            elif to_currency.upper() == 'KES':
                rate = get_exchange_rate(from_currency, 'KES')
                if rate == 0:
                    logger.error(f"Exchange rate for {from_currency} to KES is zero.")
                    return amount
                kes_amount = amount * rate
                return kes_amount.quantize(Decimal('0.01'))
            else:
                source_to_kes_rate = get_exchange_rate(from_currency, 'KES')
                if source_to_kes_rate == 0:
                    logger.error(f"Exchange rate for {from_currency} to KES is zero.")
                    return amount
                kes_amount = amount * source_to_kes_rate
                converted_amount, _, _ = convert_ksh_to_target_currency(kes_amount, to_currency)
                return converted_amount.quantize(Decimal('0.01'))
        except Exception as e:
            logger.error(f"Currency conversion error from {from_currency} to {to_currency}: {e}")
            return amount.quantize(Decimal('0.01'))

class ReportDataProcessor:
    @staticmethod
    def process_report_data(report_data: Dict[str, Any], event_id: int, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Process comprehensive report data using all available DatabaseQueryService methods."""
        total_tickets_sold = DatabaseQueryService.get_total_tickets_sold(event_id, start_date, end_date)
        total_attendees = DatabaseQueryService.get_total_attendees(event_id, start_date, end_date)
        total_revenue = DatabaseQueryService.get_total_revenue(event_id, start_date, end_date)
        attendance_rate = DatabaseQueryService.get_attendance_rate(event_id, start_date, end_date)
        tickets_by_type = DatabaseQueryService.get_tickets_sold_by_type(event_id, start_date, end_date)
        revenue_by_type = DatabaseQueryService.get_revenue_by_type(event_id, start_date, end_date)
        attendees_by_type = DatabaseQueryService.get_attendees_by_type(event_id, start_date, end_date)
        payment_methods = DatabaseQueryService.get_payment_method_usage(event_id, start_date, end_date)
        base_currency_code = DatabaseQueryService.get_event_base_currency(event_id)
        processed_data = {
            'total_tickets_sold': total_tickets_sold,
            'number_of_attendees': total_attendees,
            'total_revenue': total_revenue,
            'attendance_rate': attendance_rate,
            'tickets_by_type': dict(tickets_by_type),
            'revenue_by_type': {k: float(v) for k, v in revenue_by_type},
            'attendees_by_type': dict(attendees_by_type),
            'payment_method_usage': dict(payment_methods),
            'base_currency_code': base_currency_code,
            'report_start_date': start_date.isoformat(),
            'report_end_date': end_date.isoformat(),
            'currency_conversion_source': 'currencyapi.com',
            'conversion_cache_status': f"{len(rate_cache.cache)} rates cached",
            'scan_statistics': {},
            'data_integrity': {'valid': True, 'issues': [], 'recommendations': []},
            'no_show_rate': round(100 - attendance_rate, 2) if attendance_rate is not None else 100.0,
            'revenue_per_attendee': float(total_revenue / total_attendees) if total_attendees > 0 else 0.0,
            'average_ticket_price': float(total_revenue / total_tickets_sold) if total_tickets_sold > 0 else 0.0
        }
        report_data.update(processed_data)
        return report_data

class OrganizerReportService:
    @staticmethod
    def generate_event_metrics(event_id: int) -> Dict[str, Any]:
        logger.info("Generating event metrics for event_id: %s", event_id)
        # Tickets Sold by Type
        tickets_by_type = dict(
            db.session.query(Ticket.ticket_type, db.func.count(Ticket.id))
            .filter(Ticket.event_id == event_id)
            .group_by(Ticket.ticket_type)
            .all()
        )
        # Revenue Calculations
        revenue_original = (
            db.session.query(db.func.sum(Ticket.price))
            .filter(Ticket.event_id == event_id)
            .scalar()
            or 0.0
        )
        # Organizer & Currency
        event = Event.query.get(event_id)
        organizer = Organizer.query.get(event.organizer_id)
        original_currency = organizer.currency if organizer else "USD"
        target_currency = "KES"
        converted_revenue = EnhancedCurrencyConverter.convert_amount(
            amount=Decimal(str(revenue_original)),
            from_currency=original_currency,
            to_currency=target_currency,
        )
        # Corrected Attendees Count (distinct scanned tickets)
        attendees_count = (
            db.session.query(func.count(Scan.ticket_id.distinct()))
            .join(Ticket, Scan.ticket_id == Ticket.id)
            .filter(Ticket.event_id == event_id)
            .scalar()
        )
        logger.info(f"Final attendee count: {attendees_count}")
        # Attendees by type (if you still need this breakdown based on scans)
        attendees_by_type = dict(
            db.session.query(TicketType.type_name, func.count(Scan.ticket_id.distinct()))
            .join(Ticket, Ticket.id == Scan.ticket_id)
            .join(TicketType, Ticket.ticket_type_id == TicketType.id)
            .filter(Ticket.event_id == event_id)
            .group_by(TicketType.type_name)
            .all()
        )
        final_metrics = {
            "tickets_sold": sum(tickets_by_type.values()),
            "tickets_by_type": tickets_by_type,
            "revenue_original": float(revenue_original),
            "revenue_converted": float(converted_revenue),
            "attendees": attendees_count,
            "attendees_by_type": attendees_by_type,
            "original_currency": original_currency,
            "target_currency": target_currency,
        }
        logger.info("Final Organizer Report Metrics: %s", final_metrics)
        return final_metrics

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
            if report_data.get('tickets_by_type'):
                tickets_chart = self.chart_generator.create_pie_chart(
                    data=report_data['tickets_by_type'],
                    title="Tickets Sold by Type"
                )
                if tickets_chart:
                    chart_paths.append(tickets_chart)
            if report_data.get('revenue_by_type'):
                revenue_chart = self.chart_generator.create_bar_chart(
                    data=report_data['revenue_by_type'],
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

    def _validate_and_fix_report_data(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced validation and fixing of inconsistencies in report data before sending email."""
        try:
            logger.debug("=== VALIDATING REPORT DATA ===")
            logger.debug(f"Report data keys: {list(report_data.keys())}")
            total_revenue = float(report_data.get('total_revenue', 0))
            total_tickets_sold = int(report_data.get('total_tickets_sold', 0))
            number_of_attendees = int(report_data.get('number_of_attendees', 0))
            if total_revenue > 0 and total_tickets_sold == 0:
                logger.warning("INCONSISTENCY DETECTED: Revenue exists but tickets sold is 0. Attempting to reconstruct from breakdown data.")
                if report_data.get('tickets_by_type'):
                    reconstructed_tickets = sum(int(count) for count in report_data['tickets_by_type'].values())
                    if reconstructed_tickets > 0:
                        total_tickets_sold = reconstructed_tickets
                        report_data['total_tickets_sold'] = total_tickets_sold
                        logger.info(f"✅ Reconstructed total_tickets_sold from breakdown: {total_tickets_sold}")
            if report_data.get('attendees_by_type'):
                reconstructed_attendees = sum(int(count) for count in report_data['attendees_by_type'].values())
                logger.debug(f"Attendees from breakdown: {reconstructed_attendees}")
                if reconstructed_attendees > number_of_attendees:
                    number_of_attendees = reconstructed_attendees
                    report_data['number_of_attendees'] = number_of_attendees
                    logger.info(f"✅ Updated number_of_attendees from breakdown: {number_of_attendees}")
                elif number_of_attendees > 0 and reconstructed_attendees == 0:
                    report_data['attendees_by_type'] = {'General': number_of_attendees}
                    logger.info(f"🔧 Created default attendees breakdown with {number_of_attendees} attendees")
            elif number_of_attendees > 0:
                report_data['attendees_by_type'] = {'General': number_of_attendees}
                logger.info(f"🔧 Created default attendees breakdown with {number_of_attendees} attendees")
            if total_tickets_sold > 0 and not report_data.get('tickets_by_type'):
                report_data['tickets_by_type'] = {'General': total_tickets_sold}
                logger.info("🔧 Created default tickets breakdown")
            if total_revenue > 0 and not report_data.get('revenue_by_type'):
                report_data['revenue_by_type'] = {'General': total_revenue}
                logger.info("🔧 Created default revenue breakdown")
            if total_tickets_sold > 0:
                attendance_rate = round((number_of_attendees / total_tickets_sold) * 100, 2)
                report_data['attendance_rate'] = attendance_rate
                logger.debug(f"Recalculated attendance rate: {attendance_rate}%")
            else:
                report_data['attendance_rate'] = 0.0
            report_data['total_tickets_sold'] = max(0, int(report_data.get('total_tickets_sold', 0)))
            report_data['number_of_attendees'] = max(0, int(report_data.get('number_of_attendees', 0)))
            report_data['total_revenue'] = max(0.0, float(report_data.get('total_revenue', 0)))
            logger.info(f"=== FINAL VALIDATED DATA ===")
            logger.info(f"Tickets: {report_data['total_tickets_sold']}, Attendees: {report_data['number_of_attendees']}, Revenue: {report_data['total_revenue']}, Rate: {report_data.get('attendance_rate', 0)}%")
            return report_data
        except Exception as e:
            logger.error(f"Error in data validation: {e}")
            return report_data

    def create_report_data(self, event_id: int, start_date: datetime, end_date: datetime,
                          ticket_type_id: Optional[int] = None,
                          target_currency_code: Optional[str] = None) -> Dict[str, Any]:
        logger.info(f"=== CREATING REPORT DATA ===")
        logger.info(f"Event ID: {event_id}, Date Range: {start_date} to {end_date}")
        event = Event.query.get(event_id)
        if not event:
            raise ValueError(f"Event with ID {event_id} not found")
        # Enhanced debugging section
        logger.debug("=== DATABASE INVESTIGATION ===")
        # Check if tickets exist for this event
        ticket_count = db.session.query(func.count(Ticket.id)).filter(Ticket.event_id == event_id).scalar()
        logger.debug(f"Total tickets in database for event {event_id}: {ticket_count}")
        # Check if scans exist
        scan_count = db.session.query(func.count(Scan.id)).scalar()
        logger.debug(f"Total scans in database: {scan_count}")
        # Check if there are scans for tickets of this event
        event_scan_count = (db.session.query(func.count(Scan.id))
                           .join(Ticket, Scan.ticket_id == Ticket.id)
                           .filter(Ticket.event_id == event_id)
                           .scalar())
        logger.debug(f"Scans for event {event_id} tickets: {event_scan_count}")
        # Check scan date ranges
        if event_scan_count > 0:
            scan_date_range = (db.session.query(
                                func.min(Scan.scanned_at),
                                func.max(Scan.scanned_at)
                              )
                              .join(Ticket, Scan.ticket_id == Ticket.id)
                              .filter(Ticket.event_id == event_id)
                              .first())
            logger.debug(f"Scan date range for event {event_id}: {scan_date_range}")
            logger.debug(f"Requested date range: {start_date} to {end_date}")
        logger.debug("=== END DATABASE INVESTIGATION ===")
        base_currency_code = self.db_service.get_event_base_currency(event_id)
        display_currency_code = target_currency_code or base_currency_code
        base_currency_info = self.currency_converter.get_currency_info(base_currency_code)
        display_currency_info = self.currency_converter.get_currency_info(display_currency_code)
        logger.debug("Fetching raw database data...")
        tickets_sold_data = self.db_service.get_tickets_sold_by_type(event_id, start_date, end_date)
        logger.debug(f"Raw tickets_sold_data: {tickets_sold_data}")
        revenue_data = self.db_service.get_revenue_by_type(event_id, start_date, end_date)
        logger.debug(f"Raw revenue_data: {revenue_data}")
        attendees_data = self.db_service.get_attendees_by_type(event_id, start_date, end_date)
        logger.debug(f"Raw attendees_data: {attendees_data}")
        payment_methods = self.db_service.get_payment_method_usage(event_id, start_date, end_date)
        logger.debug(f"Raw payment_methods: {payment_methods}")
        tickets_sold_by_type = dict(tickets_sold_data)
        attendees_by_ticket_type = dict(attendees_data)
        payment_method_usage = dict(payment_methods)
        total_revenue_base = self.db_service.get_total_revenue(event_id, start_date, end_date)
        logger.debug(f"Total revenue (base currency): {total_revenue_base}")
        total_revenue_display = self.currency_converter.convert_amount(
            total_revenue_base, base_currency_code, display_currency_code
        )
        logger.debug(f"Total revenue (display currency): {total_revenue_display}")
        revenue_by_ticket_type = {}
        for ticket_type, revenue in revenue_data:
            converted_revenue = self.currency_converter.convert_amount(
                revenue, base_currency_code, display_currency_code
            )
            revenue_by_ticket_type[ticket_type] = float(converted_revenue)
        total_tickets_sold = self.db_service.get_total_tickets_sold(event_id, start_date, end_date)
        logger.debug(f"Total tickets sold: {total_tickets_sold}")
        total_attendees = self.db_service.get_total_attendees(event_id, start_date, end_date)
        logger.debug(f"Total attendees from DB service: {total_attendees}")
        # FALLBACK 1: If no scans but tickets sold, check if event requires scanning
        if total_attendees == 0 and total_tickets_sold > 0:
            logger.warning("⚠️ No attendees found but tickets were sold - investigating...")
            # Check if this is a data issue or if scanning hasn't started
            if event_scan_count == 0:
                logger.warning("🔍 No scans recorded for this event at all")
                logger.warning("💡 This could mean:")
                logger.warning("   1. Event hasn't started yet")
                logger.warning("   2. Scanning system not used")
                logger.warning("   3. Data integrity issue")
                # FALLBACK OPTION: Use tickets sold as potential attendees
                # (This should be configurable based on event type)
                logger.info("🔧 Consider using tickets sold as estimated attendees if event doesn't use scanning")
            elif event_scan_count > 0:
                logger.warning("🔍 Scans exist for this event but not in date range")
                logger.warning("💡 Check if date range is correct")
        # Calculate attendance rate
        attendance_rate = 0.0
        if total_tickets_sold > 0:
            attendance_rate = (total_attendees / total_tickets_sold * 100)
            logger.debug(f"Calculated attendance rate: {attendance_rate}%")
        else:
            logger.info("No tickets sold for this date range - attendance rate set to 0%")
        # Handle empty breakdowns
        if total_attendees > 0 and not attendees_by_ticket_type:
            logger.warning("Have total attendees but no breakdown - creating default breakdown")
            attendees_by_ticket_type = {'General': total_attendees}
        if total_tickets_sold > 0 and not tickets_sold_by_type:
            logger.warning("Have total tickets but no breakdown - creating default breakdown")
            tickets_sold_by_type = {'General': total_tickets_sold}
        # Build report data
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
            'attendance_rate': round(attendance_rate, 2),
            'tickets_by_type': tickets_sold_by_type,
            'revenue_by_type': revenue_by_ticket_type,
            'attendees_by_type': attendees_by_ticket_type,
            'payment_method_usage': payment_method_usage,
            'currency': display_currency_info['code'],
            'currency_symbol': display_currency_info['symbol'],
            'base_currency': base_currency_info['code'],
            'base_currency_symbol': base_currency_info['symbol'],
            'currency_conversion_source': 'currencyapi.com (with fallback)',
            'conversion_cache_entries': len(rate_cache.cache),
            # Debug info
            'debug_info': {
                'total_tickets_in_db': ticket_count,
                'total_scans_in_db': scan_count,
                'event_scans_count': event_scan_count,
                'scan_date_range_check': scan_date_range if event_scan_count > 0 else None,
                'requested_date_range': f"{start_date} to {end_date}"
            }
        }
        # Handle currency conversion info
        if base_currency_code != display_currency_code:
            report_data['original_revenue'] = float(total_revenue_base)
            report_data['original_currency'] = base_currency_info['code']
            report_data['conversion_rate_used'] = float(
                self.currency_converter.convert_amount(Decimal('1'), base_currency_code, display_currency_code)
            )
        # Handle ticket type filtering
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
        logger.info(f"=== REPORT DATA CREATED ===")
        logger.info(f"Final attendee count: {report_data['number_of_attendees']}")
        logger.info(f"Final attendance rate: {report_data['attendance_rate']}%")
        logger.info(f"Attendees by type: {report_data['attendees_by_type']}")
        # Additional diagnostic info
        if total_attendees == 0 and total_tickets_sold > 0:
            logger.warning("⚠️ ATTENTION: Zero attendees with non-zero ticket sales")
            logger.warning(f"📊 Tickets sold: {total_tickets_sold}")
            logger.warning(f"📅 Date range: {start_date} to {end_date}")
            logger.warning(f"🎫 Event scans available: {event_scan_count}")
        return self._sanitize_report_data(report_data)

    def save_report_to_database(self, report_data: Dict[str, Any], organizer_id: int) -> Optional[Report]:
        try:
            base_currency = Currency.query.filter_by(code=report_data.get('base_currency', 'KES')).first()
            base_currency_id = base_currency.id if base_currency else None
            if not base_currency_id:
                logger.warning(f"Base currency {report_data.get('base_currency')} not found, using default")
                base_currency = Currency.query.filter_by(code='KES').first()
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
            db.session.add(report)
            db.session.commit()
            logger.info(f"Report saved to database with ID: {report.id}")
            return report
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error saving report to database: {e}")
            raise

    def generate_complete_report(self, event_id: int, organizer_id: int, start_date: datetime,
                                end_date: datetime, session, ticket_type_id: Optional[int] = None,
                                target_currency_code: Optional[str] = None,
                                send_email: bool = False, recipient_email: str = None) -> Dict[str, Any]:
        chart_paths = []
        pdf_path = None
        csv_path = None
        try:
            report_data = self.create_report_data(
                event_id, start_date, end_date, ticket_type_id, target_currency_code
            )
            saved_report = self.save_report_to_database(report_data, organizer_id)
            if saved_report:
                report_data['database_id'] = saved_report.id
            pdf_path, csv_path = FileManager.generate_unique_paths(event_id)
            if self.config.include_charts and self.chart_generator:
                chart_paths = self._generate_charts(report_data)
            pdf_path = self.pdf_generator.generate_pdf(
                report_data=report_data,
                chart_paths=chart_paths,
                output_path=pdf_path,
                session=session,
                event_id=event_id,
                target_currency=target_currency_code or "KES"
            )
            csv_path = CSVReportGenerator.generate_csv(
                report_data=report_data,
                output_path=csv_path,
                session=session,
                event_id=event_id
            )
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
        try:
            if report_data.get('conversion_rate_used') is not None or report_data.get('target_currency'):
                logger.info("Using pre-processed report data for email (skipping validation)")
                validated_report_data = report_data
            else:
                logger.info("Applying validation to raw report data")
                validated_report_data = self._validate_and_fix_report_data(report_data.copy())
            return self._send_report_email(validated_report_data, pdf_path, csv_path, recipient_email)
        except Exception as e:
            logger.error(f"Error sending report email: {e}")
            return False

    def _send_report_email(self, report_data: Dict[str, Any], pdf_path: str,
                           csv_path: str, recipient_email: str) -> bool:
        event_name = report_data.get('event_name', 'Unknown Event')
        currency_symbol = report_data.get('currency_symbol', '$')
        subject = f"Event Analytics Report - {event_name}"
        start_date = report_data.get('filter_start_date', 'N/A')
        end_date = report_data.get('filter_end_date', 'N/A')
        total_tickets_sold = max(0, int(report_data.get('total_tickets_sold', 0)))
        total_revenue = max(0.0, float(report_data.get('total_revenue', 0)))
        number_of_attendees = max(0, int(report_data.get('number_of_attendees', 0)))
        attendance_rate = max(0.0, float(report_data.get('attendance_rate', 0)))

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
                .warning {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 4px; margin: 20px 0; color: #856404; }}
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
                        <div class="metric-value">{total_tickets_sold:,}</div>
                        <div class="metric-label">Tickets Sold</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{currency_symbol}{total_revenue:,.2f}</div>
                        <div class="metric-label">Total Revenue</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{number_of_attendees:,}</div>
                        <div class="metric-label">Attendees</div>
                    </div>
                    <div class="metric">
                        <div class="metric-value">{attendance_rate:.1f}%</div>
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
        if report_data.get('tickets_by_type'):
            body += """
                <div class="summary-box">
                    <h3>🎫 Ticket Sales Breakdown</h3>
                    <table>
                        <tr><th>Ticket Type</th><th>Tickets Sold</th><th>Revenue</th><th>Attendees</th></tr>
            """
            tickets_by_type = report_data.get('tickets_by_type', {})
            revenue_by_type = report_data.get('revenue_by_type', {})
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
        body += f"""
                <div class="insights">
                    <h3>💡 Key Insights</h3>
                    <ul>
        """
        if attendance_rate > 90:
            body += "<li>🎉 Excellent attendance rate! Most ticket holders attended the event.</li>"
        elif attendance_rate > 70:
            body += "<li>✅ Good attendance rate with room for improvement in no-show reduction.</li>"
        elif attendance_rate > 0:
            body += "<li>⚠️ Low attendance rate suggests potential areas for improvement in engagement.</li>"
        else:
            body += "<li>ℹ️ No attendance data recorded for this event period.</li>"
        if report_data.get('revenue_by_type'):
            max_revenue_type = max(report_data['revenue_by_type'].items(), key=lambda x: x[1])[0]
            body += f"<li>💰 {max_revenue_type} tickets generated the highest revenue for this event.</li>"
        if report_data.get('tickets_by_type'):
            max_sold_type = max(report_data['tickets_by_type'].items(), key=lambda x: x[1])[0]
            body += f"<li>🎫 {max_sold_type} was the most popular ticket type with {report_data['tickets_by_type'][max_sold_type]} tickets sold.</li>"
        if report_data.get('payment_method_usage'):
            preferred_method = max(report_data['payment_method_usage'].items(), key=lambda x: x[1])[0]
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
