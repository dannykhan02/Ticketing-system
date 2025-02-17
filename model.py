from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Initialize SQLAlchemy
db = SQLAlchemy()

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum('admin', 'organizer', 'attendee', name='user_roles'), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, nullable=False)
    phone_number = db.Column(db.String(255), nullable=False)
    
    events = db.relationship('Event', backref='organizer', lazy=True)
    tickets = db.relationship('Ticket', backref='buyer', lazy=True)
    scans = db.relationship('Scan', backref='scanner', lazy=True)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)
    
    def as_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "role": self.role,
            "phone_number": self.phone_number,
            "created_at": self.created_at.isoformat()
        }

# Event model
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    location = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    ticket_types = db.relationship('TicketType', backref='event', lazy=True)
    tickets = db.relationship('Ticket', backref='event', lazy=True)
    
    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "date": self.date.isoformat(),
            "start_time": str(self.start_time),
            "end_time": str(self.end_time),
            "location": self.location,
            "image": self.image,
            "user_id": self.user_id
        }

# Ticket Type model
class TicketType(db.Model):
    id = db.Column(db.BigInteger, primary_key=True)
    type_name = db.Column(db.Enum('regular', 'vip', 'student', name='ticket_types'), nullable=True)
    price = db.Column(db.Float, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    
    tickets = db.relationship('Ticket', backref='ticket_type', lazy=True)
    
    def as_dict(self):
        return {
            "id": self.id,
            "type_name": self.type_name,
            "price": self.price,
            "event_id": self.event_id
        }

# Ticket model
class Ticket(db.Model):
    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(255), nullable=False)
    email = db.Column(db.Text, nullable=False)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    qr_code = db.Column(db.String(255), nullable=False)
    scanned = db.Column(db.Boolean, nullable=False, default=False)
    
    transactions = db.relationship('Transaction', backref='ticket', lazy=True)
    scans = db.relationship('Scan', backref='ticket', lazy=True)
    
    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone_number": self.phone_number,
            "email": self.email,
            "ticket_type_id": self.ticket_type_id,
            "event_id": self.event_id,
            "user_id": self.user_id,
            "transaction_id": self.transaction_id,
            "quantity": self.quantity,
            "qr_code": self.qr_code,
            "scanned": self.scanned
        }

# Transaction model
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    amount_paid = db.Column(db.Numeric(8, 2), nullable=False)
    payment_status = db.Column(db.Enum('pending', 'completed', 'failed', name='payment_statuses'), nullable=False)
    payment_reference = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def as_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "amount_paid": float(self.amount_paid),
            "payment_status": self.payment_status,
            "payment_reference": self.payment_reference,
            "timestamp": self.timestamp.isoformat()
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
