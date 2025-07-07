from flask import request, jsonify
from flask_restful import Resource
import requests
import datetime
import base64
import uuid  # To generate unique transaction IDs
import logging
from model import db, TicketType, Ticket, Transaction, PaymentStatus, PaymentMethod, TransactionTicket  # Import your models
from dotenv import load_dotenv
import os
from flask_jwt_extended import jwt_required, get_jwt_identity
from config import Config
# from ticket import complete_ticket_operation
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


logging.basicConfig(level=logging.INFO)

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
    """Convert phone number to Safaricom's required format (254XXXXXXXXX)."""
    phone_number = phone_number.strip()

    if phone_number.startswith("+254"):
        return phone_number[1:]  # Remove '+'
    elif phone_number.startswith("0") and len(phone_number) == 10:
        return "254" + phone_number[1:]  # Convert '0XXXXXXXXX' to '254XXXXXXXXX'
    elif phone_number.startswith("254") and len(phone_number) == 12:
        return phone_number  # Already normalized
    else:
        return None  # Invalid format


class STKPush(Resource):
    @jwt_required()
    def post(self, mpesa_data):
        """Initiates STK Push for ticket payment."""
        phone_number = mpesa_data.get("phone_number")
        amount = mpesa_data.get("amount")
        transaction_id = mpesa_data.get("transaction_id")

        # Normalize the phone number
        phone_number = normalize_phone_number(phone_number)
        if not phone_number:
            return {"error": "Invalid phone number format"}, 400

        if not phone_number or not amount or not transaction_id:
            return {"error": "Phone number, amount, and transaction_id are required"}, 400

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
            "AccountReference": str(transaction_id),  # Use the transaction ID as string
            "TransactionDesc": f"Payment for transaction ID {transaction_id}"
        }

        try:
            response = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
                                    json=payload, headers=headers)
            response_data = response.json()

            # Log the response to inspect its structure
            logging.info(f"STK Push response: {response_data}")

            if response_data.get("ResponseCode") == "0":
                merchant_request_id = response_data.get("MerchantRequestID")
                checkout_request_id = response_data.get("CheckoutRequestID")

                # Update the Transaction with the merchant request ID and checkout request ID
                transaction = Transaction.query.get(transaction_id)
                if transaction:
                    # Store both IDs in the transaction for tracking
                    # You might need to add these fields to your Transaction model
                    transaction.merchant_request_id = merchant_request_id
                    transaction.checkout_request_id = checkout_request_id
                    db.session.commit()

                return {
                    "message": "STK Push initiated successfully",
                    "merchant_request_id": merchant_request_id,
                    "checkout_request_id": checkout_request_id
                }, 200
            else:
                error_message = response_data.get("errorMessage", "Unknown error")
                logging.error(f"STK Push failed: {response_data}")
                return {
                    "error": "Failed to initiate STK Push", 
                    "details": error_message
                }, 400

        except requests.RequestException as e:
            logging.error(f"Request error during STK Push: {e}")
            return {"error": "Network error occurred during payment initiation"}, 500
        except Exception as e:
            logging.error(f"Unexpected error during STK Push: {e}")
            return {"error": "An unexpected error occurred"}, 500


class STKCallback(Resource):
    def __init__(self, complete_ticket_operation_func):
        self.complete_ticket_operation = complete_ticket_operation_func

    def post(self):
        """Handles the callback from M-Pesa for STK Push."""
        data = request.get_json()
        logging.info(f"STK Callback received: {data}")

        if not data or "Body" not in data or "stkCallback" not in data["Body"]:
            return {"error": "Invalid callback data"}, 400

        callback_data = data["Body"]["stkCallback"]
        result_code = callback_data.get("ResultCode", -1)
        result_desc = callback_data.get("ResultDesc", "Unknown response")

        callback_metadata = callback_data.get("CallbackMetadata", {}).get("Item", [])
        amount = next((item["Value"] for item in callback_metadata if item["Name"] == "Amount"), 0)
        mpesa_receipt_number = next((item["Value"] for item in callback_metadata if item["Name"] == "MpesaReceiptNumber"), "")
        transaction_date = next((item["Value"] for item in callback_metadata if item["Name"] == "TransactionDate"), "")
        phone_number = next((item["Value"] for item in callback_metadata if item["Name"] == "PhoneNumber"), "")
        merchant_request_id = callback_data.get("MerchantRequestID", None)

        logging.info(f"MerchantRequestID: {merchant_request_id}")

        if result_code == 0:
            # Payment Successful
            logging.info(f"Payment Success: {mpesa_receipt_number}")

            # Find the existing PENDING transaction using merchant_request_id
            transaction = Transaction.query.filter_by(
                merchant_request_id=merchant_request_id,
                payment_status=PaymentStatus.PENDING
            ).first()

            if not transaction:
                logging.error(f"Transaction not found for MerchantRequestID: {merchant_request_id}")
                return {"error": "Transaction not found"}, 404

            # Check if already processed
            if transaction.payment_status == PaymentStatus.PAID:
                logging.info(f"Transaction {transaction.id} with MerchantRequestID {merchant_request_id} already processed.")
                return {"message": "Callback already processed"}, 200

            # Update the existing transaction
            transaction.payment_status = PaymentStatus.PAID
            transaction.payment_reference = mpesa_receipt_number  # Update with actual M-Pesa receipt
            transaction.mpesa_receipt_number = mpesa_receipt_number
            if transaction_date:
                try:
                    transaction.timestamp = datetime.datetime.strptime(str(transaction_date), "%Y%m%d%H%M%S")
                except ValueError:
                    logging.warning(f"Could not parse transaction date: {transaction_date}")

            # Update all associated tickets through TransactionTicket relationships
            transaction_tickets = TransactionTicket.query.filter_by(transaction_id=transaction.id).all()
            
            if not transaction_tickets:
                logging.error(f"No tickets found for transaction {transaction.id}")
                return {"error": "No tickets found for this transaction"}, 404

            for trans_ticket in transaction_tickets:
                ticket = Ticket.query.get(trans_ticket.ticket_id)
                if ticket:
                    ticket.payment_status = PaymentStatus.PAID
                    
                    # Reduce ticket quantity
                    ticket_type = TicketType.query.get(ticket.ticket_type_id)
                    if ticket_type:
                        ticket_type.quantity -= ticket.quantity
                    else:
                        logging.error(f"Ticket type not found for ticket ID: {ticket.id}")

            db.session.commit()
            logging.info(f"Transaction {transaction.id} updated to PAID status")

            # Complete ticket operation (this sends the email)
            self.complete_ticket_operation(transaction)

            return {"message": "Payment successful and ticket operation completed"}, 200

        else:
            # Payment failed
            error_message = result_desc
            if result_code == 1:
                error_message = "Insufficient funds"
            elif result_code == 1032:
                error_message = "Request cancelled by user"
            elif result_code == 1037:
                error_message = "Transaction timeout"
            elif result_code == 2001:
                error_message = "Insufficient funds"
            elif result_code == 2006:
                error_message = "User did not enter PIN"
            # Add more result codes and messages as needed

            # Find and update the existing transaction
            transaction = Transaction.query.filter_by(
                merchant_request_id=merchant_request_id,
                payment_status=PaymentStatus.PENDING
            ).first()

            if transaction:
                transaction.payment_status = PaymentStatus.FAILED
                
                # Update associated tickets
                transaction_tickets = TransactionTicket.query.filter_by(transaction_id=transaction.id).all()
                for trans_ticket in transaction_tickets:
                    ticket = Ticket.query.get(trans_ticket.ticket_id)
                    if ticket:
                        ticket.payment_status = PaymentStatus.FAILED

                db.session.commit()
                logging.info(f"Transaction {transaction.id} marked as FAILED")

            return {"error": "Payment failed", "details": error_message}, 400

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
            transaction_id = data.get("transaction_id")
            amount = data.get("amount")
            if not transaction_id or not amount:
                return {"error": "Missing transaction_id or amount"}, 400

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
                "TransactionID": transaction_id,
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
            logging.info(f"M-Pesa Refund Response: {res_data}")
            if res_data.get("ResponseCode") == "0":
                transaction = Transaction.query.filter_by(merchant_request_id=transaction_id).first()
                if transaction:
                    transaction.payment_status = PaymentStatus.REFUNDED
                    db.session.commit()
                return {"message": "Refund initiated successfully", "data": res_data}, 200
            return {"error": "Failed to initiate refund", "details": res_data.get("ResponseDescription", "Unknown error")}, 400
        except Exception as e:
            logging.error(f"Error initiating refund: {str(e)}")
            return {"error": "An error occurred", "details": str(e)}, 500

def register_mpesa_routes(api, complete_ticket_operation):
    """Register M-Pesa routes with the API."""
    api.add_resource(STKPush, "/mpesa/stkpush")
    api.add_resource(STKCallback, "/mpesa/stk", resource_class_kwargs={'complete_ticket_operation_func': complete_ticket_operation})
    api.add_resource(TransactionStatus, "/mpesa/status")
    api.add_resource(RefundTransaction, "/mpesa/refund")