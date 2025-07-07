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
from model import db, Currency, CurrencyCode  # Include Currency model + enum

# Import blueprints and resources
from auth import auth_bp
from oauth_config import oauth, init_oauth
from Event import register_event_resources
from ticket import register_ticket_resources, complete_ticket_operation
from scan import register_ticket_validation_resources
from mpesa_intergration import register_mpesa_routes
from paystack import register_paystack_routes
from ticket_type import register_ticket_type_resources
from admin_report import register_admin_report_resources
from email_utils import mail
from admin import register_admin_resources
from currency_routes import register_currency_resources

# Import the ReportResourceRegistry from organizer_report
from organizer_report.organizer_report import ReportResourceRegistry

# Initialize Flask app
app = Flask(__name__)

# ✅ Check for required DB env and normalize
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("EXTERNAL_DATABASE_URL environment variable is not set")

# ✅ Normalize postgres:// → postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ✅ Set DB URI before loading rest of config
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config.from_object(Config)

# Add CurrencyAPI Key to config
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

# Enable CORS
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

# Cloudinary setup
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# Register routes
app.register_blueprint(auth_bp, url_prefix="/auth")
register_event_resources(api)
register_ticket_resources(api)
register_ticket_validation_resources(api)
register_mpesa_routes(api)
register_paystack_routes(api)
register_ticket_type_resources(api)
register_admin_report_resources(api)
register_admin_resources(api)
register_currency_resources(api)

# Register organizer_report resources using the ReportResourceRegistry
ReportResourceRegistry.register_organizer_report_resources(api)

# Currency seeding logic (runs once)
from sqlalchemy.exc import IntegrityError
with app.app_context():
    db.create_all()  # Ensure all tables exist
    if Currency.query.count() == 0:
        print("🔁 Seeding currencies...")
        currency_info = {
            "USD": {"name": "US Dollar", "symbol": "$"},
            "EUR": {"name": "Euro", "symbol": "€"},
            "GBP": {"name": "British Pound", "symbol": "£"},
            "KES": {"name": "Kenyan Shilling", "symbol": "KSh"},
            "UGX": {"name": "Ugandan Shilling", "symbol": "USh"},
            "TZS": {"name": "Tanzanian Shilling", "symbol": "TSh"},
            "NGN": {"name": "Nigerian Naira", "symbol": "₦"},
            "GHS": {"name": "Ghanaian Cedi", "symbol": "₵"},
            "ZAR": {"name": "South African Rand", "symbol": "R"},
            "JPY": {"name": "Japanese Yen", "symbol": "¥"},
            "CAD": {"name": "Canadian Dollar", "symbol": "CA$"},
            "AUD": {"name": "Australian Dollar", "symbol": "A$"},
        }
        currency_objects = []
        for code in CurrencyCode:
            info = currency_info.get(code.value)
            currency = Currency(
                code=code,
                name=info["name"],
                symbol=info["symbol"],
                is_base_currency=(code.value == "USD")
            )
            currency_objects.append(currency)
        db.session.bulk_save_objects(currency_objects)
        try:
            db.session.commit()
            print("✅ Currency seeding complete.")
        except IntegrityError:
            db.session.rollback()
            print("⚠️ Currency seeding skipped (already exists).")

# Run app
if __name__ == "__main__":
    app.run(debug=True)
