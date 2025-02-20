from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy
from flask_restful import Api
from flask_migrate import Migrate
from flask_session import Session
from config import Config  
from model import db
from auth import auth_bp
from oauth_config import oauth, init_oauth
from Event import register_event_resources
from ticket import register_ticket_resources
from email_utils import mail

app = Flask(__name__)
app.config["DEBUG"] = True 
app.config.from_object(Config)  # Load configuration from config.py

# Initialize extensions
Session(app)
api = Api(app)
jwt = JWTManager(app)
db.init_app(app)
migrate = Migrate(app, db)
mail.init_app(app)  # Properly attach mail to Flask
init_oauth(app)  # Initialize OAuth

# Register authentication blueprint
app.register_blueprint(auth_bp, url_prefix="/auth")

# Register resources
register_event_resources(api)
register_ticket_resources(api)

if __name__ == "__main__":
    app.run(debug=True)
