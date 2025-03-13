from authlib.integrations.flask_client import OAuth
from config import Config

oauth = OAuth()

def init_oauth(app):
    """Initialize OAuth with Google authentication."""
    oauth.init_app(app)
    app.secret_key = app.config["SECRET_KEY"]
    oauth.register(
        name='google',
        client_id=Config.GOOGLE_CLIENT_ID,
        client_secret=Config.GOOGLE_CLIENT_SECRET,
        access_token_url='https://oauth2.googleapis.com/token',
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        userinfo_url='https://openidconnect.googleapis.com/v1/userinfo',
        client_kwargs={
            'scope': 'openid email profile',
            'redirect_uri': Config.GOOGLE_REDIRECT_URI  # Corrected redirect URI
        },
    )
#     oauth.register(
#         name='google',
#         client_id=Config.GOOGLE_CLIENT_ID,
#         client_secret=Config.GOOGLE_CLIENT_SECRET,    