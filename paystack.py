from flask import request
from flask_restful import Resource
import requests
import logging
from config import Config  # Ensure this contains your PAYSTACK_SECRET_KEY
from model import db, Transaction, PaymentStatus  # Ensure you have these imports

# Extract Paystack keys from the Config class
PAYSTACK_SECRET_KEY = Config.PAYSTACK_SECRET_KEY
PAYSTACK_CALLBACK_URL = Config.PAYSTACK_CALLBACK_URL

# Validate the existence of API keys
if not PAYSTACK_SECRET_KEY:
    raise ValueError("PAYSTACK_SECRET_KEY is missing. Check your .env file or config.py.")

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)

class InitializePayment(Resource):
    def post(self):
        """Initialize a Paystack payment."""
        try:
            data = request.get_json()

            # Validate input
            if not data or "email" not in data or "amount" not in data or "payment_method" not in data:
                return {"error": "Missing email, amount, or payment method"}, 400

            email = data["email"]
            amount = int(data["amount"]) * 100  # Convert to kobo
            payment_method = data["payment_method"]

            url = "https://api.paystack.co/transaction/initialize"
            headers = {
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "email": email,
                "amount": amount,
                "callback_url": PAYSTACK_CALLBACK_URL
            }

            response = requests.post(url, headers=headers, json=payload)
            res_data = response.json()

            # Log the response for debugging
            logging.info(f"Paystack Initialize Response: {res_data}")

            if res_data.get("status") and res_data.get("data"):
                # Create a new transaction record
                transaction = Transaction(
                    amount_paid=amount / 100,  # Convert back to base currency
                    payment_status=PaymentStatus.PENDING,
                    payment_reference=res_data["data"]["reference"],
                    payment_method=payment_method
                )
                db.session.add(transaction)
                db.session.commit()

                return {
                    "message": "Payment initialized",
                    "authorization_url": res_data["data"]["authorization_url"],
                    "reference": res_data["data"]["reference"]
                }, 200

            return {"error": "Failed to initialize payment", "details": res_data.get("message", "Unknown error")}, 400

        except Exception as e:
            logging.error(f"Error initializing payment: {str(e)}")
            return {"error": "An error occurred", "details": str(e)}, 500

class VerifyPayment(Resource):
    def get(self, reference):
        """Verify a Paystack payment by transaction reference."""
        try:
            if not reference:
                return {"error": "Payment reference is required"}, 400

            url = f"https://api.paystack.co/transaction/verify/{reference}"
            headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}

            response = requests.get(url, headers=headers)
            res_data = response.json()

            # Log response for debugging
            logging.info(f"Paystack Verify Response for {reference}: {res_data}")

            if res_data.get("status") and res_data.get("data", {}).get("status") == "success":
                # Update the transaction record
                transaction = Transaction.query.filter_by(payment_reference=reference).first()
                if transaction:
                    transaction.payment_status = PaymentStatus.SUCCESS
                    db.session.commit()

                return {"message": "Payment successful", "data": res_data["data"]}, 200

            return {
                "message": "Payment failed or not verified",
                "error": res_data.get("message", "Transaction not found"),
                "data": res_data.get("data", {})
            }, 400

        except Exception as e:
            logging.error(f"Error verifying payment: {str(e)}")
            return {"error": "An error occurred", "details": str(e)}, 500

class RefundPayment(Resource):
    def post(self):
        """Initiate a refund for a Paystack transaction."""
        try:
            data = request.get_json()

            # Validate input
            if not data or "reference" not in data or "amount" not in data:
                return {"error": "Missing reference or amount"}, 400

            reference = data["reference"]
            amount = int(data["amount"]) * 100  # Convert to kobo

            url = f"https://api.paystack.co/refund"
            headers = {
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "reference": reference,
                "amount": amount
            }

            response = requests.post(url, headers=headers, json=payload)
            res_data = response.json()

            # Log the response for debugging
            logging.info(f"Paystack Refund Response: {res_data}")

            if res_data.get("status"):
                # Update the transaction record
                transaction = Transaction.query.filter_by(payment_reference=reference).first()
                if transaction:
                    transaction.payment_status = PaymentStatus.REFUNDED
                    db.session.commit()

                return {"message": "Refund initiated successfully", "data": res_data["data"]}, 200

            return {"error": "Failed to initiate refund", "details": res_data.get("message", "Unknown error")}, 400

        except Exception as e:
            logging.error(f"Error initiating refund: {str(e)}")
            return {"error": "An error occurred", "details": str(e)}, 500

def register_paystack_routes(api):
    """Register Paystack routes with the API."""
    api.add_resource(InitializePayment, '/paystack/initialize')
    api.add_resource(VerifyPayment, '/paystack/verify/<string:reference>')
    api.add_resource(RefundPayment, '/paystack/refund')
