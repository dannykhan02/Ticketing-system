from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import enum
from sqlalchemy.dialects.postgresql import JSONB
from decimal import Decimal

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

# New Currency-related Enums
class CurrencyCode(enum.Enum):
    USD = "USD"  # US Dollar
    EUR = "EUR"  # Euro
    GBP = "GBP"  # British Pound
    KES = "KES"  # Kenyan Shilling (your local currency)
    UGX = "UGX"  # Ugandan Shilling
    TZS = "TZS"  # Tanzanian Shilling
    NGN = "NGN"  # Nigerian Naira
    GHS = "GHS"  # Ghanaian Cedi
    ZAR = "ZAR"  # South African Rand
    JPY = "JPY"  # Japanese Yen
    CAD = "CAD"  # Canadian Dollar
    AUD = "AUD"  # Australian Dollar


# Add a new association table for likes
event_likes = db.Table(
    'event_likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
)

# New Currency Model
class Currency(db.Model):
    __tablename__ = 'currencies'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.Enum(CurrencyCode), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)  # e.g., "US Dollar"
    symbol = db.Column(db.String(10), nullable=False)  # e.g., "$"
    is_base_currency = db.Column(db.Boolean, default=False)  # One currency should be base
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    exchange_rates_from = db.relationship('ExchangeRate', foreign_keys='ExchangeRate.from_currency_id', backref='from_currency', lazy=True)
    exchange_rates_to = db.relationship('ExchangeRate', foreign_keys='ExchangeRate.to_currency_id', backref='to_currency', lazy=True)
    ticket_types = db.relationship('TicketType', backref='currency', lazy=True)
    transactions = db.relationship('Transaction', backref='currency', lazy=True)
    
    def as_dict(self):
        return {
            "id": self.id,
            "code": self.code.value,
            "name": self.name,
            "symbol": self.symbol,
            "is_base_currency": self.is_base_currency,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

# New Exchange Rate Model
class ExchangeRate(db.Model):
    __tablename__ = 'exchange_rates'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    from_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=False)
    to_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=False)
    rate = db.Column(db.Numeric(15, 6), nullable=False)  # High precision for exchange rates
    effective_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    source = db.Column(db.String(100), nullable=True)  # e.g., "API", "Manual", "Bank"
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint to prevent duplicate active rates for same currency pair
    __table_args__ = (
        db.UniqueConstraint('from_currency_id', 'to_currency_id', 'is_active', 
                          name='uix_active_exchange_rate'),
    )
    
    def as_dict(self):
        return {
            "id": self.id,
            "from_currency": self.from_currency.code.value if self.from_currency else None,
            "to_currency": self.to_currency.code.value if self.to_currency else None,
            "rate": float(self.rate),
            "effective_date": self.effective_date.isoformat(),
            "source": self.source,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
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
    # Reports relationship - user can be an organizer creating reports
    reports = db.relationship('Report', backref='organizer_user', lazy=True)

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
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
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
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
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
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
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
                   "price":  float(ticket.ticket_type.price)
                    
                } if ticket.ticket_type else None
            } for ticket in self.tickets] if self.tickets else [],
            "featured": self.featured,
            "likes_count": self.likes.count(),  # Include the number of likes
            "category": self.event_category.name if self.event_category else None
        }

# TicketType model - Updated with currency support
class TicketType(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    type_name = db.Column(db.Enum(TicketTypeEnum), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)  # Changed to Numeric for precision
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=True)  # New currency field
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)

    tickets = db.relationship('Ticket', backref='ticket_type', lazy=True)
    reports = db.relationship('Report', backref='ticket_type', lazy=True)

    def get_price_in_currency(self, target_currency_id):
        """Convert ticket price to target currency"""
        if self.currency_id == target_currency_id:
            return self.price
        
        # Get the latest exchange rate
        rate = ExchangeRate.query.filter_by(
            from_currency_id=self.currency_id,
            to_currency_id=target_currency_id,
            is_active=True
        ).order_by(ExchangeRate.effective_date.desc()).first()
        
        if rate:
            return self.price * rate.rate
        
        return self.price  # Return original price if no rate found

    def as_dict(self):
        return {
            "id": self.id,
            "type_name": self.type_name.value,
            "price": float(self.price),
            "currency": self.currency.code.value if self.currency else None,
            "currency_symbol": self.currency.symbol if self.currency else None,
            "event_id": self.event_id,
            "quantity": self.quantity
        }

# Updated Report table with currency conversion support
class Report(db.Model):
    __tablename__ = 'reports'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # Core relationships
    organizer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=True, index=True)
    
    # Currency fields
    base_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=False)
    converted_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=True)
    
    # Revenue fields
    total_revenue = db.Column(db.Numeric(12, 2), nullable=False, default=0.0)
    converted_revenue = db.Column(db.Numeric(12, 2), nullable=True)
    
    # Report scope and data
    report_scope = db.Column(db.String(50), nullable=False, default="event_summary")
    total_tickets_sold = db.Column(db.Integer, nullable=False, default=0)
    number_of_attendees = db.Column(db.Integer, nullable=True, default=0)
    report_data = db.Column(JSONB, nullable=False, default=dict)
    
    # Metadata
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    report_date = db.Column(db.Date, nullable=True)

    # Relationships
    base_currency = db.relationship('Currency', foreign_keys=[base_currency_id], backref='base_reports', lazy=True)
    converted_currency = db.relationship('Currency', foreign_keys=[converted_currency_id], backref='converted_reports', lazy=True)

    def get_revenue_in_currency(self, target_currency_id):
        """Convert total revenue to target currency using latest local exchange rate."""
        if self.base_currency_id == target_currency_id:
            return self.total_revenue

        rate = ExchangeRate.query.filter_by(
            from_currency_id=self.base_currency_id,
            to_currency_id=target_currency_id,
            is_active=True
        ).order_by(ExchangeRate.effective_date.desc()).first()
        
        if rate:
            return self.total_revenue * rate.rate

        return self.total_revenue  # Fallback: original value if no rate found

    def as_dict(self, target_currency_id=None):
        """Return dictionary with revenue data in requested or stored currency."""
        # Use stored converted values if they exist
        if self.converted_currency and self.converted_revenue:
            revenue_info = {
                "total_revenue": float(self.converted_revenue),
                "currency": self.converted_currency.code.value,
                "currency_symbol": self.converted_currency.symbol,
                "original_revenue": float(self.total_revenue),
                "original_currency": self.base_currency.code.value if self.base_currency else None
            }
        elif target_currency_id:
            # Convert dynamically if requested via API
            converted_revenue = self.get_revenue_in_currency(target_currency_id)
            target_currency = Currency.query.get(target_currency_id)
            revenue_info = {
                "total_revenue": float(converted_revenue),
                "currency": target_currency.code.value if target_currency else None,
                "currency_symbol": target_currency.symbol if target_currency else None,
                "original_revenue": float(self.total_revenue),
                "original_currency": self.base_currency.code.value if self.base_currency else None
            }
        else:
            # Fallback to base currency
            revenue_info = {
                "total_revenue": float(self.total_revenue),
                "currency": self.base_currency.code.value if self.base_currency else None,
                "currency_symbol": self.base_currency.symbol if self.base_currency else None
            }

        data = {
            "id": self.id,
            "organizer_id": self.organizer_id,
            "event_id": self.event_id,
            "event_name": self.event.name if self.event else "N/A",
            "organizer_name": self.organizer_user.full_name if self.organizer_user else "N/A",
            "timestamp": self.timestamp.isoformat(),
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "scope": self.report_scope,
            "total_tickets_sold": self.total_tickets_sold,
            "number_of_attendees": self.number_of_attendees,
            "report_data": self.report_data,
            **revenue_info
        }

        if self.ticket_type_id:
            data["ticket_type_id"] = self.ticket_type_id
            data["ticket_type_name"] = self.ticket_type.type_name.value if self.ticket_type and self.ticket_type.type_name else "N/A"
        
        return data


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    phone_number = db.Column(db.String(255), nullable=True)
    email = db.Column(db.Text, nullable=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)  # Always 1 for individual tickets
    qr_code = db.Column(db.String(255), unique=True, nullable=False)  # QR code
    scanned = db.Column(db.Boolean, default=False)
    purchase_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    merchant_request_id = db.Column(db.String(255), nullable=True)  # For payment reference

    # Relationships
    transaction = db.relationship('Transaction', back_populates='tickets', foreign_keys=[transaction_id])
    payment_status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.PENDING)
    scans = db.relationship('Scan', backref='ticket', lazy=True)

    @property
    def total_price(self):
        ticket_type = TicketType.query.get(self.ticket_type_id)
        return ticket_type.price if ticket_type else 0

    def get_price_in_currency(self, target_currency_id):
        """Get ticket price in target currency"""
        if self.ticket_type:
            return self.ticket_type.get_price_in_currency(target_currency_id)
        return 0

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
            "merchant_request_id": self.merchant_request_id,
            "total_price": float(self.total_price),
            "currency": self.ticket_type.currency.code.value if self.ticket_type and self.ticket_type.currency else None
        }

# Fixed TransactionTicket model (junction table)
class TransactionTicket(db.Model):
    __tablename__ = 'transaction_ticket'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Create unique constraint to prevent duplicate entries
    __table_args__ = (db.UniqueConstraint('transaction_id', 'ticket_id', name='uix_transaction_ticket'),)

    # Relationships
    transaction = db.relationship('Transaction', backref=db.backref('transaction_tickets', lazy=True))
    ticket = db.relationship('Ticket', backref=db.backref('transaction_tickets', lazy=True))

# Updated Transaction model with currency support
class Transaction(db.Model):
    __tablename__ = 'transaction'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    amount_paid = db.Column(db.Numeric(10, 2), nullable=False)  # Changed to Numeric
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=False)  # New currency field
    payment_status = db.Column(db.Enum(PaymentStatus), nullable=False)
    payment_reference = db.Column(db.Text, nullable=False)
    payment_method = db.Column(db.Enum(PaymentMethod), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=True)
    merchant_request_id = db.Column(db.String(255), unique=True, nullable=True)
    mpesa_receipt_number = db.Column(db.String(255), nullable=True)

    # Relationships
    user = db.relationship('User', back_populates='transactions')
    organizer = db.relationship('Organizer', backref=db.backref('transaction_history', lazy=True))
    tickets = db.relationship('Ticket', back_populates='transaction', foreign_keys=[Ticket.transaction_id])

    def get_amount_in_currency(self, target_currency_id):
        """Convert transaction amount to target currency"""
        if self.currency_id == target_currency_id:
            return self.amount_paid
        
        # Get the latest exchange rate
        rate = ExchangeRate.query.filter_by(
            from_currency_id=self.currency_id,
            to_currency_id=target_currency_id,
            is_active=True
        ).order_by(ExchangeRate.effective_date.desc()).first()
        
        if rate:
            return self.amount_paid * rate.rate
        
        return self.amount_paid  # Return original if no rate found

    def get_tickets(self):
        """Get all tickets associated with this transaction through the junction table"""
        ticket_ids = [tt.ticket_id for tt in self.transaction_tickets]
        return Ticket.query.filter(Ticket.id.in_(ticket_ids)).all()

    def as_dict(self, target_currency_id=None):
        # Calculate amount in target currency if specified
        if target_currency_id:
            converted_amount = self.get_amount_in_currency(target_currency_id)
            target_currency = Currency.query.get(target_currency_id)
            amount_info = {
                "amount_paid": float(converted_amount),
                "currency": target_currency.code.value if target_currency else None,
                "currency_symbol": target_currency.symbol if target_currency else None,
                "original_amount": float(self.amount_paid),
                "original_currency": self.currency.code.value if self.currency else None
            }
        else:
            amount_info = {
                "amount_paid": float(self.amount_paid),
                "currency": self.currency.code.value if self.currency else None,
                "currency_symbol": self.currency.symbol if self.currency else None
            }

        return {
            "id": self.id,
            "payment_status": self.payment_status.value,
            "payment_reference": self.payment_reference,
            "payment_method": self.payment_method.value,
            "timestamp": self.timestamp.isoformat(),
            "merchant_request_id": self.merchant_request_id,
            "mpesa_receipt_number": self.mpesa_receipt_number,
            "user_id": self.user_id,
            "organizer_id": self.organizer_id,
            "ticket_count": len(self.transaction_tickets) if hasattr(self, 'transaction_tickets') else 0,
            **amount_info
        }

# Scan model
class Scan(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
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

# Utility functions for currency operations
class CurrencyConverter:
    @staticmethod
    def get_base_currency():
        """Get the base currency (should be only one)"""
        return Currency.query.filter_by(is_base_currency=True, is_active=True).first()
    
    @staticmethod
    def convert_amount(amount, from_currency_id, to_currency_id):
        """Convert amount between currencies"""
        if from_currency_id == to_currency_id:
            return amount
        
        rate = ExchangeRate.query.filter_by(
            from_currency_id=from_currency_id,
            to_currency_id=to_currency_id,
            is_active=True
        ).order_by(ExchangeRate.effective_date.desc()).first()
        
        if rate:
            return Decimal(str(amount)) * rate.rate
        
        return amount
    
    @staticmethod
    def get_latest_rate(from_currency_id, to_currency_id):
        """Get the latest exchange rate between two currencies"""
        return ExchangeRate.query.filter_by(
            from_currency_id=from_currency_id,
            to_currency_id=to_currency_id,
            is_active=True
        ).order_by(ExchangeRate.effective_date.desc()).first()
    
    @staticmethod
    def update_exchange_rate(from_currency_id, to_currency_id, new_rate, source="API"):
        """Update exchange rate - deactivate old rate and create new one"""
        # Deactivate existing rates
        ExchangeRate.query.filter_by(
            from_currency_id=from_currency_id,
            to_currency_id=to_currency_id,
            is_active=True
        ).update({'is_active': False})
        
        # Create new rate
        new_exchange_rate = ExchangeRate(
            from_currency_id=from_currency_id,
            to_currency_id=to_currency_id,
            rate=Decimal(str(new_rate)),
            source=source,
            is_active=True
        )
        
        db.session.add(new_exchange_rate)
        return new_exchange_rate