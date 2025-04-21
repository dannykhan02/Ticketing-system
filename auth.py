from flask import Blueprint, jsonify, request, url_for, session
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity, get_jwt, jwt_required, create_access_token
from email_validator import validate_email, EmailNotValidError
import re
import phonenumbers as pn
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from uuid import uuid4
from model import db, User, UserRole, Organizer
from datetime import timedelta
from oauth_config import oauth
from flask_mail import Message
from config import Config
import logging
import cloudinary.uploader

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Authentication Blueprint
auth_bp = Blueprint('auth', __name__)

def generate_token(user):
    return create_access_token(
        identity=str(user.id),
        additional_claims={
            "email": user.email,
            "role": str(user.role.value)
        },
        expires_delta=timedelta(days=30)
    )

@auth_bp.route('/login/google')
def google_login():
    state = str(uuid4())
    nonce = str(uuid4())  # Generate a random nonce
    session["oauth_state"] = state
    session["oauth_nonce"] = nonce  # Store nonce in session
    session.modified = True
    redirect_uri = Config.GOOGLE_REDIRECT_URI
    return oauth.google.authorize_redirect(
        redirect_uri,
        state=state,
        nonce=nonce  # Send nonce to Google
    )

@auth_bp.route("/callback/google")
def google_callback():
    try:
        # Verify state first
        received_state = request.args.get("state")
        stored_state = session.pop("oauth_state", None)
        stored_nonce = session.pop("oauth_nonce", None)

        if not stored_state or not received_state or stored_state != received_state:
            return jsonify({"error": "Invalid state, possible CSRF attack"}), 400

        # Get token and verify nonce
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.parse_id_token(token, nonce=stored_nonce)

        # Extract user information
        email = user_info["email"]
        google_id = user_info["sub"]
        name = user_info.get("name", "Google User")

        # Find or create user
        user = User.query.filter(
            (User.google_id == google_id) | (User.email == email)
        ).first()

        if not user:
            user = User(
                email=email,
                google_id=google_id,
                full_name=name,  # Store name properly
                phone_number=None,  # Leave phone number empty
                is_oauth=True,
                role=UserRole.ATTENDEE
            )
            db.session.add(user)
            db.session.commit()

        access_token = generate_token(user)
        
        # Create response with user data
        response = jsonify({
            "msg": "Login successful",
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "phone_number": user.phone_number,  # Will be None
                "role": str(user.role.value)
            }
        })

        # Set HTTP-only cookie with the access token
        response.set_cookie(
            'access_token',
            access_token,
            httponly=True,
            secure=True,  # Only send over HTTPS
            samesite='Lax',  # Helps prevent CSRF attacks
            max_age=30*24*60*60  # 30 days in seconds
        )

        return response, 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

def role_required(required_role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()

            claims = get_jwt()  # Get additional claims
            logger.debug(f"DEBUG: Claims retrieved: {claims}")  # Debugging

            if "role" not in claims or claims["role"].upper() != required_role.upper():
                return jsonify({"msg": "Forbidden: Access Denied"}), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator

def is_valid_email(email: str) -> bool:
    """Validates an email address"""
    try:
        validate_email(email, check_deliverability=True)
        return True
    except EmailNotValidError:
        return False

# Safaricom valid prefixes
SAFARICOM_PREFIXES = {
    "0701", "0702", "0703", "0704", "0705", "0706", "0707", "0708", "0709",
    "0710", "0711", "0712", "0713", "0714", "0715", "0716", "0717", "0718", "0719",
    "0720", "0721", "0722", "0723", "0724", "0725", "0726", "0727", "0728", "0729",
    "0740", "0741", "0742", "0743", "0744", "0745", "0746", "0747", "0748", "0749",
    "0757", "0758",
    "0768", "0769",
    "0790", "0791", "0792", "0793", "0794", "0795", "0796", "0797", "0798", "0799",
    "0110", "0111", "0112", "0113", "0114", "0115"
}

def normalize_phone(phone: str) -> str:
    """Converts phone numbers to a standard format: 07xxxxxxxx"""
    if not isinstance(phone, str):
        logger.warning(f"Phone number is not a string: {phone}")
        phone = str(phone)  # Ensure phone is a string

    logger.info(f"Normalizing phone number: {phone}")
    phone = re.sub(r"\D", "", phone)  # Remove non-numeric characters

    if phone.startswith("+254"):
        phone = "0" + phone[4:]
    elif phone.startswith("254") and len(phone) == 12:
        phone = "0" + phone[3:]

    logger.info(f"Normalized phone number: {phone}")
    return phone

def is_valid_safaricom_phone(phone: str, region="KE") -> bool:
    """Validates if the phone number is a valid Safaricom number."""
    phone = normalize_phone(phone)

    try:
        parsed_number = pn.parse(phone, region)
        if not pn.is_valid_number(parsed_number):
            return False
    except pn.phonenumberutil.NumberParseException:
        return False

    prefix = phone[:4] if len(phone) >= 10 else ""
    logger.info(f"Checking prefix: {prefix} in Safaricom prefixes")
    return prefix in SAFARICOM_PREFIXES

def validate_password(password: str) -> bool:
    """Password must be at least 8 characters long, contain letters and numbers"""
    return bool(re.match(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,}$', password))

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get("email")
    phone = data.get("phone_number")
    password = data.get("password")
    full_name = data.get("full_name")  # Extract full_name
    role = "ATTENDEE"

    # Validate Email
    if not is_valid_email(email):
        return jsonify({"msg": "Invalid email address"}), 400

    # Validate Safaricom Phone Number
    if not is_valid_safaricom_phone(phone):
        logger.error(f"Invalid phone number: {phone}")
        return jsonify({"msg": "Invalid phone number. Must be a valid Safaricom number."}), 400

    # Validate Password
    if not validate_password(password):
        return jsonify({"msg": "Password must be at least 8 characters long, contain letters and numbers"}), 400

    # Check if Email or Phone Already Exists
    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "Email already registered"}), 400

    if User.query.filter_by(phone_number=phone).first():
        return jsonify({"msg": "Phone number already registered"}), 400

    # Hash Password
    hashed_password = generate_password_hash(password)

    # Create and Save New User
    new_user = User(email=email, phone_number=phone, password=hashed_password, full_name=full_name, role=role)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"msg": "User registered successfully"}), 201

@auth_bp.route('/register-first-admin', methods=['POST'])
def register_first_admin():
    data = request.get_json()
    email = data.get("email")
    phone = data.get("phone_number")
    password = data.get("password")
    full_name = data.get("full_name")  # Extract full_name

    if not is_valid_email(email):
        return jsonify({"msg": "Invalid email address"}), 400

    if not phone or not is_valid_safaricom_phone(phone):
        return jsonify({"msg": "Invalid phone number. Must be a valid Safaricom number."}), 400

    if not validate_password(password):
        return jsonify({"msg": "Password must be at least 8 characters long, contain letters and numbers"}), 400

    hashed_password = generate_password_hash(password)
    new_admin = User(email=email, phone_number=phone, password=hashed_password, full_name=full_name, role=UserRole.ADMIN)
    db.session.add(new_admin)
    db.session.commit()

    return jsonify({"msg": "First admin registered successfully"}), 201

@auth_bp.route('/admin/register-admin', methods=['POST'])
@role_required('ADMIN')
def register_admin():
    data = request.get_json()
    email = data.get("email")
    phone = data.get("phone_number")
    password = data.get("password")
    full_name = data.get("full_name")  # Extract full_name

    # Validate Email
    if not is_valid_email(email):
        return jsonify({"msg": "Invalid email address"}), 400

    # Validate Safaricom Phone Number
    if not is_valid_safaricom_phone(phone):
        logger.error(f"Invalid phone number: {phone}")
        return jsonify({"msg": "Invalid phone number. Must be a valid Safaricom number."}), 400

    # Validate Password
    if not validate_password(password):
        return jsonify({"msg": "Password must be at least 8 characters long, contain letters and numbers"}), 400

    # Check if Email or Phone Already Exists
    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "Email already registered"}), 400

    if User.query.filter_by(phone_number=phone).first():
        return jsonify({"msg": "Phone number already registered"}), 400

    # Hash password and create new admin user
    hashed_password = generate_password_hash(password)
    new_admin = User(email=email, phone_number=phone, password=hashed_password, full_name=full_name, role="ADMIN")
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

    # Create response with user data
    response = jsonify({
        "message": "Login successful",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": str(user.role)
        }
    })

    # Set HTTP-only cookie with the access token
    response.set_cookie(
        'access_token',
        access_token,
        httponly=True,
        secure=True,  # Only send over HTTPS
        samesite='Lax',  # Helps prevent CSRF attacks
        max_age=30*24*60*60  # 30 days in seconds
    )

    return response, 200

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Handles user logout by clearing the access token cookie"""
    response = jsonify({"message": "Logout successful"})
    response.delete_cookie('access_token')
    return response, 200

@auth_bp.route('/admin/register-organizer', methods=['POST'])
@jwt_required()
@role_required('ADMIN')
def register_organizer():
    data = request.form  # Changed from get_json() to form to handle file uploads
    files = request.files

    if not data:
        return jsonify({"msg": "Missing form data"}), 400

    # Extract fields safely
    user_id = data.get("user_id")
    company_name = data.get("company_name")
    company_description = data.get("company_description")
    website = data.get("website")
    business_registration_number = data.get("business_registration_number")
    tax_id = data.get("tax_id")
    address = data.get("address")
    company_logo = files.get("company_logo")

    # Validate required fields
    if not user_id or not company_name:
        return jsonify({"msg": "User ID and company name are required"}), 400

    # Get the existing user
    user = User.query.get(user_id)
    if not user:
        return jsonify({"msg": "User not found"}), 404

    # Check if user is already an organizer
    if user.role == UserRole.ORGANIZER:
        return jsonify({"msg": "User is already an organizer"}), 400

    try:
        # Update user role to ORGANIZER
        user.role = UserRole.ORGANIZER

        # Handle company logo upload if provided
        logo_url = None
        if company_logo:
            try:
                # Upload to Cloudinary
                upload_result = cloudinary.uploader.upload(
                    company_logo,
                    folder="organizer_logos",
                    resource_type="auto"
                )
                logo_url = upload_result.get('secure_url')
            except Exception as e:
                logger.error(f"Error uploading company logo: {str(e)}")
                return jsonify({"msg": "Failed to upload company logo"}), 500

        # Create organizer profile
        organizer_profile = Organizer(
            user_id=user.id,
            company_name=company_name,
            company_description=company_description,
            website=website,
            business_registration_number=business_registration_number,
            tax_id=tax_id,
            address=address,
            company_logo=logo_url  # Add the logo URL to the organizer profile
        )
        db.session.add(organizer_profile)
        db.session.commit()

        return jsonify({
            "msg": "User successfully registered as organizer",
            "user": user.as_dict(),
            "organizer_profile": organizer_profile.as_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "Internal Server Error", "error": str(e)}), 500

@auth_bp.route('/admin/register-security', methods=['POST'])
@jwt_required()
@role_required('ADMIN')
def register_security():
    data = request.get_json()

    if not data:
        return jsonify({"msg": "Missing JSON data"}), 400

    # Extract fields safely
    email = data.get("email")
    phone = data.get("phone_number")
    password = data.get("password")
    full_name = data.get("full_name")  # Extract full_name

    # Validate required fields
    if not email or not phone or not password or not full_name:
        return jsonify({"msg": "Email, phone, password, and full name are required"}), 400

    # Validate email
    if not is_valid_email(email):
        return jsonify({"msg": "Invalid email address"}), 400

    # Validate Safaricom phone number
    if not is_valid_safaricom_phone(phone):
        logger.error(f"Invalid phone number: {phone}")
        return jsonify({"msg": "Invalid phone number. Must be a valid Safaricom number."}), 400

    # Validate password
    if not validate_password(password):
        return jsonify({"msg": "Password must be at least 8 characters long, contain letters and numbers"}), 400

    # Check if Email or Phone already exists
    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "Email already registered"}), 400

    if User.query.filter_by(phone_number=phone).first():
        return jsonify({"msg": "Phone number already registered"}), 400

    try:
        # Hash password before storing
        hashed_password = generate_password_hash(password)

        # Create a new security user
        new_user = User(email=email, phone_number=phone, password=hashed_password, full_name=full_name, role="SECURITY")
        db.session.add(new_user)
        db.session.commit()

        return jsonify({"msg": "Security registered successfully"}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "Internal Server Error", "error": str(e)}), 500

# 📌 Endpoint: Forgot Password (Sends Reset Link)
@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    from app import mail  # Import mail instance from app.py
    from itsdangerous import URLSafeTimedSerializer

    data = request.get_json()
    email = data.get("email")

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"msg": "Email not found"}), 404

    # Initialize serializer inside function
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY)

    # Generate password reset token
    token = serializer.dumps(email, salt="reset-password-salt")

    # Create reset link
    reset_link = url_for('auth.reset_password', token=token, _external=True)

    # Send email
    msg = Message("Password Reset Request", recipients=[email])
    msg.body = f"Click the link to reset your password: {reset_link}"
    mail.send(msg)

    return jsonify({"msg": "Reset link sent to your email"}), 200

#  Endpoint: Reset Password (Verifies Token & Updates Password)
@auth_bp.route('/reset-password/<token>', methods=['POST'])
def reset_password(token):
    from itsdangerous import URLSafeTimedSerializer

    # Initialize serializer inside function
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY)

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

@auth_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """Get user profile information"""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    if not user:
        return jsonify({"msg": "User not found"}), 404
    
    profile_data = user.as_dict()
    
    # If user is an organizer, include organizer profile
    if user.role == UserRole.ORGANIZER and hasattr(user, 'organizer_profile'):
        profile_data['organizer_profile'] = user.organizer_profile.as_dict()
    
    return jsonify(profile_data), 200

@auth_bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """Update user profile information"""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    if not user:
        return jsonify({"msg": "User not found"}), 404
    
    data = request.get_json()
    
    # Update basic user info
    if 'full_name' in data:
        user.full_name = data['full_name']
    if 'phone_number' in data:
        if not is_valid_safaricom_phone(data['phone_number']):
            return jsonify({"msg": "Invalid phone number. Must be a valid Safaricom number."}), 400
        user.phone_number = data['phone_number']
    
    # If user is an organizer, update organizer profile
    if user.role == UserRole.ORGANIZER:
        if not hasattr(user, 'organizer_profile'):
            # Create organizer profile if it doesn't exist
            organizer = Organizer(user_id=user.id)
            db.session.add(organizer)
        
        organizer = user.organizer_profile
        if 'company_name' in data:
            organizer.company_name = data['company_name']
        if 'company_description' in data:
            organizer.company_description = data['company_description']
        if 'website' in data:
            organizer.website = data['website']
        if 'social_media_links' in data:
            organizer.social_media_links = data['social_media_links']
        if 'business_registration_number' in data:
            organizer.business_registration_number = data['business_registration_number']
        if 'tax_id' in data:
            organizer.tax_id = data['tax_id']
        if 'address' in data:
            organizer.address = data['address']
    
    try:
        db.session.commit()
        return jsonify({"msg": "Profile updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "Failed to update profile", "error": str(e)}), 500

@auth_bp.route('/organizers', methods=['GET'])
@jwt_required()
@role_required('ADMIN')
def get_organizers():
    """Get list of all organizers with their event counts"""
    organizers = User.query.filter_by(role=UserRole.ORGANIZER).all()
    
    result = []
    for organizer in organizers:
        organizer_data = organizer.as_dict()
        if hasattr(organizer, 'organizer_profile'):
            organizer_data.update(organizer.organizer_profile.as_dict())
        result.append(organizer_data)
    
    return jsonify(result), 200

@auth_bp.route('/organizers/<int:organizer_id>', methods=['DELETE'])
@jwt_required()
@role_required('ADMIN')
def delete_organizer(organizer_id):
    """Delete an organizer"""

    # First fetch the user with role ORGANIZER
    user = User.query.filter_by(id=organizer_id, role=UserRole.ORGANIZER).first()

    if not user:
        return jsonify({"msg": "Organizer not found"}), 404

    try:
        # Delete the organizer profile first
        if user.organizer_profile:
            db.session.delete(user.organizer_profile)

        # Then delete the user
        db.session.delete(user)
        db.session.commit()

        return jsonify({"msg": "Organizer deleted successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "Failed to delete organizer", "error": str(e)}), 500

@auth_bp.route('/users', methods=['GET'])
@jwt_required()
@role_required('ADMIN')
def get_users():
    """Get list of all users with optional search"""
    try:
        search_query = request.args.get('search', '').lower()
        
        # Base query
        query = User.query
        
        # Apply search filter if provided
        if search_query:
            query = query.filter(
                db.or_(
                    User.full_name.ilike(f'%{search_query}%'),
                    User.email.ilike(f'%{search_query}%'),
                    User.phone_number.ilike(f'%{search_query}%')
                )
            )
        
        # Get all users
        users = query.all()
        
        # Format response
        result = []
        for user in users:
            user_data = user.as_dict()
            # Add additional fields if needed
            user_data['is_organizer'] = user.role == UserRole.ORGANIZER
            result.append(user_data)
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        return jsonify({"msg": "Failed to fetch users", "error": str(e)}), 500

