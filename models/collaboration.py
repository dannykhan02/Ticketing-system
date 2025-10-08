# """Event Collaboration model for managing partner-event relationships"""

# from datetime import datetime
# from sqlalchemy.orm import validates
# from sqlalchemy.dialects.postgresql import JSONB

# from models.base import db
# from models.enums import CollaborationType


# class EventCollaboration(db.Model):
#     """Model for tracking partnerships between events and partners"""
#     __tablename__ = 'event_collaborations'

#     id = db.Column(db.Integer, primary_key=True, autoincrement=True)
#     event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
#     partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False)
#     collaboration_type = db.Column(db.Enum(CollaborationType), 
#                                   default=CollaborationType.PARTNER, nullable=False)
#     description = db.Column(db.Text, nullable=True)
    
#     # Display Settings
#     show_on_event_page = db.Column(db.Boolean, default=True, nullable=False)
#     display_order = db.Column(db.Integer, default=0, nullable=False)
#     logo_placement = db.Column(db.String(50), default='footer')  # 'header', 'footer', 'sidebar'
    
#     # AI-Enhanced Fields
#     ai_suggested_collaboration = db.Column(db.Boolean, default=False)  # Was this AI-suggested?
#     ai_match_score = db.Column(db.Float, nullable=True)  # How well partner matches event
#     ai_value_prediction = db.Column(db.Numeric(12, 2), nullable=True)  # Predicted partnership value
#     ai_audience_overlap_score = db.Column(db.Float, nullable=True)  # Audience alignment score
#     ai_recommendation_reason = db.Column(db.Text, nullable=True)  # Why AI suggested this
    
#     # Performance Tracking (AI-analyzed)
#     engagement_metrics = db.Column(JSONB, nullable=True)  # {"clicks": 100, "conversions": 10}
#     contribution_score = db.Column(db.Float, nullable=True)  # Partner's contribution to event success
#     estimated_reach = db.Column(db.Integer, nullable=True)  # AI-estimated audience reach
#     actual_impact = db.Column(JSONB, nullable=True)  # Actual measured impact after event
    
#     # Terms and Conditions
#     partnership_terms = db.Column(JSONB, nullable=True)  # Contract details, deliverables
#     deliverables_status = db.Column(JSONB, nullable=True)  # Track what's been delivered
    
#     # AI Insights
#     ai_performance_insights = db.Column(JSONB, nullable=True)  # Post-event AI analysis
#     ai_suggested_improvements = db.Column(JSONB, nullable=True)  # How to improve next time
    
#     # Status and Metadata
#     is_active = db.Column(db.Boolean, default=True, nullable=False)
#     status = db.Column(db.String(50), default='pending')  # 'pending', 'confirmed', 'active', 'completed'
#     created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
#     updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
#     activated_at = db.Column(db.DateTime, nullable=True)
#     completed_at = db.Column(db.DateTime, nullable=True)

#     # Relationships
#     event = db.relationship('Event', backref='collaborations')
#     partner = db.relationship('Partner', back_populates='collaborations')
    
#     # AI relationships
#     ai_actions = db.relationship('AIActionLog', backref='event_collaboration', lazy=True,
#                                 foreign_keys='AIActionLog.collaboration_id')

#     __table_args__ = (
#         db.UniqueConstraint('event_id', 'partner_id', 'is_active', 
#                           name='uix_active_event_collaboration'),
#         db.Index('idx_collab_match_score', 'ai_match_score'),
#         db.Index('idx_collab_status', 'status', 'is_active'),
#     )

#     @validates('ai_match_score', 'ai_audience_overlap_score', 'contribution_score')
#     def validate_scores(self, key, value):
#         """Validate that scores are between 0 and 1"""
#         if value is not None and not (0 <= value <= 1):
#             raise ValueError(f"{key} must be between 0 and 1")
#         return value

#     def as_dict(self):
#         """Convert collaboration to dictionary representation"""
#         return {
#             "id": self.id,
#             "event_id": self.event_id,
#             "partner_id": self.partner_id,
#             "collaboration_type": self.collaboration_type.value,
#             "is_active": self.is_active,
#             "status": self.status,
#             "ai_suggested_collaboration": self.ai_suggested_collaboration,
#             "ai_match_score": self.ai_match_score,
#             "ai_value_prediction": float(self.ai_value_prediction) if self.ai_value_prediction else None,
#             "engagement_metrics": self.engagement_metrics,
#             "contribution_score": self.contribution_score,
#             "estimated_reach": self.estimated_reach
#         }

#     def calculate_contribution_score(self):
#         """Calculate partner's contribution to event success"""
#         if not self.engagement_metrics:
#             return None
        
#         # Simple calculation based on engagement
#         clicks = self.engagement_metrics.get('clicks', 0)
#         conversions = self.engagement_metrics.get('conversions', 0)
#         social_reach = self.engagement_metrics.get('social_reach', 0)
        
#         # Normalize and weight factors
#         score = (
#             min(clicks / 1000, 1) * 0.4 +  # Max 1000 clicks = full points
#             min(conversions / 50, 1) * 0.4 +  # Max 50 conversions = full points
#             min(social_reach / 10000, 1) * 0.2  # Max 10k reach = full points
#         )
        
#         self.contribution_score = round(score, 3)
#         db.session.commit()
#         return self.contribution_score

#     def __repr__(self):
#         return f"<EventCollaboration {self.id}: Event {self.event_id} + Partner {self.partner_id}>"