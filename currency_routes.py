import logging
from decimal import Decimal
from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required
from model import db, Currency, CurrencyCode
from config import Config
import requests
from datetime import datetime, timedelta
import time

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory cache for exchange rates
class ExchangeRateCache:
    def __init__(self, cache_duration_minutes=60):
        self.cache = {}
        self.cache_duration = timedelta(minutes=cache_duration_minutes)
        self.last_api_call = {}
        self.min_api_interval = 10  # Minimum seconds between API calls
    
    def get_cached_rate(self, from_currency, to_currency):
        """Get cached exchange rate if available and not expired"""
        cache_key = f"{from_currency}_{to_currency}"
        
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if datetime.now() - cached_data['timestamp'] < self.cache_duration:
                logger.info(f"Using cached rate for {from_currency} to {to_currency}")
                return cached_data['rate']
        
        return None
    
    def set_cached_rate(self, from_currency, to_currency, rate):
        """Cache the exchange rate"""
        cache_key = f"{from_currency}_{to_currency}"
        self.cache[cache_key] = {
            'rate': rate,
            'timestamp': datetime.now()
        }
        logger.info(f"Cached rate for {from_currency} to {to_currency}: {rate}")
    
    def can_make_api_call(self, currency_pair):
        """Check if enough time has passed since last API call for this pair"""
        if currency_pair not in self.last_api_call:
            return True
        
        time_since_last = time.time() - self.last_api_call[currency_pair]
        return time_since_last >= self.min_api_interval
    
    def record_api_call(self, currency_pair):
        """Record the timestamp of an API call"""
        self.last_api_call[currency_pair] = time.time()

# Global cache instance
rate_cache = ExchangeRateCache(cache_duration_minutes=60)

def get_exchange_rate(from_currency, to_currency, use_fallback=True):
    """
    Get exchange rate from CurrencyAPI with caching and rate limiting.
    """
    if from_currency == to_currency:
        return Decimal('1')

    # Check cache first
    cached_rate = rate_cache.get_cached_rate(from_currency, to_currency)
    if cached_rate:
        return cached_rate

    # Check if we can make an API call (rate limiting)
    currency_pair = f"{from_currency}_{to_currency}"
    if not rate_cache.can_make_api_call(currency_pair):
        logger.warning(f"Rate limited - using fallback for {from_currency} to {to_currency}")
        if use_fallback:
            return get_fallback_rate(from_currency, to_currency)
        raise Exception(f"Rate limited and no fallback available for {from_currency} to {to_currency}")

    url = "https://api.currencyapi.com/v3/latest"
    params = {"base_currency": from_currency}
    headers = {"apikey": Config.CURRENCY_API_KEY}

    try:
        # Record API call attempt
        rate_cache.record_api_call(currency_pair)
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if to_currency not in data["data"]:
            raise ValueError(f"Currency '{to_currency}' not found in exchange rates.")

        rate = Decimal(str(data["data"][to_currency]["value"]))
        
        # Cache the successful result
        rate_cache.set_cached_rate(from_currency, to_currency, rate)
        
        return rate
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            logger.error(f"Rate limit exceeded for {from_currency} to {to_currency}")
            if use_fallback:
                return get_fallback_rate(from_currency, to_currency)
            raise Exception(f"Rate limit exceeded: {str(e)}")
        else:
            logger.error(f"HTTP error fetching exchange rate from {from_currency} to {to_currency}: {str(e)}")
            if use_fallback:
                return get_fallback_rate(from_currency, to_currency)
            raise
    except Exception as e:
        logger.error(f"Error fetching exchange rate from {from_currency} to {to_currency}: {str(e)}")
        if use_fallback:
            return get_fallback_rate(from_currency, to_currency)
        raise

def get_fallback_rate(from_currency, to_currency):
    """
    Fallback exchange rates when API is unavailable.
    These should be updated periodically with approximate rates.
    """
    # Fallback rates (update these periodically)
    fallback_rates = {
        "KES_USD": Decimal('0.0077'),  # 1 KES = 0.0077 USD (approximate)
        "USD_EUR": Decimal('0.85'),    # 1 USD = 0.85 EUR (approximate)
        "USD_GBP": Decimal('0.79'),    # 1 USD = 0.79 GBP (approximate)
        "USD_UGX": Decimal('3700'),    # 1 USD = 3700 UGX (approximate)
        "USD_TZS": Decimal('2300'),    # 1 USD = 2300 TZS (approximate)
        "USD_NGN": Decimal('460'),     # 1 USD = 460 NGN (approximate)
        "USD_GHS": Decimal('12'),      # 1 USD = 12 GHS (approximate)
        "USD_ZAR": Decimal('18'),      # 1 USD = 18 ZAR (approximate)
        "USD_JPY": Decimal('110'),     # 1 USD = 110 JPY (approximate)
        "USD_CAD": Decimal('1.25'),    # 1 USD = 1.25 CAD (approximate)
        "USD_AUD": Decimal('1.35'),    # 1 USD = 1.35 AUD (approximate)
    }
    
    # Direct conversion
    rate_key = f"{from_currency}_{to_currency}"
    if rate_key in fallback_rates:
        logger.info(f"Using fallback rate for {from_currency} to {to_currency}")
        return fallback_rates[rate_key]
    
    # Reverse conversion
    reverse_key = f"{to_currency}_{from_currency}"
    if reverse_key in fallback_rates:
        logger.info(f"Using reverse fallback rate for {from_currency} to {to_currency}")
        return Decimal('1') / fallback_rates[reverse_key]
    
    # Multi-step conversion through USD
    if from_currency != "USD" and to_currency != "USD":
        try:
            usd_rate_key = f"{from_currency}_USD"
            target_rate_key = f"USD_{to_currency}"
            
            if usd_rate_key in fallback_rates and target_rate_key in fallback_rates:
                logger.info(f"Using multi-step fallback rate for {from_currency} to {to_currency}")
                return fallback_rates[usd_rate_key] * fallback_rates[target_rate_key]
        except:
            pass
    
    # If no fallback available, return a default rate or raise exception
    logger.warning(f"No fallback rate available for {from_currency} to {to_currency}")
    raise Exception(f"No fallback rate available for {from_currency} to {to_currency}")

def convert_ksh_to_target_currency(ksh_amount, target_currency):
    """
    Convert KSH amount to target currency via USD with caching.
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
            failed_currencies = []
            
            for currency in currencies:
                currency_code = currency.code.value
                try:
                    # Get exchange rate from KSH to this currency
                    if currency_code == "KES":
                        rate = Decimal('1')
                        rate_source = "base_currency"
                    else:
                        # Two-step conversion: KSH → USD → Target Currency
                        ksh_to_usd_rate = get_exchange_rate("KES", "USD")
                        if currency_code == "USD":
                            rate = ksh_to_usd_rate
                            rate_source = "api_or_cache"
                        else:
                            usd_to_target_rate = get_exchange_rate("USD", currency_code)
                            rate = ksh_to_usd_rate * usd_to_target_rate
                            rate_source = "api_or_cache"
                    
                    currency_list.append({
                        "id": currency.id,
                        "code": currency_code,
                        "name": currency.name,
                        "symbol": currency.symbol,
                        "exchange_rate_from_ksh": float(rate),
                        "description": f"1 KSH = {float(rate)} {currency_code}",
                        "rate_source": rate_source
                    })
                    
                except Exception as e:
                    logger.warning(f"Could not fetch rate for {currency_code}: {str(e)}")
                    failed_currencies.append(currency_code)
                    currency_list.append({
                        "id": currency.id,
                        "code": currency_code,
                        "name": currency.name,
                        "symbol": currency.symbol,
                        "exchange_rate_from_ksh": None,
                        "description": f"Rate unavailable for {currency_code}",
                        "rate_source": "unavailable"
                    })
            
            return {
                "message": "Active currencies with exchange rates retrieved successfully",
                "data": {
                    "base_currency": "KES",
                    "currencies": currency_list,
                    "total_currencies": len(currency_list),
                    "failed_currencies": failed_currencies if failed_currencies else None
                }
            }, 200
            
        except Exception as e:
            logger.error(f"Error retrieving currency list: {str(e)}")
            return {"message": f"Error retrieving currencies: {str(e)}"}, 500

class CurrencyConvertResource(Resource):
    """
    API resource to convert KSH amount to selected currency via USD with caching.
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
                    "source": "currencyapi.com (cached or fallback)"
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
                # Use a minimal test call with caching
                test_rate = get_exchange_rate("USD", "EUR", use_fallback=False)
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
                "conversion_method": "KSH → USD → Target Currency",
                "cache_status": f"{len(rate_cache.cache)} rates cached",
                "fallback_available": True
            }
        }, 200

class CurrencyCacheResource(Resource):
    """
    API resource to manage the currency cache.
    """
    @jwt_required()
    def get(self):
        """Get cache status"""
        cache_info = []
        for key, value in rate_cache.cache.items():
            cache_info.append({
                "currency_pair": key,
                "rate": float(value['rate']),
                "timestamp": value['timestamp'].isoformat(),
                "age_minutes": (datetime.now() - value['timestamp']).total_seconds() / 60
            })
        
        return {
            "message": "Currency cache status",
            "data": {
                "cache_entries": len(rate_cache.cache),
                "cache_duration_minutes": rate_cache.cache_duration.total_seconds() / 60,
                "cached_rates": cache_info
            }
        }, 200
    
    @jwt_required()
    def delete(self):
        """Clear the cache"""
        rate_cache.cache.clear()
        rate_cache.last_api_call.clear()
        return {"message": "Currency cache cleared successfully"}, 200

def register_currency_resources(api):
    """
    Register currency API resources with the Flask-RESTFUL API instance.
    """
    api.add_resource(CurrencyStatusResource, "/api/currency/status", endpoint="currency_status")
    api.add_resource(CurrencyListResource, "/api/currency/list", endpoint="currency_list")
    api.add_resource(CurrencyConvertResource, "/api/currency/convert", endpoint="currency_convert")
    api.add_resource(CurrencyCacheResource, "/api/currency/cache", endpoint="currency_cache")