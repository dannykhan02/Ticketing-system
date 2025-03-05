import os
import redis
from flask import Flask, jsonify, session
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
from scan import register_ticket_validation_resources
from email_utils import mail

app = Flask(__name__)
app.config["DEBUG"] = True 
app.config.from_object(Config)  # Load configuration from config.py

app.secret_key = "2a14d2885c2bf272f56ba0f0903c62447ba97d31f7db1f56bf8f5cef99ec25d5"

# Initialize extensions
Session(app)
api = Api(app)
jwt = JWTManager(app)
db.init_app(app)
migrate = Migrate(app, db)
mail.init_app(app)  # Properly attach mail to Flask
init_oauth(app)  # Initialize OAuth

# Debug Redis Connection
try:
    test_redis = redis.StrictRedis(host="localhost", port=6379, db=0)
    test_redis.ping()
    print("✅ Redis is connected.")
except redis.ConnectionError:
    print("❌ Redis is NOT connected! Check your Redis server.")

@app.route("/set-session")
def set_session():
    session["test_key"] = "Hello Redis"
    return "Session set!"

@app.route("/get-session")
def get_session():
    return session.get("test_key", "No session found")

# Register authentication blueprint
app.register_blueprint(auth_bp, url_prefix="/auth")

# Register resources
register_event_resources(api)
register_ticket_resources(api)
register_ticket_validation_resources(api)

# Error handling
print("SESSION_TYPE:", app.config["SESSION_TYPE"])
print("SESSION_PERMANENT:", app.config["SESSION_PERMANENT"])


if __name__ == "__main__":
    app.run(debug=True)
