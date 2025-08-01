import os
from datetime import timedelta

# Do NOT call load_dotenv here. It should be in app.py

class Config:
    # Paystack
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
    PAYSTACK_CALLBACK_URL = os.getenv("PAYSTACK_CALLBACK_URL")
    PAYSTACK_WEBHOOK_URL = os.getenv("PAYSTACK_WEBHOOK_URL")

    # Google OAuth
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "default-client-id")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "default-client-secret")
    GOOGLE_REDIRECT_URI = "https://ticketing-system-994g.onrender.com/auth/callback/google"
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

    # Email
    SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587").strip() or 587)
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER") or MAIL_USERNAME or "no-reply@example.com"

    # Database URI - Let app.py handle the URL construction
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "fallback-jwt-secret")

    # M-Pesa
    CONSUMER_KEY = os.getenv("CONSUMER_KEY")
    CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
    BUSINESS_SHORTCODE = os.getenv("BUSINESS_SHORTCODE")
    PASSKEY = os.getenv("PASSKEY")
    CALLBACK_URL = os.getenv("CALLBACK_URL")

    # Session Configuration - Remove conflicting session configs
    # These will be set in app.py after proper initialization
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)

    # Frontend
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

    # CurrencyAPI
    CURRENCY_API_KEY = os.getenv("CURRENCY_API_KEY")

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")