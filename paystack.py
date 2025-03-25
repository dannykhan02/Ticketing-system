from flask import Flask, request, jsonify
from flask_restful import Api, Resource
from flask_sqlalchemy import SQLAlchemy
import requests
import logging
from config import Config  # Ensure this contains PAYSTACK_SECRET_KEY
from model import db, Transaction, PaymentStatus, PaymentMethod
from flask_jwt_extended import jwt_required, get_jwt_identity  # Import JWT decorators
import hashlib
import hmac
# Removed: from ticket import complete_ticket_operation  # Import the function from ticket.py

# Extract Paystack keys from the Config class
PAYSTACK_SECRET_KEY = Config.PAYSTACK_SECRET_KEY
PAYSTACK_CALLBACK_URL = Config.PAYSTACK_CALLBACK_URL

# Validate the existence of API keys
if not PAYSTACK_SECRET_KEY:
    raise ValueError("PAYSTACK_SECRET_KEY is missing. Check your .env file or config.py.")

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InitializePayment(Resource):
    @jwt_required()  # Require JWT authentication
    def post(self):
        try:
            identity = get_jwt_identity()
            # Assuming your user model has an 'id' attribute matching the JWT identity
            from model import User
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            data = request.get_json()
            if not data or "amount" not in data or "payment_method" not in data:
                return {"error": "Missing amount or payment method"}, 400

            email = user.email  # Use the authenticated user's email
            amount = int(data["amount"])  # Amount is already multiplied by 100 in the request
            payment_method = PaymentMethod(data["payment_method"])

            url = "https://api.paystack.co/transaction/initialize"
            headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
            payload = {"email": email, "amount": amount, "callback_url": PAYSTACK_CALLBACK_URL}

            response = requests.post(url, headers=headers, json=payload)
            res_data = response.json()
            logging.info(f"Paystack Initialize Response: {res_data}")

            if res_data.get("status") and res_data.get("data"):
                transaction = Transaction(
                    amount_paid=amount / 100,
                    payment_status=PaymentStatus.PENDING,
                    payment_reference=res_data["data"]["reference"],
                    payment_method=payment_method,
                    user_id=user.id  # Set the user_id from the authenticated user
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
    @jwt_required()  # Require JWT authentication
    def get(self, reference):
        try:
            identity = get_jwt_identity()
            from model import User
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            url = f"https://api.paystack.co/transaction/verify/{reference}"
            headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
            response = requests.get(url, headers=headers)
            res_data = response.json()
            logging.info(f"Paystack Verify Response for {reference}: {res_data}")

            if res_data.get("status") and res_data.get("data", {}).get("status") == "success":
                transaction = Transaction.query.filter_by(payment_reference=reference, user_id=user.id).first()
                if transaction:
                    transaction.payment_status = PaymentStatus.COMPLETED
                    db.session.commit()
                    return {"message": "Payment successful", "data": res_data["data"]}, 200

            return {"message": "Payment failed or not verified", "error": res_data.get("message", "Transaction not found"), "data": res_data.get("data", {})}, 400
        except Exception as e:
            logging.error(f"Error verifying payment: {str(e)}")
            return {"error": "An error occurred", "details": str(e)}, 500

class PaystackCallback(Resource):
    def post(self):
        # Verify Paystack Signature
        signature = request.headers.get('x-paystack-signature')
        if not signature:
            return jsonify({'error': 'No signature sent'}), 400

        try:
            body = request.get_data(as_text=True)
            computed_signature = hmac.new(
                PAYSTACK_SECRET_KEY.encode('utf-8'),
                body.encode('utf-8'),
                hashlib.sha512
            ).hexdigest()

            if computed_signature != signature:
                return jsonify({'error': 'Invalid signature'}), 401

            data = request.get_json()
            logger.info(f"Paystack Callback Received: {data}")

            event = data.get('event')
            if event == 'charge.success':
                payment_data = data.get('data')
                reference = payment_data.get('reference')

                if reference:
                    transaction = Transaction.query.filter_by(payment_reference=reference).first()
                    if transaction:
                        if transaction.payment_status != PaymentStatus.COMPLETED:  # Avoid duplicate processing
                            transaction.payment_status = PaymentStatus.COMPLETED
                            db.session.commit()
                            logger.info(f"Payment successful for reference: {reference}. Triggering ticket completion.")
                            try:
                                from ticket import complete_ticket_operation  # Import here to avoid circular import
                                complete_ticket_operation(transaction)
                            except Exception as e:
                                logger.error(f"Error in complete_ticket_operation: {e}")
                                # You might want to handle this error appropriately (e.g., retry, log)
                            return jsonify({'message': 'Payment successful and ticket processing initiated'}), 200
                        else:
                            logger.info(f"Callback received for already completed transaction: {reference}")
                            return jsonify({'message': 'Transaction already processed'}), 200
                    else:
                        logger.error(f"Transaction not found for reference: {reference}")
                        return jsonify({'error': 'Transaction not found'}), 404
                else:
                    logger.error("Payment reference not found in callback data")
                    return jsonify({'error': 'Payment reference missing'}), 400
            else:
                logger.info(f"Received Paystack callback event: {event}")
                return jsonify({'message': 'Callback received for non-success event'}), 200

        except Exception as e:
            logger.error(f"Error processing Paystack callback: {e}")
            return jsonify({'error': 'Error processing callback'}), 500

class RefundPayment(Resource):
    @jwt_required()  # Require JWT authentication
    def post(self):
        try:
            identity = get_jwt_identity()
            from model import User
            user = User.query.get(identity)

            if not user:
                return {"error": "User not found"}, 404

            data = request.get_json()
            if not data or "reference" not in data or "amount" not in data:
                return {"error": "Missing reference or amount"}, 400

            reference = data["reference"]
            amount = int(data["amount"]) * 100

            url = "https://api.paystack.co/refund"
            headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
            payload = {"reference": reference, "amount": amount}

            response = requests.post(url, headers=headers, json=payload)
            res_data = response.json()
            logging.info(f"Paystack Refund Response: {res_data}")

            if res_data.get("status"):
                transaction = Transaction.query.filter_by(payment_reference=reference, user_id=user.id).first()
                if transaction:
                    transaction.payment_status = PaymentStatus.REFUNDED
                    db.session.commit()
                    return {"message": "Refund initiated successfully", "data": res_data["data"]}, 200

            return {"error": "Failed to initiate refund", "details": res_data.get("message", "Unknown error")}, 400
        except Exception as e:
            logging.error(f"Error initiating refund: {str(e)}")
            return {"error": "An error occurred", "details": str(e)}, 500

# Register routes
def register_paystack_routes(api):
    api.add_resource(InitializePayment, '/paystack/initialize')
    api.add_resource(VerifyPayment, '/paystack/verify/<string:reference>')
    api.add_resource(PaystackCallback, '/paystack/callback')
    api.add_resource(RefundPayment, '/paystack/refund')