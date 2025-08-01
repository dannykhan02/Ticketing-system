import os
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_restful import Api
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_session import Session
from flask_cors import CORS
import cloudinary

# Config and models
from config import Config
from model import db, Currency, CurrencyCode

# Blueprints and modules
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
from organizer_report.organizer_report import ReportResourceRegistry
from stats import register_secure_system_stats_resources

# ✅ Normalize and validate DATABASE_URL
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("EXTERNAL_DATABASE_URL environment variable is not set")

# Fix postgres:// to postgresql:// and ensure SSL
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Add SSL parameter if not present
if "sslmode=" not in DATABASE_URL:
    separator = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{separator}sslmode=require"

# ✅ Create Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Override database URI with our fixed version
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL

# ✅ Enhanced SSL configuration for PostgreSQL
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    'pool_size': 5,
    'max_overflow': 10,
    'pool_timeout': 30,
    'pool_recycle': 1800,
    'pool_pre_ping': True,
    'connect_args': {
        'sslmode': 'require',
        'sslcert': None,
        'sslkey': None,
        'sslrootcert': None,
    }
}

# External APIs
app.config['CURRENCY_API_KEY'] = os.getenv('CURRENCY_API_KEY')

# JWT Cookie Configuration
app.config['JWT_COOKIE_SECURE'] = True
app.config['JWT_COOKIE_SAMESITE'] = "None"
app.config['JWT_COOKIE_CSRF_PROTECT'] = False
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_ACCESS_COOKIE_NAME'] = 'access_token'
app.config['JWT_HEADER_NAME'] = 'Authorization'
app.config['JWT_HEADER_TYPE'] = 'Bearer'

# CORS Config
CORS(app,
     origins=["http://localhost:8080", "https://pulse-ticket-verse.netlify.app"],
     supports_credentials=True,
     expose_headers=["Set-Cookie"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"])

# ✅ Initialize extensions
db.init_app(app)

# ✅ Setup Flask-Session with proper configuration
app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = db
app.config['SESSION_SQLALCHEMY_TABLE'] = 'sessions'
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'session:'

# Create session instance but don't initialize yet
session = Session()

api = Api(app)
jwt = JWTManager(app)
migrate = Migrate(app, db)
mail.init_app(app)
init_oauth(app)

# ✅ Cloudinary Configuration
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# ✅ Initialize session after all database setup is complete
def init_session_tables():
    """Initialize session tables safely"""
    try:
        with app.app_context():
            # Ensure all tables are created first
            db.create_all()
            # Now initialize Flask-Session
            session.init_app(app)
            print("✅ Session tables initialized successfully")
    except Exception as e:
        print(f"❌ Error initializing session tables: {e}")
        # Fallback to filesystem sessions if database sessions fail
        app.config['SESSION_TYPE'] = 'filesystem'
        session.init_app(app)
        print("⚠️ Falling back to filesystem sessions")

# ✅ Register all routes
app.register_blueprint(auth_bp, url_prefix="/auth")
register_event_resources(api)
register_ticket_resources(api)
register_ticket_validation_resources(api)
register_mpesa_routes(api, complete_ticket_operation)
register_paystack_routes(api)
register_ticket_type_resources(api)
register_admin_report_resources(api)
register_admin_resources(api)
register_currency_resources(api)
ReportResourceRegistry.register_organizer_report_resources(api)
register_secure_system_stats_resources(api)

# ✅ Initialize everything properly
def initialize_app():
    """Initialize the application with proper error handling"""
    with app.app_context():
        try:
            # Create all database tables
            db.create_all()
            print("✅ Database tables created")
            
            # Initialize session tables
            session.init_app(app)
            print("✅ Session initialized")
            
            # Seed currencies if needed
            if Currency.query.count() == 0:
                print("🔁 Seeding currencies...")
                from sqlalchemy.exc import IntegrityError
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
        except Exception as e:
            print(f"❌ Initialization error: {e}")
            # If database sessions fail, use filesystem sessions
            app.config['SESSION_TYPE'] = 'filesystem'
            session.init_app(app)
            print("⚠️ Using filesystem sessions as fallback")

# ✅ Run app locally
if __name__ == "__main__":
    initialize_app()    
    app.run(debug=True)

# ✅ For production (Gunicorn), initialize when imported
else:
    initialize_app()