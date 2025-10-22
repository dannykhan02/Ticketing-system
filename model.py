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
    
    # AI relationships - FIXED: Changed backref to back_populates to avoid conflict
    ai_insights = db.relationship('AICategoryInsight', backref='category', lazy=True, 
                                 cascade="all, delete")
    ai_actions = db.relationship('AIActionLog', backref='category', lazy=True,
                                foreign_keys='AIActionLog.category_id')
    ai_suggestions = db.relationship('AIEventSuggestion', 
                                    foreign_keys='AIEventSuggestion.suggested_category_id',
                                    back_populates='suggested_category', lazy=True)

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
    
    # AI-Enhanced Fields
    ai_description_enhanced = db.Column(db.Boolean, default=False)
    ai_partnership_score = db.Column(db.Float, nullable=True)  # 0-1 score of partnership value
    ai_recommended_collaboration_types = db.Column(JSONB, nullable=True)  # Suggested collaboration types
    ai_target_audience_overlap = db.Column(JSONB, nullable=True)  # Audience matching data
    ai_suggested_events = db.Column(JSONB, nullable=True)  # Events this partner would be good for
    
    # Partnership Performance Metrics (AI-calculated)
    performance_score = db.Column(db.Float, default=0.0)  # Overall performance score
    engagement_rate = db.Column(db.Float, nullable=True)  # Partner engagement metrics
    roi_estimate = db.Column(db.Numeric(12, 2), nullable=True)  # Estimated ROI from partnership
    
    # AI Preferences
    ai_auto_suggest_events = db.Column(db.Boolean, default=True)
    ai_smart_matching_enabled = db.Column(db.Boolean, default=True)
    
    # Status and Metadata
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_ai_analysis = db.Column(db.DateTime, nullable=True)

    # Relationships
    collaborations = db.relationship('EventCollaboration', back_populates='partner', lazy=True)
    
    # AI relationships
    ai_actions = db.relationship('AIActionLog', backref='partner', lazy=True,
                                foreign_keys='AIActionLog.partner_id')
    ai_insights = db.relationship('AIPartnerInsight', backref='partner', lazy=True, 
                                 cascade="all, delete")
    ai_match_recommendations = db.relationship('AIPartnerMatchRecommendation', 
                                              backref='partner', lazy=True,
                                              cascade="all, delete")

    @validates('ai_partnership_score', 'performance_score', 'engagement_rate')
    def validate_scores(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError(f"{key} must be between 0 and 1")
        return value

    def as_dict(self):
        return {
            "id": self.id,
            "organizer_id": self.organizer_id,
            "company_name": self.company_name,
            "logo_url": self.logo_url,
            "website_url": self.website_url,
            "total_collaborations": len([c for c in self.collaborations if c.is_active]),
            "ai_partnership_score": self.ai_partnership_score,
            "performance_score": self.performance_score,
            "ai_description_enhanced": self.ai_description_enhanced,
            "engagement_rate": self.engagement_rate
        }

    def calculate_performance_score(self):
        """AI-calculated performance based on collaboration success"""
        from sqlalchemy import func
        
        # Count successful collaborations
        successful_collabs = sum(1 for c in self.collaborations 
                                if c.is_active and c.engagement_metrics.get('success', False))
        total_collabs = len([c for c in self.collaborations if c.is_active])
        
        if total_collabs == 0:
            self.performance_score = 0.5  # Neutral score for new partners
        else:
            self.performance_score = successful_collabs / total_collabs
        
        db.session.commit()
        return self.performance_score

class EventCollaboration(db.Model):
    __tablename__ = 'event_collaborations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False)
    collaboration_type = db.Column(db.Enum(CollaborationType), 
                                  default=CollaborationType.PARTNER, nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Display Settings
    show_on_event_page = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    logo_placement = db.Column(db.String(50), default='footer')  # 'header', 'footer', 'sidebar'
    
    # AI-Enhanced Fields
    ai_suggested_collaboration = db.Column(db.Boolean, default=False)  # Was this AI-suggested?
    ai_match_score = db.Column(db.Float, nullable=True)  # How well partner matches event
    ai_value_prediction = db.Column(db.Numeric(12, 2), nullable=True)  # Predicted partnership value
    ai_audience_overlap_score = db.Column(db.Float, nullable=True)  # Audience alignment score
    ai_recommendation_reason = db.Column(db.Text, nullable=True)  # Why AI suggested this
    
    # Performance Tracking (AI-analyzed)
    engagement_metrics = db.Column(JSONB, nullable=True)  # {"clicks": 100, "conversions": 10}
    contribution_score = db.Column(db.Float, nullable=True)  # Partner's contribution to event success
    estimated_reach = db.Column(db.Integer, nullable=True)  # AI-estimated audience reach
    actual_impact = db.Column(JSONB, nullable=True)  # Actual measured impact after event
    
    # Terms and Conditions
    partnership_terms = db.Column(JSONB, nullable=True)  # Contract details, deliverables
    deliverables_status = db.Column(JSONB, nullable=True)  # Track what's been delivered
    
    # AI Insights
    ai_performance_insights = db.Column(JSONB, nullable=True)  # Post-event AI analysis
    ai_suggested_improvements = db.Column(JSONB, nullable=True)  # How to improve next time
    
    # Status and Metadata
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    status = db.Column(db.String(50), default='pending')  # 'pending', 'confirmed', 'active', 'completed'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    activated_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    event = db.relationship('Event', backref='collaborations')
    partner = db.relationship('Partner', back_populates='collaborations')
    
    # AI relationships
    ai_actions = db.relationship('AIActionLog', backref='event_collaboration', lazy=True,
                                foreign_keys='AIActionLog.collaboration_id')

    __table_args__ = (
        db.UniqueConstraint('event_id', 'partner_id', 'is_active', 
                          name='uix_active_event_collaboration'),
        db.Index('idx_collab_match_score', 'ai_match_score'),
        db.Index('idx_collab_status', 'status', 'is_active'),
    )

    @validates('ai_match_score', 'ai_audience_overlap_score', 'contribution_score')
    def validate_scores(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError(f"{key} must be between 0 and 1")
        return value

    def as_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "partner_id": self.partner_id,
            "collaboration_type": self.collaboration_type.value,
            "is_active": self.is_active,
            "status": self.status,
            "ai_suggested_collaboration": self.ai_suggested_collaboration,
            "ai_match_score": self.ai_match_score,
            "ai_value_prediction": float(self.ai_value_prediction) if self.ai_value_prediction else None,
            "engagement_metrics": self.engagement_metrics,
            "contribution_score": self.contribution_score,
            "estimated_reach": self.estimated_reach
        }

    def calculate_contribution_score(self):
        """Calculate partner's contribution to event success"""
        if not self.engagement_metrics:
            return None
        
        # Simple calculation based on engagement
        clicks = self.engagement_metrics.get('clicks', 0)
        conversions = self.engagement_metrics.get('conversions', 0)
        social_reach = self.engagement_metrics.get('social_reach', 0)
        
        # Normalize and weight factors
        score = (
            min(clicks / 1000, 1) * 0.4 +  # Max 1000 clicks = full points
            min(conversions / 50, 1) * 0.4 +  # Max 50 conversions = full points
            min(social_reach / 10000, 1) * 0.2  # Max 10k reach = full points
        )
        
        self.contribution_score = round(score, 3)
        db.session.commit()
        return self.contribution_score

class AIPartnerInsight(db.Model):
    """AI-generated insights about partners"""
    __tablename__ = 'ai_partner_insights'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False, index=True)
    
    # Insight details
    insight_type = db.Column(db.String(50), nullable=False, index=True)
    # Types: 'performance_analysis', 'opportunity_identification', 'risk_assessment', 
    #        'optimization_suggestion', 'trend_analysis'
    
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    
    # Analysis data
    insight_data = db.Column(JSONB, nullable=True)
    # Example: {"avg_engagement": 0.75, "best_collaboration_type": "Media Partner"}
    
    recommended_actions = db.Column(JSONB, nullable=True)
    # Example: [{"action": "increase_visibility", "reason": "High performing partner"}]
    
    # Metrics
    confidence_score = db.Column(db.Float, nullable=True)
    priority = db.Column(db.String(20), default='medium', index=True)  # 'low', 'medium', 'high', 'critical'
    potential_value_increase = db.Column(db.Numeric(12, 2), nullable=True)
    
    # Status
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_read = db.Column(db.Boolean, default=False)
    is_acted_upon = db.Column(db.Boolean, default=False)
    
    # Timestamps
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    acted_upon_at = db.Column(db.DateTime, nullable=True)
    
    @validates('confidence_score')
    def validate_confidence(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError("Confidence score must be between 0 and 1")
        return value
    
    __table_args__ = (
        db.Index('idx_partner_active_insights', 'partner_id', 'is_active'),
    )
    
    def as_dict(self):
        return {
            "id": self.id,
            "partner_id": self.partner_id,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "insight_data": self.insight_data,
            "recommended_actions": self.recommended_actions,
            "confidence_score": self.confidence_score,
            "priority": self.priority,
            "potential_value_increase": float(self.potential_value_increase) if self.potential_value_increase else None,
            "is_read": self.is_read,
            "generated_at": self.generated_at.isoformat()
        }

class AIPartnerMatchRecommendation(db.Model):
    """AI recommendations for partner-event matching"""
    __tablename__ = 'ai_partner_match_recommendations'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False, index=True)
    
    # Matching details
    match_score = db.Column(db.Float, nullable=False)  # 0-1 score
    suggested_collaboration_type = db.Column(db.Enum(CollaborationType), nullable=False)
    
    # Reasoning
    match_reason = db.Column(db.Text, nullable=False)
    matching_factors = db.Column(JSONB, nullable=True)
    # Example: {
    #   "audience_overlap": 0.85,
    #   "category_match": true,
    #   "past_success_rate": 0.90,
    #   "geographic_alignment": 0.75
    # }
    
    # Value predictions
    predicted_value = db.Column(db.Numeric(12, 2), nullable=True)
    predicted_reach = db.Column(db.Integer, nullable=True)
    predicted_engagement = db.Column(db.Float, nullable=True)
    confidence_level = db.Column(db.Float, nullable=True)
    
    # Suggested terms
    suggested_terms = db.Column(JSONB, nullable=True)
    # Example: {
    #   "deliverables": ["social_media_posts", "logo_placement"],
    #   "expected_reach": 5000,
    #   "duration": "30_days"
    # }
    
    # Status
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_viewed = db.Column(db.Boolean, default=False)
    is_accepted = db.Column(db.Boolean, default=False)
    is_rejected = db.Column(db.Boolean, default=False)
    
    created_collaboration_id = db.Column(db.Integer, 
                                        db.ForeignKey('event_collaborations.id'), 
                                        nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    viewed_at = db.Column(db.DateTime, nullable=True)
    responded_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    
    # Relationships
    organizer = db.relationship('Organizer', backref='partner_recommendations')
    event = db.relationship('Event', backref='partner_recommendations')
    created_collaboration = db.relationship('EventCollaboration', 
                                           foreign_keys=[created_collaboration_id])
    
    @validates('match_score', 'predicted_engagement', 'confidence_level')
    def validate_scores(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError(f"{key} must be between 0 and 1")
        return value
    
    __table_args__ = (
        db.Index('idx_organizer_active_recs', 'organizer_id', 'is_active'),
        db.Index('idx_event_match_score', 'event_id', 'match_score'),
    )
    
    def as_dict(self):
        return {
            "id": self.id,
            "partner_id": self.partner_id,
            "event_id": self.event_id,
            "match_score": self.match_score,
            "suggested_collaboration_type": self.suggested_collaboration_type.value,
            "match_reason": self.match_reason,
            "matching_factors": self.matching_factors,
            "predicted_value": float(self.predicted_value) if self.predicted_value else None,
            "predicted_reach": self.predicted_reach,
            "confidence_level": self.confidence_level,
            "is_viewed": self.is_viewed,
            "is_accepted": self.is_accepted,
            "created_at": self.created_at.isoformat()
        }

# ===== ENHANCED COLLABORATION MANAGER WITH AI =====
class CollaborationManager:
    """Enhanced helper class for managing event collaborations with AI features"""

    @staticmethod
    def create_partner(organizer_id, company_name, logo_url=None, website_url=None, 
                      company_description=None, contact_email=None, contact_person=None,
                      enable_ai_features=True):
        """Create a new partner with optional AI features"""
        partner = Partner(
            organizer_id=organizer_id,
            company_name=company_name,
            logo_url=logo_url,
            website_url=website_url,
            company_description=company_description,
            contact_email=contact_email,
            contact_person=contact_person,
            ai_auto_suggest_events=enable_ai_features,
            ai_smart_matching_enabled=enable_ai_features
        )
        db.session.add(partner)
        db.session.commit()
        
        # Trigger AI analysis if enabled
        if enable_ai_features:
            CollaborationManager.analyze_partner_with_ai(partner.id)
        
        return partner

    @staticmethod
    def add_event_collaboration(event_id, partner_id, collaboration_type="Partner", 
                               description=None, display_order=0, ai_suggested=False,
                               match_score=None):
        """Add event collaboration with AI tracking"""
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
            display_order=display_order,
            ai_suggested_collaboration=ai_suggested,
            ai_match_score=match_score,
            status='confirmed' if not ai_suggested else 'pending'
        )

        db.session.add(collaboration)
        db.session.commit()
        
        # Log AI action if AI-suggested
        if ai_suggested:
            AIManager.log_action(
                user_id=Event.query.get(event_id).organizer.user_id,
                action_type=AIIntentType.MANAGE_PARTNERS,
                action_description=f"AI suggested collaboration between event {event_id} and partner {partner_id}",
                target_table='event_collaborations',
                target_id=collaboration.id
            )
        
        return {"success": True, "collaboration": collaboration}

    @staticmethod
    def analyze_partner_with_ai(partner_id):
        """Run AI analysis on a partner"""
        partner = Partner.query.get(partner_id)
        if not partner:
            return None
        
        # Calculate partnership score based on historical performance
        total_collabs = len([c for c in partner.collaborations if c.is_active])
        successful_collabs = len([c for c in partner.collaborations 
                                 if c.is_active and c.contribution_score and c.contribution_score > 0.5])
        
        if total_collabs > 0:
            partner.ai_partnership_score = successful_collabs / total_collabs
        else:
            partner.ai_partnership_score = 0.5  # Neutral for new partners
        
        partner.last_ai_analysis = datetime.utcnow()
        db.session.commit()
        
        return partner

    @staticmethod
    def generate_partner_recommendations(event_id, limit=5):
        """Generate AI partner recommendations for an event"""
        event = Event.query.get(event_id)
        if not event:
            return []
        
        # Get all active partners for the organizer
        partners = Partner.query.filter_by(
            organizer_id=event.organizer_id,
            is_active=True
        ).all()
        
        recommendations = []
        expires_at = datetime.utcnow() + timedelta(days=30)
        
        for partner in partners:
            # Skip if already collaborating
            existing = EventCollaboration.query.filter_by(
                event_id=event_id,
                partner_id=partner.id,
                is_active=True
            ).first()
            
            if existing:
                continue
            
            # Calculate match score (simplified - can be enhanced with ML)
            match_score = partner.ai_partnership_score or 0.5
            
            # Create recommendation
            recommendation = AIPartnerMatchRecommendation(
                partner_id=partner.id,
                event_id=event_id,
                organizer_id=event.organizer_id,
                match_score=match_score,
                suggested_collaboration_type=CollaborationType.PARTNER,
                match_reason=f"Partner has {match_score*100:.0f}% success rate with similar events",
                confidence_level=match_score,
                expires_at=expires_at
            )
            
            recommendations.append(recommendation)
        
        # Sort by match score and limit
        recommendations.sort(key=lambda x: x.match_score, reverse=True)
        recommendations = recommendations[:limit]
        
        # Save to database
        for rec in recommendations:
            db.session.add(rec)
        db.session.commit()
        
        return recommendations

    @staticmethod
    def track_collaboration_performance(collaboration_id, engagement_data):
        """Track and analyze collaboration performance"""
        collaboration = EventCollaboration.query.get(collaboration_id)
        if not collaboration:
            return None
        
        # Update engagement metrics
        collaboration.engagement_metrics = engagement_data
        
        # Calculate contribution score
        collaboration.calculate_contribution_score()
        
        # Generate AI insights
        if collaboration.contribution_score:
            insight_title = "Collaboration Performance Analysis"
            
            if collaboration.contribution_score > 0.7:
                insight_desc = f"Excellent performance! This partnership is driving significant value."
                priority = 'high'
            elif collaboration.contribution_score > 0.4:
                insight_desc = f"Good performance with room for optimization."
                priority = 'medium'
            else:
                insight_desc = f"Underperforming partnership. Consider reviewing terms or strategy."
                priority = 'high'
            
            insight = AIPartnerInsight(
                partner_id=collaboration.partner_id,
                insight_type='performance_analysis',
                title=insight_title,
                description=insight_desc,
                insight_data={
                    'collaboration_id': collaboration_id,
                    'contribution_score': collaboration.contribution_score,
                    'engagement_metrics': engagement_data
                },
                confidence_score=0.85,
                priority=priority
            )
            
            db.session.add(insight)
        
        db.session.commit()
        return collaboration

# ===== AI EVENT ASSISTANCE MODELS =====
class AIEventDraft(db.Model):
    """Stores AI-assisted event drafts during creation/editing"""
    __tablename__ = 'ai_event_drafts'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('ai_conversations.id'), nullable=True)
    
    # Draft status
    draft_status = db.Column(db.String(20), default='in_progress', index=True)
    # 'in_progress', 'ready_for_review', 'approved', 'rejected', 'published'
    
    # Event fields (AI-suggested or user-provided)
    suggested_name = db.Column(db.Text, nullable=True)
    name_confidence = db.Column(db.Float, nullable=True)
    name_source = db.Column(db.String(20), default='ai')  # 'ai', 'user', 'hybrid'
    
    suggested_description = db.Column(db.Text, nullable=True)
    description_confidence = db.Column(db.Float, nullable=True)
    description_source = db.Column(db.String(20), default='ai')
    
    suggested_city = db.Column(db.String(100), nullable=True)
    city_confidence = db.Column(db.Float, nullable=True)
    city_source = db.Column(db.String(20), default='user')
    
    suggested_location = db.Column(db.Text, nullable=True)
    location_confidence = db.Column(db.Float, nullable=True)
    location_source = db.Column(db.String(20), default='user')
    
    suggested_amenities = db.Column(JSONB, nullable=True)
    # Format: [{"name": "Parking", "confidence": 0.9, "source": "ai", "reason": "Large venue"}]
    
    suggested_date = db.Column(db.Date, nullable=True)
    date_confidence = db.Column(db.Float, nullable=True)
    date_source = db.Column(db.String(20), default='user')
    
    suggested_start_time = db.Column(db.Time, nullable=True)
    start_time_confidence = db.Column(db.Float, nullable=True)
    start_time_source = db.Column(db.String(20), default='user')
    
    suggested_end_time = db.Column(db.Time, nullable=True)
    end_time_confidence = db.Column(db.Float, nullable=True)
    end_time_source = db.Column(db.String(20), default='user')
    
    suggested_category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    category_confidence = db.Column(db.Float, nullable=True)
    category_source = db.Column(db.String(20), default='ai')
    
    suggested_image_url = db.Column(db.String(255), nullable=True)
    image_source = db.Column(db.String(20), default='user')
    
    # AI reasoning and alternatives
    ai_reasoning = db.Column(JSONB, nullable=True)
    # Format: {
    #   "name_reasoning": "Based on description and category",
    #   "amenities_reasoning": "Standard amenities for concerts",
    #   "alternatives": {...}
    # }
    
    alternative_suggestions = db.Column(JSONB, nullable=True)
    # Format: {
    #   "names": ["Alt Name 1", "Alt Name 2"],
    #   "dates": ["2025-12-01", "2025-12-15"],
    #   "amenities": [["WiFi", "Catering"], ["Parking", "Security"]]
    # }
    
    # User interaction tracking
    user_edits = db.Column(JSONB, nullable=True)
    # Track what fields user modified vs accepted AI suggestions
    
    user_feedback = db.Column(db.Text, nullable=True)
    ai_iterations = db.Column(db.Integer, default=0)  # How many AI refinements
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_event_id = db.Column(db.Integer, nullable=True)  # No FK - breaks circular dependency
    
    # Relationships
    organizer = db.relationship('Organizer', backref='event_drafts')
    suggested_category = db.relationship('Category', foreign_keys=[suggested_category_id])
    # Note: published_event relationship is accessed via Event.created_from_draft backref
    
    __table_args__ = (
        db.Index('idx_organizer_status', 'organizer_id', 'draft_status'),
    )
    
    @validates('name_confidence', 'description_confidence', 'city_confidence', 
               'location_confidence', 'date_confidence', 'start_time_confidence',
               'end_time_confidence', 'category_confidence')
    def validate_confidence(self, key, value):
        if value is not None and not (0 <= value <= 1):
            raise ValueError(f"{key} must be between 0 and 1")
        return value
    
    def as_dict(self):
        return {
            "id": self.id,
            "organizer_id": self.organizer_id,
            "draft_status": self.draft_status,
            "suggested_name": self.suggested_name,
            "name_confidence": self.name_confidence,
            "name_source": self.name_source,
            "suggested_description": self.suggested_description,
            "description_confidence": self.description_confidence,
            "description_source": self.description_source,
            "suggested_city": self.suggested_city,
            "suggested_location": self.suggested_location,
            "suggested_amenities": self.suggested_amenities,
            "suggested_date": self.suggested_date.isoformat() if self.suggested_date else None,
            "suggested_start_time": self.suggested_start_time.isoformat() if self.suggested_start_time else None,
            "suggested_end_time": self.suggested_end_time.isoformat() if self.suggested_end_time else None,
            "suggested_category_id": self.suggested_category_id,
            "category_confidence": self.category_confidence,
            "ai_reasoning": self.ai_reasoning,
            "alternative_suggestions": self.alternative_suggestions,
            "ai_iterations": self.ai_iterations,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


class AIEventAssistanceLog(db.Model):
    """Tracks AI assistance provided during event creation/updates"""
    __tablename__ = 'ai_event_assistance_logs'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True, index=True)
    draft_id = db.Column(db.Integer, db.ForeignKey('ai_event_drafts.id'), nullable=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False)
    
    # Assistance type
    assistance_type = db.Column(db.String(50), nullable=False, index=True)
    # Types: 'name_generation', 'description_enhancement', 'amenity_suggestion',
    #        'time_optimization', 'category_classification', 'full_creation'
    
    # Input from user
    user_input = db.Column(JSONB, nullable=True)
    # What the organizer provided
    
    # AI output
    ai_suggestions = db.Column(JSONB, nullable=False)
    # What AI suggested
    
    # User decision
    user_accepted = db.Column(db.Boolean, nullable=True)
    user_modified = db.Column(db.Boolean, nullable=True)
    final_value = db.Column(JSONB, nullable=True)
    # What was actually used
    
    # Quality metrics
    confidence_score = db.Column(db.Float, nullable=True)
    processing_time_ms = db.Column(db.Integer, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    event = db.relationship('Event', backref='ai_assistance_logs')
    draft = db.relationship('AIEventDraft', backref='assistance_logs')
    
    def as_dict(self):
        return {
            "id": self.id,
            "assistance_type": self.assistance_type,
            "user_input": self.user_input,
            "ai_suggestions": self.ai_suggestions,
            "user_accepted": self.user_accepted,
            "user_modified": self.user_modified,
            "final_value": self.final_value,
            "confidence_score": self.confidence_score,
            "processing_time_ms": self.processing_time_ms,
            "created_at": self.created_at.isoformat()
        }


# ===== EVENT MODEL WITH AI ASSISTANCE =====
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
    
    # AI Copilot - Creation/Update Tracking
    ai_assisted_creation = db.Column(db.Boolean, default=False)
    ai_generated_fields = db.Column(JSONB, nullable=True)
    # Format: ["name", "description", "amenities"] - which fields were AI-generated
    
    ai_confidence_score = db.Column(db.Float, nullable=True)
    # Overall confidence in AI-generated content (0.0 - 1.0)
    
    created_from_draft_id = db.Column(db.Integer, 
                                     db.ForeignKey('ai_event_drafts.id'), 
                                     nullable=True)
    
    # Original user input (for learning and improvement)
    original_user_input = db.Column(JSONB, nullable=True)
    # What organizer initially provided before AI enhancement
    
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
    
    # AI Copilot relationship (one-way to avoid circular dependency)
    created_from_draft = db.relationship('AIEventDraft',
                                        foreign_keys=[created_from_draft_id],
                                        backref='published_events')

    def __init__(self, name, description, date, start_time, end_time, city, location, 
                 amenities, image, organizer_id, category_id, 
                 ai_assisted_creation=False, created_from_draft_id=None):
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
        self.ai_assisted_creation = ai_assisted_creation
        self.created_from_draft_id = created_from_draft_id
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
            "category": self.event_category.name if self.event_category else None,
            "ai_assisted_creation": self.ai_assisted_creation,
            "ai_generated_fields": self.ai_generated_fields,
            "ai_confidence_score": self.ai_confidence_score,
            "created_from_draft_id": self.created_from_draft_id
        }


# ===== AI EVENT MANAGER =====
class AIEventManager:
    """Manager for AI-assisted event creation and updates"""
    
    @staticmethod
    def create_draft_from_conversation(organizer_id, user_input, conversation_id=None):
        """
        Create an event draft from conversational input
        
        Args:
            organizer_id: ID of the organizer
            user_input: Dict containing user's input like:
                {
                    "raw_text": "I want to create a tech conference...",
                    "name": "optional explicit name",
                    "city": "Nairobi",
                    "date": "2025-12-01",
                    etc.
                }
            conversation_id: Optional conversation ID for context
        """
        draft = AIEventDraft(
            organizer_id=organizer_id,
            conversation_id=conversation_id,
            draft_status='in_progress'
        )
        
        # Process user input and generate AI suggestions
        # This is where you'd call your AI model/service
        
        # Example: Extract from user input
        if 'name' in user_input:
            draft.suggested_name = user_input['name']
            draft.name_source = 'user'
            draft.name_confidence = 1.0
        
        if 'city' in user_input:
            draft.suggested_city = user_input['city']
            draft.city_source = 'user'
            draft.city_confidence = 1.0
        
        if 'location' in user_input:
            draft.suggested_location = user_input['location']
            draft.location_source = 'user'
            draft.location_confidence = 1.0
        
        if 'date' in user_input:
            draft.suggested_date = user_input['date']
            draft.date_source = 'user'
            draft.date_confidence = 1.0
        
        if 'start_time' in user_input:
            draft.suggested_start_time = user_input['start_time']
            draft.start_time_source = 'user'
            draft.start_time_confidence = 1.0
        
        if 'end_time' in user_input:
            draft.suggested_end_time = user_input['end_time']
            draft.end_time_source = 'user'
            draft.end_time_confidence = 1.0
        
        db.session.add(draft)
        db.session.commit()
        
        return draft
    
    @staticmethod
    def generate_event_name(description, category=None):
        """
        Generate event name suggestions based on description
        This would integrate with your AI model
        """
        # Placeholder for AI integration
        # In reality, you'd call Claude/GPT here
        
        suggestions = {
            "primary": "AI-Generated Event Name",
            "alternatives": [
                "Alternative Name 1",
                "Alternative Name 2",
                "Alternative Name 3"
            ],
            "confidence": 0.85,
            "reasoning": "Based on description keywords and category"
        }
        
        return suggestions
    
    @staticmethod
    def enhance_description(draft_description, event_name=None, category=None):
        """
        Enhance/expand event description using AI
        """
        # Placeholder for AI enhancement
        enhanced = {
            "enhanced_text": f"{draft_description}\n\n[AI Enhanced Content]",
            "confidence": 0.9,
            "improvements": ["Added context", "Improved clarity", "SEO optimization"]
        }
        
        return enhanced
    
    @staticmethod
    def suggest_amenities(event_name=None, description=None, category=None, 
                         location=None, user_provided_amenities=None):
        """
        Suggest appropriate amenities based on event details
        """
        suggested = []
        
        # AI logic would go here
        # For now, simple rule-based suggestions
        
        base_amenities = ["Parking", "WiFi", "Security"]
        
        if category:
            category_name = Category.query.get(category).name if isinstance(category, int) else category
            if "conference" in category_name.lower() or "tech" in category_name.lower():
                base_amenities.extend(["Projector", "Microphone", "Catering"])
            elif "concert" in category_name.lower() or "music" in category_name.lower():
                base_amenities.extend(["Sound System", "Stage", "Lighting"])
        
        # Format with confidence scores
        for amenity in base_amenities[:5]:  # Max 5
            suggested.append({
                "name": amenity,
                "confidence": 0.8,
                "source": "ai",
                "reason": f"Standard for this type of event"
            })
        
        # Merge with user-provided amenities
        if user_provided_amenities:
            for amenity in user_provided_amenities:
                suggested.append({
                    "name": amenity,
                    "confidence": 1.0,
                    "source": "user",
                    "reason": "User specified"
                })
        
        return suggested[:5]  # Return max 5
    
    @staticmethod
    def classify_category(event_name, description):
        """
        Auto-classify event category based on name and description
        """
        # AI classification would go here
        # Simple keyword matching for now
        
        keywords_map = {
            "tech": ["technology", "tech", "software", "coding", "developer"],
            "music": ["concert", "music", "festival", "band", "performance"],
            "sports": ["sports", "tournament", "match", "game", "athletic"],
            "business": ["conference", "summit", "networking", "business"],
        }
        
        text = f"{event_name} {description}".lower()
        
        for category_type, keywords in keywords_map.items():
            if any(keyword in text for keyword in keywords):
                category = Category.query.filter(
                    Category.name.ilike(f"%{category_type}%")
                ).first()
                
                if category:
                    return {
                        "category_id": category.id,
                        "category_name": category.name,
                        "confidence": 0.75,
                        "reasoning": f"Detected keywords: {', '.join([k for k in keywords if k in text])}"
                    }
        
        return None
    
    @staticmethod
    def update_draft_with_ai(draft_id, field_name, user_value=None, regenerate=False):
        """
        Update a specific field in the draft with AI assistance
        
        Args:
            draft_id: Draft ID
            field_name: Field to update ('name', 'description', 'amenities', etc.)
            user_value: Optional user-provided value
            regenerate: Whether to regenerate AI suggestion
        """
        draft = AIEventDraft.query.get(draft_id)
        if not draft:
            return None
        
        # Log the assistance
        assistance_log = AIEventAssistanceLog(
            draft_id=draft_id,
            organizer_id=draft.organizer_id,
            assistance_type=f"{field_name}_{'regeneration' if regenerate else 'update'}",
            ai_suggestions={}  # Will be populated below
        )
        
        if field_name == 'name':
            if user_value:
                draft.suggested_name = user_value
                draft.name_source = 'user'
                draft.name_confidence = 1.0
                assistance_log.user_input = {"value": user_value}
                assistance_log.user_accepted = True
                assistance_log.ai_suggestions = {"accepted_user_input": True}
            elif regenerate:
                suggestions = AIEventManager.generate_event_name(
                    draft.suggested_description,
                    draft.suggested_category_id
                )
                draft.suggested_name = suggestions['primary']
                draft.name_confidence = suggestions['confidence']
                draft.name_source = 'ai'
                assistance_log.ai_suggestions = suggestions
        
        elif field_name == 'description':
            if user_value:
                draft.suggested_description = user_value
                draft.description_source = 'user'
                draft.description_confidence = 1.0
                assistance_log.user_input = {"value": user_value}
                assistance_log.user_accepted = True
                assistance_log.ai_suggestions = {"accepted_user_input": True}
            elif regenerate or not draft.suggested_description:
                enhanced = AIEventManager.enhance_description(
                    draft.suggested_description or user_value,
                    draft.suggested_name,
                    draft.suggested_category_id
                )
                draft.suggested_description = enhanced['enhanced_text']
                draft.description_confidence = enhanced['confidence']
                draft.description_source = 'ai'
                assistance_log.ai_suggestions = enhanced
        
        elif field_name == 'amenities':
            suggestions = AIEventManager.suggest_amenities(
                draft.suggested_name,
                draft.suggested_description,
                draft.suggested_category_id,
                draft.suggested_location,
                user_value
            )
            draft.suggested_amenities = suggestions
            assistance_log.ai_suggestions = {"amenities": suggestions}
        
        elif field_name == 'category':
            if user_value:
                draft.suggested_category_id = user_value
                draft.category_source = 'user'
                draft.category_confidence = 1.0
                assistance_log.user_input = {"value": user_value}
                assistance_log.user_accepted = True
                assistance_log.ai_suggestions = {"accepted_user_input": True}
            elif regenerate:
                classification = AIEventManager.classify_category(
                    draft.suggested_name or "",
                    draft.suggested_description or ""
                )
                if classification:
                    draft.suggested_category_id = classification['category_id']
                    draft.category_confidence = classification['confidence']
                    draft.category_source = 'ai'
                    assistance_log.ai_suggestions = classification
        
        draft.ai_iterations += 1
        draft.updated_at = datetime.utcnow()
        
        db.session.add(assistance_log)
        db.session.commit()
        
        return draft
    
    @staticmethod
    def publish_draft(draft_id):
        """
        Convert a draft to an actual Event
        """
        draft = AIEventDraft.query.get(draft_id)
        if not draft or draft.draft_status == 'published':
            return None
        
        # Validate required fields
        if not all([draft.suggested_name, draft.suggested_description, 
                   draft.suggested_date, draft.suggested_start_time,
                   draft.suggested_city, draft.suggested_location]):
            raise ValueError("Missing required fields for event creation")
        
        # Extract amenity names
        amenities = []
        if draft.suggested_amenities:
            amenities = [a['name'] for a in draft.suggested_amenities if isinstance(a, dict)]
        
        # Create the event
        event = Event(
            name=draft.suggested_name,
            description=draft.suggested_description,
            date=draft.suggested_date,
            start_time=draft.suggested_start_time,
            end_time=draft.suggested_end_time,
            city=draft.suggested_city,
            location=draft.suggested_location,
            amenities=amenities,
            image=draft.suggested_image_url,
            organizer_id=draft.organizer_id,
            category_id=draft.suggested_category_id,
            ai_assisted_creation=True,
            created_from_draft_id=draft_id
        )
        
        # Track which fields were AI-generated
        ai_fields = []
        if draft.name_source == 'ai':
            ai_fields.append('name')
        if draft.description_source == 'ai':
            ai_fields.append('description')
        if draft.category_source == 'ai':
            ai_fields.append('category')
        if any(a.get('source') == 'ai' for a in (draft.suggested_amenities or [])):
            ai_fields.append('amenities')
        
        event.ai_generated_fields = ai_fields
        
        # Calculate overall confidence
        confidences = [c for c in [
            draft.name_confidence,
            draft.description_confidence,
            draft.category_confidence
        ] if c is not None]
        
        if confidences:
            event.ai_confidence_score = sum(confidences) / len(confidences)
        
        # Store original user input
        event.original_user_input = {
            "name": draft.suggested_name if draft.name_source == 'user' else None,
            "description": draft.suggested_description if draft.description_source == 'user' else None,
            "city": draft.suggested_city,
            "location": draft.suggested_location,
            "date": draft.suggested_date.isoformat() if draft.suggested_date else None
        }
        
        # Update draft status
        draft.draft_status = 'published'
        draft.published_event_id = event.id
        
        db.session.add(event)
        db.session.flush()  # Get event.id before commit
        
        # Update draft with published event ID
        draft.published_event_id = event.id
        
        db.session.commit()
        
        # Log the action
        AIManager.log_action(
            user_id=draft.organizer.user_id,
            action_type=AIIntentType.CREATE_EVENT,
            action_description=f"Published AI-assisted event: {event.name}",
            target_table='event',
            target_id=event.id,
            request_data=draft.as_dict()
        )
        
        return event
    
    @staticmethod
    def get_organizer_drafts(organizer_id, status=None):
        """Get all drafts for an organizer"""
        query = AIEventDraft.query.filter_by(organizer_id=organizer_id)
        
        if status:
            query = query.filter_by(draft_status=status)
        
        return query.order_by(AIEventDraft.updated_at.desc()).all()

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
    collaboration_id = db.Column(db.Integer, db.ForeignKey('event_collaborations.id'), 
                            nullable=True, index=True)

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