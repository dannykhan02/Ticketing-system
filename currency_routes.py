import logging
from decimal import Decimal
from datetime import datetime
from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required
from model import db, Currency, ExchangeRate, CurrencyConverter, CurrencyCode, Report
from config import Config
import requests

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_email_with_attachment(recipient, subject, body, attachments=None, is_html=False):
    """Dummy implementation for sending email with attachments."""
    logger.info(f"Sending email to {recipient} with subject '{subject}' and {len(attachments or [])} attachments.")
    return True

def convert_currency(amount, from_currency, to_currency):
    """
    Converts an amount from one currency to another using CurrencyAPI's /v3/latest endpoint.
    """
    if from_currency == to_currency:
        return Decimal(amount), Decimal('1')

    url = "https://api.currencyapi.com/v3/latest"
    params = {"base_currency": from_currency}
    headers = {"apikey": Config.CURRENCY_API_KEY}

    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    data = response.json()

    if to_currency not in data["data"]:
        raise ValueError(f"Currency '{to_currency}' not found.")

    rate = Decimal(str(data["data"][to_currency]["value"]))
    converted_amount = Decimal(amount) * rate
    return converted_amount.quantize(Decimal('0.01')), rate

class CurrencyStatusResource(Resource):
    """
    API resource to check the status of the currency API and related services.
    """
    @jwt_required()
    def get(self):
        try:
            db.session.query(Currency).first()
            db_status = "connected"
        except Exception as e:
            db_status = f"error ({e})"

        external_api_status = "unknown"
        try:
            if Config.CURRENCY_API_KEY:
                url = "https://api.currencyapi.com/v3/latest"
                params = {"base_currency": "USD"}
                headers = {"apikey": Config.CURRENCY_API_KEY}
                response = requests.get(url, params=params, headers=headers)
                response.raise_for_status()
                external_api_status = "reachable"
            else:
                external_api_status = "API Key missing"
        except Exception as e:
            external_api_status = f"error ({e})"

        return {
            "message": "Currency service status",
            "data": {
                "database_connection": db_status,
                "external_currency_api": external_api_status
            }
        }, 200

class CurrencyListResource(Resource):
    """
    API resource to list all active currencies supported by the system.
    """
    @jwt_required()
    def get(self):
        try:
            currencies = Currency.query.filter_by(is_active=True).all()
            currency_list = [{"id": c.id, "code": c.code.value, "name": c.name, "symbol": c.symbol} for c in currencies]
            return {"message": "Active currencies retrieved successfully", "data": currency_list}, 200
        except Exception as e:
            logger.error(f"Error retrieving currency list: {str(e)}")
            return {"message": f"Error retrieving currencies: {str(e)}"}, 500

class CurrencyLatestRatesResource(Resource):
    """
    API resource to get the latest exchange rates for a given base currency.
    """
    @jwt_required()
    def get(self):
        try:
            base_currency = request.args.get('base', 'USD')

            url = "https://api.currencyapi.com/v3/latest"
            params = {"base_currency": base_currency}
            headers = {"apikey": Config.CURRENCY_API_KEY}
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            result = response.json()

            if 'data' not in result or not result['data']:
                return {"message": f"No latest rates found for {base_currency}"}, 404

            rates = {code: data['value'] for code, data in result['data'].items()}
            return {
                "message": f"Latest exchange rates for {base_currency} retrieved successfully",
                "data": {
                    "base_currency": base_currency,
                    "rates": rates,
                    "source": "currencyapi.com"
                }
            }, 200
        except Exception as e:
            logger.error(f"Error fetching latest rates: {str(e)}")
            return {"message": f"Error fetching latest rates: {str(e)}"}, 500

class CurrencyHistoricalRatesResource(Resource):
    """
    API resource to get historical exchange rates for a specific date.
    """
    @jwt_required()
    def get(self, date):
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return {"message": "Invalid date format. Please use YYYY-MM-DD."}, 400

        try:
            base_currency = request.args.get('base', 'USD')

            url = "https://api.currencyapi.com/v3/historical"
            params = {"date": date, "base_currency": base_currency}
            headers = {"apikey": Config.CURRENCY_API_KEY}
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            result = response.json()

            if 'data' not in result or not result['data']:
                return {"message": f"No historical rates found for {base_currency} on {date}"}, 404

            rates = {code: data['value'] for code, data in result['data'].items()}
            return {
                "message": f"Historical exchange rates for {base_currency} on {date} retrieved successfully",
                "data": {
                    "date": date,
                    "base_currency": base_currency,
                    "rates": rates,
                    "source": "currencyapi.com"
                }
            }, 200
        except Exception as e:
            logger.error(f"Error fetching historical rates: {str(e)}")
            return {"message": f"Error fetching historical rates: {str(e)}"}, 500

class CurrencyRangeRatesResource(Resource):
    """
    API resource to get exchange rates for a specified date range.
    """
    @jwt_required()
    def get(self, start_date, end_date):
        try:
            datetime.strptime(start_date, '%Y-%m-%d')
            datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            return {"message": "Invalid date format. Please use YYYY-MM-DD for both start_date and end_date."}, 400

        try:
            base_currency = request.args.get('base', 'USD')

            url = "https://api.currencyapi.com/v3/range"
            params = {"datetime_start": start_date, "datetime_end": end_date, "base_currency": base_currency}
            headers = {"apikey": Config.CURRENCY_API_KEY}
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            result = response.json()

            if 'data' not in result or not result['data']:
                return {"message": f"No range rates found for {base_currency} from {start_date} to {end_date}"}, 404

            formatted_data = {}
            for date_key, data_value in result['data'].items():
                formatted_data[date_key] = {code: item['value'] for code, item in data_value.items()}

            return {
                "message": f"Exchange rates for {base_currency} from {start_date} to {end_date} retrieved successfully",
                "data": {
                    "base_currency": base_currency,
                    "dates": formatted_data,
                    "source": "currencyapi.com"
                }
            }, 200
        except Exception as e:
            logger.error(f"Error fetching range rates: {str(e)}")
            return {"message": f"Error fetching range rates: {str(e)}"}, 500

class CurrencyConvertResource(Resource):
    """
    API resource to convert an amount from one currency to another using the latest rates.
    """
    @jwt_required()
    def get(self, amount):
        from_currency = request.args.get('from')
        to_currency = request.args.get('to')

        if not from_currency or not to_currency:
            return {"message": "'from' and 'to' query parameters are required."}, 400

        try:
            logger.info(f"Converting {amount} from {from_currency} to {to_currency}")

            converted_value, conversion_rate = convert_currency(amount, from_currency, to_currency)

            return {
                "message": "Conversion successful",
                "data": {
                    "original_amount": float(amount),
                    "from_currency": from_currency,
                    "to_currency": to_currency,
                    "converted_amount": float(converted_value),
                    "conversion_rate": float(conversion_rate)
                }
            }, 200
        except Exception as e:
            logger.error(f"Error converting {amount} from {from_currency} to {to_currency}: {str(e)}")
            return {"message": f"Conversion error: {str(e)}"}, 500

class RevenueConvertResource(Resource):
    @jwt_required()
    def get(self):
        try:
            to_currency = request.args.get('to_currency')
            report_id = request.args.get('report_id')
            date_from = request.args.get('date_from')
            date_to = request.args.get('date_to')
            use_latest_rates = request.args.get('use_latest_rates', 'true').lower() == 'true'
            persist_conversion = request.args.get('persist_conversion', 'false').lower() == 'true'

            if not to_currency:
                return {"message": "'to_currency' query parameter is required"}, 400

            target_currency = Currency.query.filter_by(code=CurrencyCode(to_currency), is_active=True).first()
            if not target_currency:
                return {"message": f"Currency '{to_currency}' not found in system"}, 400

            query = Report.query
            if report_id:
                query = query.filter(Report.id == report_id)
            if date_from:
                try:
                    query = query.filter(Report.timestamp >= datetime.strptime(date_from, '%Y-%m-%d').date())
                except ValueError:
                    return {"message": "Invalid date_from format. Use YYYY-MM-DD"}, 400
            if date_to:
                try:
                    query = query.filter(Report.timestamp <= datetime.strptime(date_to, '%Y-%m-%d').date())
                except ValueError:
                    return {"message": "Invalid date_to format. Use YYYY-MM-DD"}, 400

            reports = query.all()
            if not reports:
                return {"message": "No reports found matching the criteria"}, 404

            revenue_by_currency = {}
            reports_by_currency = {}
            for report in reports:
                currency_code = report.base_currency.code.value if report.base_currency else 'USD'
                revenue = report.total_revenue or Decimal('0')
                revenue_by_currency.setdefault(currency_code, Decimal('0'))
                revenue_by_currency[currency_code] += Decimal(str(revenue))
                if currency_code not in reports_by_currency:
                    reports_by_currency[currency_code] = []
                reports_by_currency[currency_code].append(report)

            total_converted = Decimal('0')
            converted_amounts = []
            updated_reports = 0

            for from_currency, amount in revenue_by_currency.items():
                try:
                    if from_currency == to_currency:
                        converted_amount = amount
                        conversion_rate = Decimal('1')
                    elif use_latest_rates:
                        converted_amount, conversion_rate = convert_currency(amount, from_currency, to_currency)
                    else:
                        base = Currency.query.filter_by(code=CurrencyCode(from_currency), is_active=True).first()
                        if not base:
                            return {"message": f"Currency '{from_currency}' not found in local DB"}, 400

                        rate = ExchangeRate.query.filter_by(
                            from_currency_id=base.id,
                            to_currency_id=target_currency.id,
                            is_active=True
                        ).order_by(ExchangeRate.effective_date.desc()).first()

                        if not rate:
                            return {"message": f"No exchange rate found for {from_currency} to {to_currency}"}, 400

                        conversion_rate = Decimal(str(rate.rate))
                        converted_amount = amount * conversion_rate

                    if persist_conversion and from_currency in reports_by_currency:
                        for report in reports_by_currency[from_currency]:
                            individual_rate = conversion_rate
                            individual_converted = (report.total_revenue or Decimal('0')) * individual_rate
                            report.converted_currency_id = target_currency.id
                            report.converted_revenue = individual_converted
                            updated_reports += 1
                            logger.info(f"Updated report {report.id}: {report.total_revenue} {from_currency} -> {individual_converted} {to_currency}")

                    converted_amounts.append({
                        "original_currency": from_currency,
                        "original_amount": float(amount),
                        "converted_currency": to_currency,
                        "converted_amount": float(converted_amount),
                        "conversion_rate": float(conversion_rate),
                        "reports_count": len(reports_by_currency.get(from_currency, []))
                    })

                    total_converted += converted_amount

                except Exception as e:
                    logger.error(f"Error converting {from_currency} to {to_currency}: {str(e)}")
                    return {"message": f"Conversion error for {from_currency}: {str(e)}"}, 500

            if persist_conversion and updated_reports > 0:
                try:
                    db.session.commit()
                    logger.info(f"Successfully persisted conversions to {updated_reports} reports")
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Error persisting converted values: {str(e)}")
                    return {"message": f"Error persisting converted values: {str(e)}"}, 500

            response_data = {
                "total_reports": len(reports),
                "target_currency": to_currency,
                "target_currency_symbol": target_currency.symbol,
                "total_converted_revenue": float(total_converted),
                "breakdown_by_original_currency": converted_amounts,
                "conversion_source": "latest_rates" if use_latest_rates else "local_database",
                "filters_applied": {
                    "report_id": report_id,
                    "date_from": date_from,
                    "date_to": date_to
                },
                "persistence": {
                    "requested": persist_conversion,
                    "reports_updated": updated_reports if persist_conversion else 0
                }
            }

            success_message = f"Revenue successfully converted to {to_currency}"
            if persist_conversion and updated_reports > 0:
                success_message += f" and persisted to {updated_reports} reports"

            return {
                "message": success_message,
                "data": response_data
            }, 200

        except Exception as e:
            logger.error(f"Revenue conversion error: {str(e)}")
            if persist_conversion:
                db.session.rollback()
            return {"message": f"Unexpected error: {str(e)}"}, 500

class ConvertedReportsResource(Resource):
    """
    API resource to retrieve reports that have been converted to specific currencies.
    """
    @jwt_required()
    def get(self):
        try:
            currency_code = request.args.get('currency')
            date_from = request.args.get('date_from')
            date_to = request.args.get('date_to')

            query = Report.query.filter(Report.converted_currency_id.isnot(None))
            if currency_code:
                currency = Currency.query.filter_by(code=CurrencyCode(currency_code), is_active=True).first()
                if currency:
                    query = query.filter(Report.converted_currency_id == currency.id)
            if date_from:
                try:
                    query = query.filter(Report.timestamp >= datetime.strptime(date_from, '%Y-%m-%d').date())
                except ValueError:
                    return {"message": "Invalid date_from format. Use YYYY-MM-DD"}, 400
            if date_to:
                try:
                    query = query.filter(Report.timestamp <= datetime.strptime(date_to, '%Y-%m-%d').date())
                except ValueError:
                    return {"message": "Invalid date_to format. Use YYYY-MM-DD"}, 400

            reports = query.all()
            converted_reports = []
            for report in reports:
                converted_reports.append({
                    "id": report.id,
                    "event_id": report.event_id,
                    "original_revenue": float(report.total_revenue) if report.total_revenue else 0,
                    "original_currency": report.base_currency.code.value if report.base_currency else None,
                    "converted_revenue": float(report.converted_revenue) if report.converted_revenue else 0,
                    "converted_currency": report.converted_currency.code.value if report.converted_currency else None,
                    "conversion_date": report.timestamp.isoformat() if report.timestamp else None,
                    "report_scope": report.report_scope
                })

            return {
                "message": f"Found {len(converted_reports)} reports with conversions",
                "data": {
                    "total_reports": len(converted_reports),
                    "filters_applied": {
                        "currency": currency_code,
                        "date_from": date_from,
                        "date_to": date_to
                    },
                    "reports": converted_reports
                }
            }, 200
        except Exception as e:
            logger.error(f"Error retrieving converted reports: {str(e)}")
            return {"message": f"Error retrieving converted reports: {str(e)}"}, 500

class ClearConvertedDataResource(Resource):
    """
    API resource to clear converted currency data from reports.
    """
    @jwt_required()
    def delete(self):
        try:
            currency_code = request.args.get('currency')
            date_from = request.args.get('date_from')
            date_to = request.args.get('date_to')
            confirm = request.args.get('confirm', 'false').lower() == 'true'

            if not confirm:
                return {"message": "Please add confirm=true to proceed with clearing converted data"}, 400

            query = Report.query.filter(Report.converted_currency_id.isnot(None))
            if currency_code:
                currency = Currency.query.filter_by(code=CurrencyCode(currency_code), is_active=True).first()
                if currency:
                    query = query.filter(Report.converted_currency_id == currency.id)
            if date_from:
                try:
                    query = query.filter(Report.timestamp >= datetime.strptime(date_from, '%Y-%m-%d').date())
                except ValueError:
                    return {"message": "Invalid date_from format. Use YYYY-MM-DD"}, 400
            if date_to:
                try:
                    query = query.filter(Report.timestamp <= datetime.strptime(date_to, '%Y-%m-%d').date())
                except ValueError:
                    return {"message": "Invalid date_to format. Use YYYY-MM-DD"}, 400

            reports = query.all()
            cleared_count = 0
            for report in reports:
                report.converted_currency_id = None
                report.converted_revenue = None
                cleared_count += 1

            db.session.commit()
            logger.info(f"Cleared converted data from {cleared_count} reports")

            return {
                "message": f"Successfully cleared converted data from {cleared_count} reports",
                "data": {
                    "reports_cleared": cleared_count,
                    "filters_applied": {
                        "currency": currency_code,
                        "date_from": date_from,
                        "date_to": date_to
                    }
                }
            }, 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error clearing converted data: {str(e)}")
            return {"message": f"Error clearing converted data: {str(e)}"}, 500

def register_currency_resources(api):
    """
    Register all currency-related API resources with the Flask-RESTFUL API instance.
    """
    api.add_resource(CurrencyStatusResource, "/api/currency/status", endpoint="currency_status")
    api.add_resource(CurrencyListResource, "/api/currency/list", endpoint="currency_list")
    api.add_resource(CurrencyLatestRatesResource, "/api/currency/latest", endpoint="currency_latest")
    api.add_resource(CurrencyHistoricalRatesResource, "/api/currency/historical/<string:date>", endpoint="currency_historical")
    api.add_resource(CurrencyRangeRatesResource, "/api/currency/range/<string:start_date>/<string:end_date>", endpoint="currency_range")
    api.add_resource(CurrencyConvertResource, "/api/currency/convert/<float:amount>", endpoint="currency_convert")
    api.add_resource(RevenueConvertResource, "/api/currency/revenue/convert", endpoint="revenue_convert")
    api.add_resource(ConvertedReportsResource, "/api/currency/reports/converted", endpoint="converted_reports")
    api.add_resource(ClearConvertedDataResource, "/api/currency/reports/clear_converted")
