from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Transaction, PaymentStatus, PaymentMethod
from config import Config
import requests
import logging
import os
import hashlib
import hmac
import json

logger = logging.getLogger(__name__)

PAYSTACK_SECRET_KEY = Config.PAYSTACK_SECRET_KEY
PAYSTACK_CALLBACK_URL = Config.PAYSTACK_CALLBACK_URL

def initialize_paystack_payment(email, amount):
    """Initializes a Paystack payment and returns the authorization URL and reference."""
    url = "https://api.paystack.co/transaction/initialize"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
    # Amount should be in kobo (cents for other currencies)
    payload = {"email": email, "amount": int(amount * 100), "callback_url": PAYSTACK_CALLBACK_URL}

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        res_data = response.json()
        logger.info(f"Paystack Initialize Response: {res_data}")
        if res_data.get("status") and res_data.get("data"):
            return {
                "authorization_url": res_data["data"]["authorization_url"],
                "reference": res_data["data"]["reference"]
            }
        else:
            error_message = res_data.get("message", "Unknown error")
            logger.error(f"Paystack initialization failed: {error_message}")
            return {"error": "Failed to initialize payment", "details": error_message}, 400
    except requests.exceptions.RequestException as e:
        logger.error(f"Error communicating with Paystack API: {e}")
        return {"error": f"Error communicating with Paystack: {e}"}, 500

def verify_paystack_payment(reference):
    """Verifies a Paystack payment using the transaction reference."""
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        res_data = response.json()
        logger.info(f"Paystack Verify Response for {reference}: {res_data}")
        if res_data.get("status") and res_data.get("data") and res_data["data"]["status"] == "success":
            return res_data["data"]
        else:
            error_message = res_data.get("message", "Unknown error")
            logger.error(f"Paystack verification failed for {reference}: {error_message}")
            return {"error": "Payment verification failed", "details": error_message}, 400
    except requests.exceptions.RequestException as e:
        logger.error(f"Error communicating with Paystack API for verification: {e}")
        return {"error": f"Error communicating with Paystack: {e}"}, 500

def refund_paystack_payment(reference, amount):
    """Initiates a Paystack refund for a given transaction reference and amount."""
    url = "https://api.paystack.co/refund"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
    # Amount should be in kobo (cents for other currencies)
    payload = {"transaction": reference, "amount": int(amount * 100)}
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        res_data = response.json()
        logger.info(f"Paystack Refund Response for {reference}: {res_data}")
        if res_data.get("status"):
            return res_data["data"]
        else:
            error_message = res_data.get("message", "Unknown error")
            logger.error(f"Paystack refund failed for {reference}: {error_message}")
            return {"error": "Refund initiation failed", "details": error_message}, 400
    except requests.exceptions.RequestException as e:
        logger.error(f"Error communicating with Paystack API for refund: {e}")
        return {"error": f"Error communicating with Paystack: {e}"}, 500

class VerifyPayment(Resource):
    @jwt_required()
    def get(self, reference):
        """Verifies a Paystack payment by reference."""
        verification_result = verify_paystack_payment(reference)
        if "error" in verification_result:
            return verification_result, 400
        return verification_result, 200

class RefundPayment(Resource):
    @jwt_required()
    def post(self):
        """Initiates a Paystack refund and updates the transaction status."""
        data = request.get_json()
        reference = data.get("reference")
        amount = data.get("amount")
        if not reference or amount is None:
            return {"error": "Missing payment reference or refund amount"}, 400

        refund_result = refund_paystack_payment(reference, amount)
        if "error" in refund_result:
            return refund_result, 400

        # Update the transaction status to REFUNDED
        transaction = Transaction.query.filter_by(payment_reference=reference).first()
        if transaction:
            transaction.payment_status = PaymentStatus.REFUNDED
            db.session.commit()
            return {"message": "Refund initiated successfully", "data": refund_result}, 200
        else:
            return {"error": "Transaction not found for the given reference"}, 404

class PaystackCallback(Resource):
    def __init__(self, complete_ticket_operation_func):
        self.complete_ticket_operation = complete_ticket_operation_func

    def post(self):
        signature = request.headers.get('X-Paystack-Signature')

        if not signature:
            logger.warning("Paystack callback: Missing signature")
            return {"message": "Missing signature"}, 400

        try:
            body = request.get_data(as_text=True)
            # Verify Paystack signature
            expected_signature = hmac.new(
                PAYSTACK_SECRET_KEY.encode('utf-8'),
                body.encode('utf-8'),
                hashlib.sha512
            ).hexdigest()

            if expected_signature != signature:
                logger.error(f"Paystack callback: Invalid signature. Expected: {expected_signature}, Received: {signature}")
                return {"message": "Invalid signature"}, 401

            payload = request.get_json()
            logger.info(f"Paystack callback received: {payload}")

            event = payload.get('event')
            data = payload.get('data')

            if event == 'charge.success':
                reference = data.get('reference')
                if reference:
                    transaction = Transaction.query.filter_by(payment_reference=reference).first()
                    if transaction:
                        if transaction.payment_status != PaymentStatus.COMPLETED:  # Avoid duplicate processing
                            transaction.payment_status = PaymentStatus.COMPLETED
                            db.session.commit()
                            logger.info(f"Payment successful for reference: {reference}. Triggering ticket completion.")
                            try:
                                # Ensure complete_ticket_operation is defined and accessible
                                self.complete_ticket_operation(transaction)
                            except Exception as e:
                                logger.error(f"Error in complete_ticket_operation: {e}")
                                return {"error": "Error completing ticket operation", "details": str(e)}, 500
                            return {"message": "Payment successful and ticket processing initiated"}, 200
                        else:
                            logger.info(f"Callback received for already completed transaction: {reference}")
                            return {"message": "Transaction already processed"}, 200
                    else:
                        logger.error(f"Transaction not found for reference: {reference}")
                        return {"message": "Transaction not found"}, 404
                else:
                    logger.warning("Paystack callback: Missing reference in charge.success event")
                    return {"message": "Missing reference"}, 400
            else:
                logger.info(f"Paystack callback received for event: {event}")
                return {"message": f"Event received: {event}"}, 200

        except Exception as e:
            logger.error(f"Error processing Paystack callback: {e}")
            return {"error": "Error processing callback", "details": str(e)}, 500

def register_paystack_routes(api, complete_ticket_operation_func):
    api.add_resource(VerifyPayment, '/paystack/verify/<string:reference>')
    api.add_resource(PaystackCallback, '/paystack/callback', resource_class_kwargs={'complete_ticket_operation_func': complete_ticket_operation_func})
    api.add_resource(RefundPayment, '/paystack/refund')