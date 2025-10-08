# """AI-generated insights about partners"""

# from datetime import datetime
# from sqlalchemy.orm import validates
# from sqlalchemy.dialects.postgresql import JSONB

# from models.base import db


# class AIPartnerInsight(db.Model):
#     """AI-generated insights about partners"""
#     __tablename__ = 'ai_partner_insights'
    
#     id = db.Column(db.Integer, primary_key=True, autoincrement=True)
#     partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False, index=True)
    
#     # Insight details
#     insight_type = db.Column(db.String(50), nullable=False, index=True)
#     # Types: 'performance_analysis', 'opportunity_identification', 'risk_assessment', 
#     #        'optimization_suggestion', 'trend_analysis'
    
#     title = db.Column(db.String(255), nullable=False)
#     description = db.Column(db.Text, nullable=False)
    
#     # Analysis data
#     insight_data = db.Column(JSONB, nullable=True)
#     # Example: {"avg_engagement": 0.75, "best_collaboration_type": "Media Partner"}
    
#     recommended_actions = db.Column(JSONB, nullable=True)
#     # Example: [{"action": "increase_visibility", "reason": "High performing partner"}]
    
#     # Metrics
#     confidence_score = db.Column(db.Float, nullable=True)
#     priority = db.Column(db.String(20), default='medium', index=True)  # 'low', 'medium', 'high', 'critical'
#     potential_value_increase = db.Column(db.Numeric(12, 2), nullable=True)
    
#     # Status
#     is_active = db.Column(db.Boolean, default=True, index=True)
#     is_read = db.Column(db.Boolean, default=False)
#     is_acted_upon = db.Column(db.Boolean, default=False)
    
#     # Timestamps
#     generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
#     expires_at = db.Column(db.DateTime, nullable=True, index=True)
#     acted_upon_at = db.Column(db.DateTime, nullable=True)
    
#     @validates('confidence_score')
#     def validate_confidence(self, key, value):
#         """Validate confidence score is between 0 and 1"""
#         if value is not None and not (0 <= value <= 1):
#             raise ValueError("Confidence score must be between 0 and 1")
#         return value
    
#     __table_args__ = (
#         db.Index('idx_partner_active_insights', 'partner_id', 'is_active'),
#     )
    
#     def as_dict(self):
#         """Convert insight to dictionary representation"""
#         return {
#             "id": self.id,
#             "partner_id": self.partner_id,
#             "insight_type": self.insight_type,
#             "title": self.title,
#             "description": self.description,
#             "insight_data": self.insight_data,
#             "recommended_actions": self.recommended_actions,
#             "confidence_score": self.confidence_score,
#             "priority": self.priority,
#             "potential_value_increase": float(self.potential_value_increase) if self.potential_value_increase else None,
#             "is_read": self.is_read,
#             "generated_at": self.generated_at.isoformat()
#         }

#     def __repr__(self):
#         return f"<AIPartnerInsight {self.id}: {self.insight_type} for Partner {self.partner_id}>"