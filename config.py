import os
import tempfile
import redis
from datetime import timedelta

# Do NOT call load_dotenv here. It should be in app.py

class Config:
    # Environment Detection
    ENVIRONMENT = os.getenv("FLASK_ENV", "production")
    DEBUG = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1")
    
    # Paystack Configuration
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
    PAYSTACK_CALLBACK_URL = os.getenv("PAYSTACK_CALLBACK_URL")
    PAYSTACK_WEBHOOK_URL = os.getenv("PAYSTACK_WEBHOOK_URL")

    # Google OAuth Configuration
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "default-client-id")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "default-client-secret")
    
    # Dynamic redirect URI based on environment
    BASE_URL = os.getenv("BASE_URL", "https://ticketing-system-994g.onrender.com")
    GOOGLE_REDIRECT_URI = f"{BASE_URL}/auth/callback/google"
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

    # Security Configuration
    SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
    
    # Enhanced Email Configuration
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587").strip() or 587)
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "False").lower() in ("true", "1", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_USERNAME") or "no-reply@ticketing-system.com"
    
    # Email timeout and retry configuration
    MAIL_TIMEOUT = int(os.getenv("MAIL_TIMEOUT", "30"))
    MAIL_MAX_EMAILS = int(os.getenv("MAIL_MAX_EMAILS", "50"))

    # Database Configuration
    # Priority: DATABASE_URL > EXTERNAL_DATABASE_URL > fallback
    _database_url = os.getenv("DATABASE_URL") or os.getenv("EXTERNAL_DATABASE_URL")
    if _database_url:
        # Render/Heroku often provide postgres:// but SQLAlchemy needs postgresql://
        if _database_url.startswith("postgres://"):
            _database_url = _database_url.replace("postgres://", "postgresql://", 1)
        # Ensure SSL mode is set for PostgreSQL connections
        if "postgresql://" in _database_url and "sslmode=" not in _database_url:
            _database_url += "?sslmode=require" if "?" not in _database_url else "&sslmode=require"
        SQLALCHEMY_DATABASE_URI = _database_url
    else:
        # Fallback for local development
        SQLALCHEMY_DATABASE_URI = os.getenv(
            "SQLALCHEMY_DATABASE_URI",
            "sqlite:///ticketing_system.db"
        )
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = DEBUG  # Only record queries in debug mode
    SQLALCHEMY_ECHO = DEBUG and os.getenv("SQL_ECHO", "False").lower() in ("true", "1")
    
    # Database connection pool settings (will be merged with app.py settings)
    DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))

    # JWT Configuration
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "fallback-jwt-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=int(os.getenv("JWT_ACCESS_TOKEN_HOURS", "24")))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(os.getenv("JWT_REFRESH_TOKEN_DAYS", "30")))
    
    # JWT Cookie settings for production
    JWT_COOKIE_SECURE = not DEBUG  # Secure cookies in production
    JWT_COOKIE_HTTPONLY = True
    JWT_COOKIE_SAMESITE = "None" if not DEBUG else "Lax"  # None for cross-origin in production
    JWT_COOKIE_CSRF_PROTECT = False  # Simplified for API usage
    JWT_TOKEN_LOCATION = ["cookies", "headers"]  # Support both methods
    JWT_ACCESS_COOKIE_NAME = "access_token"
    JWT_REFRESH_COOKIE_NAME = "refresh_token"
    JWT_HEADER_NAME = "Authorization"
    JWT_HEADER_TYPE = "Bearer"

    # M-Pesa Configuration
    CONSUMER_KEY = os.getenv("CONSUMER_KEY")
    CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
    BUSINESS_SHORTCODE = os.getenv("BUSINESS_SHORTCODE")
    PASSKEY = os.getenv("PASSKEY")
    CALLBACK_URL = os.getenv("CALLBACK_URL")
    
    # M-Pesa timeout settings
    MPESA_TIMEOUT = int(os.getenv("MPESA_TIMEOUT", "30"))
    MPESA_RETRY_ATTEMPTS = int(os.getenv("MPESA_RETRY_ATTEMPTS", "3"))

    # Redis Configuration (moved up for session config)
    REDIS_URL = os.getenv("REDIS_URL")
    REDIS_TIMEOUT = int(os.getenv("REDIS_TIMEOUT", "5"))

    # Session Configuration - Improved with Redis fallback
    SESSION_COOKIE_SECURE = not DEBUG  # Secure cookies in production
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "None" if not DEBUG else "Lax"  # Match JWT settings for consistency
    SESSION_COOKIE_DOMAIN = None  # Let browser handle domain
    PERMANENT_SESSION_LIFETIME = timedelta(
        hours=int(os.getenv("SESSION_LIFETIME_HOURS", "24"))
    )
    
    # Smart session storage - prefer Redis in production, filesystem in development
    _has_redis = bool(REDIS_URL)
    SESSION_TYPE = "redis" if _has_redis else "filesystem"
    
    # Redis session config (used if Redis is available)
    if _has_redis:
        try:
            SESSION_REDIS = redis.from_url(REDIS_URL, 
                                         socket_timeout=REDIS_TIMEOUT,
                                         socket_connect_timeout=REDIS_TIMEOUT,
                                         decode_responses=True)
            SESSION_USE_SIGNER = True
            SESSION_KEY_PREFIX = "ticketing_oauth:"
        except Exception:
            # Fallback to filesystem if Redis connection fails
            SESSION_TYPE = "filesystem"
    
    # Filesystem session config (fallback or development)
    if SESSION_TYPE == "filesystem":
        SESSION_FILE_DIR = os.path.join(tempfile.gettempdir(), "flask_sessions")
        SESSION_FILE_THRESHOLD = int(os.getenv("SESSION_FILE_THRESHOLD", "500"))
        SESSION_USE_SIGNER = True
        SESSION_KEY_PREFIX = "ticketing_session:"
        
        # Ensure session directory exists
        try:
            os.makedirs(SESSION_FILE_DIR, exist_ok=True)
        except Exception:
            pass  # Will fall back to default temp directory
    
    SESSION_PERMANENT = True

    # Frontend Configuration
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://pulse-ticket-verse.netlify.app')
    
    # Additional allowed origins for CORS
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173", 
        "http://localhost:8080",
        "https://pulse-ticket-verse.netlify.app",
        BASE_URL
    ]

    # Currency API Configuration
    CURRENCY_API_KEY = os.getenv("CURRENCY_API_KEY")
    CURRENCY_API_BASE_URL = os.getenv("CURRENCY_API_BASE_URL", "https://api.currencyapi.com/v3")
    CURRENCY_UPDATE_INTERVAL = int(os.getenv("CURRENCY_UPDATE_INTERVAL", "3600"))  # 1 hour

    # File Upload Configuration
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", "16777216"))  # 16MB
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/tmp/uploads")
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

    # Cloudinary Configuration (for file uploads)
    CLOUDINARY_CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
    CLOUDINARY_API_KEY = os.getenv('CLOUDINARY_API_KEY')
    CLOUDINARY_API_SECRET = os.getenv('CLOUDINARY_API_SECRET')
    CLOUDINARY_TIMEOUT = int(os.getenv("CLOUDINARY_TIMEOUT", "30"))

    # API Rate Limiting
    RATELIMIT_STORAGE_URL = REDIS_URL or "memory://"
    RATELIMIT_STRATEGY = "fixed-window"
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "1000 per hour")

    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    # Application Performance
    TESTING = os.getenv("TESTING", "False").lower() in ("true", "1")
    PREFERRED_URL_SCHEME = "https" if not DEBUG else "http"
    
    # Health Check Configuration
    HEALTH_CHECK_TIMEOUT = int(os.getenv("HEALTH_CHECK_TIMEOUT", "30"))
    DATABASE_PING_TIMEOUT = int(os.getenv("DATABASE_PING_TIMEOUT", "10"))
    
    # Feature Flags
    ENABLE_SWAGGER = os.getenv("ENABLE_SWAGGER", "False").lower() in ("true", "1")
    ENABLE_METRICS = os.getenv("ENABLE_METRICS", "True").lower() in ("true", "1")
    ENABLE_CACHING = os.getenv("ENABLE_CACHING", "True").lower() in ("true", "1")
    
    # AI Assistant Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")
    AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
    AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.7"))
    AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "500"))
    AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "30"))
    AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "3"))  # Add this line
    ENABLE_AI_FEATURES = os.getenv("ENABLE_AI_FEATURES", "true").lower() in ("true", "1")

    @classmethod
    def validate_config(cls):
        """Validate critical configuration values"""
        required_vars = [
            'SECRET_KEY',
            'JWT_SECRET_KEY',
        ]
        
        missing_vars = []
        for var in required_vars:
            if not getattr(cls, var) or getattr(cls, var).startswith('fallback-'):
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # Validate email configuration if email features are used
        if cls.MAIL_USERNAME and not cls.MAIL_PASSWORD:
            raise ValueError("MAIL_PASSWORD is required when MAIL_USERNAME is set")
        
        # Validate payment configurations
        if cls.PAYSTACK_SECRET_KEY and not cls.PAYSTACK_PUBLIC_KEY:
            raise ValueError("PAYSTACK_PUBLIC_KEY is required when PAYSTACK_SECRET_KEY is set")
        
        return True

    @classmethod
    def get_database_engine_options(cls):
        """Get database engine options based on configuration"""
        options = {
            'pool_size': cls.DB_POOL_SIZE,
            'max_overflow': cls.DB_MAX_OVERFLOW,
            'pool_timeout': cls.DB_POOL_TIMEOUT,
            'pool_recycle': cls.DB_POOL_RECYCLE,
            'pool_pre_ping': True,
            'echo': cls.SQLALCHEMY_ECHO
        }
        
        # Only add connect_args for PostgreSQL
        if cls.SQLALCHEMY_DATABASE_URI and 'postgresql' in cls.SQLALCHEMY_DATABASE_URI:
            options['connect_args'] = {
                'sslmode': 'require',  # Changed from 'prefer' to 'require' for Render
                'connect_timeout': cls.DATABASE_PING_TIMEOUT,
                'application_name': 'ticketing_system'
            }
        
        return options

    @classmethod
    def is_production(cls):
        """Check if running in production environment"""
        return cls.ENVIRONMENT.lower() == 'production'
    
    @classmethod
    def is_development(cls):
        """Check if running in development environment"""
        return cls.ENVIRONMENT.lower() in ('development', 'dev')

    @classmethod
    def get_session_config_info(cls):
        """Get information about current session configuration"""
        return {
            "session_type": cls.SESSION_TYPE,
            "has_redis": cls._has_redis,
            "session_dir": getattr(cls, 'SESSION_FILE_DIR', None),
            "cookie_secure": cls.SESSION_COOKIE_SECURE,
            "cookie_samesite": cls.SESSION_COOKIE_SAMESITE,
            "permanent_session": cls.SESSION_PERMANENT
        }


class DevelopmentConfig(Config):
    """Development-specific configuration"""
    DEBUG = True
    TESTING = False
    
    # Use less strict settings for development
    JWT_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = "Lax"
    
    # Force filesystem sessions in development for easier debugging
    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = os.path.join(tempfile.gettempdir(), "flask_sessions_dev")
    
    # More verbose logging in development
    SQLALCHEMY_ECHO = True
    LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    """Production-specific configuration"""
    DEBUG = False
    TESTING = False
    
    # Enforce security in production
    JWT_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "None"  # Required for cross-origin
    
    # Prefer Redis sessions in production
    if Config.REDIS_URL:
        SESSION_TYPE = "redis"
    
    # Minimal logging in production
    SQLALCHEMY_ECHO = False
    LOG_LEVEL = "WARNING"


class TestingConfig(Config):
    """Testing-specific configuration"""
    TESTING = True
    DEBUG = True
    
    # Use in-memory database for testing
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    
    # Use in-memory sessions for testing
    SESSION_TYPE = "null"  # No session persistence needed for tests
    
    # Disable external services in testing
    MAIL_SUPPRESS_SEND = True
    WTF_CSRF_ENABLED = False


# Configuration dictionary for easy switching
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': Config
}