from flask import Blueprint, jsonify, request, url_for, session, redirect, render_template, current_app
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
from itsdangerous import URLSafeTimedSerializer
from urllib.parse import urlencode

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
    """Initiate Google OAuth login"""
    try:
        # Generate state and nonce for security
        state = str(uuid4())
        nonce = str(uuid4())
        
        # Store in session with debugging
        session["oauth_state"] = state
        session["oauth_nonce"] = nonce
        session.permanent = True
        session.modified = True
        
        # Debug logging
        logger.info(f"Initiating Google OAuth - State: {state}")
        logger.debug(f"Session storage type: {current_app.config.get('SESSION_TYPE', 'unknown')}")
        logger.debug(f"Session contents after setting: {dict(session)}")
        
        # Verify session was saved
        if session.get("oauth_state") != state:
            logger.error("Session state not properly stored")
            return jsonify({"error": "Session storage error"}), 500
        
        redirect_uri = Config.GOOGLE_REDIRECT_URI
        logger.info(f"Redirecting to Google with URI: {redirect_uri}")
        
        # Handle API clients differently (like Postman)
        user_agent = request.headers.get('User-Agent', '')
        if 'PostmanRuntime' in user_agent or 'curl' in user_agent or request.args.get('api_test'):
            # For API testing, return the authorization URL with session info
            auth_url = oauth.google.create_authorization_url(
                redirect_uri,
                state=state,
                nonce=nonce,
                scope='openid email profile'  # Explicitly specify scopes
            )
            
            # Store session ID or identifier that can be used later
            session_id = getattr(session, 'sid', None) or str(uuid4())
            
            # Log the actual URL being generated for debugging
            logger.info(f"Generated OAuth URL: {auth_url['url']}")
            
            # Parse the URL to verify state parameter is included
            from urllib.parse import urlparse, parse_qs
            parsed_url = urlparse(auth_url['url'])
            query_params = parse_qs(parsed_url.query)
            
            logger.debug(f"OAuth URL parameters: {query_params}")
            
            return jsonify({
                "message": "For API testing: Copy this URL and visit it in a browser. The callback will handle the rest.",
                "auth_url": auth_url['url'],
                "state": state,
                "session_id": session_id,
                "redirect_uri": redirect_uri,
                "url_contains_state": 'state' in query_params,
                "oauth_params": {
                    "client_id": query_params.get('client_id', ['not_found'])[0] if 'client_id' in query_params else 'missing',
                    "redirect_uri": query_params.get('redirect_uri', ['not_found'])[0] if 'redirect_uri' in query_params else 'missing',
                    "state": query_params.get('state', ['not_found'])[0] if 'state' in query_params else 'missing',
                    "scope": query_params.get('scope', ['not_found'])[0] if 'scope' in query_params else 'missing'
                },
                "instructions": [
                    "1. Verify that 'url_contains_state' is true above",
                    "2. Copy the auth_url above",
                    "3. Open it in a web browser (must be a real browser, not Postman)",
                    "4. Complete Google authentication",
                    "5. The callback will return JSON with your token",
                    "6. If still getting state parameter errors, check the redirect_uri configuration"
                ]
            })
        
        # For browsers, redirect directly
        try:
            # Ensure proper scope is included
            return oauth.google.authorize_redirect(
                redirect_uri,
                state=state,
                nonce=nonce,
                scope='openid email profile'
            )
        except Exception as redirect_error:
            logger.error(f"Failed to create OAuth redirect: {str(redirect_error)}")
            return jsonify({
                "error": "Failed to create OAuth redirect",
                "details": str(redirect_error),
                "redirect_uri": redirect_uri,
                "google_config": {
                    "client_id_set": bool(current_app.config.get('GOOGLE_CLIENT_ID')),
                    "client_secret_set": bool(current_app.config.get('GOOGLE_CLIENT_SECRET')),
                    "discovery_url": current_app.config.get('GOOGLE_DISCOVERY_URL')
                }
            }), 500
        
    except Exception as e:
        logger.error(f"Error in google_login: {str(e)}")
        return jsonify({"error": "Failed to initiate Google login"}), 500


@auth_bp.route("/callback/google")
def google_callback():
    """Handle Google OAuth callback"""
    try:
        # Get parameters from the request
        received_state = request.args.get("state")
        error = request.args.get("error")
        
        # Handle OAuth errors from Google
        if error:
            logger.error(f"Google OAuth error: {error}")
            error_description = request.args.get("error_description", "Unknown error")
            
            # For API testing, return JSON error
            if request.headers.get('Accept') == 'application/json':
                return jsonify({"error": f"Google OAuth failed: {error_description}"}), 400
            
            # For browsers, redirect with error
            error_url = f"{Config.FRONTEND_URL}/auth/login?error={error}"
            return redirect(error_url)
        
        # Debug: Log all received parameters
        logger.debug(f"Callback parameters: {dict(request.args)}")
        logger.debug(f"Received state: {received_state}")
        
        # Check session contents
        stored_state = session.get("oauth_state")
        stored_nonce = session.get("oauth_nonce")
        
        logger.debug(f"Stored state: {stored_state}")
        logger.debug(f"Stored nonce: {stored_nonce}")
        logger.debug(f"Current session contents: {dict(session)}")
        
        # Verify state parameter exists
        if not received_state:
            logger.error("No state parameter received from Google")
            
            # Get the full callback URL for debugging
            full_url = request.url
            logger.error(f"Full callback URL: {full_url}")
            logger.error(f"All query parameters: {dict(request.args)}")
            
            # Check if this looks like a Google OAuth callback at all
            has_code = request.args.get("code")
            has_error = request.args.get("error")
            
            error_details = {
                "error": "Missing state parameter",
                "details": "The OAuth callback didn't receive the required state parameter",
                "full_callback_url": full_url,
                "received_params": dict(request.args),
                "has_auth_code": bool(has_code),
                "has_error": bool(has_error),
                "troubleshooting": {
                    "possible_causes": [
                        "The OAuth URL was not generated properly",
                        "The redirect_uri configuration is incorrect",
                        "Google is not including the state parameter in the callback",
                        "The OAuth app configuration in Google Console is wrong"
                    ],
                    "next_steps": [
                        "1. Check that the redirect_uri in Google Console matches exactly: " + Config.GOOGLE_REDIRECT_URI,
                        "2. Verify the OAuth URL includes the state parameter before visiting it",
                        "3. Make sure you're using the exact URL returned by /auth/login/google",
                        "4. Check Google Console OAuth app settings"
                    ]
                }
            }
            
            return jsonify(error_details), 400
        
        # Check if we have stored state
        if not stored_state:
            logger.error("No stored OAuth state found in session")
            
            # For API testing, provide more helpful error
            session_info = {
                "session_id": getattr(session, 'sid', 'No SID'),
                "session_permanent": session.permanent,
                "session_new": getattr(session, 'new', 'Unknown'),
                "session_keys": list(session.keys())
            }
            
            logger.debug(f"Session debug info: {session_info}")
            
            return jsonify({
                "error": "Session expired or invalid",
                "details": "Please initiate the OAuth flow again by visiting /auth/login/google",
                "troubleshooting": {
                    "possible_causes": [
                        "Session storage is not working properly",
                        "Too much time passed between login initiation and callback",
                        "Browser cookies are disabled",
                        "Session backend (Redis/filesystem) is not accessible"
                    ],
                    "session_info": session_info if current_app.debug else None
                }
            }), 400
        
        # Verify state matches (CSRF protection)
        if stored_state != received_state:
            logger.error(f"State mismatch - Stored: {stored_state}, Received: {received_state}")
            return jsonify({
                "error": "Invalid state, possible CSRF attack",
                "details": "The state parameter doesn't match what was stored in the session"
            }), 400
        
        # Clear the OAuth state and nonce from session after successful verification
        session.pop("oauth_state", None)
        session.pop("oauth_nonce", None)
        
        logger.info("State verification successful, proceeding with token exchange")
        
        # Exchange authorization code for tokens
        try:
            token = oauth.google.authorize_access_token()
            logger.debug("Successfully obtained access token from Google")
        except Exception as token_error:
            logger.error(f"Failed to get access token: {str(token_error)}")
            return jsonify({
                "error": "Failed to exchange authorization code for token",
                "details": str(token_error) if current_app.debug else "Token exchange failed"
            }), 500
        
        # Parse ID token and verify nonce
        try:
            user_info = oauth.google.parse_id_token(token, nonce=stored_nonce)
            logger.debug(f"Successfully parsed user info: {user_info.get('email', 'No email')}")
        except Exception as parse_error:
            logger.error(f"Failed to parse ID token: {str(parse_error)}")
            return jsonify({
                "error": "Failed to parse user information from Google",
                "details": str(parse_error) if current_app.debug else "ID token parsing failed"
            }), 500
        
        # Extract user information
        email = user_info.get("email")
        google_id = user_info.get("sub")
        name = user_info.get("name", "Google User")
        
        if not email or not google_id:
            logger.error("Missing required user information from Google")
            return jsonify({
                "error": "Incomplete user information from Google",
                "received_info": {k: v for k, v in user_info.items() if k in ['email', 'name', 'sub']}
            }), 400
        
        # Find or create user
        user = User.query.filter(
            (User.google_id == google_id) | (User.email == email)
        ).first()
        
        try:
            if not user:
                logger.info(f"Creating new user for email: {email}")
                user = User(
                    email=email,
                    google_id=google_id,
                    full_name=name,
                    phone_number=None,
                    is_oauth=True,
                    role=UserRole.ATTENDEE
                )
                db.session.add(user)
                db.session.commit()
                logger.info(f"Successfully created user with ID: {user.id}")
            else:
                logger.info(f"Found existing user: {user.id}")
                # Update Google ID if it was missing
                if not user.google_id:
                    user.google_id = google_id
                    db.session.commit()
        except Exception as db_error:
            db.session.rollback()
            logger.error(f"Database error during user creation/update: {str(db_error)}")
            return jsonify({
                "error": "Failed to create or update user",
                "details": str(db_error) if current_app.debug else "Database operation failed"
            }), 500
        
        # Generate access token
        try:
            access_token = generate_token(user)
            logger.info(f"Successfully generated access token for user: {user.id}")
        except Exception as token_gen_error:
            logger.error(f"Failed to generate access token: {str(token_gen_error)}")
            return jsonify({
                "error": "Failed to generate access token",
                "details": str(token_gen_error) if current_app.debug else "Token generation failed"
            }), 500
        
        # Prepare user data for response
        user_data = {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "phone_number": user.phone_number,
            "role": str(user.role.value)
        }
        
        # Check if this is an API request or browser request
        user_agent = request.headers.get('User-Agent', '')
        accept_header = request.headers.get('Accept', '')
        
        # Determine if this should return JSON (for API testing)
        is_api_request = (
            'PostmanRuntime' in user_agent or 
            'curl' in user_agent or
            'application/json' in accept_header or
            request.args.get('format') == 'json'
        )
        
        if is_api_request:
            # Return JSON response for API clients
            logger.info(f"Returning JSON response for API client: {user_agent}")
            return jsonify({
                "message": "Login successful",
                "user": user_data,
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 30 * 24 * 60 * 60,  # 30 days in seconds
                "usage": {
                    "header": f"Authorization: Bearer {access_token}",
                    "cookie": "access_token cookie will be set for browser requests"
                }
            }), 200
        
        # For browsers, set cookie and redirect
        frontend_callback_url = f"{Config.FRONTEND_URL}/auth/callback/google"
        
        # Add success parameters to the frontend URL
        params = {
            "success": "true",
            "user_id": user.id,
            "email": user.email
        }
        frontend_url_with_params = f"{frontend_callback_url}?{urlencode(params)}"
        
        response = redirect(frontend_url_with_params)
        
        # Set HTTP-only cookie with the access token
        cookie_settings = {
            'httponly': True,
            'secure': not current_app.debug,
            'samesite': 'None' if not current_app.debug else 'Lax',
            'path': '/',
            'max_age': 30*24*60*60  # 30 days
        }
        
        response.set_cookie('access_token', access_token, **cookie_settings)
        
        logger.info(f"Successful Google OAuth login for user: {user.id}, redirecting to: {frontend_url_with_params}")
        return response
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Unexpected error in Google callback: {str(e)}")
        
        error_response = {
            "error": "Internal server error",
            "details": str(e) if current_app.debug else "Please try again"
        }
        
        # Check if this should return JSON
        user_agent = request.headers.get('User-Agent', '')
        if 'PostmanRuntime' in user_agent or 'curl' in user_agent or 'application/json' in request.headers.get('Accept', ''):
            return jsonify(error_response), 500
        
        # For browsers, redirect to frontend with error
        error_url = f"{Config.FRONTEND_URL}/auth/login?error=oauth_failed"
        return redirect(error_url)


# Add a test endpoint specifically for API testing
@auth_bp.route('/auth/test-oauth')
def test_oauth():
    """Test endpoint to initiate OAuth specifically for API testing"""
    return redirect(url_for('auth.google_login', api_test=True))


# Add an endpoint to get token info for testing
@auth_bp.route('/auth/token-info')
@jwt_required()
def token_info():
    """Get information about the current token (for testing)"""
    current_user_id = get_jwt_identity()
    claims = get_jwt()
    
    return jsonify({
        "user_id": current_user_id,
        "email": claims.get("email"),
        "role": claims.get("role"),
        "token_valid": True,
        "expires": claims.get("exp")
    })


# Debug endpoint for session information
@auth_bp.route('/debug/session-info')
def debug_session_info():
    """Debug endpoint to check session configuration"""
    if not current_app.debug:
        return jsonify({"error": "Debug endpoint only available in debug mode"}), 404
    
    from config import Config
    session_info = Config.get_session_config_info()
    
    return jsonify({
        "session_config": session_info,
        "current_session": {
            "permanent": session.permanent,
            "new": getattr(session, 'new', 'unknown'),
            "sid": getattr(session, 'sid', 'no_sid'),
            "keys": list(session.keys()),
            "oauth_state": session.get("oauth_state", "not_set"),
            "oauth_nonce": session.get("oauth_nonce", "not_set"),
            "debug_oauth_state": session.get("debug_oauth_state", "not_set"),
            "debug_oauth_nonce": session.get("debug_oauth_nonce", "not_set")
        },
        "request_info": {
            "user_agent": request.headers.get('User-Agent'),
            "accept": request.headers.get('Accept'),
            "cookies": list(request.cookies.keys()),
            "full_url": request.url,
            "query_params": dict(request.args)
        }
    })
    """Debug OAuth configuration and test URL generation"""
    if not current_app.debug:
        return jsonify({"error": "Debug endpoint only available in debug mode"}), 404
    
    try:
        from config import Config
        import json
        
        # Test OAuth URL generation
        test_state = "test_state_123"
        test_nonce = "test_nonce_123"
        
        try:
            test_auth_url = oauth.google.create_authorization_url(
                Config.GOOGLE_REDIRECT_URI,
                state=test_state,
                nonce=test_nonce,
                scope='openid email profile'
            )
            url_generation_success = True
            test_url = test_auth_url['url']
        except Exception as url_error:
            url_generation_success = False
            test_url = None
            url_error_msg = str(url_error)
        
        # Parse the test URL to check parameters
        url_params = {}
        if test_url:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(test_url)
            url_params = parse_qs(parsed.query)
        
        debug_info = {
            "oauth_config": {
                "google_client_id": current_app.config.get('GOOGLE_CLIENT_ID', 'NOT_SET')[:20] + "..." if current_app.config.get('GOOGLE_CLIENT_ID') else 'NOT_SET',
                "google_client_secret_set": bool(current_app.config.get('GOOGLE_CLIENT_SECRET')),
                "google_discovery_url": current_app.config.get('GOOGLE_DISCOVERY_URL'),
                "base_url": Config.BASE_URL,
                "redirect_uri": Config.GOOGLE_REDIRECT_URI,
                "frontend_url": Config.FRONTEND_URL
            },
            "url_generation": {
                "success": url_generation_success,
                "test_url": test_url if url_generation_success else None,
                "error": url_error_msg if not url_generation_success else None,
                "url_contains_state": 'state' in url_params and url_params['state'][0] == test_state if url_params else False,
                "parsed_params": {k: v[0] if v else None for k, v in url_params.items()} if url_params else {}
            },
            "session_info": {
                "session_type": current_app.config.get('SESSION_TYPE'),
                "session_permanent": getattr(session, 'permanent', 'unknown'),
                "session_keys": list(session.keys())
            },
            "environment": {
                "flask_env": os.getenv('FLASK_ENV', 'not_set'),
                "debug_mode": current_app.debug,
                "base_url": Config.BASE_URL
            }
        }
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({
            "error": "Failed to generate debug info",
            "details": str(e)
        }), 500


# Add a manual OAuth URL generator for testing
@auth_bp.route('/debug/generate-oauth-url')
def generate_oauth_url_debug():
    """Manually generate OAuth URL for debugging"""
    if not current_app.debug:
        return jsonify({"error": "Debug endpoint only available in debug mode"}), 404
    
    try:
        from config import Config
        
        # Generate fresh state and nonce
        state = f"debug_{str(uuid4())}"
        nonce = f"debug_{str(uuid4())}"
        
        # Store in session
        session["debug_oauth_state"] = state
        session["debug_oauth_nonce"] = nonce
        session.permanent = True
        session.modified = True
        
        # Generate URL
        redirect_uri = Config.GOOGLE_REDIRECT_URI
        
        # Try the OAuth library method
        try:
            auth_url_data = oauth.google.create_authorization_url(
                redirect_uri,
                state=state,
                nonce=nonce,
                scope='openid email profile'
            )
            oauth_lib_success = True
            oauth_lib_url = auth_url_data['url']
            oauth_lib_error = None
        except Exception as e:
            oauth_lib_success = False
            oauth_lib_url = None
            oauth_lib_error = str(e)
        
        # Also try manual URL construction as backup
        import urllib.parse
        
        manual_params = {
            'client_id': current_app.config.get('GOOGLE_CLIENT_ID'),
            'redirect_uri': redirect_uri,
            'scope': 'openid email profile',
            'response_type': 'code',
            'state': state,
            'nonce': nonce,
            'access_type': 'offline'
        }
        
        manual_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode(manual_params)
        
        return jsonify({
            "oauth_library": {
                "success": oauth_lib_success,
                "url": oauth_lib_url,
                "error": oauth_lib_error
            },
            "manual_construction": {
                "url": manual_url,
                "parameters": manual_params
            },
            "session_storage": {
                "state_stored": session.get("debug_oauth_state") == state,
                "nonce_stored": session.get("debug_oauth_nonce") == nonce
            },
            "instructions": [
                "1. Try the oauth_library.url first (if success is true)",
                "2. If that fails, try the manual_construction.url",
                "3. Complete OAuth flow and check callback for state parameter",
                "4. Use /debug/session-info to verify session persistence"
            ]
        })
        
    except Exception as e:
        return jsonify({
            "error": "Failed to generate OAuth URL",
            "details": str(e)
        }), 500


# Health check endpoint for OAuth flow
@auth_bp.route('/auth/health')
def auth_health_check():
    """Health check for authentication system"""
    try:
        # Check if we can create a session
        from datetime import datetime
        test_key = f"health_check_{datetime.now().timestamp()}"
        session[test_key] = "test"
        session.modified = True
        
        # Check if session persisted
        session_working = session.get(test_key) == "test"
        
        # Clean up
        session.pop(test_key, None)
        
        health_data = {
            "status": "healthy" if session_working else "degraded",
            "session_type": current_app.config.get('SESSION_TYPE', 'unknown'),
            "session_working": session_working,
            "google_oauth_configured": bool(
                current_app.config.get('GOOGLE_CLIENT_ID') and 
                current_app.config.get('GOOGLE_CLIENT_SECRET')
            ),
            "database_accessible": True  # If we got this far, DB is accessible
        }
        
        if not session_working:
            health_data["warning"] = "Session storage not working - OAuth flow may fail"
        
        status_code = 200 if session_working else 503
        return jsonify(health_data), status_code
        
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "session_working": False
        }), 500
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
    "0110", "0111", "0112", "0113", "0114", "0115", "0116"
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

    # Additional length check
    if len(phone) not in [9, 10]:
        logger.warning(f"Invalid length for phone number: {phone}")
        return False

    try:
        parsed_number = pn.parse(phone, region)
        if not pn.is_valid_number(parsed_number):
            logger.warning(f"Invalid phone number format: {phone}")
            return False
    except pn.phonenumberutil.NumberParseException:
        logger.warning(f"Failed to parse phone number: {phone}")
        return False

    prefix = phone[:4] if len(phone) >= 10 else phone[:3]
    logger.info(f"Checking prefix: {prefix} in Safaricom prefixes for number: {phone}")

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

@auth_bp.route('/check-admin', methods=['GET'])
def check_admin():
    """Check if an admin user exists in the system"""
    try:
        admin_exists = User.query.filter_by(role=UserRole.ADMIN).first() is not None
        return jsonify({"admin_exists": admin_exists}), 200
    except Exception as e:
        return jsonify({"msg": "Error checking admin status"}), 500


@auth_bp.route('/register-first-admin', methods=['POST'])
def register_first_admin():
    """Register the first admin user - only available when no admin exists"""
    # Check if any admin already exists in the database
    existing_admin = User.query.filter_by(role=UserRole.ADMIN).first()
    if existing_admin:
        return jsonify({"msg": "Admin already exists. First admin registration is no longer available."}), 403
    
    data = request.get_json()
    
    # Extract and validate input data
    email = data.get("email")
    phone = data.get("phone_number")
    password = data.get("password")
    full_name = data.get("full_name")

    # Validate required fields
    if not all([email, phone, password, full_name]):
        return jsonify({"msg": "All fields are required"}), 400

    # Validate email format
    if not is_valid_email(email):
        return jsonify({"msg": "Invalid email address"}), 400

    # Validate phone number
    if not is_valid_safaricom_phone(phone):
        return jsonify({"msg": "Invalid phone number. Must be a valid Safaricom number."}), 400

    # Validate password strength
    if not validate_password(password):
        return jsonify({"msg": "Password must be at least 8 characters long, contain letters and numbers"}), 400

    # Check if email already exists (additional safety check)
    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "Email already registered"}), 409

    try:
        # Double-check admin doesn't exist before creating (race condition protection)
        existing_admin = User.query.filter_by(role=UserRole.ADMIN).first()
        if existing_admin:
            return jsonify({"msg": "Admin already exists. First admin registration is no longer available."}), 403
        
        # Create new admin user
        hashed_password = generate_password_hash(password)
        new_admin = User(
            email=email, 
            phone_number=phone, 
            password=hashed_password, 
            full_name=full_name, 
            role=UserRole.ADMIN
        )
        
        db.session.add(new_admin)
        db.session.commit()
        
        return jsonify({
            "msg": "First admin registered successfully",
            "admin_id": new_admin.id,
            "email": new_admin.email
        }), 201
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "Registration failed. Please try again."}), 500
    
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
        samesite='None',
        path='/',
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
    """Register a user as organizer - prevents converting the last admin"""
    
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

    # CRITICAL SECURITY CHECK: Prevent converting the last admin
    if user.role == UserRole.ADMIN:
        admin_count = User.query.filter_by(role=UserRole.ADMIN).count()
        if admin_count <= 1:
            logger.warning(f"Attempted to convert last admin to organizer. Admin: {user.email}, Current Admin: {get_jwt_identity()}")
            return jsonify({"msg": "Cannot convert the last admin user. At least one admin must remain in the system."}), 403

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

        logger.info(f"User converted to organizer: {user.email} -> {company_name}")
        return jsonify({
            "msg": "User successfully registered as organizer",
            "user": user.as_dict(),
            "organizer_profile": organizer_profile.as_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error converting user to organizer: {str(e)}")
        return jsonify({"msg": "Internal Server Error"}), 500

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

    # ⭐ THIS IS THE CORRECTED LINE ⭐
    # It now uses the FRONTEND_URL from your Config class (which is dynamically loaded from environment variables)
    reset_link = f"{Config.FRONTEND_URL}/reset-password/{token}"


    # Send email
    msg = Message("Password Reset Request", recipients=[email])
    msg.body = f"Click the link to reset your password: {reset_link}"
    mail.send(msg)

    return jsonify({"msg": "Reset link sent to your email"}), 200

#  Endpoint: Reset Password (Verifies Token & Updates Password)
@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Initialize serializer inside function
    serializer = URLSafeTimedSerializer(Config.SECRET_KEY)

    try:
        # Load and validate the token
        email = serializer.loads(token, salt="reset-password-salt", max_age=3600)  # Token expires in 1 hour
    except Exception as e:
        # Log the exception for debugging purposes
        print(f"Token validation error: {e}")
        return jsonify({"msg": "Invalid or expired token"}), 400

    if request.method == 'GET':
        # Return a simple message or render a form
        return jsonify({"msg": "Token is valid. You can now reset your password.", "email": email}), 200
        # OR: return render_template('reset_password_form.html', token=token)

    # POST method (same logic you already have)
    data = request.get_json()
    new_password = data.get("password")

    if not new_password or len(new_password) < 6:
        return jsonify({"msg": "Password must be at least 6 characters long"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"msg": "User not found"}), 404

    try:
        # Hash the new password
        user.password = generate_password_hash(new_password)
        db.session.commit()
        return jsonify({"msg": "Password reset successful"}), 200
    except Exception as e:
        # Log the exception for debugging purposes
        print(f"Error updating password: {e}")
        db.session.rollback()
        return jsonify({"msg": "An error occurred while updating the password"}), 500

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
    try:
        organizers = User.query.filter_by(role=UserRole.ORGANIZER).all()

        result = []
        for organizer in organizers:
            # Get base user data
            organizer_data = organizer.as_dict()

            # Add organizer profile data if it exists
            if organizer.organizer_profile:
                profile_data = organizer.organizer_profile.as_dict()
                # Remove user_id from profile data to avoid redundancy
                profile_data.pop('user_id', None)
                # Add profile data under a nested key
                organizer_data['organizer_profile'] = profile_data
            else:
                organizer_data['organizer_profile'] = None

            result.append(organizer_data)

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Error fetching organizers: {str(e)}")
        return jsonify({"error": "Failed to fetch organizers"}), 500

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
