import logging
from datetime import datetime, time
from typing import Optional, Tuple, Dict
from decimal import Decimal
import tempfile
import os

# FIXED: Add the missing imports
from model import Currency, ExchangeRate

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_email_with_attachment(recipient, subject, body, attachments=None, is_html=False):
    logger.info(f"Sending email to {recipient} with subject '{subject}' and {len(attachments or [])} attachments.")
    return True

class DateUtils:
    @staticmethod
    def parse_date_param(date_str: str, param_name: str) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            logger.warning(f"Invalid {param_name} format: {date_str}. Expected YYYY-MM-DD.")
            return None

    @staticmethod
    def adjust_end_date(end_date: datetime) -> datetime:
        if isinstance(end_date, datetime):
            return end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            return datetime.combine(end_date, time(23, 59, 59, 999999))

class CurrencyConverter:
    @staticmethod
    def convert_amount(amount: Decimal, from_currency_id: int, to_currency_id: int) -> Decimal:
        if from_currency_id == to_currency_id:
            return amount
        rate = ExchangeRate.query.filter_by(
            from_currency_id=from_currency_id,
            to_currency_id=to_currency_id,
            is_active=True
        ).order_by(ExchangeRate.effective_date.desc()).first()
        if rate:
            return amount * rate.rate
        logger.warning(f"No exchange rate found from currency {from_currency_id} to {to_currency_id}")
        return amount

    @staticmethod
    def get_currency_info(currency_id: int) -> Dict[str, str]:
        currency = Currency.query.get(currency_id)
        if currency:
            return {
                'code': currency.code,
                'symbol': currency.symbol or '$'
            }
        return {'code': 'USD', 'symbol': '$'}

class FileManager:
    @staticmethod
    def generate_unique_paths(event_id: int) -> Tuple[str, str]:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pdf_path = tempfile.mktemp(suffix=f'_event_{event_id}_{timestamp}.pdf')
        csv_path = tempfile.mktemp(suffix=f'_event_{event_id}_{timestamp}.csv')
        return pdf_path, csv_path

    @staticmethod
    def cleanup_files(file_paths: list):
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.warning(f"Failed to remove file {file_path}: {e}")

# FIXED: Add missing AuthorizationMixin class that was referenced in organizer_report.py
class AuthorizationMixin:
    @staticmethod
    def get_current_user():
        from flask_jwt_extended import get_jwt_identity
        from model import User
        
        current_user_id = get_jwt_identity()
        return User.query.get(current_user_id)
    
    @staticmethod
    def check_organizer_access(user):
        from model import Organizer
        
        if not user:
            return False
        
        # Check if user is an organizer
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        return organizer is not None
    
    @staticmethod
    def check_event_ownership(event, user):
        from model import Organizer, UserRole
        
        if not user or not event:
            return False
        
        # Check if user is admin
        if hasattr(user, 'role') and user.role == UserRole.ADMIN:
            return True
        
        # Check if user owns the event through organizer profile
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if organizer and event.organizer_id == organizer.id:
            return True
        
        return False

class DateValidator:
    @staticmethod
    def validate_date_range(start_date_str: str, end_date_str: str) -> Tuple[Optional[datetime], Optional[datetime], Optional[dict]]:
        """
        Validate and parse date range parameters
        
        Returns:
            Tuple of (start_date, end_date, error_dict)
            If error_dict is not None, there was a validation error
        """
        start_date = None
        end_date = None
        
        if start_date_str:
            start_date = DateUtils.parse_date_param(start_date_str, 'start_date')
            if not start_date:
                return None, None, {'error': 'Invalid start_date format. Use YYYY-MM-DD.', 'status': 400}
        
        if end_date_str:
            end_date = DateUtils.parse_date_param(end_date_str, 'end_date')
            if not end_date:
                return None, None, {'error': 'Invalid end_date format. Use YYYY-MM-DD.', 'status': 400}
        
        # If both dates provided, validate range
        if start_date and end_date:
            if start_date > end_date:
                return None, None, {'error': 'start_date cannot be after end_date', 'status': 400}
        
        # Adjust end date to end of day if provided
        if end_date:
            end_date = DateUtils.adjust_end_date(end_date)
        
        return start_date, end_date, None