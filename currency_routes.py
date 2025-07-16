import logging
from decimal import Decimal
from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required
from model import db, Currency, CurrencyCode
from config import Config
import requests

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_exchange_rate(from_currency, to_currency):
    """
    Get exchange rate from CurrencyAPI using /v3/latest endpoint.
    """
    if from_currency == to_currency:
        return Decimal('1')

    url = "https://api.currencyapi.com/v3/latest"
    params = {"base_currency": from_currency}
    headers = {"apikey": Config.CURRENCY_API_KEY}

    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        if to_currency not in data["data"]:
            raise ValueError(f"Currency '{to_currency}' not found in exchange rates.")

        rate = Decimal(str(data["data"][to_currency]["value"]))
        return rate
    except Exception as e:
        logger.error(f"Error fetching exchange rate from {from_currency} to {to_currency}: {str(e)}")
        raise

def convert_ksh_to_target_currency(ksh_amount, target_currency):
    """
    Convert KSH amount to target currency via USD (KSH → USD → Target Currency).
    This is the core conversion logic for your system.
    """
    ksh_amount = Decimal(str(ksh_amount))
    
    if target_currency == "KES":
        return ksh_amount, Decimal('1'), Decimal('1')
    
    # Step 1: Convert KSH to USD
    ksh_to_usd_rate = get_exchange_rate("KES", "USD")
    usd_amount = ksh_amount * ksh_to_usd_rate
    
    if target_currency == "USD":
        return usd_amount, ksh_to_usd_rate, Decimal('1')
    
    # Step 2: Convert USD to target currency
    usd_to_target_rate = get_exchange_rate("USD", target_currency)
    target_amount = usd_amount * usd_to_target_rate
    
    return target_amount, ksh_to_usd_rate, usd_to_target_rate

class CurrencyListResource(Resource):
    """
    API resource to list all active currencies with their current exchange rates from KSH.
    """
    @jwt_required()
    def get(self):
        try:
            # Get all active currencies from database
            currencies = Currency.query.filter_by(is_active=True).all()
            
            if not currencies:
                return {"message": "No active currencies found"}, 404
            
            currency_list = []
            
            for currency in currencies:
                currency_code = currency.code.value
                try:
                    # Get exchange rate from KSH to this currency
                    if currency_code == "KES":
                        rate = Decimal('1')
                    else:
                        # Two-step conversion: KSH → USD → Target Currency
                        ksh_to_usd_rate = get_exchange_rate("KES", "USD")
                        if currency_code == "USD":
                            rate = ksh_to_usd_rate
                        else:
                            usd_to_target_rate = get_exchange_rate("USD", currency_code)
                            rate = ksh_to_usd_rate * usd_to_target_rate
                    
                    currency_list.append({
                        "id": currency.id,
                        "code": currency_code,
                        "name": currency.name,
                        "symbol": currency.symbol,
                        "exchange_rate_from_ksh": float(rate),
                        "description": f"1 KSH = {float(rate)} {currency_code}"
                    })
                    
                except Exception as e:
                    logger.warning(f"Could not fetch rate for {currency_code}: {str(e)}")
                    currency_list.append({
                        "id": currency.id,
                        "code": currency_code,
                        "name": currency.name,
                        "symbol": currency.symbol,
                        "exchange_rate_from_ksh": None,
                        "description": f"Rate unavailable for {currency_code}"
                    })
            
            return {
                "message": "Active currencies with exchange rates retrieved successfully",
                "data": {
                    "base_currency": "KES",
                    "currencies": currency_list,
                    "total_currencies": len(currency_list)
                }
            }, 200
            
        except Exception as e:
            logger.error(f"Error retrieving currency list: {str(e)}")
            return {"message": f"Error retrieving currencies: {str(e)}"}, 500

class CurrencyConvertResource(Resource):
    """
    API resource to convert KSH amount to selected currency via USD.
    This handles the core conversion logic: KSH → USD → Selected Currency
    """
    @jwt_required()
    def get(self):
        try:
            # Get parameters
            ksh_amount = request.args.get('amount')
            target_currency = request.args.get('to_currency')
            
            # Validate parameters
            if not ksh_amount or not target_currency:
                return {
                    "message": "Both 'amount' and 'to_currency' parameters are required."
                }, 400
            
            try:
                ksh_amount = float(ksh_amount)
                if ksh_amount <= 0:
                    return {"message": "Amount must be greater than 0."}, 400
            except ValueError:
                return {"message": "Invalid amount format."}, 400
            
            # Verify target currency exists in system
            target_currency_obj = Currency.query.filter_by(
                code=CurrencyCode(target_currency), 
                is_active=True
            ).first()
            
            if not target_currency_obj:
                return {
                    "message": f"Currency '{target_currency}' not found or not active in system."
                }, 400
            
            # Perform conversion
            logger.info(f"Converting {ksh_amount} KSH to {target_currency}")
            
            converted_amount, ksh_to_usd_rate, usd_to_target_rate = convert_ksh_to_target_currency(
                ksh_amount, target_currency
            )
            
            # Calculate overall conversion rate
            overall_rate = ksh_to_usd_rate * usd_to_target_rate if target_currency != "KES" else Decimal('1')
            
            return {
                "message": "Conversion successful",
                "data": {
                    "original_amount": ksh_amount,
                    "original_currency": "KES",
                    "target_currency": target_currency,
                    "target_currency_symbol": target_currency_obj.symbol,
                    "converted_amount": float(converted_amount.quantize(Decimal('0.01'))),
                    "conversion_steps": {
                        "step_1": {
                            "description": "KSH to USD",
                            "rate": float(ksh_to_usd_rate),
                            "amount": float((Decimal(str(ksh_amount)) * ksh_to_usd_rate).quantize(Decimal('0.01')))
                        },
                        "step_2": {
                            "description": f"USD to {target_currency}",
                            "rate": float(usd_to_target_rate),
                            "amount": float(converted_amount.quantize(Decimal('0.01')))
                        }
                    },
                    "overall_conversion_rate": float(overall_rate),
                    "source": "currencyapi.com"
                }
            }, 200
            
        except Exception as e:
            logger.error(f"Error converting KSH to {target_currency}: {str(e)}")
            return {"message": f"Conversion error: {str(e)}"}, 500

class CurrencyStatusResource(Resource):
    """
    API resource to check the status of the currency API and database.
    """
    @jwt_required()
    def get(self):
        try:
            # Check database connection
            db.session.query(Currency).first()
            db_status = "connected"
        except Exception as e:
            db_status = f"error ({e})"

        # Check external API status
        external_api_status = "unknown"
        try:
            if Config.CURRENCY_API_KEY:
                url = "https://api.currencyapi.com/v3/latest"
                params = {"base_currency": "KES"}
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
                "external_currency_api": external_api_status,
                "base_currency": "KES",
                "conversion_method": "KSH → USD → Target Currency"
            }
        }, 200

def register_currency_resources(api):
    """
    Register streamlined currency API resources with the Flask-RESTFUL API instance.
    """
    api.add_resource(CurrencyStatusResource, "/api/currency/status", endpoint="currency_status")
    api.add_resource(CurrencyListResource, "/api/currency/list", endpoint="currency_list")
    api.add_resource(CurrencyConvertResource, "/api/currency/convert", endpoint="currency_convert")