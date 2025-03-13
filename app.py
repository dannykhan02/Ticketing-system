import os
import base64
import datetime
from flask import Flask, jsonify, request, session
from flask_sqlalchemy import SQLAlchemy
from flask_restful import Api, Resource
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_session import Session
from dotenv import load_dotenv

# Import modules
from config import Config  # Ensure you have config.py with Paystack/M-Pesa credentials
from model import db  # Ensure this is the only db instance
from auth import auth_bp
from oauth_config import oauth, init_oauth
from Event import register_event_resources
from ticket import register_ticket_resources
from scan import register_ticket_validation_resources
from mpesa_intergration import register_mpesa_routes
from paystack import register_paystack_routes
from email_utils import mail
from update_ngork import update_ngrok_urls  # Import the function

# Load environment variables
load_dotenv()

# Ensure Ngrok URLs are updated before starting the app
update_ngrok_urls()

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)  # Load configuration

# ✅ Initialize database FIRST
db.init_app(app)

# ✅ Configure sessions (No Redis, using SQLAlchemy for session storage)
app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = db  # Use the same db instance

# ✅ Initialize Flask extensions
Session(app)
api = Api(app)
jwt = JWTManager(app)
migrate = Migrate(app, db)
mail.init_app(app)
init_oauth(app)

# ✅ Register blueprints and resources
app.register_blueprint(auth_bp, url_prefix="/auth")
register_event_resources(api)
register_ticket_resources(api)
register_ticket_validation_resources(api)
register_mpesa_routes(api)
register_paystack_routes(api)

if __name__ == "__main__":
    app.run(debug=True)
