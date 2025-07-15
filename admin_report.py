from flask import jsonify, request, Response, send_file
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func
from datetime import datetime
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import requests
from decimal import Decimal, ROUND_HALF_UP

# Your application-specific imports
from model import User, Event, Organizer, Report, db, Currency, ExchangeRate
from pdf_utils import CSVExporter
from pdf_utils import PDFReportGenerator
from email_utils import send_email_with_attachment

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
    base_currency_code: str = 'KSH'  # Default base currency is Kenyan Shilling
    intermediate_currency_code: str = 'USD'  # Intermediate currency for conversion

class CurrencyConversionService:
    """Service for handling multi-step currency conversion"""

    @staticmethod
    def get_exchange_rate(from_currency: str, to_currency: str, use_latest: bool = True) -> Optional[float]:
        """Get exchange rate between two currencies"""
        try:
            if from_currency == to_currency:
                return 1.0

            # Try to get from database first
            if use_latest:
                rate = ExchangeRate.query.filter_by(
                    from_currency=from_currency,
                    to_currency=to_currency
                ).order_by(ExchangeRate.timestamp.desc()).first()

                if rate and rate.is_current():
                    return float(rate.rate)

            # If not found or not current, fetch from API
            return CurrencyConversionService.fetch_exchange_rate_from_api(from_currency, to_currency)
        except Exception as e:
            logger.error(f"Error getting exchange rate from {from_currency} to {to_currency}: {e}")
            return None

    @staticmethod
    def fetch_exchange_rate_from_api(from_currency: str, to_currency: str) -> Optional[float]:
        """Fetch exchange rate from external API"""
        try:
            # Example using exchangerate-api.com (replace with your preferred API)
            api_url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            if to_currency in data.get('rates', {}):
                rate = float(data['rates'][to_currency])

                # Store in database for caching
                CurrencyConversionService.store_exchange_rate(from_currency, to_currency, rate)
                return rate

            return None
        except Exception as e:
            logger.error(f"Error fetching exchange rate from API: {e}")
            return None

    @staticmethod
    def store_exchange_rate(from_currency: str, to_currency: str, rate: float):
        """Store exchange rate in database"""
        try:
            exchange_rate = ExchangeRate(
                from_currency=from_currency,
                to_currency=to_currency,
                rate=rate,
                timestamp=datetime.utcnow()
            )
            db.session.add(exchange_rate)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error storing exchange rate: {e}")
            db.session.rollback()

    @staticmethod
    def convert_ksh_to_target_currency(ksh_amount: float, target_currency_code: str,
                                       use_latest_rates: bool = True) -> Dict[str, Any]:
        """
        Convert KSH amount to target currency via USD
        KSH → USD → Target Currency
        """
        try:
            ksh_amount = Decimal(str(ksh_amount))

            # Step 1: Convert KSH to USD
            ksh_to_usd_rate = CurrencyConversionService.get_exchange_rate('KSH', 'USD', use_latest_rates)
            if not ksh_to_usd_rate:
                logger.error("Failed to get KSH to USD exchange rate")
                return {
                    'success': False,
                    'error': 'Failed to get KSH to USD exchange rate',
                    'original_amount': float(ksh_amount),
                    'original_currency': 'KSH',
                    'target_currency': target_currency_code
                }

            usd_amount = ksh_amount * Decimal(str(ksh_to_usd_rate))

            # Step 2: Convert USD to target currency
            if target_currency_code == 'USD':
                final_amount = usd_amount
                usd_to_target_rate = 1.0
            else:
                usd_to_target_rate = CurrencyConversionService.get_exchange_rate('USD', target_currency_code, use_latest_rates)
                if not usd_to_target_rate:
                    logger.error(f"Failed to get USD to {target_currency_code} exchange rate")
                    return {
                        'success': False,
                        'error': f'Failed to get USD to {target_currency_code} exchange rate',
                        'original_amount': float(ksh_amount),
                        'original_currency': 'KSH',
                        'target_currency': target_currency_code,
                        'intermediate_amount': float(usd_amount),
                        'intermediate_currency': 'USD'
                    }

                final_amount = usd_amount * Decimal(str(usd_to_target_rate))

            # Round to 2 decimal places
            final_amount = final_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            return {
                'success': True,
                'original_amount': float(ksh_amount),
                'original_currency': 'KSH',
                'intermediate_amount': float(usd_amount),
                'intermediate_currency': 'USD',
                'final_amount': float(final_amount),
                'target_currency': target_currency_code,
                'conversion_rates': {
                    'ksh_to_usd': ksh_to_usd_rate,
                    'usd_to_target': usd_to_target_rate
                },
                'conversion_timestamp': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Error in currency conversion: {e}")
            return {
                'success': False,
                'error': str(e),
                'original_amount': float(ksh_amount) if ksh_amount else 0,
                'original_currency': 'KSH',
                'target_currency': target_currency_code
            }

class AdminReportService:
    @staticmethod
    def format_report_data_for_frontend(report_data, config):
        """Format report data to ensure frontend compatibility with currency conversion"""

        # Ensure events is a list and contains the required fields
        if 'events' not in report_data:
            report_data['events'] = []

        # Get target currency info
        target_currency_code = 'KSH'  # Default
        target_currency_symbol = 'KSh'

        if config.target_currency_id:
            target_currency = Currency.query.get(config.target_currency_id)
            if target_currency:
                target_currency_code = target_currency.code.value
                target_currency_symbol = target_currency.symbol

        # Format each event to ensure numeric values and currency conversion
        formatted_events = []
        for event in report_data.get('events', []):
            original_revenue = float(event.get('revenue', 0))

            # Convert KSH revenue to target currency
            if config.currency_conversion and target_currency_code != 'KSH':
                conversion_result = CurrencyConversionService.convert_ksh_to_target_currency(
                    original_revenue, target_currency_code, config.use_latest_rates
                )
                if conversion_result['success']:
                    converted_revenue = conversion_result['final_amount']
                else:
                    converted_revenue = original_revenue
                    logger.warning(f"Currency conversion failed for event {event.get('event_id')}: {conversion_result.get('error')}")
            else:
                converted_revenue = original_revenue

            formatted_event = {
                'event_id': event.get('event_id', ''),
                'event_name': event.get('event_name', 'Unknown Event'),
                'event_date': event.get('event_date', ''),
                'location': event.get('location', 'N/A'),
                'revenue': converted_revenue,
                'original_revenue_ksh': original_revenue,
                'attendees': int(event.get('attendees', 0)),
                'tickets_sold': int(event.get('tickets_sold', 0)),
                'currency_code': target_currency_code,
                'currency_symbol': target_currency_symbol
            }
            formatted_events.append(formatted_event)

        # Update currency information in report data
        report_data['currency_code'] = target_currency_code
        report_data['currency_symbol'] = target_currency_symbol

        # Calculate summary statistics with converted amounts
        total_converted_revenue = sum(event['revenue'] for event in formatted_events)
        total_original_revenue = sum(event['original_revenue_ksh'] for event in formatted_events)

        report_data['summary'] = {
            'total_events': len(formatted_events),
            'total_revenue': total_converted_revenue,
            'total_revenue_ksh': total_original_revenue,
            'total_attendees': sum(event['attendees'] for event in formatted_events),
            'total_tickets_sold': sum(event['tickets_sold'] for event in formatted_events),
            'currency_code': target_currency_code,
            'currency_symbol': target_currency_symbol
        }
        report_data['events'] = formatted_events
        return report_data

    @staticmethod
    def validate_admin_access(user: User) -> bool:
        """Validate that the user has admin access"""
        return user and user.role.value == "ADMIN"

    @staticmethod
    def get_organizer_by_id(organizer_id: int) -> Optional[User]:
        """Get organizer user by ID"""
        try:
            return User.query.filter_by(id=organizer_id, role='ORGANIZER').first()
        except Exception as e:
            logger.error(f"Database error fetching organizer {organizer_id}: {e}")
            return None

    @staticmethod
    def get_events_by_organizer(organizer_id: int) -> List[Event]:
        """Get all events for a specific organizer"""
        try:
            query = Event.query.join(Organizer).filter(Organizer.user_id == organizer_id)
            return query.all()
        except Exception as e:
            logger.error(f"Database error fetching events for organizer {organizer_id}: {e}")
            return []

    @staticmethod
    def get_reports_by_organizer(organizer_id: int) -> List[Report]:
        """Get all reports for a specific organizer"""
        try:
            query = Report.query.filter_by(organizer_id=organizer_id)
            return query.order_by(Report.timestamp.desc()).all()
        except Exception as e:
            logger.error(f"Database error fetching reports for organizer {organizer_id}: {e}")
            return []

    @staticmethod
    def get_reports_by_event(event_id: int) -> List[Report]:
        """Get all reports for a specific event"""
        try:
            query = Report.query.filter_by(event_id=event_id)
            return query.order_by(Report.timestamp.desc()).all()
        except Exception as e:
            logger.error(f"Database error fetching reports for event {event_id}: {e}")
            return []

    @staticmethod
    def aggregate_organizer_reports(reports: List[Report], target_currency_id: Optional[int] = None,
                                  use_latest_rates: bool = True) -> Dict[str, Any]:
        """Aggregate multiple reports for an organizer with enhanced currency conversion"""
        if not reports:
            return {
                "total_tickets_sold": 0,
                "total_revenue": 0.0,
                "total_revenue_ksh": 0.0,
                "total_attendees": 0,
                "event_count": 0,
                "report_count": 0,
                "currency_code": "KSH",
                "currency_symbol": "KSh",
                "events": []
            }

        # Get target currency info
        target_currency_code = 'KSH'
        target_currency_symbol = 'KSh'

        if target_currency_id:
            target_currency = Currency.query.get(target_currency_id)
            if target_currency:
                target_currency_code = target_currency.code.value
                target_currency_symbol = target_currency.symbol

        total_tickets = sum(report.total_tickets_sold for report in reports)
        total_attendees = sum(report.number_of_attendees or 0 for report in reports)
        total_revenue_ksh = sum(float(report.total_revenue) for report in reports)
        total_converted_revenue = 0.0

        # Convert total revenue from KSH to target currency
        if target_currency_code != 'KSH':
            conversion_result = CurrencyConversionService.convert_ksh_to_target_currency(
                total_revenue_ksh, target_currency_code, use_latest_rates
            )
            if conversion_result['success']:
                total_converted_revenue = conversion_result['final_amount']
            else:
                total_converted_revenue = total_revenue_ksh
                logger.warning(f"Failed to convert total revenue: {conversion_result.get('error')}")
        else:
            total_converted_revenue = total_revenue_ksh

        # Process individual events
        unique_events = list(set(report.event_id for report in reports))
        event_details = []

        for event_id in unique_events:
            event_reports = [r for r in reports if r.event_id == event_id]
            event = Event.query.get(event_id)
            if event:
                event_revenue_ksh = sum(float(r.total_revenue) for r in event_reports)
                event_converted_revenue = 0.0

                # Convert event revenue
                if target_currency_code != 'KSH':
                    conversion_result = CurrencyConversionService.convert_ksh_to_target_currency(
                        event_revenue_ksh, target_currency_code, use_latest_rates
                    )
                    if conversion_result['success']:
                        event_converted_revenue = conversion_result['final_amount']
                    else:
                        event_converted_revenue = event_revenue_ksh
                else:
                    event_converted_revenue = event_revenue_ksh

                event_tickets = sum(r.total_tickets_sold for r in event_reports)
                event_attendees = sum(r.number_of_attendees or 0 for r in event_reports)

                event_details.append({
                    "event_id": event.id,
                    "event_name": event.name,
                    "event_date": event.date.isoformat() if event.date else None,
                    "location": event.location,
                    "tickets_sold": event_tickets,
                    "revenue": event_converted_revenue,
                    "revenue_ksh": event_revenue_ksh,
                    "attendees": event_attendees,
                    "report_count": len(event_reports),
                    "currency_code": target_currency_code,
                    "currency_symbol": target_currency_symbol
                })

        return {
            "total_tickets_sold": total_tickets,
            "total_revenue": total_converted_revenue,
            "total_revenue_ksh": total_revenue_ksh,
            "total_attendees": total_attendees,
            "event_count": len(unique_events),
            "report_count": len(reports),
            "currency_code": target_currency_code,
            "currency_symbol": target_currency_symbol,
            "events": event_details
        }

    @staticmethod
    def aggregate_event_reports(event: Event, reports: List[Report], target_currency_id: Optional[int],
                                  use_latest_rates: bool = True) -> Dict[str, Any]:
        """Aggregate data for a single event with currency conversion"""
        tickets = sum(r.total_tickets_sold for r in reports)
        attendees = sum(r.number_of_attendees or 0 for r in reports)
        revenue_ksh = sum(float(r.total_revenue) for r in reports)

        # Get target currency info
        target_currency_code = 'KSH'
        target_currency_symbol = 'KSh'

        if target_currency_id:
            target_currency = Currency.query.get(target_currency_id)
            if target_currency:
                target_currency_code = target_currency.code.value
                target_currency_symbol = target_currency.symbol

        # Convert revenue to target currency
        converted_revenue = 0.0
        if target_currency_code != 'KSH':
            conversion_result = CurrencyConversionService.convert_ksh_to_target_currency(
                revenue_ksh, target_currency_code, use_latest_rates
            )
            if conversion_result['success']:
                converted_revenue = conversion_result['final_amount']
            else:
                converted_revenue = revenue_ksh
                logger.warning(f"Failed to convert event revenue: {conversion_result.get('error')}")
        else:
            converted_revenue = revenue_ksh

        return {
            "event_id": event.id,
            "event_name": event.name,
            "event_date": event.date.isoformat() if event.date else None,
            "location": event.location,
            "tickets_sold": tickets,
            "attendees": attendees,
            "revenue": converted_revenue,
            "revenue_ksh": revenue_ksh,
            "currency_code": target_currency_code,
            "currency_symbol": target_currency_symbol,
            "report_count": len(reports)
        }

    @staticmethod
    def generate_organizer_summary_report(organizer_id: int, config: AdminReportConfig) -> Dict[str, Any]:
        """Generate a comprehensive summary report for an organizer with currency conversion"""
        try:
            organizer = AdminReportService.get_organizer_by_id(organizer_id)
            if not organizer:
                return {"error": "Organizer not found", "status": 404}

            reports = AdminReportService.get_reports_by_organizer(organizer_id)
            aggregated_data = AdminReportService.aggregate_organizer_reports(
                reports, config.target_currency_id, config.use_latest_rates
            )

            # Get target currency info for display
            target_currency_code = 'KSH'
            target_currency_symbol = 'KSh'

            if config.target_currency_id:
                target_currency = Currency.query.get(config.target_currency_id)
                if target_currency:
                    target_currency_code = target_currency.code.value
                    target_currency_symbol = target_currency.symbol

            summary_report = {
                "organizer_info": {
                    "organizer_id": organizer.id,
                    "organizer_name": organizer.full_name,
                    "email": organizer.email,
                    "phone": organizer.phone_number
                },
                "report_period": {
                    "days": "All available data"
                },
                "currency_settings": {
                    "base_currency": "KSH",
                    "target_currency_id": config.target_currency_id,
                    "target_currency_code": target_currency_code,
                    "target_currency_symbol": target_currency_symbol,
                    "use_latest_rates": config.use_latest_rates,
                    "conversion_enabled": config.currency_conversion
                },
                "summary": aggregated_data,
                "detailed_reports": [
                    {
                        **report.as_dict(),
                        "converted_revenue": CurrencyConversionService.convert_ksh_to_target_currency(
                            float(report.total_revenue), target_currency_code, config.use_latest_rates
                        ) if target_currency_code != 'KSH' else {"final_amount": float(report.total_revenue), "success": True}
                    }
                    for report in reports
                ],
                "generation_timestamp": datetime.utcnow().isoformat()
            }

            # Format the report data for frontend compatibility
            summary_report = AdminReportService.format_report_data_for_frontend(summary_report, config)

            return summary_report
        except Exception as e:
            logger.error(f"Error generating organizer summary report: {e}")
            return {"error": "Failed to generate report", "status": 500}

    @staticmethod
    def generate_event_admin_report(event_id: int, organizer_id: int, config: AdminReportConfig) -> Dict[str, Any]:
        """Generate an admin report for a specific event with currency conversion"""
        try:
            event = Event.query.join(Organizer).filter(
                Event.id == event_id,
                Organizer.user_id == organizer_id
            ).first()

            if not event:
                return {"error": "Event not found or doesn't belong to organizer", "status": 404}

            existing_reports = AdminReportService.get_reports_by_event(event_id)

            # Get target currency info
            target_currency_code = 'KSH'
            target_currency_symbol = 'KSh'

            if config.target_currency_id:
                target_currency = Currency.query.get(config.target_currency_id)
                if target_currency:
                    target_currency_code = target_currency.code.value
                    target_currency_symbol = target_currency.symbol

            fresh_report_data = None
            try:
                if existing_reports:
                    fresh_summary = AdminReportService.aggregate_event_reports(
                        event, existing_reports, config.target_currency_id, config.use_latest_rates
                    )
                    fresh_report_data = {
                        "event_summary": fresh_summary,
                        "report_timestamp": datetime.utcnow().isoformat(),
                        "currency_conversion": {
                            "base_currency": "KSH",
                            "target_currency_id": config.target_currency_id,
                            "target_currency_code": target_currency_code,
                            "use_latest_rates": config.use_latest_rates
                        },
                        "currency_info": {
                            "currency_code": target_currency_code,
                            "currency_symbol": target_currency_symbol
                        }
                    }
                else:
                    fresh_report_data = {
                        "event_summary": {
                            "event_id": event.id,
                            "event_name": event.name,
                            "tickets_sold": 0,
                            "revenue": 0.0,
                            "revenue_ksh": 0.0,
                            "attendees": 0,
                            "currency_code": target_currency_code,
                            "currency_symbol": target_currency_symbol,
                        },
                        "report_timestamp": datetime.utcnow().isoformat(),
                        "currency_conversion": {
                            "base_currency": "KSH",
                            "target_currency_id": config.target_currency_id,
                            "target_currency_code": target_currency_code,
                            "use_latest_rates": config.use_latest_rates
                        },
                        "currency_info": {
                            "currency_code": target_currency_code,
                            "currency_symbol": target_currency_symbol
                        }
                    }
            except Exception as e:
                logger.warning(f"Could not generate fresh report data: {e}")
                fresh_report_data = {
                    "error": "Fresh report generation failed",
                    "details": str(e),
                    "event_summary": {
                        "event_id": event.id,
                        "event_name": event.name,
                        "tickets_sold": 0,
                        "revenue": 0.0,
                        "revenue_ksh": 0.0,
                        "attendees": 0,
                        "currency_code": target_currency_code,
                        "currency_symbol": target_currency_symbol,
                    },
                    "currency_info": {
                        "currency_code": target_currency_code,
                        "currency_symbol": target_currency_symbol
                    }
                }

            admin_report = {
                "event_info": {
                    "event_id": event.id,
                    "event_name": event.name,
                    "event_date": event.date.isoformat() if event.date else None,
                    "location": event.location,
                    "organizer_id": organizer_id,
                    "organizer_name": event.organizer.user.full_name if event.organizer and event.organizer.user else "N/A"
                },
                "report_period": {
                    "days": "All available data"
                },
                "currency_settings": {
                    "base_currency": "KSH",
                    "target_currency_id": config.target_currency_id,
                    "target_currency_code": target_currency_code,
                    "target_currency_symbol": target_currency_symbol,
                    "use_latest_rates": config.use_latest_rates,
                    "conversion_enabled": config.currency_conversion
                },
                "existing_reports": [
                    {
                        **report.as_dict(),
                        "converted_revenue": CurrencyConversionService.convert_ksh_to_target_currency(
                            float(report.total_revenue), target_currency_code, config.use_latest_rates
                        ) if target_currency_code != 'KSH' else {"final_amount": float(report.total_revenue), "success": True}
                    }
                    for report in existing_reports
                ],
                "fresh_report_data": fresh_report_data,
                "summary": {
                    "total_stored_reports": len(existing_reports),
                    "latest_report_date": existing_reports[0].timestamp.isoformat() if existing_reports else None
                },
                "generation_timestamp": datetime.utcnow().isoformat()
            }

            # Format the report data for frontend compatibility
            admin_report = AdminReportService.format_report_data_for_frontend(admin_report, config)

            return admin_report
        except Exception as e:
            logger.error(f"Error generating event admin report: {e}")
            return {"error": "Failed to generate event report", "status": 500}

    @staticmethod
    def send_report_email(report_data: Dict[str, Any], recipient_email: str) -> bool:
        """Send report via email with enhanced formatting and currency conversion info"""
        try:
            is_event_report = 'event_info' in report_data
            currency_symbol = report_data.get('currency_symbol', 'KSh')
            currency_code = report_data.get('currency_code', 'KSH')

            if is_event_report:
                report_title = report_data['event_info'].get('event_name', 'Unknown Event')
                subject = f"Event Analytics Report - {report_title}"
                total_tickets_sold = report_data['fresh_report_data']['event_summary'].get('tickets_sold', 0)
                total_revenue = report_data['fresh_report_data']['event_summary'].get('revenue', 0.0)
                total_revenue_ksh = report_data['fresh_report_data']['event_summary'].get('revenue_ksh', 0.0)
                number_of_attendees = report_data['fresh_report_data']['event_summary'].get('attendees', 0)
            else:
                report_title = report_data['organizer_info'].get('organizer_name', 'Unknown Organizer')
                subject = f"Organizer Summary Report - {report_title}"
                total_tickets_sold = report_data['summary'].get('total_tickets_sold', 0)
                total_revenue = report_data['summary'].get('total_revenue', 0.0)
                total_revenue_ksh = report_data['summary'].get('total_revenue_ksh', 0.0)
                number_of_attendees = report_data['summary'].get('total_attendees', 0)

            # Currency conversion info
            currency_conversion_info = ""
            if currency_code != 'KSH':
                currency_conversion_info = f"""
                <div class="currency-conversion-info" style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 4px; margin: 20px 0;">
                    <h4>💱 Currency Conversion Details</h4>
                    <p><strong>Base Currency:</strong> Kenyan Shilling (KSh)</p>
                    <p><strong>Display Currency:</strong> {currency_code} ({currency_symbol})</p>
                    <p><strong>Original Amount (KSh):</strong> KSh {total_revenue_ksh:,.2f}</p>
                    <p><strong>Converted Amount ({currency_code}):</strong> {currency_symbol}{total_revenue:,.2f}</p>
                    <p><em>Conversion: KSh → USD → {currency_code}</em></p>
                </div>
                """

            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .header {{ background: linear-gradient(135deg, #2E86AB, #A23B72); color: white; padding: 20px; text-align: center; border-bottom: 5px solid #2874a6; }}
                    .container {{ width: 80%; margin: 20px auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
                    h2 {{ color: #2E86AB; border-bottom: 2px solid #A23B72; padding-bottom: 10px; }}
                    .summary-box {{ background: #f9f9f9; border: 1px solid #eee; padding: 15px; margin-bottom: 20px; border-radius: 5px; }}
                    .summary-box p {{ margin: 5px 0; }}
                    .footer {{ text-align: center; margin-top: 30px; font-size: 0.9em; color: #777; }}
                    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    th {{ background-color: #f2f2f2; color: #333; }}
                    .highlight {{ font-weight: bold; color: #A23B72; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📊 Eventbrite Admin Report</h1>
                    <p>Comprehensive Analytics for Your Events</p>
                </div>
                <div class="container">
                    <h2>Report for {report_title}</h2>
                    <p><strong>Date Generated:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>

                    {currency_conversion_info}
                    <div class="summary-box">
                        <h3>Summary</h3>
                        <p>Total Tickets Sold: <span class="highlight">{total_tickets_sold:,.0f}</span></p>
                        <p>Total Attendees: <span class="highlight">{number_of_attendees:,.0f}</span></p>
                        <p>Total Revenue ({currency_code}): <span class="highlight">{currency_symbol}{total_revenue:,.2f}</span></p>
                    </div>
                    <h3>Detailed Event Data</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Event Name</th>
                                <th>Date</th>
                                <th>Location</th>
                                <th>Tickets Sold</th>
                                <th>Attendees</th>
                                <th>Revenue ({currency_code})</th>
                                <th>Original Revenue (KSh)</th>
                            </tr>
                        </thead>
                        <tbody>
            """

            events_data = []
            if is_event_report:
                if 'fresh_report_data' in report_data and 'event_summary' in report_data['fresh_report_data']:
                    event_summary = report_data['fresh_report_data']['event_summary']
                    events_data.append(event_summary)
            elif 'events' in report_data:
                events_data = report_data['events']

            for event in events_data:
                html_body += f"""
                            <tr>
                                <td>{event.get('event_name', 'N/A')}</td>
                                <td>{event.get('event_date', 'N/A')}</td>
                                <td>{event.get('location', 'N/A')}</td>
                                <td>{event.get('tickets_sold', 0):,.0f}</td>
                                <td>{event.get('attendees', 0):,.0f}</td>
                                <td>{currency_symbol}{event.get('revenue', 0.0):,.2f}</td>
                                <td>KSh {event.get('original_revenue_ksh', 0.0):,.2f}</td>
                            </tr>
                """

            html_body += """
                        </tbody>
                    </table>

                    <div class="footer">
                        <p>This report was generated by the Eventbrite Admin System.</p>
                        <p>&copy; 2025 Eventbrite. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            # For simplicity, let's assume send_email_with_attachment can send HTML directly.
            # In a real application, you might want to attach a PDF/CSV version as well.
            return send_email_with_attachment(recipient_email, subject, html_body, content_type="text/html")
        except Exception as e:
            logger.error(f"Error sending report email: {e}")
            return False

class AdminReportResource(Resource):
    """API resource for admin-level reports"""

    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        # Parse query parameters for report configuration
        include_charts = request.args.get('include_charts', 'true').lower() == 'true'
        include_email = request.args.get('include_email', 'false').lower() == 'true'
        format_type = request.args.get('format', 'json').lower()
        currency_conversion = request.args.get('currency_conversion', 'true').lower() == 'true'
        target_currency_id_str = request.args.get('target_currency_id')
        group_by_organizer = request.args.get('group_by_organizer', 'true').lower() == 'true'
        use_latest_rates = request.args.get('use_latest_rates', 'true').lower() == 'true'

        target_currency_id = None
        if target_currency_id_str:
            try:
                target_currency_id = int(target_currency_id_str)
            except ValueError:
                return {"message": "Invalid target_currency_id"}, 400

        config = AdminReportConfig(
            include_charts=include_charts,
            include_email=include_email,
            format_type=format_type,
            currency_conversion=currency_conversion,
            target_currency_id=target_currency_id,
            group_by_organizer=group_by_organizer,
            use_latest_rates=use_latest_rates
        )

        try:
            if config.group_by_organizer:
                # Get all organizers
                organizers = User.query.filter_by(role='ORGANIZER').all()
                all_reports = []
                for organizer in organizers:
                    organizer_reports = AdminReportService.generate_organizer_summary_report(organizer.id, config)
                    if organizer_reports and organizer_reports.get('status') != 404:
                        all_reports.append(organizer_reports)

                final_report_data = {
                    "total_organizers": len(all_reports),
                    "reports_by_organizer": all_reports,
                    "generation_timestamp": datetime.utcnow().isoformat(),
                    "global_currency_settings": {
                        "base_currency": config.base_currency_code,
                        "intermediate_currency": config.intermediate_currency_code,
                        "target_currency_id": config.target_currency_id,
                        "use_latest_rates": config.use_latest_rates,
                        "conversion_enabled": config.currency_conversion
                    }
                }
            else:
                # Generate a global report (not grouped by organizer)
                all_events = Event.query.all()
                global_events_data = []
                for event in all_events:
                    event_reports = AdminReportService.get_reports_by_event(event.id)
                    if event_reports:
                        aggregated_event_data = AdminReportService.aggregate_event_reports(
                            event, event_reports, config.target_currency_id, config.use_latest_rates
                        )
                        global_events_data.append(aggregated_event_data)

                # Calculate overall totals for non-grouped report
                total_tickets_sold = sum(e.get('tickets_sold', 0) for e in global_events_data)
                total_attendees = sum(e.get('attendees', 0) for e in global_events_data)
                total_revenue = sum(e.get('revenue', 0.0) for e in global_events_data)
                total_revenue_ksh = sum(e.get('revenue_ksh', 0.0) for e in global_events_data)

                final_report_data = {
                    "report_type": "Global Event Report",
                    "total_events": len(global_events_data),
                    "summary": {
                        "total_tickets_sold": total_tickets_sold,
                        "total_attendees": total_attendees,
                        "total_revenue": total_revenue,
                        "total_revenue_ksh": total_revenue_ksh,
                        "currency_code": global_events_data[0].get('currency_code', 'KSH') if global_events_data else 'KSH',
                        "currency_symbol": global_events_data[0].get('currency_symbol', 'KSh') if global_events_data else 'KSh'
                    },
                    "events": global_events_data,
                    "generation_timestamp": datetime.utcnow().isoformat(),
                    "global_currency_settings": {
                        "base_currency": config.base_currency_code,
                        "intermediate_currency": config.intermediate_currency_code,
                        "target_currency_id": config.target_currency_id,
                        "use_latest_rates": config.use_latest_rates,
                        "conversion_enabled": config.currency_conversion
                    }
                }

            if config.format_type == 'pdf':
                pdf_output = PDFReportGenerator.generate_admin_report_pdf(final_report_data)
                return Response(pdf_output, mimetype='application/pdf', headers={'Content-Disposition': 'attachment;filename=admin_report.pdf'})
            elif config.format_type == 'csv':
                csv_output = CSVExporter.export_admin_report_to_csv(final_report_data)
                return Response(csv_output, mimetype='text/csv', headers={'Content-Disposition': 'attachment;filename=admin_report.csv'})
            else: # Default to json
                if config.include_email and user.email:
                    email_success = AdminReportService.send_report_email(final_report_data, user.email)
                    if not email_success:
                        logger.error(f"Failed to send email to {user.email}")
                return final_report_data, 200
        except Exception as e:
            logger.error(f"Error generating admin report: {e}")
            return {"message": "Internal server error during report generation", "error": str(e)}, 500

class AdminOrganizerListResource(Resource):
    """API resource for listing all organizers for admin"""

    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        try:
            organizers = User.query.filter_by(role='ORGANIZER').all()
            organizer_list = [{
                'id': org.id,
                'full_name': org.full_name,
                'email': org.email,
                'phone_number': org.phone_number,
                'registration_date': org.created_at.isoformat() if org.created_at else None
            } for org in organizers]

            return organizer_list, 200
        except Exception as e:
            logger.error(f"Error fetching organizer list: {e}")
            return {"message": "Internal server error fetching organizers"}, 500

class AdminEventListResource(Resource):
    """API resource for listing events of a specific organizer for admin"""

    @jwt_required()
    def get(self, organizer_id):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not AdminReportService.validate_admin_access(user):
            return {"message": "Admin access required"}, 403

        organizer = AdminReportService.get_organizer_by_id(organizer_id)
        if not organizer:
            return {"message": "Organizer not found"}, 404

        try:
            events = AdminReportService.get_events_by_organizer(organizer_id)
            event_list = [{
                'event_id': event.id,
                'event_name': event.name,
                'event_date': event.date.isoformat() if event.date else None,
                'location': event.location,
                'description': event.description,
                'total_tickets': event.total_tickets,
                'tickets_available': event.tickets_available,
                'price_per_ticket': float(event.price_per_ticket) if event.price_per_ticket else 0.0,
                'created_at': event.created_at.isoformat() if event.created_at else None
            } for event in events]

            return event_list, 200
        except Exception as e:
            logger.error(f"Error fetching events for organizer {organizer_id}: {e}")
            return {"message": f"Internal server error fetching events for organizer {organizer_id}"}, 500

def register_admin_report_resources(api):
    """Register admin report resources with the Flask-RESTful API"""
    api.add_resource(AdminReportResource, '/admin/reports')
    api.add_resource(AdminOrganizerListResource, '/admin/organizers')
    api.add_resource(AdminEventListResource, '/admin/organizers/<int:organizer_id>/events')
