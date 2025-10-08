# """Enhanced helper class for managing event collaborations with AI features"""

# from datetime import datetime, timedelta

# from models.base import db
# from models.partner import Partner
# from models.collaboration import EventCollaboration
# from models.event import Event
# from models.enums import CollaborationType, AIIntentType
# from models.ai.partner_insight import AIPartnerInsight
# from models.ai.partner_match_recommendation import AIPartnerMatchRecommendation
# from managers.ai_manager import AIManager


# class CollaborationManager:
#     """Enhanced helper class for managing event collaborations with AI features"""

#     @staticmethod
#     def create_partner(organizer_id, company_name, logo_url=None, website_url=None, 
#                       company_description=None, contact_email=None, contact_person=None,
#                       enable_ai_features=True):
#         """
#         Create a new partner with optional AI features
        
#         Args:
#             organizer_id: ID of the organizer creating the partner
#             company_name: Name of the partner company
#             logo_url: URL to partner's logo
#             website_url: Partner's website URL
#             company_description: Description of the partner
#             contact_email: Partner's contact email
#             contact_person: Name of contact person
#             enable_ai_features: Enable AI analysis for this partner
            
#         Returns:
#             Partner: Created partner instance
#         """
#         partner = Partner(
#             organizer_id=organizer_id,
#             company_name=company_name,
#             logo_url=logo_url,
#             website_url=website_url,
#             company_description=company_description,
#             contact_email=contact_email,
#             contact_person=contact_person,
#             ai_auto_suggest_events=enable_ai_features,
#             ai_smart_matching_enabled=enable_ai_features
#         )
#         db.session.add(partner)
#         db.session.commit()
        
#         # Trigger AI analysis if enabled
#         if enable_ai_features:
#             CollaborationManager.analyze_partner_with_ai(partner.id)
        
#         return partner

#     @staticmethod
#     def add_event_collaboration(event_id, partner_id, collaboration_type="Partner", 
#                                description=None, display_order=0, ai_suggested=False,
#                                match_score=None):
#         """
#         Add event collaboration with AI tracking
        
#         Args:
#             event_id: ID of the event
#             partner_id: ID of the partner
#             collaboration_type: Type of collaboration (from CollaborationType enum)
#             description: Description of the collaboration
#             display_order: Order for display on event page
#             ai_suggested: Whether this was AI-suggested
#             match_score: AI match score if applicable
            
#         Returns:
#             dict: Result with success status and collaboration instance
#         """
#         # Check for existing active collaboration
#         existing = EventCollaboration.query.filter_by(
#             event_id=event_id,
#             partner_id=partner_id,
#             is_active=True
#         ).first()

#         if existing:
#             return {"error": "Collaboration already exists", "collaboration": existing}

#         # Create collaboration
#         collaboration = EventCollaboration(
#             event_id=event_id,
#             partner_id=partner_id,
#             collaboration_type=CollaborationType(collaboration_type) if isinstance(collaboration_type, str) else collaboration_type,
#             description=description,
#             display_order=display_order,
#             ai_suggested_collaboration=ai_suggested,
#             ai_match_score=match_score,
#             status='confirmed' if not ai_suggested else 'pending'
#         )

#         db.session.add(collaboration)
#         db.session.commit()
        
#         # Log AI action if AI-suggested
#         if ai_suggested:
#             event = Event.query.get(event_id)
#             if event and hasattr(event, 'organizer'):
#                 AIManager.log_action(
#                     user_id=event.organizer.user_id,
#                     action_type=AIIntentType.MANAGE_PARTNERS,
#                     action_description=f"AI suggested collaboration between event {event_id} and partner {partner_id}",
#                     target_table='event_collaborations',
#                     target_id=collaboration.id
#                 )
        
#         return {"success": True, "collaboration": collaboration}

#     @staticmethod
#     def analyze_partner_with_ai(partner_id):
#         """
#         Run AI analysis on a partner
        
#         Args:
#             partner_id: ID of the partner to analyze
            
#         Returns:
#             Partner: Updated partner instance or None if not found
#         """
#         partner = Partner.query.get(partner_id)
#         if not partner:
#             return None
        
#         # Calculate partnership score based on historical performance
#         total_collabs = len([c for c in partner.collaborations if c.is_active])
#         successful_collabs = len([
#             c for c in partner.collaborations 
#             if c.is_active and c.contribution_score and c.contribution_score > 0.5
#         ])
        
#         if total_collabs > 0:
#             partner.ai_partnership_score = successful_collabs / total_collabs
#         else:
#             partner.ai_partnership_score = 0.5  # Neutral for new partners
        
#         partner.last_ai_analysis = datetime.utcnow()
#         db.session.commit()
        
#         return partner

#     @staticmethod
#     def generate_partner_recommendations(event_id, limit=5):
#         """
#         Generate AI partner recommendations for an event
        
#         Args:
#             event_id: ID of the event
#             limit: Maximum number of recommendations to generate
            
#         Returns:
#             list: List of AIPartnerMatchRecommendation instances
#         """
#         event = Event.query.get(event_id)
#         if not event:
#             return []
        
#         # Get all active partners for the organizer
#         partners = Partner.query.filter_by(
#             organizer_id=event.organizer_id,
#             is_active=True
#         ).all()
        
#         recommendations = []
#         expires_at = datetime.utcnow() + timedelta(days=30)
        
#         for partner in partners:
#             # Skip if already collaborating
#             existing = EventCollaboration.query.filter_by(
#                 event_id=event_id,
#                 partner_id=partner.id,
#                 is_active=True
#             ).first()
            
#             if existing:
#                 continue
            
#             # Calculate match score (simplified - can be enhanced with ML)
#             match_score = partner.ai_partnership_score or 0.5
            
#             # Create recommendation
#             recommendation = AIPartnerMatchRecommendation(
#                 partner_id=partner.id,
#                 event_id=event_id,
#                 organizer_id=event.organizer_id,
#                 match_score=match_score,
#                 suggested_collaboration_type=CollaborationType.PARTNER,
#                 match_reason=f"Partner has {match_score*100:.0f}% success rate with similar events",
#                 confidence_level=match_score,
#                 expires_at=expires_at
#             )
            
#             recommendations.append(recommendation)
        
#         # Sort by match score and limit
#         recommendations.sort(key=lambda x: x.match_score, reverse=True)
#         recommendations = recommendations[:limit]
        
#         # Save to database
#         for rec in recommendations:
#             db.session.add(rec)
#         db.session.commit()
        
#         return recommendations

#     @staticmethod
#     def track_collaboration_performance(collaboration_id, engagement_data):
#         """
#         Track and analyze collaboration performance
        
#         Args:
#             collaboration_id: ID of the collaboration
#             engagement_data: Dictionary with engagement metrics
            
#         Returns:
#             EventCollaboration: Updated collaboration instance or None
#         """
#         collaboration = EventCollaboration.query.get(collaboration_id)
#         if not collaboration:
#             return None
        
#         # Update engagement metrics
#         collaboration.engagement_metrics = engagement_data
        
#         # Calculate contribution score
#         collaboration.calculate_contribution_score()
        
#         # Generate AI insights
#         if collaboration.contribution_score:
#             insight_title = "Collaboration Performance Analysis"
            
#             if collaboration.contribution_score > 0.7:
#                 insight_desc = "Excellent performance! This partnership is driving significant value."
#                 priority = 'high'
#             elif collaboration.contribution_score > 0.4:
#                 insight_desc = "Good performance with room for optimization."
#                 priority = 'medium'
#             else:
#                 insight_desc = "Underperforming partnership. Consider reviewing terms or strategy."
#                 priority = 'high'
            
#             insight = AIPartnerInsight(
#                 partner_id=collaboration.partner_id,
#                 insight_type='performance_analysis',
#                 title=insight_title,
#                 description=insight_desc,
#                 insight_data={
#                     'collaboration_id': collaboration_id,
#                     'contribution_score': collaboration.contribution_score,
#                     'engagement_metrics': engagement_data
#                 },
#                 confidence_score=0.85,
#                 priority=priority
#             )
            
#             db.session.add(insight)
        
#         db.session.commit()
#         return collaboration

#     @staticmethod
#     def get_partner_insights(partner_id, active_only=True):
#         """
#         Get AI insights for a partner
        
#         Args:
#             partner_id: ID of the partner
#             active_only: Only return active insights
            
#         Returns:
#             list: List of AIPartnerInsight instances
#         """
#         query = AIPartnerInsight.query.filter_by(partner_id=partner_id)
        
#         if active_only:
#             query = query.filter_by(is_active=True)
        
#         return query.order_by(AIPartnerInsight.generated_at.desc()).all()

#     @staticmethod
#     def accept_recommendation(recommendation_id):
#         """
#         Accept an AI partner recommendation and create collaboration
        
#         Args:
#             recommendation_id: ID of the recommendation
            
#         Returns:
#             dict: Result with collaboration or error
#         """
#         recommendation = AIPartnerMatchRecommendation.query.get(recommendation_id)
#         if not recommendation:
#             return {"error": "Recommendation not found"}
        
#         if recommendation.is_accepted or recommendation.is_rejected:
#             return {"error": "Recommendation already processed"}
        
#         # Create the collaboration
#         result = CollaborationManager.add_event_collaboration(
#             event_id=recommendation.event_id,
#             partner_id=recommendation.partner_id,
#             collaboration_type=recommendation.suggested_collaboration_type,
#             ai_suggested=True,
#             match_score=recommendation.match_score
#         )
        
#         if "success" in result:
#             # Update recommendation status
#             recommendation.is_accepted = True
#             recommendation.responded_at = datetime.utcnow()
#             recommendation.created_collaboration_id = result["collaboration"].id
#             db.session.commit()
        
#         return result

#     @staticmethod
#     def reject_recommendation(recommendation_id):
#         """
#         Reject an AI partner recommendation
        
#         Args:
#             recommendation_id: ID of the recommendation
            
#         Returns:
#             bool: Success status
#         """
#         recommendation = AIPartnerMatchRecommendation.query.get(recommendation_id)
#         if not recommendation:
#             return False
        
#         recommendation.is_rejected = True
#         recommendation.responded_at = datetime.utcnow()
#         db.session.commit()
        
#         return True

#     @staticmethod
#     def get_active_recommendations(organizer_id, event_id=None):
#         """
#         Get active recommendations for an organizer
        
#         Args:
#             organizer_id: ID of the organizer
#             event_id: Optional event ID to filter by
            
#         Returns:
#             list: List of AIPartnerMatchRecommendation instances
#         """
#         query = AIPartnerMatchRecommendation.query.filter_by(
#             organizer_id=organizer_id,
#             is_active=True,
#             is_accepted=False,
#             is_rejected=False
#         ).filter(
#             AIPartnerMatchRecommendation.expires_at > datetime.utcnow()
#         )
        
#         if event_id:
#             query = query.filter_by(event_id=event_id)
        
#         return query.order_by(
#             AIPartnerMatchRecommendation.match_score.desc()
#         ).all()

#     @staticmethod
#     def update_partner(partner_id, **kwargs):
#         """
#         Update partner details
        
#         Args:
#             partner_id: ID of the partner
#             **kwargs: Fields to update
            
#         Returns:
#             Partner: Updated partner instance or None
#         """
#         partner = Partner.query.get(partner_id)
#         if not partner:
#             return None
        
#         # Update allowed fields
#         allowed_fields = [
#             'company_name', 'company_description', 'logo_url', 
#             'website_url', 'contact_email', 'contact_person',
#             'ai_auto_suggest_events', 'ai_smart_matching_enabled',
#             'is_active'
#         ]
        
#         for key, value in kwargs.items():
#             if key in allowed_fields:
#                 setattr(partner, key, value)
        
#         partner.updated_at = datetime.utcnow()
#         db.session.commit()
        
#         return partner

#     @staticmethod
#     def delete_partner(partner_id, soft_delete=True):
#         """
#         Delete or deactivate a partner
        
#         Args:
#             partner_id: ID of the partner
#             soft_delete: If True, deactivate instead of deleting
            
#         Returns:
#             bool: Success status
#         """
#         partner = Partner.query.get(partner_id)
#         if not partner:
#             return False
        
#         if soft_delete:
#             partner.is_active = False
#             db.session.commit()
#         else:
#             db.session.delete(partner)
#             db.session.commit()
        
#         return True

#     @staticmethod
#     def get_partner_statistics(partner_id):
#         """
#         Get comprehensive statistics for a partner
        
#         Args:
#             partner_id: ID of the partner
            
#         Returns:
#             dict: Partner statistics
#         """
#         partner = Partner.query.get(partner_id)
#         if not partner:
#             return None
        
#         collaborations = [c for c in partner.collaborations if c.is_active]
        
#         total_reach = sum(c.estimated_reach or 0 for c in collaborations)
#         avg_contribution = sum(c.contribution_score or 0 for c in collaborations) / len(collaborations) if collaborations else 0
        
#         return {
#             "partner_id": partner_id,
#             "total_collaborations": len(collaborations),
#             "active_collaborations": len([c for c in collaborations if c.status == 'active']),
#             "completed_collaborations": len([c for c in collaborations if c.status == 'completed']),
#             "total_estimated_reach": total_reach,
#             "average_contribution_score": round(avg_contribution, 3),
#             "partnership_score": partner.ai_partnership_score,
#             "performance_score": partner.performance_score,
#             "last_analysis": partner.last_ai_analysis.isoformat() if partner.last_ai_analysis else None
#         }