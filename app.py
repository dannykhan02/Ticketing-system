from dotenv import load_dotenv
load_dotenv()  # Load environment variables first

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_restful import Api
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_session import Session
from flask_cors import CORS
import cloudinary

# Load configuration
from config import Config
from model import db
from auth import auth_bp
from oauth_config import oauth, init_oauth
from Event import register_event_resources
from ticket import register_ticket_resources, complete_ticket_operation
from scan import register_ticket_validation_resources
from mpesa_intergration import register_mpesa_routes
from paystack import register_paystack_routes
from ticket_type import register_ticket_type_resources
from organizer_report import ReportResourceRegistry
from admin_report import register_admin_report_resources
from email_utils import mail
from admin import register_admin_resources

# ✅ Import currency-related resources as a module
from currency_routes import register_currency_resources # This is correct and remains the same

# Initialize Flask app
app = Flask(__name__)

# Check for required DB env
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("EXTERNAL_DATABASE_URL environment variable is not set")

# App configuration
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config.from_object(Config)

# ✅ Add CurrencyAPI Key to config
app.config['CURRENCY_API_KEY'] = os.getenv('CURRENCY_API_KEY')

# JWT and Session Config
app.config['JWT_COOKIE_SECURE'] = True
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_ACCESS_COOKIE_NAME'] = 'access_token'
app.config['JWT_HEADER_NAME'] = 'Authorization'
app.config['JWT_HEADER_TYPE'] = 'Bearer'
app.config['JWT_COOKIE_CSRF_PROTECT'] = False
app.config['JWT_COOKIE_SAMESITE'] = "None"
app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Enable CORS for frontends
CORS(app,
     origins=["http://localhost:8080", "https://pulse-ticket-verse.netlify.app"],
     supports_credentials=True,
     expose_headers=["Set-Cookie"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"])

# Initialize extensions
db.init_app(app)
Session(app)
api = Api(app)
jwt = JWTManager(app)
migrate = Migrate(app, db)
mail.init_app(app)
init_oauth(app)

# Cloudinary config
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# Register all routes and resources
app.register_blueprint(auth_bp, url_prefix="/auth")
register_event_resources(api)
register_ticket_resources(api)
register_ticket_validation_resources(api)
register_mpesa_routes(api, complete_ticket_operation)
register_paystack_routes(api)
register_ticket_type_resources(api)
ReportResourceRegistry.register_organizer_report_resources(api)
register_admin_report_resources(api)
register_admin_resources(api)

# ✅ Register all currency-related API routes in one function
register_currency_resources(api) # This call now correctly registers all currency routes from currency_routes.py

# Run app
if __name__ == "__main__":
    app.run(debug=True)