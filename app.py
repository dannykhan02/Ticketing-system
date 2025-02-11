from flask import Flask
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy
from flask_restful import Api
from flask_migrate import Migrate 
from model import db  # Importing db instance from model.py

# Initialize extensions
app = Flask(__name__)
api = Api(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///Ticketingsystem.db'  # Replace with your new DB name
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'dd3954b719940298113dfd9714aa2390baf22f81759e253e8df2ef2fa6177210'

jwt = JWTManager(app)
db.init_app(app)
migrate = Migrate(app, db)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # Create tables if they don't exist
    app.run(debug=True)



