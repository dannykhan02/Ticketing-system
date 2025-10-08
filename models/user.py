# """
# User model
# Handles user authentication, roles, and AI preferences
# """
# from datetime import datetime
# from werkzeug.security import generate_password_hash, check_password_hash
# from models.base import db
# from models.enums import UserRole


# class User(db.Model):
#     """
#     User model for authentication and profile management
#     Supports both OAuth and traditional password authentication
#     """
#     __tablename__ = 'user'
    
#     # Primary identification
#     id = db.Column(db.Integer, primary_key=True, autoincrement=True)
#     email = db.Column(db.String(255), nullable=False, unique=True, index=True)
#     password = db.Column(db.String(255), nullable=True)  # Nullable for OAuth users
    
#     # Profile information
#     full_name = db.Column(db.String(100), nullable=True)
#     phone_number = db.Column(db.String(255), nullable=True)
#     role = db.Column(db.Enum(UserRole), nullable=False, index=True)
    
#     # OAuth fields
#     google_id = db.Column(db.String(255), unique=True, nullable=True)
#     is_oauth = db.Column(db.Boolean, default=False)
    
#     # AI preferences
#     ai_enabled = db.Column(db.Boolean, default=True)
#     ai_language_preference = db.Column(db.String(10), default='en')
#     ai_notification_preference = db.Column(db.Boolean, default=True)
    
#     # Timestamps
#     created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, nullable=False)
    
#     # Relationships - Core
#     tickets = db.relationship('Ticket', backref='buyer', lazy=True)
#     transactions = db.relationship('Transaction', back_populates='user', lazy=True)
#     scans = db.relationship('Scan', backref='scanner', lazy=True)
#     reports = db.relationship('Report', backref='organizer_user', lazy=True)
    
#     # Relationships - Organizer profile (one-to-one)
#     organizer_profile = db.relationship(
#         'Organizer', 
#         backref=db.backref('user', uselist=False),
#         uselist=False,
#         lazy=True
#     )
    
#     # Relationships - AI features
#     ai_conversations = db.relationship(
#         'AIConversation', 
#         backref='user', 
#         lazy=True, 
#         cascade="all, delete-orphan"
#     )
#     ai_preferences = db.relationship(
#         'AIUserPreference', 
#         backref='user', 
#         uselist=False, 
#         cascade="all, delete-orphan"
#     )
#     ai_actions = db.relationship(
#         'AIActionLog', 
#         backref='user', 
#         lazy=True, 
#         cascade="all, delete-orphan"
#     )
#     ai_usage_metrics = db.relationship(
#         'AIUsageMetrics', 
#         backref='user', 
#         lazy=True, 
#         cascade="all, delete-orphan"
#     )
#     ai_feedback = db.relationship(
#         'AIFeedback', 
#         backref='user', 
#         lazy=True, 
#         cascade="all, delete-orphan"
#     )
    
#     def set_password(self, password):
#         """Hash and set user password"""
#         self.password = generate_password_hash(password)
    
#     def check_password(self, password):
#         """Verify password against hash"""
#         if not self.password:
#             return False
#         return check_password_hash(self.password, password)
    
#     def as_dict(self):
#         """Convert user to dictionary for API responses"""
#         return {
#             "id": self.id,
#             "email": self.email,
#             "full_name": self.full_name,
#             "role": self.role.value,
#             "phone_number": self.phone_number,
#             "created_at": self.created_at.isoformat(),
#             "ai_enabled": self.ai_enabled,
#             "is_oauth": self.is_oauth
#         }
    
#     @staticmethod
#     def validate_role(role):
#         """Validate and convert role to UserRole enum"""
#         if isinstance(role, str):
#             role = role.upper()
#         return UserRole(role)
    
#     def is_organizer(self):
#         """Check if user is an organizer"""
#         return self.role == UserRole.ORGANIZER
    
#     def is_admin(self):
#         """Check if user is an admin"""
#         return self.role == UserRole.ADMIN
    
#     def __repr__(self):
#         return f'<User {self.email} ({self.role.value})>'