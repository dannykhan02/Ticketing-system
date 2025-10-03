from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import validates
from decimal import Decimal

# Initialize SQLAlchemy
db = SQLAlchemy()

# ===== ENUMS =====
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

class CurrencyCode(enum.Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    KES = "KES"
    UGX = "UGX"
    TZS = "TZS"
    NGN = "NGN"
    GHS = "GHS"
    ZAR = "ZAR"
    JPY = "JPY"
    CAD = "CAD"
    AUD = "AUD"

class CollaborationType(enum.Enum):
    PARTNER = "Partner"
    OFFICIAL_PARTNER = "Official Partner"
    COLLABORATOR = "Collaborator"
    SUPPORTER = "Supporter"
    MEDIA_PARTNER = "Media Partner"
    def __str__(self):
        return self.value

class AIIntentType(enum.Enum):
    """Types of user intents the AI can recognize"""
    CREATE_EVENT = "create_event"
    UPDATE_EVENT = "update_event"
    DELETE_EVENT = "delete_event"
    SEARCH_EVENTS = "search_events"
    CREATE_TICKETS = "create_tickets"
    UPDATE_TICKETS = "update_tickets"
    ANALYZE_SALES = "analyze_sales"
    GENERATE_REPORT = "generate_report"
    MANAGE_PARTNERS = "manage_partners"
    PRICING_RECOMMENDATION = "pricing_recommendation"
    INVENTORY_CHECK = "inventory_check"
    REVENUE_ANALYSIS = "revenue_analysis"
    BULK_OPERATION = "bulk_operation"
    GENERAL_QUERY = "general_query"

class AIActionStatus(enum.Enum):
    """Status of AI-executed actions"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    CANCELLED = "cancelled"

class AICachePriority(enum.Enum):
    """Priority levels for cached analytics"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

# ===== ASSOCIATION TABLES =====
event_likes = db.Table(
    'event_likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
)

# ===== CORE MODELS =====
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    password = db.Column(db.String(255))
    full_name = db.Column(db.String(100))
    role = db.Column(db.Enum(UserRole), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, nullable=False)
    phone_number = db.Column(db.String(255))
    google_id = db.Column(db.String(255), unique=True)
    is_oauth = db.Column(db.Boolean, default=False)
    # AI preferences and settings
    ai_enabled = db.Column(db.Boolean, default=True)
    ai_language_preference = db.Column(db.String(10), default='en')
    ai_notification_preference = db.Column(db.Boolean, default=True)
    # Relationships
    tickets = db.relationship('Ticket', backref='buyer', lazy=True)
    transactions = db.relationship('Transaction', back_populates='user', lazy=True)
    scans = db.relationship('Scan', backref='scanner', lazy=True)
    reports = db.relationship('Report', backref='organizer_user', lazy=True)

    # AI-related relationships
    ai_conversations = db.relationship('AIConversation', backref='user', lazy=True, cascade="all, delete")
    ai_preferences = db.relationship('AIUserPreference', backref='user', uselist=False, cascade="all, delete")
    ai_actions = db.relationship('AIActionLog', backref='user', lazy=True, cascade="all, delete")
    ai_usage_metrics = db.relationship('AIUsageMetrics', backref='user', lazy=True, cascade="all, delete")
    ai_feedback = db.relationship('AIFeedback', backref='user', lazy=True, cascade="all, delete")

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def as_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role.value,
            "phone_number": self.phone_number,
            "created_at": self.created_at.isoformat(),
            "ai_enabled": self.ai_enabled
        }

    @staticmethod
    def validate_role(role):
        if isinstance(role, str):
            role = role.upper()
        return UserRole(role)

class Currency(db.Model):
    __tablename__ = 'currencies'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.Enum(CurrencyCode), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    symbol = db.Column(db.String(10), nullable=False)
    is_base_currency = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
            "is_active": self.is_active
        }

class ExchangeRate(db.Model):
    __tablename__ = 'exchange_rates'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    from_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=False)
    to_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=False)
    rate = db.Column(db.Numeric(15, 6), nullable=False)
    effective_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    source = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
            "effective_date": self.effective_date.isoformat()
        }

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
    partners = db.relationship('Partner', backref='organizer', lazy=True)

    # AI relationships
    ai_insights = db.relationship('AIInsight', backref='organizer', lazy=True,
                                 foreign_keys='AIInsight.organizer_id')
    ai_suggestions = db.relationship('AIEventSuggestion', backref='organizer', lazy=True)
    ai_analytics_cache = db.relationship('AIAnalyticsCache', backref='organizer', lazy=True,
                                        foreign_keys='AIAnalyticsCache.organizer_id')
    ai_revenue_analyses = db.relationship('AIRevenueAnalysis', backref='organizer', lazy=True)

    def as_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "company_name": self.company_name,
            "company_logo": self.company_logo,
            "events_count": len(self.events),
            "partners_count": len([p for p in self.partners if p.is_active])
        }


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    
    # AI-enhanced fields
    ai_description_enhanced = db.Column(db.Boolean, default=False)
    ai_suggested_keywords = db.Column(JSONB, nullable=True)  # Keywords for better event matching
    popularity_score = db.Column(db.Float, default=0.0)  # AI-calculated popularity
    trending_score = db.Column(db.Float, default=0.0)  # Real-time trending indicator
    
    # Metadata
    created_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    events = db.relationship('Event', backref='event_category', lazy=True)
    
    # AI relationships
    ai_insights = db.relationship('AICategoryInsight', backref='category', lazy=True, 
                                 cascade="all, delete")
    ai_actions = db.relationship('AIActionLog', backref='category', lazy=True,
                                foreign_keys='AIActionLog.category_id')
    ai_suggestions = db.relationship('AIEventSuggestion', 
                                    foreign_keys='AIEventSuggestion.suggested_category_id',
                                    backref='suggested_category', lazy=True)

    @validates('popularity_score', 'trending_score')
    def validate_scores(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError(f"{key} must be between 0 and 1")
        return value

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "ai_description_enhanced": self.ai_description_enhanced,
            "ai_suggested_keywords": self.ai_suggested_keywords,
            "popularity_score": self.popularity_score,
            "trending_score": self.trending_score,
            "events_count": len(self.events),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
    
    def get_trending_events(self, limit=10):
        """Get trending events in this category"""
        return Event.query.filter_by(
            category_id=self.id
        ).order_by(Event.date.desc()).limit(limit).all()
    
    def calculate_popularity(self):
        """Calculate popularity based on events and engagement"""
        from sqlalchemy import func
        
        # Count active future events
        active_events = Event.query.filter(
            Event.category_id == self.id,
            Event.date >= datetime.utcnow().date()
        ).count()
        
        # Count total tickets sold in category
        total_tickets = db.session.query(func.sum(Ticket.quantity)).join(
            Event
        ).filter(Event.category_id == self.id).scalar() or 0
        
        # Simple popularity calculation (can be made more sophisticated)
        self.popularity_score = min(1.0, (active_events * 0.3 + total_tickets * 0.001))
        db.session.commit()
        return self.popularity_score


class AICategoryInsight(db.Model):
    """AI-generated insights specific to categories"""
    __tablename__ = 'ai_category_insights'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False, index=True)
    
    # Insight details
    insight_type = db.Column(db.String(50), nullable=False, index=True)
    # Types: 'trending', 'seasonal_pattern', 'pricing_analysis', 'demand_forecast'
    
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    
    # Analysis data
    insight_data = db.Column(JSONB, nullable=True)
    # Example: {"avg_ticket_price": 1500, "peak_months": [6,7,12], "growth_rate": 15.3}
    
    recommended_actions = db.Column(JSONB, nullable=True)
    # Example: [{"action": "increase_inventory", "reason": "High demand expected"}]
    
    # Metrics
    confidence_score = db.Column(db.Float, nullable=True)
    potential_revenue_impact = db.Column(db.Numeric(12, 2), nullable=True)
    
    # Status
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_read = db.Column(db.Boolean, default=False)
    
    # Timestamps
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    
    @validates('confidence_score')
    def validate_confidence(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError("Confidence score must be between 0 and 1")
        return value
    
    __table_args__ = (
        db.Index('idx_category_active', 'category_id', 'is_active'),
    )
    
    def as_dict(self):
        return {
            "id": self.id,
            "category_id": self.category_id,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "insight_data": self.insight_data,
            "recommended_actions": self.recommended_actions,
            "confidence_score": self.confidence_score,
            "potential_revenue_impact": float(self.potential_revenue_impact) if self.potential_revenue_impact else None,
            "is_read": self.is_read,
            "generated_at": self.generated_at.isoformat()
        }

class Partner(db.Model):
    __tablename__ = 'partners'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False)
    company_name = db.Column(db.String(255), nullable=False)
    company_description = db.Column(db.Text, nullable=True)
    logo_url = db.Column(db.String(500), nullable=True)
    website_url = db.Column(db.String(500), nullable=True)
    contact_email = db.Column(db.String(255), nullable=True)
    contact_person = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    collaborations = db.relationship('EventCollaboration', back_populates='partner', lazy=True)

    # AI relationships
    ai_actions = db.relationship('AIActionLog', backref='partner', lazy=True,
                                foreign_keys='AIActionLog.partner_id')

    def as_dict(self):
        return {
            "id": self.id,
            "organizer_id": self.organizer_id,
            "company_name": self.company_name,
            "logo_url": self.logo_url,
            "total_collaborations": len([c for c in self.collaborations if c.is_active])
        }

class EventCollaboration(db.Model):
    __tablename__ = 'event_collaborations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False)
    collaboration_type = db.Column(db.Enum(CollaborationType), default=CollaborationType.PARTNER, nullable=False)
    description = db.Column(db.Text, nullable=True)
    show_on_event_page = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship('Event', backref='collaborations')
    partner = db.relationship('Partner', back_populates='collaborations')

    __table_args__ = (
        db.UniqueConstraint('event_id', 'partner_id', 'is_active', name='uix_active_event_collaboration'),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "partner_id": self.partner_id,
            "collaboration_type": self.collaboration_type.value,
            "is_active": self.is_active
        }

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=True)
    city = db.Column(db.String(100), nullable=False, index=True, server_default="Unknown")
    location = db.Column(db.Text, nullable=False)
    amenities = db.Column(db.JSON, nullable=True)
    image = db.Column(db.String(255), nullable=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False)
    featured = db.Column(db.Boolean, default=False, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    # AI-generated content flags
    ai_description_enhanced = db.Column(db.Boolean, default=False)
    ai_recommendations_enabled = db.Column(db.Boolean, default=True)
    # Existing relationships
    likes = db.relationship('User', secondary=event_likes, backref='liked_events', lazy='dynamic')
    ticket_types = db.relationship('TicketType', backref='event', lazy=True, cascade="all, delete")
    tickets = db.relationship('Ticket', backref='event', lazy=True, cascade="all, delete")
    reports = db.relationship('Report', backref='event', lazy=True, cascade="all, delete")

    # AI relationships
    ai_insights = db.relationship('AIInsight', backref='event', lazy=True,
                                 foreign_keys='AIInsight.event_id')
    ai_suggestions = db.relationship('AIEventSuggestion',
                                    foreign_keys='AIEventSuggestion.created_event_id',
                                    backref='created_event', lazy=True)
    ai_analytics_cache = db.relationship('AIAnalyticsCache', backref='event', lazy=True,
                                        foreign_keys='AIAnalyticsCache.event_id')
    ai_actions = db.relationship('AIActionLog', backref='event', lazy=True,
                                foreign_keys='AIActionLog.event_id')
    ai_revenue_analyses = db.relationship('AIRevenueAnalysis', backref='event', lazy=True,
                                         foreign_keys='AIRevenueAnalysis.event_id')
    ai_ticket_analyses = db.relationship('AITicketAnalysis', backref='event', lazy=True)

    def __init__(self, name, description, date, start_time, end_time, city, location, amenities, image, organizer_id, category_id):
        self.name = name
        self.description = description
        self.date = date
        self.start_time = start_time
        self.end_time = end_time
        self.city = city
        self.location = location
        self.amenities = self.validate_amenities(amenities)
        self.image = image
        self.organizer_id = organizer_id
        self.category_id = category_id
        self.validate_datetime()

    def validate_amenities(self, amenities):
        if amenities is None:
            return []
        if not isinstance(amenities, list):
            raise ValueError("Amenities must be a list.")
        if len(amenities) > 5:
            raise ValueError("Maximum of 5 amenities allowed per event.")

        validated_amenities = []
        for amenity in amenities:
            if isinstance(amenity, str) and amenity.strip() and amenity.strip() not in validated_amenities:
                validated_amenities.append(amenity.strip())
        return validated_amenities

    def validate_datetime(self):
        if self.date < datetime.utcnow().date():
            raise ValueError("Event date cannot be in the past.")
        start_datetime = datetime.combine(self.date, self.start_time)
        if self.end_time:
            end_datetime = datetime.combine(self.date, self.end_time)
            if end_datetime <= start_datetime:
                end_datetime += timedelta(days=1)
            if start_datetime >= end_datetime:
                raise ValueError("Start time must be before end time.")
            self.end_datetime = end_datetime
        else:
            self.end_datetime = None

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "date": self.date.strftime("%Y-%m-%d") if self.date else None,
            "city": self.city,
            "location": self.location,
            "featured": self.featured,
            "likes_count": self.likes.count(),
            "category": self.event_category.name if self.event_category else None
        }

class TicketType(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    type_name = db.Column(db.Enum(TicketTypeEnum), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    # AI pricing insights
    ai_suggested_price = db.Column(db.Numeric(10, 2), nullable=True)
    ai_price_confidence = db.Column(db.Float, nullable=True)
    # Existing relationships
    tickets = db.relationship('Ticket', backref='ticket_type', lazy=True)
    reports = db.relationship('Report', backref='ticket_type', lazy=True)

    # AI relationships
    pricing_recommendations = db.relationship('AIPricingRecommendation',
                                             backref='ticket_type', lazy=True)
    ai_actions = db.relationship('AIActionLog', backref='ticket_type', lazy=True,
                                foreign_keys='AIActionLog.ticket_type_id')
    ai_ticket_analyses = db.relationship('AITicketAnalysis', backref='ticket_type', lazy=True,
                                        foreign_keys='AITicketAnalysis.ticket_type_id')

    @validates('ai_price_confidence')
    def validate_confidence(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError("AI price confidence must be between 0 and 1")
        return value

    def get_price_in_currency(self, target_currency_id):
        if self.currency_id == target_currency_id:
            return self.price

        rate = ExchangeRate.query.filter_by(
            from_currency_id=self.currency_id,
            to_currency_id=target_currency_id,
            is_active=True
        ).order_by(ExchangeRate.effective_date.desc()).first()

        if rate:
            return self.price * rate.rate
        return self.price

    def as_dict(self):
        return {
            "id": self.id,
            "type_name": self.type_name.value,
            "price": float(self.price),
            "currency": self.currency.code.value if self.currency else None,
            "event_id": self.event_id,
            "quantity": self.quantity,
            "ai_suggested_price": float(self.ai_suggested_price) if self.ai_suggested_price else None
        }

class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=True, index=True)
    base_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=False)
    converted_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=True)
    total_revenue = db.Column(db.Numeric(12, 2), nullable=False, default=0.0)
    converted_revenue = db.Column(db.Numeric(12, 2), nullable=True)
    report_scope = db.Column(db.String(50), nullable=False, default="event_summary")
    total_tickets_sold = db.Column(db.Integer, nullable=False, default=0)
    number_of_attendees = db.Column(db.Integer, nullable=True, default=0)
    report_data = db.Column(JSONB, nullable=False, default=dict)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    report_date = db.Column(db.Date, nullable=True)
    # AI-generated insights
    ai_insights = db.Column(JSONB, nullable=True)
    ai_recommendations = db.Column(JSONB, nullable=True)
    generated_by_ai_action_id = db.Column(db.Integer,
                                         db.ForeignKey('ai_action_logs.id'),
                                         nullable=True)
    base_currency = db.relationship('Currency', foreign_keys=[base_currency_id], backref='base_reports', lazy=True)
    converted_currency = db.relationship('Currency', foreign_keys=[converted_currency_id], backref='converted_reports', lazy=True)
    generating_action = db.relationship('AIActionLog', foreign_keys=[generated_by_ai_action_id], backref='generated_reports')

    def as_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "total_revenue": float(self.total_revenue),
            "total_tickets_sold": self.total_tickets_sold,
            "ai_insights": self.ai_insights
        }

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    phone_number = db.Column(db.String(255), nullable=True)
    email = db.Column(db.Text, nullable=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    qr_code = db.Column(db.String(255), unique=True, nullable=False)
    scanned = db.Column(db.Boolean, default=False)
    purchase_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    merchant_request_id = db.Column(db.String(255), nullable=True)
    payment_status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.PENDING)
    transaction = db.relationship('Transaction', back_populates='tickets', foreign_keys=[transaction_id])
    scans = db.relationship('Scan', backref='ticket', lazy=True)

    # AI relationships
    ai_actions = db.relationship('AIActionLog', backref='ticket', lazy=True,
                                foreign_keys='AIActionLog.ticket_id')

    @property
    def total_price(self):
        ticket_type = TicketType.query.get(self.ticket_type_id)
        return ticket_type.price if ticket_type else 0

    def as_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "quantity": self.quantity,
            "scanned": self.scanned,
            "total_price": float(self.total_price)
        }

class TransactionTicket(db.Model):
    __tablename__ = 'transaction_ticket'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('transaction_id', 'ticket_id', name='uix_transaction_ticket'),)
    transaction = db.relationship('Transaction', backref=db.backref('transaction_tickets', lazy=True))
    ticket = db.relationship('Ticket', backref=db.backref('transaction_tickets', lazy=True))

class Transaction(db.Model):
    __tablename__ = 'transaction'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    amount_paid = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=True)
    payment_status = db.Column(db.Enum(PaymentStatus), nullable=False, index=True)
    payment_reference = db.Column(db.Text, nullable=False)
    payment_method = db.Column(db.Enum(PaymentMethod), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=True)
    merchant_request_id = db.Column(db.String(255), unique=True, nullable=True)
    mpesa_receipt_number = db.Column(db.String(255), nullable=True)
    user = db.relationship('User', back_populates='transactions')
    organizer = db.relationship('Organizer', backref=db.backref('transaction_history', lazy=True))
    tickets = db.relationship('Ticket', back_populates='transaction', foreign_keys=[Ticket.transaction_id])

    # AI relationships
    ai_actions = db.relationship('AIActionLog', backref='transaction', lazy=True,
                                foreign_keys='AIActionLog.transaction_id')

    def as_dict(self):
        return {
            "id": self.id,
            "amount_paid": float(self.amount_paid),
            "payment_status": self.payment_status.value,
            "timestamp": self.timestamp.isoformat()
        }

class Scan(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    scanned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def as_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "scanned_at": self.scanned_at.isoformat()
        }

# ===== AI-SPECIFIC MODELS =====
class AIConversation(db.Model):
    """Stores AI chat conversations for context and history"""
    __tablename__ = 'ai_conversations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    session_id = db.Column(db.String(100), nullable=False, index=True)

    # Conversation metadata
    title = db.Column(db.String(255), nullable=True)
    intent_type = db.Column(db.Enum(AIIntentType), nullable=True)

    # Tracking
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    message_count = db.Column(db.Integer, default=0)

    # Relationships
    messages = db.relationship('AIMessage', backref='conversation', lazy=True, cascade="all, delete")
    actions = db.relationship('AIActionLog', backref='conversation', lazy=True, cascade="all, delete")

    __table_args__ = (
        db.Index('idx_user_active', 'user_id', 'is_active'),
        db.Index('idx_user_last_message', 'user_id', 'last_message_at'),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "title": self.title,
            "intent_type": self.intent_type.value if self.intent_type else None,
            "started_at": self.started_at.isoformat(),
            "message_count": self.message_count,
            "is_active": self.is_active
        }

    @staticmethod
    def close_inactive_sessions(hours=24):
        """Close sessions with no activity"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        AIConversation.query.filter(
            AIConversation.last_message_at < cutoff,
            AIConversation.is_active == True
        ).update({'is_active': False})
        db.session.commit()

class AIMessage(db.Model):
    """Individual messages within AI conversations"""
    __tablename__ = 'ai_messages'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('ai_conversations.id'), nullable=False, index=True)

    # Message content
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)

    # Metadata
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    tokens_used = db.Column(db.Integer, nullable=True)

    # Extracted entities (for context)
    extracted_entities = db.Column(JSONB, nullable=True)
    detected_intent = db.Column(db.Enum(AIIntentType), nullable=True)

    # AI feedback relationship
    feedback = db.relationship('AIFeedback', backref='message', uselist=False, cascade="all, delete")

    def as_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "detected_intent": self.detected_intent.value if self.detected_intent else None
        }

class AIActionLog(db.Model):
    """Logs AI-executed actions for auditing and rollback"""
    __tablename__ = 'ai_action_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('ai_conversations.id'), nullable=True)

    # Action details
    action_type = db.Column(db.Enum(AIIntentType), nullable=False, index=True)
    action_status = db.Column(db.Enum(AIActionStatus), default=AIActionStatus.PENDING, nullable=False, index=True)

    # What was done - Generic target tracking
    target_table = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)

    # Specific foreign keys for major entities
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True, index=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=True, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transaction.id'), nullable=True, index=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=True, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=True, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True, index=True)

    action_description = db.Column(db.Text, nullable=False)

    # Data payload
    request_data = db.Column(JSONB, nullable=True)
    executed_data = db.Column(JSONB, nullable=True)
    previous_state = db.Column(JSONB, nullable=True)

    # Results
    result_message = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    # Tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    executed_at = db.Column(db.DateTime, nullable=True)
    requires_confirmation = db.Column(db.Boolean, default=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('idx_user_action_status', 'user_id', 'action_status'),
        db.Index('idx_event_actions', 'event_id', 'action_type'),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "action_type": self.action_type.value,
            "action_status": self.action_status.value,
            "target_table": self.target_table,
            "action_description": self.action_description,
            "created_at": self.created_at.isoformat(),
            "requires_confirmation": self.requires_confirmation
        }

    @staticmethod
    def rollback_action(action_id):
        """Rollback an AI action"""
        action = AIActionLog.query.get(action_id)
        if not action or not action.previous_state:
            return {"success": False, "error": "No rollback data available"}

        try:
            # Restore previous state based on target_table
            if action.target_table == 'event' and action.event_id:
                event = Event.query.get(action.event_id)
                if event:
                    for key, value in action.previous_state.items():
                        setattr(event, key, value)

            elif action.target_table == 'ticket_type' and action.ticket_type_id:
                ticket_type = TicketType.query.get(action.ticket_type_id)
                if ticket_type:
                    for key, value in action.previous_state.items():
                        setattr(ticket_type, key, value)

            # Mark action as cancelled
            action.action_status = AIActionStatus.CANCELLED
            db.session.commit()
            return {"success": True, "message": "Action rolled back successfully"}

        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}

class AIUserPreference(db.Model):
    """Stores user preferences for AI behavior"""
    __tablename__ = 'ai_user_preferences'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)

    # Interaction preferences
    preferred_language = db.Column(db.String(10), default='en')
    verbosity_level = db.Column(db.String(20), default='balanced')

    # Feature toggles
    auto_confirm_simple_actions = db.Column(db.Boolean, default=False)
    enable_price_suggestions = db.Column(db.Boolean, default=True)
    enable_sales_insights = db.Column(db.Boolean, default=True)
    enable_proactive_alerts = db.Column(db.Boolean, default=True)

    # Notification preferences
    notify_on_low_inventory = db.Column(db.Boolean, default=True)
    notify_on_pricing_opportunities = db.Column(db.Boolean, default=True)
    notify_on_unusual_patterns = db.Column(db.Boolean, default=True)

    # Learning preferences
    save_conversation_history = db.Column(db.Boolean, default=True)
    learn_from_interactions = db.Column(db.Boolean, default=True)

    # Default settings
    default_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=True)
    default_time_zone = db.Column(db.String(50), default='Africa/Nairobi')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    default_currency = db.relationship('Currency', foreign_keys=[default_currency_id])

    def as_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "preferred_language": self.preferred_language,
            "verbosity_level": self.verbosity_level,
            "enable_price_suggestions": self.enable_price_suggestions,
            "enable_sales_insights": self.enable_sales_insights
        }

class AIAnalyticsCache(db.Model):
    """Caches expensive AI analytics computations"""
    __tablename__ = 'ai_analytics_cache'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Cache key components
    cache_key = db.Column(db.String(255), unique=True, nullable=False, index=True)
    query_type = db.Column(db.String(100), nullable=False, index=True)

    # Scope
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=True, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True, index=True)

   # Cached data
    result_data = db.Column(JSONB, nullable=False)
    meta_data = db.Column("metadata", JSONB, nullable=True)  # 👈 fixed
    data_size_kb = db.Column(db.Integer, nullable=True)
    is_compressed = db.Column(db.Boolean, default=False)

    # Cache management
    priority = db.Column(db.Enum(AICachePriority), default=AICachePriority.MEDIUM)
    hit_count = db.Column(db.Integer, default=0)
    last_accessed = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    # Expiration
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    is_valid = db.Column(db.Boolean, default=True, index=True)

    __table_args__ = (
        db.Index('idx_cache_expiry', 'is_valid', 'expires_at'),
    )

    def is_expired(self):
        return datetime.utcnow() > self.expires_at

    def increment_hit(self):
        self.hit_count += 1
        self.last_accessed = datetime.utcnow()
        db.session.commit()

    def as_dict(self):
        return {
            "id": self.id,
            "cache_key": self.cache_key,
            "query_type": self.query_type,
            "result_data": self.result_data,
            "hit_count": self.hit_count,
            "expires_at": self.expires_at.isoformat()
        }

    @staticmethod
    def cleanup_expired_cache():
        """Remove expired cache entries"""
        AIAnalyticsCache.query.filter(
            AIAnalyticsCache.expires_at < datetime.utcnow()
        ).delete()
        db.session.commit()

class AIInsight(db.Model):
    """Stores AI-generated insights and recommendations"""
    __tablename__ = 'ai_insights'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Scope
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=True, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True, index=True)

    # Insight details
    insight_type = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)

    # Data and recommendations
    insight_data = db.Column(JSONB, nullable=True)
    recommended_actions = db.Column(JSONB, nullable=True)

    # Priority and impact
    priority = db.Column(db.String(20), default='medium', index=True)
    potential_impact = db.Column(db.Text, nullable=True)
    confidence_score = db.Column(db.Float, nullable=True)

    # Status tracking
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_read = db.Column(db.Boolean, default=False)
    is_acted_upon = db.Column(db.Boolean, default=False)
    acted_upon_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)

    @validates('confidence_score')
    def validate_confidence(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError("Confidence score must be between 0 and 1")
        return value

    __table_args__ = (
        db.Index('idx_organizer_active', 'organizer_id', 'is_active'),
        db.Index('idx_event_insights', 'event_id', 'insight_type'),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "recommended_actions": self.recommended_actions,
            "confidence_score": self.confidence_score,
            "is_read": self.is_read,
            "generated_at": self.generated_at.isoformat()
        }

class AIPricingRecommendation(db.Model):
    """Stores AI pricing recommendations for ticket types"""
    __tablename__ = 'ai_pricing_recommendations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)

    # Current pricing
    current_price = db.Column(db.Numeric(10, 2), nullable=False)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.id'), nullable=False)

    # Recommendation
    recommended_price = db.Column(db.Numeric(10, 2), nullable=False)
    price_change_percentage = db.Column(db.Float, nullable=False)

    # Reasoning
    recommendation_reason = db.Column(db.Text, nullable=False)
    factors_considered = db.Column(JSONB, nullable=True)

    # Predictions
    expected_revenue_current = db.Column(db.Numeric(12, 2), nullable=True)
    expected_revenue_recommended = db.Column(db.Numeric(12, 2), nullable=True)
    confidence_level = db.Column(db.Float, nullable=True)

    # Metadata
    based_on_events_count = db.Column(db.Integer, nullable=True)
    market_average_price = db.Column(db.Numeric(10, 2), nullable=True)

    # Status
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_applied = db.Column(db.Boolean, default=False)
    applied_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)

    currency = db.relationship('Currency', foreign_keys=[currency_id])

    @validates('confidence_level')
    def validate_confidence(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError("Confidence level must be between 0 and 1")
        return value

    def as_dict(self):
        return {
            "id": self.id,
            "ticket_type_id": self.ticket_type_id,
            "current_price": float(self.current_price),
            "recommended_price": float(self.recommended_price),
            "price_change_percentage": self.price_change_percentage,
            "recommendation_reason": self.recommendation_reason,
            "confidence_level": self.confidence_level,
            "is_applied": self.is_applied,
            "created_at": self.created_at.isoformat()
        }

class AIEventSuggestion(db.Model):
    """AI-generated event suggestions for organizers"""
    __tablename__ = 'ai_event_suggestions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False, index=True)

    # Suggestion details
    suggested_event_name = db.Column(db.String(255), nullable=False)
    suggested_category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    suggested_description = db.Column(db.Text, nullable=True)

    # Timing suggestions
    suggested_date_range_start = db.Column(db.Date, nullable=True)
    suggested_date_range_end = db.Column(db.Date, nullable=True)
    suggested_cities = db.Column(JSONB, nullable=True)

    # Reasoning
    suggestion_reason = db.Column(db.Text, nullable=False)
    market_opportunity = db.Column(db.Text, nullable=True)

    # Data backing
    based_on_analysis = db.Column(JSONB, nullable=True)
    estimated_attendance = db.Column(db.Integer, nullable=True)
    estimated_revenue_potential = db.Column(db.Numeric(12, 2), nullable=True)

    # Status
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_viewed = db.Column(db.Boolean, default=False)
    is_accepted = db.Column(db.Boolean, default=False)
    created_event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    suggested_category = db.relationship('Category', foreign_keys=[suggested_category_id])

    def as_dict(self):
        return {
            "id": self.id,
            "suggested_event_name": self.suggested_event_name,
            "suggestion_reason": self.suggestion_reason,
            "estimated_attendance": self.estimated_attendance,
            "estimated_revenue_potential": float(self.estimated_revenue_potential) if self.estimated_revenue_potential else None,
            "is_viewed": self.is_viewed,
            "created_at": self.created_at.isoformat()
        }

class AIQueryTemplate(db.Model):
    """Stores common query templates for faster AI processing"""
    __tablename__ = 'ai_query_templates'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Template identification
    template_name = db.Column(db.String(100), nullable=False, unique=True)
    intent_type = db.Column(db.Enum(AIIntentType), nullable=False, index=True)

    # Template patterns (for matching user queries)
    # Format: {"keywords": ["create", "event"], "regex": ["create\\s+event"], "examples": [...]}
    patterns = db.Column(JSONB, nullable=False)

    # Execution details
    sql_template = db.Column(db.Text, nullable=True)
    api_endpoints = db.Column(JSONB, nullable=True)
    required_parameters = db.Column(JSONB, nullable=True)
    optional_parameters = db.Column(JSONB, nullable=True)

    # Response formatting
    response_template = db.Column(db.Text, nullable=True)

    # Metadata
    usage_count = db.Column(db.Integer, default=0)
    success_rate = db.Column(db.Float, default=1.0)
    average_execution_time = db.Column(db.Float, nullable=True)

    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def as_dict(self):
        return {
            "id": self.id,
            "template_name": self.template_name,
            "intent_type": self.intent_type.value,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate
        }

class AIUsageMetrics(db.Model):
    """Track AI API usage for billing/limits"""
    __tablename__ = 'ai_usage_metrics'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)

    # Usage tracking
    total_tokens = db.Column(db.Integer, default=0)
    total_requests = db.Column(db.Integer, default=0)
    total_conversations = db.Column(db.Integer, default=0)
    total_actions_executed = db.Column(db.Integer, default=0)

    # Cost tracking (optional)
    estimated_cost = db.Column(db.Numeric(10, 4), default=0.0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='uix_user_date_usage'),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "date": self.date.isoformat(),
            "total_tokens": self.total_tokens,
            "total_requests": self.total_requests,
            "total_conversations": self.total_conversations,
            "estimated_cost": float(self.estimated_cost)
        }

class AIFeedback(db.Model):
    """User feedback on AI responses for improvement"""
    __tablename__ = 'ai_feedback'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    message_id = db.Column(db.Integer, db.ForeignKey('ai_messages.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)

    # Feedback
    rating = db.Column(db.Integer, nullable=False)
    feedback_text = db.Column(db.Text, nullable=True)
    feedback_type = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @validates('rating')
    def validate_rating(self, key, value):
        if not (1 <= value <= 5):
            raise ValueError("Rating must be between 1 and 5")
        return value

    def as_dict(self):
        return {
            "id": self.id,
            "message_id": self.message_id,
            "rating": self.rating,
            "feedback_text": self.feedback_text,
            "created_at": self.created_at.isoformat()
        }

class AIRevenueAnalysis(db.Model):
    """Detailed revenue pattern analysis"""
    __tablename__ = 'ai_revenue_analysis'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True, index=True)

    # Analysis period
    analysis_period_start = db.Column(db.Date, nullable=False)
    analysis_period_end = db.Column(db.Date, nullable=False)

    # Revenue data
    total_revenue = db.Column(db.Numeric(12, 2), nullable=False)
    revenue_by_ticket_type = db.Column(JSONB, nullable=True)
    revenue_trends = db.Column(JSONB, nullable=True)
    payment_method_breakdown = db.Column(JSONB, nullable=True)

    # Insights
    insights = db.Column(JSONB, nullable=True)
    recommendations = db.Column(JSONB, nullable=True)

    # Predictions
    forecasted_revenue = db.Column(db.Numeric(12, 2), nullable=True)
    confidence_level = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @validates('confidence_level')
    def validate_confidence(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError("Confidence level must be between 0 and 1")
        return value

    __table_args__ = (
        db.Index('idx_organizer_period', 'organizer_id', 'analysis_period_start'),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "organizer_id": self.organizer_id,
            "event_id": self.event_id,
            "total_revenue": float(self.total_revenue),
            "analysis_period_start": self.analysis_period_start.isoformat(),
            "analysis_period_end": self.analysis_period_end.isoformat(),
            "forecasted_revenue": float(self.forecasted_revenue) if self.forecasted_revenue else None,
            "confidence_level": self.confidence_level
        }

class AITicketAnalysis(db.Model):
    """AI analysis of ticket sales patterns"""
    __tablename__ = 'ai_ticket_analysis'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=True, index=True)

    # Analysis type
    analysis_type = db.Column(db.String(50), nullable=False, index=True)  # 'velocity', 'demographics', 'timing', 'conversion'

    # Analysis results
    insights = db.Column(JSONB, nullable=False)
    recommendations = db.Column(JSONB, nullable=True)

    # Metrics
    sales_velocity = db.Column(db.Float, nullable=True)  # Tickets per hour/day
    projected_sellout_date = db.Column(db.DateTime, nullable=True)
    conversion_rate = db.Column(db.Float, nullable=True)
    peak_sales_hours = db.Column(JSONB, nullable=True)  # [14, 15, 20] (hours of day)

    # Predictions
    forecasted_sales = db.Column(db.Integer, nullable=True)
    confidence_level = db.Column(db.Float, nullable=True)

    analyzed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @validates('confidence_level')
    def validate_confidence(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError("Confidence level must be between 0 and 1")
        return value

    __table_args__ = (
        db.Index('idx_event_analysis_type', 'event_id', 'analysis_type'),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "ticket_type_id": self.ticket_type_id,
            "analysis_type": self.analysis_type,
            "insights": self.insights,
            "sales_velocity": self.sales_velocity,
            "projected_sellout_date": self.projected_sellout_date.isoformat() if self.projected_sellout_date else None,
            "confidence_level": self.confidence_level,
            "analyzed_at": self.analyzed_at.isoformat()

        }

# ===== AI MANAGER UTILITY CLASS =====
class AIManager:
    """Helper class for AI operations"""

    @staticmethod
    def create_conversation(user_id, session_id):
        """Create a new AI conversation session"""
        conversation = AIConversation(
            user_id=user_id,
            session_id=session_id
        )
        db.session.add(conversation)
        db.session.commit()
        return conversation

    @staticmethod
    def add_message(conversation_id, role, content, detected_intent=None, extracted_entities=None):
        """Add a message to conversation"""
        message = AIMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            detected_intent=detected_intent,
            extracted_entities=extracted_entities
        )
        db.session.add(message)

        # Update conversation
        conversation = AIConversation.query.get(conversation_id)
        conversation.message_count += 1
        conversation.last_message_at = datetime.utcnow()

        db.session.commit()
        return message

    @staticmethod
    def log_action(user_id, action_type, action_description, target_table=None, 
                   target_id=None, request_data=None, conversation_id=None, 
                   requires_confirmation=False):
        """Log an AI action"""
        action_log = AIActionLog(
            user_id=user_id,
            conversation_id=conversation_id,
            action_type=action_type,
            action_description=action_description,
            target_table=target_table,
            target_id=target_id,
            request_data=request_data,
            requires_confirmation=requires_confirmation
        )
        db.session.add(action_log)
        db.session.commit()
        return action_log

    @staticmethod
    def cache_analytics(cache_key, query_type, result_data, expires_in_hours=24, 
                       user_id=None, event_id=None, organizer_id=None, priority=AICachePriority.MEDIUM):
        """Cache expensive analytics results"""
        expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)

        existing = AIAnalyticsCache.query.filter_by(cache_key=cache_key).first()
        if existing:
            existing.result_data = result_data
            existing.expires_at = expires_at
            existing.is_valid = True
        else:
            cache = AIAnalyticsCache(
                cache_key=cache_key,
                query_type=query_type,
                result_data=result_data,
                user_id=user_id,
                event_id=event_id,
                organizer_id=organizer_id,
                priority=priority,
                expires_at=expires_at
            )
            db.session.add(cache)

        db.session.commit()
        return existing if existing else cache

    @staticmethod
    def get_cached_analytics(cache_key):
        """Retrieve cached analytics if valid"""
        cache = AIAnalyticsCache.query.filter_by(cache_key=cache_key, is_valid=True).first()

        if cache and not cache.is_expired():
            cache.increment_hit()
            return cache.result_data

        return None

    @staticmethod
    def create_insight(organizer_id, insight_type, title, description, 
                      event_id=None, recommended_actions=None, priority='medium',
                      confidence_score=None, expires_in_days=7):
        """Create an AI insight/recommendation"""
        expires_at = datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None

        insight = AIInsight(
            organizer_id=organizer_id,
            event_id=event_id,
            insight_type=insight_type,
            title=title,
            description=description,
            recommended_actions=recommended_actions,
            priority=priority,
            confidence_score=confidence_score,
            expires_at=expires_at
        )
        db.session.add(insight)
        db.session.commit()
        return insight

    @staticmethod
    def create_pricing_recommendation(ticket_type_id, event_id, recommended_price,
                                     recommendation_reason, current_price, currency_id,
                                     confidence_level=None, expires_in_days=7):
        """Create a pricing recommendation"""
        price_change = ((recommended_price - current_price) / current_price) * 100
        expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        recommendation = AIPricingRecommendation(
            ticket_type_id=ticket_type_id,
            event_id=event_id,
            current_price=current_price,
            currency_id=currency_id,
            recommended_price=recommended_price,
            price_change_percentage=price_change,
            recommendation_reason=recommendation_reason,
            confidence_level=confidence_level,
            expires_at=expires_at
        )
        db.session.add(recommendation)
        db.session.commit()
        return recommendation

    # Existing methods
    @staticmethod
    def log_error(user_id, error_type, error_message, context_data=None):
        """Track AI errors for debugging"""
        error_log = AIActionLog(
            user_id=user_id,
            action_type=AIIntentType.GENERAL_QUERY,
            action_status=AIActionStatus.FAILED,
            action_description=f"Error: {error_type}",
            error_message=error_message,
            request_data=context_data
        )
        db.session.add(error_log)
        db.session.commit()
        return error_log

    @staticmethod
    def get_user_conversations(user_id, page=1, per_page=20):
        """Get paginated user conversations"""
        return AIConversation.query.filter_by(
            user_id=user_id, is_active=True
        ).order_by(AIConversation.last_message_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )


# ===== COLLABORATION MANAGER =====
class CollaborationManager:
    """Helper class for managing event collaborations"""

    @staticmethod
    def create_partner(organizer_id, company_name, logo_url=None, website_url=None, 
                      company_description=None, contact_email=None, contact_person=None):
        partner = Partner(
            organizer_id=organizer_id,
            company_name=company_name,
            logo_url=logo_url,
            website_url=website_url,
            company_description=company_description,
            contact_email=contact_email,
            contact_person=contact_person
        )
        db.session.add(partner)
        db.session.commit()
        return partner

    @staticmethod
    def add_event_collaboration(event_id, partner_id, collaboration_type="Partner", 
                               description=None, display_order=0):
        existing = EventCollaboration.query.filter_by(
            event_id=event_id,
            partner_id=partner_id,
            is_active=True
        ).first()

        if existing:
            return {"error": "Collaboration already exists", "collaboration": existing}

        collaboration = EventCollaboration(
            event_id=event_id,
            partner_id=partner_id,
            collaboration_type=CollaborationType(collaboration_type) if isinstance(collaboration_type, str) else collaboration_type,
            description=description,
            display_order=display_order
        )

        db.session.add(collaboration)
        db.session.commit()
        return {"success": True, "collaboration": collaboration}


# ===== CURRENCY CONVERTER =====
class CurrencyConverter:
    """Helper class for currency operations"""

    @staticmethod
    def get_base_currency():
        return Currency.query.filter_by(is_base_currency=True, is_active=True).first()

    @staticmethod
    def convert_amount(amount, from_currency_id, to_currency_id):
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
    def update_exchange_rate(from_currency_id, to_currency_id, new_rate, source="API"):
        ExchangeRate.query.filter_by(
            from_currency_id=from_currency_id,
            to_currency_id=to_currency_id,
            is_active=True
        ).update({'is_active': False})

        new_exchange_rate = ExchangeRate(
            from_currency_id=from_currency_id,
            to_currency_id=to_currency_id,
            rate=Decimal(str(new_rate)),
            source=source,
            is_active=True
        )

        db.session.add(new_exchange_rate)
        db.session.commit()
        return new_exchange_rate
