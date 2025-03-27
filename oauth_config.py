from authlib.integrations.flask_client import OAuth
from config import Config

oauth = OAuth()

def init_oauth(app):
    oauth.init_app(app)
    app.secret_key = app.config["SECRET_KEY"]
    oauth.register(
        name='google',
        client_id=Config.GOOGLE_CLIENT_ID,
        client_secret=Config.GOOGLE_CLIENT_SECRET,
        access_token_url='https://oauth2.googleapis.com/token',
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        api_base_url='https://www.googleapis.com/oauth2/v1/',
        userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
        jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
        client_kwargs={
            'scope': 'openid email profile',
            'redirect_uri': Config.GOOGLE_REDIRECT_URI
        }
    )