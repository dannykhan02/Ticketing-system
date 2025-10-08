# """Partner model for managing event partnerships"""

# from datetime import datetime
# from sqlalchemy.orm import validates
# from sqlalchemy.dialects.postgresql import JSONB

# from models.base import db


# class Partner(db.Model):
#     """Partner model for companies/organizations that collaborate on events"""
#     __tablename__ = 'partners'

#     id = db.Column(db.Integer, primary_key=True, autoincrement=True)
#     organizer_id = db.Column(db.Integer, db.ForeignKey('organizer.id'), nullable=False)
#     company_name = db.Column(db.String(255), nullable=False)
#     company_description = db.Column(db.Text, nullable=True)
#     logo_url = db.Column(db.String(500), nullable=True)
#     website_url = db.Column(db.String(500), nullable=True)
#     contact_email = db.Column(db.String(255), nullable=True)
#     contact_person = db.Column(db.String(255), nullable=True)
    
#     # AI-Enhanced Fields
#     ai_description_enhanced = db.Column(db.Boolean, default=False)
#     ai_partnership_score = db.Column(db.Float, nullable=True)  # 0-1 score of partnership value
#     ai_recommended_collaboration_types = db.Column(JSONB, nullable=True)  # Suggested collaboration types
#     ai_target_audience_overlap = db.Column(JSONB, nullable=True)  # Audience matching data
#     ai_suggested_events = db.Column(JSONB, nullable=True)  # Events this partner would be good for
    
#     # Partnership Performance Metrics (AI-calculated)
#     performance_score = db.Column(db.Float, default=0.0)  # Overall performance score
#     engagement_rate = db.Column(db.Float, nullable=True)  # Partner engagement metrics
#     roi_estimate = db.Column(db.Numeric(12, 2), nullable=True)  # Estimated ROI from partnership
    
#     # AI Preferences
#     ai_auto_suggest_events = db.Column(db.Boolean, default=True)
#     ai_smart_matching_enabled = db.Column(db.Boolean, default=True)
    
#     # Status and Metadata
#     is_active = db.Column(db.Boolean, default=True, nullable=False)
#     created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
#     updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
#     last_ai_analysis = db.Column(db.DateTime, nullable=True)

#     # Relationships
#     collaborations = db.relationship('EventCollaboration', back_populates='partner', lazy=True)
    
#     # AI relationships
#     ai_actions = db.relationship('AIActionLog', backref='partner', lazy=True,
#                                 foreign_keys='AIActionLog.partner_id')
#     ai_insights = db.relationship('AIPartnerInsight', backref='partner', lazy=True, 
#                                  cascade="all, delete")
#     ai_match_recommendations = db.relationship('AIPartnerMatchRecommendation', 
#                                               backref='partner', lazy=True,
#                                               cascade="all, delete")

#     @validates('ai_partnership_score', 'performance_score', 'engagement_rate')
#     def validate_scores(self, key, value):
#         """Validate that scores are between 0 and 1"""
#         if value is not None and not (0 <= value <= 1):
#             raise ValueError(f"{key} must be between 0 and 1")
#         return value

#     def as_dict(self):
#         """Convert partner to dictionary representation"""
#         return {
#             "id": self.id,
#             "organizer_id": self.organizer_id,
#             "company_name": self.company_name,
#             "logo_url": self.logo_url,
#             "website_url": self.website_url,
#             "total_collaborations": len([c for c in self.collaborations if c.is_active]),
#             "ai_partnership_score": self.ai_partnership_score,
#             "performance_score": self.performance_score,
#             "ai_description_enhanced": self.ai_description_enhanced,
#             "engagement_rate": self.engagement_rate
#         }

#     def calculate_performance_score(self):
#         """AI-calculated performance based on collaboration success"""
#         # Count successful collaborations
#         successful_collabs = sum(1 for c in self.collaborations 
#                                 if c.is_active and c.engagement_metrics and 
#                                 c.engagement_metrics.get('success', False))
#         total_collabs = len([c for c in self.collaborations if c.is_active])
        
#         if total_collabs == 0:
#             self.performance_score = 0.5  # Neutral score for new partners
#         else:
#             self.performance_score = successful_collabs / total_collabs
        
#         db.session.commit()
#         return self.performance_score

#     def __repr__(self):
#         return f"<Partner {self.id}: {self.company_name}>"