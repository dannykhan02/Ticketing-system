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

# ✅ Use EXTERNAL_DATABASE_URL first, then try INTERNAL as fallback
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL") or os.getenv("INTERNAL_DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("Neither EXTERNAL_DATABASE_URL nor INTERNAL_DATABASE_URL environment variable is set")

# Fix postgres:// to postgresql:// 
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ✅ More robust SSL parameter handling
def prepare_database_url(url):
    """Prepare database URL with proper SSL configuration for Render"""
    # Always use SSL for external connections
    if "sslmode=" in url:
        return url
    
    # Add SSL parameters for Render PostgreSQL connections
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}sslmode=prefer"

DATABASE_URL = prepare_database_url(DATABASE_URL)

# ✅ Create Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Override database URI with our fixed version
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL

# ✅ Enhanced and more flexible SSL configuration for PostgreSQL
def get_engine_options(database_url):
    """Get appropriate engine options based on database URL"""
    return {
        'pool_size': 3,
        'max_overflow': 5,
        'pool_timeout': 20,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
        'connect_args': {
            'sslmode': 'prefer',
            'connect_timeout': 10,
            'application_name': 'ticketing_system'
        }
    }

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = get_engine_options(DATABASE_URL)

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

# ✅ Setup Flask-Session with filesystem fallback for reliability
app.config['SESSION_TYPE'] = 'filesystem'  # Start with filesystem
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'  # Render-compatible path
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'session:'

# Create session instance
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

# ✅ Enhanced initialization with better error handling and retries
def test_database_connection():
    """Test database connection with fallback for different SQLAlchemy versions"""
    try:
        # Try SQLAlchemy 2.x syntax first
        with db.engine.connect() as conn:
            result = conn.execute(db.text("SELECT 1")).fetchone()
            return True
    except AttributeError:
        try:
            # Fallback to SQLAlchemy 1.x syntax
            result = db.engine.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False
    except Exception:
        return False
def initialize_app():
    """Initialize the application with proper error handling and retries"""
    import time
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            with app.app_context():
                print(f"🔄 Initializing app (attempt {attempt + 1}/{max_retries})...")
                
                # Test database connection first
                if test_database_connection():
                    print("✅ Database connection successful")
                else:
                    raise Exception("Database connection test failed")
                
                # Create all database tables
                db.create_all()
                print("✅ Database tables created")
                
                # Initialize session
                session.init_app(app)
                print("✅ Session initialized")
                
                # Seed currencies if needed
                seed_currencies()
                
                print("🎉 Application initialized successfully!")
                return True
                
        except Exception as e:
            print(f"❌ Initialization attempt {attempt + 1} failed: {e}")
            
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print("❌ All initialization attempts failed")
                # Fallback to basic configuration
                try:
                    session.init_app(app)
                    print("⚠️ Running with minimal configuration")
                except Exception as session_error:
                    print(f"⚠️ Session initialization also failed: {session_error}")
                return False
    
    return False

def seed_currencies():
    """Seed currencies with error handling"""
    try:
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
                if info:  # Only add if we have info for this currency
                    currency = Currency(
                        code=code,
                        name=info["name"],
                        symbol=info["symbol"],
                        is_base_currency=(code.value == "USD")
                    )
                    currency_objects.append(currency)
            
            db.session.bulk_save_objects(currency_objects)
            db.session.commit()
            print("✅ Currency seeding complete.")
        else:
            print("ℹ️ Currencies already exist, skipping seeding.")
            
    except Exception as e:
        print(f"⚠️ Currency seeding failed: {e}")
        db.session.rollback()

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

# ✅ Add a basic health check route
@app.route('/')
def health_check():
    return {"status": "healthy", "message": "Ticketing system is running"}, 200

@app.route('/health')
def detailed_health_check():
    try:
        # Test database connection with fallback
        if test_database_connection():
            db_status = "connected"
        else:
            db_status = "connection failed"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "ok",
        "database": db_status,
        "database_url": DATABASE_URL.split('@')[0] + '@***',  # Hide credentials
        "timestamp": os.getenv("RENDER_GIT_COMMIT", "unknown")
    }, 200

# ✅ Run app locally
if __name__ == "__main__":
    initialize_app()    
    app.run(debug=True)

# ✅ For production (Gunicorn), initialize when imported
else:
    initialize_app()