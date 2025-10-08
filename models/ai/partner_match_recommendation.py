# """AI recommendations for partner-event matching"""

# from datetime import datetime
# from sqlalchemy.orm import validates
# from sqlalchemy.dialects.postgresql import JSONB

# from models.base import db
# from models.enums import CollaborationType


# class AIPartnerMatchRecommendation(db.Model):
#     """AI recommendations for partner-event matching"""
#     __tablename__ = 'ai_partner_match_recommendations'
    
#     id = db.Column(db.Integer, primary_key=True, autoincrement=True)
#     partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False, index=True)
#     event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False, index=True)
#     organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False, index=True)
    
#     # Matching details
#     match_score = db.Column(db.Float, nullable=False)  # 0-1 score
#     suggested_collaboration_type = db.Column(db.Enum(CollaborationType), nullable=False)
    
#     # Reasoning
#     match_reason = db.Column(db.Text, nullable=False)
#     matching_factors = db.Column(JSONB, nullable=True)
#     # Example: {
#     #   "audience_overlap": 0.85,
#     #   "category_match": true,
#     #   "past_success_rate": 0.90,
#     #   "geographic_alignment": 0.75
#     # }
    
#     # Value predictions
#     predicted_value = db.Column(db.Numeric(12, 2), nullable=True)
#     predicted_reach = db.Column(db.Integer, nullable=True)
#     predicted_engagement = db.Column(db.Float, nullable=True)
#     confidence_level = db.Column(db.Float, nullable=True)
    
#     # Suggested terms
#     suggested_terms = db.Column(JSONB, nullable=True)
#     # Example: {
#     #   "deliverables": ["social_media_posts", "logo_placement"],
#     #   "expected_reach": 5000,
#     #   "duration": "30_days"
#     # }
    
#     # Status
#     is_active = db.Column(db.Boolean, default=True, index=True)
#     is_viewed = db.Column(db.Boolean, default=False)
#     is_accepted = db.Column(db.Boolean, default=False)
#     is_rejected = db.Column(db.Boolean, default=False)
    
#     created_collaboration_id = db.Column(db.Integer, 
#                                         db.ForeignKey('event_collaborations.id'), 
#                                         nullable=True)
    
#     # Timestamps
#     created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
#     viewed_at = db.Column(db.DateTime, nullable=True)
#     responded_at = db.Column(db.DateTime, nullable=True)
#     expires_at = db.Column(db.DateTime, nullable=False, index=True)
    
#     # Relationships
#     organizer = db.relationship('Organizer', backref='partner_recommendations')
#     event = db.relationship('Event', backref='partner_recommendations')
#     created_collaboration = db.relationship('EventCollaboration', 
#                                            foreign_keys=[created_collaboration_id])
    
#     @validates('match_score', 'predicted_engagement', 'confidence_level')
#     def validate_scores(self, key, value):
#         """Validate scores are between 0 and 1"""
#         if value is not None and not (0 <= value <= 1):
#             raise ValueError(f"{key} must be between 0 and 1")
#         return value
    
#     __table_args__ = (
#         db.Index('idx_organizer_active_recs', 'organizer_id', 'is_active'),
#         db.Index('idx_event_match_score', 'event_id', 'match_score'),
#     )
    
#     def as_dict(self):
#         """Convert recommendation to dictionary representation"""
#         return {
#             "id": self.id,
#             "partner_id": self.partner_id,
#             "event_id": self.event_id,
#             "match_score": self.match_score,
#             "suggested_collaboration_type": self.suggested_collaboration_type.value,
#             "match_reason": self.match_reason,
#             "matching_factors": self.matching_factors,
#             "predicted_value": float(self.predicted_value) if self.predicted_value else None,
#             "predicted_reach": self.predicted_reach,
#             "confidence_level": self.confidence_level,
#             "is_viewed": self.is_viewed,
#             "is_accepted": self.is_accepted,
#             "created_at": self.created_at.isoformat()
#         }

#     def __repr__(self):
#         return f"<AIPartnerMatchRecommendation {self.id}: Partner {self.partner_id} + Event {self.event_id}>"