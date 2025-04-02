from flask import request, jsonify
from flask_restful import Resource
import requests
import datetime
import base64
import uuid  # To generate unique transaction IDs
import logging
from model import db, TicketType, Ticket, Transaction, PaymentStatus, PaymentMethod  # Import your models
from dotenv import load_dotenv
import os
from flask_jwt_extended import jwt_required, get_jwt_identity
from config import Config

# Load environment variables from .env file
load_dotenv()

# M-Pesa Credentials
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORTCODE = os.getenv("BUSINESS_SHORTCODE")
PASSKEY = os.getenv("PASSKEY")
CALLBACK_URL = os.getenv("CALLBACK_URL")

# Validate the existence of API keys
if not all([CONSUMER_KEY, CONSUMER_SECRET, BUSINESS_SHORTCODE, PASSKEY, CALLBACK_URL]):
    raise ValueError("One or more M-Pesa credentials are missing. Check your .env file.")

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_access_token():
    """Fetches the access token from M-Pesa API."""
    consumer_key = Config.CONSUMER_KEY
    consumer_secret = Config.CONSUMER_SECRET
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}"
    }
    response = requests.get(api_url, headers=headers)
    response_data = response.json()
    access_token = response_data.get("access_token")
    return access_token

def generate_password():
    """Generates a base64-encoded password for STK push request."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    raw_password = BUSINESS_SHORTCODE + PASSKEY + timestamp
    encoded_password = base64.b64encode(raw_password.encode()).decode()
    return encoded_password, timestamp

def normalize_phone_number(phone_number):
    """Convert phone number to Safaricom's required format (2547XXXXXXXX)."""
    phone_number = phone_number.strip()  # Remove spaces

    if phone_number.startswith("+254"):
        return phone_number[1:]  # Remove the "+"
    elif phone_number.startswith("07"):
        return "254" + phone_number[1:]  # Replace "07" with "2547"
    elif phone_number.startswith("254"):
        return phone_number  # Already in correct format
    else:
        return None  # Invalid number

def initiate_stk_push(phone_number, amount, ticket_id, temp_transaction_id):
    """Initiates an STK Push for M-Pesa payment."""
    # Normalize the phone number
    phone_number = normalize_phone_number(phone_number)
    if not phone_number:
        raise ValueError("Invalid phone number format")

    # Get access token for M-Pesa API
    access_token = get_access_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{BUSINESS_SHORTCODE}{PASSKEY}{timestamp}".encode()).decode()

    payload = {
        "BusinessShortCode": BUSINESS_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": BUSINESS_SHORTCODE,
        "PhoneNumber": phone_number,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": temp_transaction_id,  # Use the temporary transaction ID
        "TransactionDesc": f"Payment for ticket ID {ticket_id}"
    }

    response = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
                            json=payload, headers=headers)
    response_data = response.json()

    # Log the response to inspect its structure
    logger.info(f"STK Push response: {response_data}")

    return response_data

class STKPushResource(Resource):
    @jwt_required()
    def post(self):
        """Initiates STK Push for ticket payment."""
        data = request.get_json()
        phone_number = data.get("phone_number")
        amount = data.get("amount")
        ticket_id = data.get("ticket_id")
        temp_transaction_id = data.get("temp_transaction_id")  # Expecting the temporary transaction ID

        # Normalize the phone number
        phone_number = normalize_phone_number(phone_number)
        if not phone_number:
            return {"error": "Invalid phone number format"}, 400

        if not phone_number or not amount or not ticket_id or not temp_transaction_id:
            return {"error": "Phone number, amount, ticket_id, and temp_transaction_id are required"}, 400

        response_data = initiate_stk_push(phone_number, amount, ticket_id, temp_transaction_id)

        if response_data.get("ResponseCode") == "0":
            merchant_request_id = response_data.get("MerchantRequestID")

            # Update the Ticket with the merchant request ID
            ticket = Ticket.query.get(ticket_id)
            if ticket:
                ticket.merchant_request_id = merchant_request_id
                db.session.commit()

            return {
                "message": "STK Push initiated",
                "data": response_data
            }, 200
        else:
            return {"error": "Failed to initiate STK Push", "details": response_data}, 400

class STKCallback(Resource):
    def __init__(self, complete_ticket_operation_func):
        self.complete_ticket_operation = complete_ticket_operation_func

    def post(self):
        """Handles the callback from M-Pesa for STK Push."""
        data = request.get_json()
        logger.info(f"STK Callback received: {data}")

        if not data or "Body" not in data or "stkCallback" not in data["Body"]:
            logger.error("Invalid callback data format")
            return {"error": "Invalid callback data"}, 400

        callback_data = data["Body"]["stkCallback"]
        result_code = callback_data.get("ResultCode", -1)
        result_desc = callback_data.get("ResultDesc", "Unknown response")
        merchant_request_id = callback_data.get("MerchantRequestID", None)

        logger.info(f"MerchantRequestID from callback: {merchant_request_id}")
        logger.info(f"ResultCode from callback: {result_code}")
        logger.info(f"ResultDesc from callback: {result_desc}")

        # Extract metadata
        callback_metadata = callback_data.get("CallbackMetadata", {}).get("Item", [])
        amount = next((item["Value"] for item in callback_metadata if item["Name"] == "Amount"), 0)
        mpesa_receipt_number = next((item["Value"] for item in callback_metadata if item["Name"] == "MpesaReceiptNumber"), "")
        transaction_date = next((item["Value"] for item in callback_metadata if item["Name"] == "TransactionDate"), "")
        phone_number = next((item["Value"] for item in callback_metadata if item["Name"] == "PhoneNumber"), "")

        # Find the existing transaction using the merchant_request_id
        transaction = Transaction.query.filter_by(merchant_request_id=merchant_request_id).first()

        if transaction:
            if transaction.payment_status == PaymentStatus.COMPLETED:
                logger.info(f"Callback received for already completed transaction with MerchantRequestID: {merchant_request_id}")
                self.complete_ticket_operation(transaction)
                return {"message": "Callback already processed"}, 200

            if result_code == 0:
                # Payment Successful
                logger.info(f"Payment Success for MerchantRequestID: {merchant_request_id}, MpesaReceiptNumber: {mpesa_receipt_number}")
                transaction.payment_status = PaymentStatus.COMPLETED
                transaction.payment_reference = mpesa_receipt_number
                transaction.timestamp = datetime.datetime.strptime(str(transaction_date), "%Y%m%d%H%M%S")
                transaction.mpesa_receipt_number = mpesa_receipt_number
                transaction.amount_paid = amount
                db.session.commit()
                logger.info(f"Transaction ID {transaction.id} updated to COMPLETED.")
                self.complete_ticket_operation(transaction)
                return {"message": "Payment successful and ticket operation completed"}, 200
            else:
                # Payment failed
                error_message = result_desc
                logger.error(f"Payment failed for MerchantRequestID {merchant_request_id}: Result Code: {result_code}, Description: {error_message}")
                transaction.payment_status = PaymentStatus.FAILED
                db.session.commit()
                logger.info(f"Transaction ID {transaction.id} updated to FAILED.")
                return {"error": "Payment failed", "details": error_message}, 400
        else:
            logger.error(f"Transaction not found for MerchantRequestID: {merchant_request_id}")
            return {"error": "Transaction not found"}, 404

class TransactionStatus(Resource):
    @jwt_required()
    def post(self):
        """Checks the status of an M-Pesa transaction."""
        access_token = get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        data = request.get_json()
        transaction_id = data.get("TransactionID")
        if not transaction_id:
            return {"error": "TransactionID is required"}, 400
        payload = {
            "Initiator": "testapi",
            "SecurityCredential": "your_security_credential",  # Replace with actual security credential
            "CommandID": "TransactionStatusQuery",
            "TransactionID": transaction_id,
            "PartyA": BUSINESS_SHORTCODE,
            "IdentifierType": "4",
            "ResultURL": CALLBACK_URL,
            "QueueTimeOutURL": CALLBACK_URL,
            "Remarks": "Checking transaction status",
            "Occasion": "Payment Verification"
        }
        url = "https://sandbox.safaricom.co.ke/mpesa/transactionstatus/v1/query"
        response = requests.post(url, json=payload, headers=headers)
        return response.json()

class RefundTransaction(Resource):
    @jwt_required()
    def post(self):
        """Initiates a refund for an M-Pesa transaction."""
        try:
            data = request.get_json()
            merchant_request_id = data.get("transaction_id") # Expecting MerchantRequestID here
            amount = data.get("amount")
            if not merchant_request_id or not amount:
                return {"error": "Missing transaction_id (MerchantRequestID) or amount"}, 400

            # Get access token for M-Pesa API
            access_token = get_access_token()
            if not access_token:
                return {"error": "Failed to obtain access token"}, 500

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "Initiator": "testapi",
                "SecurityCredential": "your_security_credential",  # Replace with actual security credential
                "CommandID": "TransactionReversal",
                "TransactionID": merchant_request_id, # Use MerchantRequestID for reversal
                "Amount": amount,
                "ReceiverParty": BUSINESS_SHORTCODE,
                "ReceiverIdentifierType": "11",
                "ResultURL": CALLBACK_URL,
                "QueueTimeOutURL": CALLBACK_URL,
                "Remarks": "Refund for transaction",
                "Occasion": "Refund"
            }
            url = "https://sandbox.safaricom.co.ke/mpesa/reversal/v1/request"
            response = requests.post(url, json=payload, headers=headers)
            res_data = response.json()
            logger.info(f"M-Pesa Refund Response: {res_data}")
            if res_data.get("ResponseCode") == "0":
                transaction = Transaction.query.filter_by(merchant_request_id=merchant_request_id).first()
                if transaction:
                    transaction.payment_status = PaymentStatus.REFUNDED
                    db.session.commit()
                    return {"message": "Refund initiated successfully", "data": res_data}, 200
                return {"error": "Transaction not found for the given MerchantRequestID"}, 404
            return {"error": "Failed to initiate refund", "details": res_data.get("ResponseDescription", "Unknown error")}, 400
        except Exception as e:
            logger.error(f"Error initiating refund: {str(e)}")
            return {"error": "An error occurred", "details": str(e)}, 500

def register_mpesa_routes(api, complete_ticket_operation_func):
    """Register M-Pesa routes with the API."""
    api.add_resource(STKPushResource, "/mpesa/stkpush")
    api.add_resource(STKCallback, "/mpesa/stk", resource_class_kwargs={'complete_ticket_operation_func': complete_ticket_operation_func})
    api.add_resource(TransactionStatus, "/mpesa/status")
    api.add_resource(RefundTransaction, "/mpesa/refund")