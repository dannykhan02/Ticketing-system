from flask import Blueprint, jsonify, request, url_for
from flask_jwt_extended import (
    create_access_token, get_jwt_identity, jwt_required
)
from email_validator import validate_email, EmailNotValidError
import phonenumbers as pn
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from uuid import uuid4
from flask import session
from model import db, User
from datetime import timedelta
from oauth_config import oauth


from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer
from config import Config


auth_bp = Blueprint('auth', __name__)

# Serializer for generating secure tokens
serializer = URLSafeTimedSerializer(Config.SECRET_KEY)

@auth_bp.route('/login/google')
def google_login():
    state = str(uuid4())  # Generate a unique state
    session['_state'] = state  # Store in session
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri, state=state)

@auth_bp.route('/callback/google')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.get('userinfo').json()
        email = user_info['email']
        name = user_info.get('name', '')

        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, name=name, role="ATTENDEE")
            db.session.add(user)
            db.session.commit()

        access_token = create_access_token(
            identity={"id": user.id, "email": user.email, "role": user.role}
        )
        return jsonify({"msg": "Login successful", "access_token": access_token}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



def generate_token(user):
    return create_access_token(
        identity=str(user.id),  # Convert user ID to string
        additional_claims={
            "email": user.email,
            "role": str(user.role)  # Convert Enum to string if necessary
        },
        expires_delta=timedelta(days=30)
    )





def role_required(required_role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            jwt_required()(fn)
            identity = get_jwt_identity()
            if identity["role"].upper() != required_role.upper():
                return jsonify({"msg": "Forbidden: Access Denied"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def is_valid_email(email):
    try:
        validate_email(email)
        return True
    except EmailNotValidError:
        return False

def is_valid_phone(phone, region="KEN"):
    try:
        parsed_number = pn.parse(phone, region)
        return pn.is_valid_number(parsed_number)
    except pn.phonenumberutil.NumberParseException:
        return False

def validate_password(password):
    return bool(password and len(password) >= 8 and not password.isdigit() and not password.isalpha())

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get("email")
    phone = data.get("phone")
    password = data.get("password")
    role = "ATTENDEE"

    if not is_valid_email(email):
        return jsonify({"msg": "Invalid email address"}), 400
    if not is_valid_phone(phone):
        return jsonify({"msg": "Invalid phone number"}), 400
    if not validate_password(password):
        return jsonify({"msg": "Password must be at least 8 characters long, contain letters and numbers"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "Email already registered"}), 400

    hashed_password = generate_password_hash(password)
    new_user = User(email=email, phone_number=phone, password=hashed_password, role=role)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"msg": "User registered successfully"}), 201


@auth_bp.route('/admin/register-admin', methods=['POST'])
@role_required('ADMIN')
def register_admin():
    data = request.get_json()
    email = data.get("email")
    phone = data.get("phone")
    password = data.get("password")

    # Validate inputs
    if not is_valid_email(email):
        return jsonify({"msg": "Invalid email address"}), 400
    if not is_valid_phone(phone):
        return jsonify({"msg": "Invalid phone number"}), 400
    if not validate_password(password):
        return jsonify({"msg": "Password must be at least 8 characters long, contain letters and numbers"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "Email already registered"}), 400

    # Hash password and create new admin user
    hashed_password = generate_password_hash(password)
    new_admin = User(email=email, phone_number=phone, password=hashed_password, role="ADMIN")
    db.session.add(new_admin)
    db.session.commit()

    return jsonify({"msg": "Admin registered successfully"}), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    """Handles user authentication and token generation"""
    data = request.get_json()

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({"error": "Invalid email or password"}), 401

    # Generate JWT token
    access_token = generate_token(user)

    return jsonify({
        "message": "Login successful",
        "access_token": access_token,
        "role": user.role.value
    }), 200

@auth_bp.route('/admin/register-organizer', methods=['POST'])
@jwt_required() 
@role_required('ADMIN')
def register_organizer():
    data = request.get_json()
    email = data.get("email")
    phone = data.get("phone")
    password = data.get("password")
    if not is_valid_email(email) or not is_valid_phone(phone) or not validate_password(password) or User.query.filter_by(email=email).first():
        return jsonify({"msg": "Invalid input or email already registered"}), 400
    hashed_password = generate_password_hash(password)
    new_user = User(email=email, phone_number=phone, password=hashed_password, role="ORGANIZER")
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"msg": "Organizer registered successfully"}), 201

@auth_bp.route('/admin/register-security', methods=['POST'])
@jwt_required() 
@role_required('ADMIN')
def register_security():
    data = request.get_json()
    email = data.get("email")
    phone = data.get("phone")
    password = data.get("password")
    if not is_valid_email(email) or not is_valid_phone(phone) or not validate_password(password) or User.query.filter_by(email=email).first():
        return jsonify({"msg": "Invalid input or email already registered"}), 400
    hashed_password = generate_password_hash(password)
    new_user = User(email=email, phone_number=phone, password=hashed_password, role="SECURITY")
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"msg": "Security registered successfully"}), 201



# 📌 Endpoint: Forgot Password (Sends Reset Link)
@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():

    from app import mail # Import mail instance from app.py

    data = request.get_json()
    email = data.get("email")

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"msg": "Email not found"}), 404

    # Generate password reset token
    token = serializer.dumps(email, salt="reset-password-salt")

    # Create reset link
    reset_link = url_for('auth.reset_password', token=token, _external=True)

    # Send email
    msg = Message("Password Reset Request", recipients=[email])
    msg.body = f"Click the link to reset your password: {reset_link}"
    mail.send(msg)

    return jsonify({"msg": "Reset link sent to your email"}), 200

# 📌 Endpoint: Reset Password (Verifies Token & Updates Password)
@auth_bp.route('/reset-password/<token>', methods=['POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt="reset-password-salt", max_age=3600)  # Token expires in 1 hour
    except:
        return jsonify({"msg": "Invalid or expired token"}), 400

    data = request.get_json()
    new_password = data.get("password")

    if not new_password or len(new_password) < 6:
        return jsonify({"msg": "Password must be at least 6 characters long"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"msg": "User not found"}), 404

    # Hash the new password
    user.password = generate_password_hash(new_password)
    db.session.commit()

    return jsonify({"msg": "Password reset successful"}), 200