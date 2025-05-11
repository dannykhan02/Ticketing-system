from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import enum

# Initialize SQLAlchemy
db = SQLAlchemy()

# Enum definitions
class UserRole(enum.Enum):
    ADMIN = "ADMIN"
    ORGANIZER = "ORGANIZER"
    ATTENDEE = "ATTENDEE"
    SECURITY = "SECURITY"

    def __str__(self):
        return self.value

class TicketTypeEnum(enum.Enum):
    REGULAR = "REGULAR"
    VIP = "VIP"
    STUDENT = "STUDENT"
    GROUP_OF_5 = "GROUP_OF_5"
    COUPLES = "COUPLES"
    EARLY_BIRD = "EARLY_BIRD"
    VVIP = "VVIP"
    GIVEAWAY = "GIVEAWAY"

class PaymentStatus(enum.Enum):
    PENDING = 'pending'
    COMPLETED = 'completed'
    PAID = 'paid'
    FAILED = 'failed'
    REFUNDED = 'refunded'
    CANCELED = 'canceled'
    CHARGEBACK = 'chargeback'
    ON_HOLD = 'on_hold'

class PaymentMethod(enum.Enum):
    MPESA = 'Mpesa'
    PAYSTACK = 'Paystack'

# Add a new association table for likes
event_likes = db.Table(
    'event_likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
)

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password = db.Column(db.String(255))
    full_name = db.Column(db.String(100))  # New field for name storage
    role = db.Column(db.Enum(UserRole), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, nullable=False)
    phone_number = db.Column(db.String(255))  # Now strictly for phone numbers

    google_id = db.Column(db.String(255), unique=True)
    is_oauth = db.Column(db.Boolean, default=False)

    tickets = db.relationship('Ticket', backref='buyer', lazy=True)
    transactions = db.relationship('Transaction', back_populates='user', lazy=True)
    scans = db.relationship('Scan', backref='scanner', lazy=True)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def as_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,  # Include name in response
            "role": self.role.value,
            "phone_number": self.phone_number,
            "created_at": self.created_at.isoformat()
        }

    @staticmethod
    def validate_role(role):
        """Ensure role is stored in uppercase."""
        if isinstance(role, str):
            role = role.upper()
        return UserRole(role)

class Organizer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    company_name = db.Column(db.String(255), nullable=False)
    company_logo = db.Column(db.String(255), nullable=True)
    company_description = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(255), nullable=True)
    social_media_links = db.Column(db.JSON, nullable=True)
    business_registration_number = db.Column(db.String(255), nullable=True)
    tax_id = db.Column(db.String(255), nullable=True)
    address = db.Column(db.Text, nullable=True)
   

    created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    user = db.relationship('User', backref=db.backref('organizer_profile', uselist=False))
    events = db.relationship('Event', backref='organizer', lazy=True)
    tickets = db.relationship('Ticket', backref='organizer', lazy=True)

    def as_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "company_name": self.company_name,
            "company_logo": self.company_logo,
            "company_description": self.company_description,
            "website": self.website,
            "social_media_links": self.social_media_links,
            "business_registration_number": self.business_registration_number,
            "tax_id": self.tax_id,
            "address": self.address,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "events_count": len(self.events)
        }

# Add Category model before Event model
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    events = db.relationship('Event', backref='event_category', lazy=True)

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

# Event model
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)  # Index for faster search
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=True)  # Made nullable if optional
    location = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255), nullable=True)  # Made nullable if optional
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False)
    featured = db.Column(db.Boolean, default=False, nullable=False)  # New featured column
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)  # Changed from category to category_id

    # Many-to-many relationship for likes
    likes = db.relationship('User', secondary=event_likes, backref='liked_events', lazy='dynamic')

    ticket_types = db.relationship('TicketType', backref='event', lazy=True, cascade="all, delete")
    tickets = db.relationship('Ticket', backref='event', lazy=True, cascade="all, delete")
    reports = db.relationship('Report', backref='event', lazy=True, cascade="all, delete")

    def __init__(self, name, description, date, start_time, end_time, location, image, organizer_id, category_id):
        self.name = name
        self.description = description
        self.date = date
        self.start_time = start_time
        self.end_time = end_time
        self.location = location
        self.image = image
        self.organizer_id = organizer_id
        self.category_id = category_id
        self.validate_datetime()  

    def validate_datetime(self):
        """Ensures start_time is before end_time and date is not in the past."""
        if self.date < datetime.utcnow().date():
            raise ValueError("Event date cannot be in the past.")

        start_datetime = datetime.combine(self.date, self.start_time)

        if self.end_time:
            end_datetime = datetime.combine(self.date, self.end_time)

            # Allow overnight events (e.g., 22:00 - 06:00)
            if end_datetime <= start_datetime:
                end_datetime += timedelta(days=1)

            if start_datetime >= end_datetime:
                raise ValueError("Start time must be before end time.")
        else:
            end_datetime = None  # No end time means "Till Late"

        self.end_datetime = end_datetime  # Store for later use

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "date": self.date.strftime("%Y-%m-%d") if self.date else None,
            "start_time": self.start_time.strftime("%H:%M:%S") if self.start_time else None,
            "end_time": self.end_time.strftime("%H:%M:%S") if self.end_time else None,
            "location": self.location,
            "image": self.image,
            "organizer_id": self.organizer_id,
            "organizer": {
                "id": self.organizer.id,
                "company_name": self.organizer.company_name,
                "company_description": self.organizer.company_description
            } if self.organizer else None,
            "tickets": [{
                "id": ticket.id,
                "quantity": ticket.quantity,
                "payment_status": ticket.payment_status.value,
                "ticket_type": {
                    "price": ticket.ticket_type.price
                } if ticket.ticket_type else None
            } for ticket in self.tickets] if self.tickets else [],
            "featured": self.featured,
            "likes_count": self.likes.count(),  # Include the number of likes
            "category": self.event_category.name if self.event_category else None
        }

# TicketType model
class TicketType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type_name = db.Column(db.Enum(TicketTypeEnum), nullable=False)
    price = db.Column(db.Float, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)  # Add this line

    tickets = db.relationship('Ticket', backref='ticket_type', lazy=True)
    reports = db.relationship('Report', backref='ticket_type', lazy=True)

    def as_dict(self):
        return {
            "id": self.id,
            "type_name": self.type_name.value,
            "price": self.price,
            "event_id": self.event_id,
            "quantity": self.quantity
        }

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False, index=True)

    total_tickets_sold = db.Column(db.Integer, nullable=False, default=0)
    total_revenue = db.Column(db.Float, nullable=False, default=0.0)

    # Relationships (uncomment if needed)
    # event = db.relationship('Event', backref=db.backref('reports', lazy=True))
    # ticket_type = db.relationship('TicketType', backref=db.backref('reports', lazy=True))

    def as_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "event_name": self.event.name,
            "ticket_type": self.ticket_type.type_name.value,
            "total_tickets_sold": self.total_tickets_sold,
            "total_revenue": self.total_revenue
        }

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(255), nullable=True)
    email = db.Column(db.Text, nullable=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    qr_code = db.Column(db.String(255), unique=True, nullable=False)  # QR code
    scanned = db.Column(db.Boolean, default=False)
    purchase_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    merchant_request_id = db.Column(db.String(255), unique=True, nullable=True)  # New field

    transaction = db.relationship('Transaction', back_populates='tickets', foreign_keys=[transaction_id])
    payment_status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.PENDING)
    scans = db.relationship('Scan', backref='ticket', lazy=True)

    @property
    def total_price(self):
        ticket_type = TicketType.query.get(self.ticket_type_id)
        return self.quantity * ticket_type.price if ticket_type else 0

    def as_dict(self):
        return {
            "id": self.id,
            "phone_number": self.phone_number,
            "email": self.email,
            "ticket_type_id": self.ticket_type_id,
            "event_id": self.event_id,
            "user_id": self.user_id,
            "organizer_id": self.organizer_id,
            "transaction_id": self.transaction_id,
            "quantity": self.quantity,
            "qr_code": self.qr_code,
            "scanned": self.scanned,
            "purchase_date": self.purchase_date.isoformat(),
            "merchant_request_id": self.merchant_request_id,  # New field
            "total_price": self.total_price
        }

# Transaction model
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount_paid = db.Column(db.Numeric(8, 2), nullable=False)
    payment_status = db.Column(db.Enum(PaymentStatus), nullable=False)
    payment_reference = db.Column(db.Text, nullable=False)
    payment_method = db.Column(db.Enum(PaymentMethod), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=True)
    merchant_request_id = db.Column(db.String(255), unique=True, nullable=True)
    mpesa_receipt_number = db.Column(db.String(255), nullable=True)

    user = db.relationship('User', back_populates='transactions')
    organizer = db.relationship('Organizer', backref=db.backref('transaction_history', lazy=True))
    tickets = db.relationship('Ticket', back_populates='transaction', foreign_keys=[Ticket.transaction_id])

    def as_dict(self):
        return {
            "id": self.id,
            "amount_paid": float(self.amount_paid),
            "payment_status": self.payment_status.value,
            "payment_reference": self.payment_reference,
            "payment_method": self.payment_method.value,
            "timestamp": self.timestamp.isoformat(),
            "merchant_request_id": self.merchant_request_id,
            "mpesa_receipt_number": self.mpesa_receipt_number,
            "user_id": self.user_id,
            "organizer_id": self.organizer_id
        }

# Scan model
class Scan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    scanned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def as_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "scanned_at": self.scanned_at.isoformat(),
            "scanned_by": self.scanned_by
        }
