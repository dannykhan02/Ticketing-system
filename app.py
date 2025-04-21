import os
import base64
import datetime
from flask import Flask, jsonify, request, session
from flask_sqlalchemy import SQLAlchemy
from flask_restful import Api, Resource
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_session import Session
from flask_cors import CORS
from dotenv import load_dotenv

# Import modules
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
from report import register_report_resources
from email_utils import mail
from admin import register_admin_resources  # Import the admin registration function

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Configure CORS with specific settings
CORS(app,
     origins=["http://localhost:8080", "https://ticketing-system-994g.onrender.com"],
     supports_credentials=True,
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"])

# ✅ Configure and initialize database
db.init_app(app)
app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = db
DATABASE_URL = os.getenv("EXTERNAL_DATABASE_URL") or os.getenv("INTERNAL_DATABASE_URL") or \
               'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app.db')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL

# ✅ Initialize extensions
Session(app)
api = Api(app)
jwt = JWTManager(app)
migrate = Migrate(app, db)
mail.init_app(app)
init_oauth(app)

# ✅ Register blueprints and API resources
app.register_blueprint(auth_bp, url_prefix="/auth")
register_event_resources(api)
register_ticket_resources(api)
register_ticket_validation_resources(api)
register_mpesa_routes(api, complete_ticket_operation)
register_paystack_routes(api)
register_ticket_type_resources(api)
register_report_resources(api)
register_admin_resources(api)  # Register admin resources

# ✅ Run app
if __name__ == "__main__":
    app.run(debug=True)
