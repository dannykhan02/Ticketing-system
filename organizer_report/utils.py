import logging
from datetime import datetime, time
from typing import Optional, Tuple, Dict
from decimal import Decimal
import tempfile
import os

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
