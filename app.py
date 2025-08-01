import os
from dotenv import load_dotenv
import time
import sys

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
from config import Config, config
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

def get_database_url():
    """Get the correct database URL with proper priority and validation"""
    # Check for external URL first (for Render production)
    external_url = os.getenv("EXTERNAL_DATABASE_URL")
    internal_url = os.getenv("INTERNAL_DATABASE_URL") 
    database_url = os.getenv("DATABASE_URL")  # Fallback for other platforms
    
    # Priority order: EXTERNAL -> DATABASE_URL -> INTERNAL
    selected_url = external_url or database_url or internal_url
    
    if not selected_url:
        raise ValueError("No database URL found. Please set EXTERNAL_DATABASE_URL, DATABASE_URL, or INTERNAL_DATABASE_URL")
    
    # Log which URL type we're using (without exposing credentials)
    if external_url and selected_url == external_url:
        print("🔗 Using EXTERNAL_DATABASE_URL (recommended for production)")
    elif database_url and selected_url == database_url:
        print("🔗 Using DATABASE_URL")
    else:
        print("🔗 Using INTERNAL_DATABASE_URL (fallback)")
    
    # Fix postgres:// to postgresql://
    if selected_url.startswith("postgres://"):
        selected_url = selected_url.replace("postgres://", "postgresql://", 1)
        print("🔄 Fixed postgres:// to postgresql://")
    
    # Validate that we're not using internal hostname for production
    if "dpg-" in selected_url and "-a.ohio-postgres.render.com" in selected_url:
        print("⚠️ Warning: Using internal hostname - this may cause connectivity issues")
    elif "ohio-postgres.render.com" in selected_url:
        print("✅ Using external hostname - optimal for production")
    
    return selected_url

def prepare_database_url(url):
    """Prepare database URL with proper SSL configuration"""
    if not url:
        return url
        
    # Skip SSL modification if already present
    if "sslmode=" in url:
        return url
    
    # Add SSL parameters for PostgreSQL connections
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}sslmode=prefer&connect_timeout=30"

def get_engine_options():
    """Get database engine options optimized for Render"""
    # Use configuration values if available, otherwise use defaults
    config_class = config.get(os.getenv('FLASK_ENV', 'production'), Config)
    
    return {
        'pool_size': getattr(config_class, 'DB_POOL_SIZE', 5),
        'max_overflow': getattr(config_class, 'DB_MAX_OVERFLOW', 10),
        'pool_timeout': getattr(config_class, 'DB_POOL_TIMEOUT', 30),
        'pool_recycle': getattr(config_class, 'DB_POOL_RECYCLE', 3600),
        'pool_pre_ping': True,
        'connect_args': {
            'sslmode': 'prefer',
            'connect_timeout': getattr(config_class, 'DATABASE_PING_TIMEOUT', 30),
            'application_name': 'ticketing_system',
            'options': '-c statement_timeout=30000'  # 30 second statement timeout
        }
    }

# ✅ Get and prepare database URL
try:
    DATABASE_URL = get_database_url()
    DATABASE_URL = prepare_database_url(DATABASE_URL)
    print(f"✅ Database URL configured: {DATABASE_URL.split('@')[0]}@***")
except Exception as e:
    print(f"❌ Database URL configuration failed: {e}")
    sys.exit(1)

# ✅ Create Flask app with environment-specific configuration
app = Flask(__name__)

# Load appropriate configuration based on environment
config_name = os.getenv('FLASK_ENV', 'production')
config_class = config.get(config_name, Config)
app.config.from_object(config_class)

# Validate configuration
try:
    config_class.validate_config()
    print("✅ Configuration validation passed")
except ValueError as e:
    print(f"❌ Configuration validation failed: {e}")
    # Don't exit in production, but log the error
    if config_name == 'production':
        print("⚠️ Continuing with potentially invalid configuration in production")
    else:
        sys.exit(1)

# Override database configuration
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = config_class.get_database_engine_options()

# External APIs
app.config['CURRENCY_API_KEY'] = os.getenv('CURRENCY_API_KEY')

# JWT Cookie Configuration - Production optimized
app.config['JWT_COOKIE_SECURE'] = True
app.config['JWT_COOKIE_SAMESITE'] = "None"
app.config['JWT_COOKIE_CSRF_PROTECT'] = False
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_ACCESS_COOKIE_NAME'] = 'access_token'
app.config['JWT_HEADER_NAME'] = 'Authorization'
app.config['JWT_HEADER_TYPE'] = 'Bearer'

# CORS Configuration - Use configuration values
CORS(app,
     origins=app.config.get('CORS_ORIGINS', [
         "http://localhost:8080", 
         "https://pulse-ticket-verse.netlify.app",
         "https://ticketing-system-994g.onrender.com"
     ]),
     supports_credentials=True,
     expose_headers=["Set-Cookie"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"])

# ✅ Initialize extensions
db.init_app(app)

# ✅ Enhanced Flask-Session configuration
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.getenv('SESSION_DIR', '/tmp/flask_sessions')
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'session:'
app.config['SESSION_FILE_THRESHOLD'] = 500

# Create session directory if it doesn't exist
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

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

def test_database_connection(max_retries=3, retry_delay=2):
    """Test database connection with retries"""
    for attempt in range(max_retries):
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
            except Exception as e:
                print(f"Database connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
        except Exception as e:
            print(f"Database connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
    
    return False

def seed_currencies():
    """Seed currencies with comprehensive error handling"""
    try:
        # Check if currencies already exist
        existing_count = Currency.query.count()
        if existing_count > 0:
            print(f"ℹ️ Found {existing_count} currencies, skipping seeding.")
            return True

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
            if info:
                currency = Currency(
                    code=code,
                    name=info["name"],
                    symbol=info["symbol"],
                    is_base_currency=(code.value == "USD")
                )
                currency_objects.append(currency)
        
        if currency_objects:
            db.session.bulk_save_objects(currency_objects)
            db.session.commit()
            print(f"✅ Successfully seeded {len(currency_objects)} currencies.")
            return True
        else:
            print("⚠️ No currency objects to seed.")
            return True
            
    except Exception as e:
        print(f"❌ Currency seeding failed: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return False

def initialize_app():
    """Initialize the application with enhanced error handling and graceful degradation"""
    max_retries = 5
    base_retry_delay = 2
    
    print("🚀 Starting application initialization...")
    
    for attempt in range(max_retries):
        retry_delay = base_retry_delay * (2 ** attempt)  # Exponential backoff
        
        try:
            with app.app_context():
                print(f"🔄 Initialization attempt {attempt + 1}/{max_retries}...")
                
                # Test database connection with retries
                print("🔍 Testing database connection...")
                if not test_database_connection():
                    raise Exception("Database connection failed after retries")
                
                print("✅ Database connection successful")
                
                # Create database tables
                print("📋 Creating database tables...")
                db.create_all()
                print("✅ Database tables created/verified")
                
                # Initialize session
                print("🔧 Initializing session...")
                session.init_app(app)
                print("✅ Session initialized")
                
                # Seed currencies
                print("💱 Checking currency data...")
                if seed_currencies():
                    print("✅ Currency data ready")
                else:
                    print("⚠️ Currency seeding had issues, but continuing...")
                
                print("🎉 Application initialized successfully!")
                return True
                
        except Exception as e:
            print(f"❌ Initialization attempt {attempt + 1} failed: {e}")
            
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print("❌ All initialization attempts failed")
                print("🔄 Attempting graceful degradation...")
                
                # Try minimal initialization as fallback
                try:
                    with app.app_context():
                        session.init_app(app)
                        print("⚠️ Running with minimal configuration (session only)")
                        return False
                except Exception as fallback_error:
                    print(f"❌ Even minimal configuration failed: {fallback_error}")
                    return False
    
    return False

# ✅ Register all routes
print("📡 Registering application routes...")
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
print("✅ Routes registered")

# ✅ Enhanced health check routes
@app.route('/')
def health_check():
    """Basic health check"""
    return {
        "status": "healthy", 
        "message": "Ticketing system is running",
        "timestamp": time.time()
    }, 200

@app.route('/health')
def detailed_health_check():
    """Detailed health check with database status"""
    health_info = {
        "status": "ok",
        "timestamp": time.time(),
        "version": os.getenv("RENDER_GIT_COMMIT", "unknown")
    }
    
    # Test database connection
    try:
        if test_database_connection(max_retries=1):
            health_info["database"] = "connected"
        else:
            health_info["database"] = "connection failed"
            health_info["status"] = "degraded"
    except Exception as e:
        health_info["database"] = f"error: {str(e)}"
        health_info["status"] = "degraded"
    
    # Add database URL info (without credentials)
    if DATABASE_URL:
        health_info["database_url"] = DATABASE_URL.split('@')[0] + '@***'
    
    status_code = 200 if health_info["status"] == "ok" else 503
    return health_info, status_code

@app.route('/ready')
def readiness_check():
    """Kubernetes/Docker readiness probe"""
    try:
        with app.app_context():
            if test_database_connection(max_retries=1):
                return {"status": "ready"}, 200
            else:
                return {"status": "not ready", "reason": "database unavailable"}, 503
    except Exception as e:
        return {"status": "not ready", "reason": str(e)}, 503

# ✅ Error handlers
@app.errorhandler(500)
def internal_error(error):
    return {"error": "Internal server error", "status": 500}, 500

@app.errorhandler(404)
def not_found(error):
    return {"error": "Resource not found", "status": 404}, 404

# ✅ Application startup
if __name__ == "__main__":
    # Development mode
    print("🏃‍♂️ Running in development mode")
    initialize_app()
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
else:
    # Production mode (Gunicorn)
    print("🏭 Running in production mode")
    app_initialized = initialize_app()
    if not app_initialized:
        print("⚠️ Application started with degraded functionality")