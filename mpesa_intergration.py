import os
import requests
import base64
import datetime
import logging
from flask import request
from flask_restful import Resource
from dotenv import load_dotenv
from model import db, Transaction, PaymentStatus  # Ensure you have these imports

# Load environment variables from .env file
load_dotenv()

# M-Pesa Credentials
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
BUSINESS_SHORTCODE = os.getenv("BUSINESS_SHORTCODE")
PASSKEY = os.getenv("PASSKEY")
CALLBACK_URL = os.getenv("CALLBACK_URL")
SECURITY_CREDENTIAL = os.getenv("SECURITY_CREDENTIAL")


def get_access_token():
    """Generates a fresh access token from Safaricom API."""
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = (CONSUMER_KEY, CONSUMER_SECRET)
    response = requests.get(url, auth=auth)
    response_data = response.json()
    if "access_token" in response_data:
        return response_data["access_token"]
    else:
        raise Exception(f"Failed to get access token: {response_data}")


def generate_password():
    """Generates a base64-encoded password for STK push request."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    raw_password = BUSINESS_SHORTCODE + PASSKEY + timestamp
    encoded_password = base64.b64encode(raw_password.encode()).decode()
    return encoded_password, timestamp


class STKPush(Resource):
    def post(self):
        """Handles STK Push Payment Request."""
        access_token = get_access_token()
        password, timestamp = generate_password()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "BusinessShortCode": BUSINESS_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": 1,
            "PartyA": "254746604602",
            "PartyB": BUSINESS_SHORTCODE,
            "PhoneNumber": "254746604602",
            "CallBackURL": CALLBACK_URL,
            "AccountReference": "TestPay",
            "TransactionDesc": "Payment for Test"
        }
        url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
        response = requests.post(url, json=payload, headers=headers)
        return response.json()


class STKCallback(Resource):
    def post(self):
        """Handles STK Callback Response."""
        data = request.get_json()
        logging.info(f"STK Callback Received: {data}")
        if data and "Body" in data and "stkCallback" in data["Body"]:
            callback_data = data["Body"]["stkCallback"]
            result_code = callback_data.get("ResultCode", -1)
            result_desc = callback_data.get("ResultDesc", "Unknown response")
            amount = callback_data.get("Amount", 0)
            mpesa_receipt_number = callback_data.get("MpesaReceiptNumber", "")
            transaction_date = callback_data.get("TransactionDate", "")
            phone_number = callback_data.get("PhoneNumber", "")
            payment_status = PaymentStatus.SUCCESS if result_code == 0 else PaymentStatus.FAILED
            transaction = Transaction(
                amount_paid=amount,
                payment_status=payment_status,
                payment_reference=mpesa_receipt_number,
                payment_method='Mpesa',
                timestamp=datetime.datetime.strptime(transaction_date, "%Y%m%d%H%M%S")
            )
            db.session.add(transaction)
            db.session.commit()
        return {"message": "STK Callback received"}, 200


class TransactionStatus(Resource):
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
            "SecurityCredential": SECURITY_CREDENTIAL,
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
    def post(self):
        """Initiate a refund for an M-Pesa transaction."""
        try:
            data = request.get_json()
            transaction_id = data.get("transaction_id")
            amount = data.get("amount")
            if not transaction_id or not amount:
                return {"error": "Missing transaction_id or amount"}, 400
            access_token = get_access_token()
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "Initiator": "testapi",
                "SecurityCredential": SECURITY_CREDENTIAL,
                "CommandID": "TransactionReversal",
                "TransactionID": transaction_id,
                "Amount": amount,
                "ReceiverParty": BUSINESS_SHORTCODE,
                "RecieverIdentifierType": "11",
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
                transaction = Transaction.query.filter_by(payment_reference=transaction_id).first()
                if transaction:
                    transaction.payment_status = PaymentStatus.REFUNDED
                    db.session.commit()
                return {"message": "Refund initiated successfully", "data": res_data}, 200
            return {"error": "Failed to initiate refund", "details": res_data.get("ResponseDescription", "Unknown error")}, 400
        except Exception as e:
            logging.error(f"Error initiating refund: {str(e)}")
            return {"error": "An error occurred", "details": str(e)}, 500


def register_mpesa_routes(api):
    """Register M-Pesa routes with the API."""
    api.add_resource(STKPush, "/mpesa/stkpush")
    api.add_resource(STKCallback, "/mpesa/stk")
    api.add_resource(TransactionStatus, "/mpesa/status")
    api.add_resource(RefundTransaction, "/mpesa/refund")
