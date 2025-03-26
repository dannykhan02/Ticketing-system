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

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, nullable=False)
    phone_number = db.Column(db.String(255), nullable=False)

    events = db.relationship('Event', backref='organizer', lazy=True)
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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    ticket_types = db.relationship('TicketType', backref='event', lazy=True, cascade="all, delete")
    tickets = db.relationship('Ticket', backref='event', lazy=True, cascade="all, delete")

    def __init__(self, name, description, date, start_time, end_time, location, image, user_id):
        self.name = name
        self.description = description
        self.date = date
        self.start_time = start_time
        self.end_time = end_time
        self.location = location
        self.image = image
        self.user_id = user_id

        self.validate_datetime()  # Ensure valid date and time

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
            "date": self.date.strftime("%Y-%m-%d"),  # Convert to string for JSON
            "start_time": self.start_time.strftime("%H:%M:%S"),  # Convert to HH:MM:SS
            "end_time": self.end_time.strftime("%H:%M:%S") if self.end_time else "Till Late",  # Handle None
            "location": self.location,
            "image": self.image,
            "user_id": self.user_id
        }

# TicketType model
class TicketType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type_name = db.Column(db.Enum(TicketTypeEnum), nullable=False)
    price = db.Column(db.Float, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)  # Add this line

    tickets = db.relationship('Ticket', backref='ticket_type', lazy=True)

    def as_dict(self):
        return {
            "id": self.id,
            "type_name": self.type_name.value,
            "price": self.price,
            "event_id": self.event_id,
            "quantity": self.quantity
        }

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(255), nullable=True)
    email = db.Column(db.Text, nullable=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    qr_code = db.Column(db.String(255), nullable=True)
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
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    merchant_request_id = db.Column(db.String(255), unique=True, nullable=True)  # Changed nullable to True
    mpesa_receipt_number = db.Column(db.String(255), nullable=True)

    user = db.relationship('User', back_populates='transactions')
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
            "mpesa_receipt_number": self.mpesa_receipt_number
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
