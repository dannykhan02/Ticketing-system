"""
AI Partner & Collaboration Assistant - Comprehensive partnership management with AI
Handles partner discovery, collaboration suggestions, performance analysis, and optimization
Enhanced with graceful degradation and intelligent fallback logic
"""

from typing import Dict, Optional, List, Tuple
import logging
from ai.llm_client import llm_client
from model import (
    Partner, EventCollaboration, Event, Organizer, Category,
    CollaborationType, AIPartnerInsight, AIPartnerMatchRecommendation,
    db
)
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_
import json
import re

logger = logging.getLogger(__name__)


class PartnerAssistant:
    """AI assistant for partner and collaboration management with fallback logic"""
    
    def __init__(self):
        self.llm = llm_client
    
    # ==================== PARTNER CREATION & ENHANCEMENT ====================
    
    def suggest_partner_from_description(self, organizer_id: int, description: str) -> Optional[Dict]:
        """
        Suggest partner details based on a description
        Falls back to rule-based suggestions if AI is unavailable
        
        Args:
            organizer_id: Organizer creating the partner
            description: User's description of the partner
        
        Returns:
            dict: Suggested partner details or None
        """
        if not self.llm.is_enabled():
            logger.info("AI unavailable, using rule-based partner suggestion")
            return self._fallback_partner_suggestion(description)
        
        messages = [
            self.llm.build_system_message(
                "You are helping create business partners for event management. Suggest partner details "
                "based on user input. Respond ONLY with valid JSON format with keys: "
                "'company_name' (concise, professional), 'company_description' (2-3 sentences), "
                "'suggested_collaboration_types' (array of types from: Partner, Official Partner, "
                "Collaborator, Supporter, Media Partner), 'target_audience' (brief description). "
                "Do not include any markdown formatting or code blocks."
            ),
            {
                "role": "user",
                "content": f"Create a partner profile for: {description}"
            }
        ]
        
        try:
            response = self.llm.chat_completion(
                messages, 
                temperature=0.7,
                quick_mode=True,
                fallback_response=None
            )
            
            if response:
                # Clean response - remove markdown if present
                cleaned = response.strip()
                if cleaned.startswith('```'):
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
                    if json_match:
                        cleaned = json_match.group(1)
                    else:
                        cleaned = cleaned.replace('```json', '').replace('```', '').strip()
                
                result = json.loads(cleaned)
                
                # Validate structure
                if 'company_name' in result and 'company_description' in result:
                    logger.info("AI partner suggestion generated successfully")
                    return result
                else:
                    logger.warning("AI response missing required fields, using fallback")
                    return self._fallback_partner_suggestion(description)
                    
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return self._fallback_partner_suggestion(description)
        except Exception as e:
            logger.error(f"Error suggesting partner: {e}")
            return self._fallback_partner_suggestion(description)
        
        return self._fallback_partner_suggestion(description)
    
    def _fallback_partner_suggestion(self, description: str) -> Dict:
        """Rule-based fallback for partner suggestions"""
        words = description.strip().split()
        company_name = ' '.join(words[:4]).title()
        
        # Extract potential collaboration types from keywords
        collab_types = []
        if any(word in description.lower() for word in ['media', 'press', 'news', 'publication']):
            collab_types.append('Media Partner')
        if any(word in description.lower() for word in ['sponsor', 'official', 'main']):
            collab_types.append('Official Partner')
        if any(word in description.lower() for word in ['support', 'help', 'assist']):
            collab_types.append('Supporter')
        
        if not collab_types:
            collab_types = ['Partner']
        
        return {
            "company_name": company_name,
            "company_description": description[:300],
            "suggested_collaboration_types": collab_types,
            "target_audience": "General audience",
            "source": "fallback"
        }
    
    def enhance_partner_description(self, partner_id: int) -> Optional[str]:
        """
        Enhance or generate a partner description using AI
        Returns original or basic description if AI unavailable
        
        Args:
            partner_id: Partner to enhance
        
        Returns:
            str: Enhanced description or fallback
        """
        partner = Partner.query.get(partner_id)
        if not partner:
            return None
        
        if not self.llm.is_enabled():
            logger.info("AI unavailable, using fallback description")
            return self._fallback_partner_description(partner)
        
        context = f"Company: {partner.company_name}"
        if partner.company_description:
            context += f"\nCurrent description: {partner.company_description}"
        if partner.website_url:
            context += f"\nWebsite: {partner.website_url}"
        
        # Get collaboration history for context
        collab_count = len([c for c in partner.collaborations if c.is_active])
        if collab_count > 0:
            context += f"\nHas {collab_count} active collaborations"
        
        messages = [
            self.llm.build_system_message(
                "You write compelling, professional partner company descriptions for event management. "
                "Focus on value proposition and partnership benefits. Keep it 2-3 sentences, engaging and professional."
            ),
            {"role": "user", "content": f"Enhance this partner description:\n{context}"}
        ]
        
        enhanced = self.llm.chat_completion(
            messages, 
            temperature=0.7, 
            max_tokens=150,
            quick_mode=True,
            fallback_response=None
        )
        
        if enhanced:
            # Update the partner record
            partner.company_description = enhanced
            partner.ai_description_enhanced = True
            db.session.commit()
            return enhanced
        
        return self._fallback_partner_description(partner)
    
    def _fallback_partner_description(self, partner: Partner) -> str:
        """Generate basic description when AI is unavailable"""
        if partner.company_description:
            return partner.company_description
        
        collab_count = len([c for c in partner.collaborations if c.is_active])
        if collab_count > 0:
            return f"{partner.company_name} is a trusted partner with {collab_count} successful collaborations in event management."
        
        return f"{partner.company_name} is a professional partner for event collaborations and sponsorships."
    
    # ==================== COLLABORATION MATCHING & RECOMMENDATIONS ====================
    
    def suggest_collaborations_for_event(self, event_id: int, limit: int = 5) -> List[Dict]:
        """
        Suggest best partner matches for an event
        Uses AI when available, falls back to rule-based matching
        
        Args:
            event_id: Event to find partners for
            limit: Maximum number of suggestions
        
        Returns:
            list: Partner suggestions with match scores
        """
        event = Event.query.get(event_id)
        if not event:
            return []
        
        # Get available partners
        partners = Partner.query.filter_by(
            organizer_id=event.organizer_id,
            is_active=True
        ).all()
        
        # Filter out existing collaborations
        existing_partner_ids = {c.partner_id for c in event.collaborations if c.is_active}
        available_partners = [p for p in partners if p.id not in existing_partner_ids]
        
        if not available_partners:
            return []
        
        if self.llm.is_enabled():
            return self._ai_match_partners(event, available_partners, limit)
        else:
            return self._rule_based_match_partners(event, available_partners, limit)
    
    def _ai_match_partners(self, event: Event, partners: List[Partner], limit: int) -> List[Dict]:
        """AI-powered partner matching"""
        event_context = {
            "name": event.name,
            "category": event.event_category.name if event.event_category else "General",
            "city": event.city,
            "description": event.description[:200]
        }
        
        partner_list = [
            {
                "id": p.id,
                "name": p.company_name,
                "description": p.company_description or "No description",
                "past_collaborations": len([c for c in p.collaborations if c.is_active]),
                "performance_score": p.performance_score or 0.5
            }
            for p in partners[:10]  # Limit to prevent token overflow
        ]
        
        messages = [
            self.llm.build_system_message(
                "You are an expert at matching event partners. Analyze the event and partners, "
                "then return ONLY valid JSON (no markdown) with format: "
                '{"recommendations": [{"partner_id": int, "match_score": float(0-1), '
                '"collaboration_type": str, "reason": str}]}. '
                "Collaboration types: Partner, Official Partner, Collaborator, Supporter, Media Partner"
            ),
            {
                "role": "user",
                "content": f"Event: {json.dumps(event_context)}\n\n"
                          f"Available Partners: {json.dumps(partner_list)}\n\n"
                          f"Suggest the best {limit} partner matches."
            }
        ]
        
        try:
            response = self.llm.chat_completion(
                messages,
                temperature=0.5,
                quick_mode=True,
                fallback_response=None
            )
            
            if response:
                cleaned = response.strip()
                if cleaned.startswith('```'):
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
                    if json_match:
                        cleaned = json_match.group(1)
                    else:
                        cleaned = cleaned.replace('```json', '').replace('```', '').strip()
                
                result = json.loads(cleaned)
                recommendations = result.get('recommendations', [])
                
                # Save recommendations to database
                self._save_match_recommendations(event.id, event.organizer_id, recommendations)
                
                return recommendations[:limit]
                
        except Exception as e:
            logger.error(f"Error in AI partner matching: {e}")
        
        return self._rule_based_match_partners(event, partners, limit)
    
    def _rule_based_match_partners(self, event: Event, partners: List[Partner], limit: int) -> List[Dict]:
        """Rule-based fallback for partner matching"""
        recommendations = []
        
        for partner in partners:
            score = 0.5  # Base score
            reason_parts = []
            
            # Check performance score
            if partner.performance_score:
                score = partner.performance_score
                if score > 0.7:
                    reason_parts.append("high performance history")
            
            # Check past collaborations
            past_collabs = len([c for c in partner.collaborations if c.is_active])
            if past_collabs > 3:
                score += 0.1
                reason_parts.append(f"{past_collabs} successful collaborations")
            
            # Check if partner has worked with similar events
            similar_events = 0
            for collab in partner.collaborations:
                if collab.event and collab.event.category_id == event.category_id:
                    similar_events += 1
            
            if similar_events > 0:
                score += 0.15
                reason_parts.append(f"experience with {event.event_category.name} events")
            
            # Normalize score
            score = min(1.0, score)
            
            reason = "Good match based on: " + ", ".join(reason_parts) if reason_parts else "Potential new partnership opportunity"
            
            recommendations.append({
                "partner_id": partner.id,
                "partner_name": partner.company_name,
                "match_score": round(score, 2),
                "collaboration_type": "Partner",
                "reason": reason
            })
        
        # Sort by score and limit
        recommendations.sort(key=lambda x: x['match_score'], reverse=True)
        return recommendations[:limit]
    
    def _save_match_recommendations(self, event_id: int, organizer_id: int, recommendations: List[Dict]):
        """Save AI recommendations to database"""
        try:
            expires_at = datetime.utcnow() + timedelta(days=30)
            
            for rec in recommendations:
                match_rec = AIPartnerMatchRecommendation(
                    partner_id=rec['partner_id'],
                    event_id=event_id,
                    organizer_id=organizer_id,
                    match_score=rec['match_score'],
                    suggested_collaboration_type=CollaborationType(rec['collaboration_type']),
                    match_reason=rec['reason'],
                    expires_at=expires_at
                )
                db.session.add(match_rec)
            
            db.session.commit()
        except Exception as e:
            logger.error(f"Error saving match recommendations: {e}")
            db.session.rollback()
    
    # ==================== PERFORMANCE ANALYSIS ====================
    
    def analyze_partner_performance(self, partner_id: int) -> Optional[Dict]:
        """
        Comprehensive performance analysis of a partner
        Provides AI insights when available, statistics always
        
        Args:
            partner_id: Partner to analyze
        
        Returns:
            dict: Performance analysis with insights
        """
        partner = Partner.query.get(partner_id)
        if not partner:
            return None
        
        # Gather statistics (always available)
        stats = self._calculate_partner_stats(partner)
        
        # Try to generate AI insights
        insights_text = None
        recommendations = []
        
        if self.llm.is_enabled():
            insights_text, recommendations = self._generate_ai_performance_insights(partner, stats)
        
        # Generate fallback insights if AI unavailable
        if not insights_text:
            insights_text = self._generate_fallback_performance_insights(partner, stats)
        
        # Save insights to database
        self._save_partner_insights(partner_id, stats, insights_text, recommendations)
        
        return {
            "partner_id": partner_id,
            "partner_name": partner.company_name,
            "statistics": stats,
            "insights": insights_text,
            "recommendations": recommendations,
            "generated_at": datetime.utcnow().isoformat(),
            "ai_powered": self.llm.is_enabled()
        }
    
    def _calculate_partner_stats(self, partner: Partner) -> Dict:
        """Calculate detailed partner statistics"""
        total_collabs = len(partner.collaborations)
        active_collabs = len([c for c in partner.collaborations if c.is_active])
        
        # Collaboration types breakdown
        collab_types = {}
        for collab in partner.collaborations:
            ctype = collab.collaboration_type.value
            collab_types[ctype] = collab_types.get(ctype, 0) + 1
        
        # Calculate average contribution score
        contribution_scores = [c.contribution_score for c in partner.collaborations 
                              if c.contribution_score is not None]
        avg_contribution = sum(contribution_scores) / len(contribution_scores) if contribution_scores else 0
        
        # Engagement metrics aggregation
        total_reach = 0
        total_clicks = 0
        total_conversions = 0
        
        for collab in partner.collaborations:
            if collab.engagement_metrics:
                total_reach += collab.engagement_metrics.get('social_reach', 0)
                total_clicks += collab.engagement_metrics.get('clicks', 0)
                total_conversions += collab.engagement_metrics.get('conversions', 0)
        
        # Recent performance (last 3 months)
        three_months_ago = datetime.utcnow() - timedelta(days=90)
        recent_collabs = [c for c in partner.collaborations 
                         if c.created_at >= three_months_ago]
        
        return {
            "total_collaborations": total_collabs,
            "active_collaborations": active_collabs,
            "collaboration_types": collab_types,
            "performance_score": partner.performance_score or 0.5,
            "avg_contribution_score": round(avg_contribution, 2),
            "total_reach": total_reach,
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "recent_collaborations_count": len(recent_collabs),
            "partnership_score": partner.ai_partnership_score or 0.5
        }
    
    def _generate_ai_performance_insights(self, partner: Partner, stats: Dict) -> Tuple[str, List[Dict]]:
        """Generate AI-powered performance insights"""
        messages = [
            self.llm.build_system_message(
                "You analyze event partner performance data and provide actionable insights. "
                "Provide 2-3 key insights and 2-3 specific recommendations in clear, concise language."
            ),
            {
                "role": "user",
                "content": f"Analyze this partner's performance:\n\n"
                          f"Partner: {partner.company_name}\n"
                          f"Statistics: {json.dumps(stats, indent=2)}\n\n"
                          f"Provide insights and recommendations."
            }
        ]
        
        try:
            response = self.llm.chat_completion(
                messages,
                temperature=0.7,
                max_tokens=300,
                quick_mode=True,
                fallback_response=None
            )
            
            if response:
                # Try to extract structured recommendations
                recommendations = self._extract_recommendations_from_text(response)
                return response, recommendations
                
        except Exception as e:
            logger.error(f"Error generating AI performance insights: {e}")
        
        return None, []
    
    def _extract_recommendations_from_text(self, text: str) -> List[Dict]:
        """Extract actionable recommendations from AI text"""
        recommendations = []
        
        # Simple pattern matching for common recommendation formats
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if any(line.lower().startswith(word) for word in ['recommend', 'suggest', 'consider', '•', '-', '*']):
                # Clean up the line
                clean_line = re.sub(r'^[•\-*]\s*', '', line)
                clean_line = re.sub(r'^(recommend|suggest|consider):\s*', '', clean_line, flags=re.IGNORECASE)
                
                if len(clean_line) > 10:  # Meaningful recommendation
                    recommendations.append({
                        "action": clean_line,
                        "priority": "medium"
                    })
        
        return recommendations[:5]  # Limit to 5 recommendations
    
    def _generate_fallback_performance_insights(self, partner: Partner, stats: Dict) -> str:
        """Generate basic insights when AI is unavailable"""
        insights = []
        
        total = stats['total_collaborations']
        active = stats['active_collaborations']
        perf_score = stats['performance_score']
        contribution = stats['avg_contribution_score']
        
        # Performance assessment
        if perf_score > 0.7:
            insights.append(f"{partner.company_name} is a high-performing partner with excellent results.")
        elif perf_score > 0.4:
            insights.append(f"{partner.company_name} shows good performance with room for optimization.")
        else:
            insights.append(f"{partner.company_name}'s performance suggests review of partnership strategy is needed.")
        
        # Collaboration activity
        if active > 5:
            insights.append(f"Very active partnership with {active} ongoing collaborations.")
        elif active == 0 and total > 0:
            insights.append("No current active collaborations. Consider re-engagement opportunities.")
        
        # Contribution analysis
        if contribution > 0.6:
            insights.append(f"Strong engagement contribution (score: {contribution:.2f}). This partner drives significant value.")
        elif contribution < 0.3 and contribution > 0:
            insights.append("Lower engagement metrics suggest optimization needed in collaboration approach.")
        
        # Reach analysis
        if stats['total_reach'] > 10000:
            insights.append(f"Excellent reach with {stats['total_reach']:,} total audience impressions.")
        
        return " ".join(insights) if insights else "Limited data available for comprehensive analysis."
    
    def _save_partner_insights(self, partner_id: int, stats: Dict, insights_text: str, recommendations: List[Dict]):
        """Save generated insights to database"""
        try:
            # Determine priority based on performance
            priority = 'medium'
            if stats['performance_score'] > 0.7:
                priority = 'high'
            elif stats['performance_score'] < 0.3:
                priority = 'critical'
            
            insight = AIPartnerInsight(
                partner_id=partner_id,
                insight_type='performance_analysis',
                title=f"Performance Analysis",
                description=insights_text,
                insight_data=stats,
                recommended_actions=recommendations if recommendations else None,
                confidence_score=0.8 if self.llm.is_enabled() else 0.6,
                priority=priority
            )
            
            db.session.add(insight)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error saving partner insights: {e}")
            db.session.rollback()
    
    # ==================== COLLABORATION OPTIMIZATION ====================
    
    def optimize_collaboration(self, collaboration_id: int) -> Optional[Dict]:
        """
        Analyze and suggest optimizations for an existing collaboration
        
        Args:
            collaboration_id: Collaboration to optimize
        
        Returns:
            dict: Optimization suggestions
        """
        collab = EventCollaboration.query.get(collaboration_id)
        if not collab:
            return None
        
        # Gather collaboration data
        collab_data = {
            "collaboration_type": collab.collaboration_type.value,
            "status": collab.status,
            "engagement_metrics": collab.engagement_metrics or {},
            "contribution_score": collab.contribution_score,
            "show_on_event_page": collab.show_on_event_page,
            "display_order": collab.display_order
        }
        
        if self.llm.is_enabled():
            return self._ai_optimize_collaboration(collab, collab_data)
        else:
            return self._rule_based_optimize_collaboration(collab, collab_data)
    
    def _ai_optimize_collaboration(self, collab: EventCollaboration, collab_data: Dict) -> Dict:
        """AI-powered collaboration optimization"""
        messages = [
            self.llm.build_system_message(
                "You optimize event-partner collaborations. Analyze the data and suggest "
                "specific improvements. Return JSON with keys: 'status' (str), "
                "'optimizations' (array of {change: str, reason: str, expected_impact: str}), "
                "'overall_assessment' (str). No markdown."
            ),
            {
                "role": "user",
                "content": f"Optimize this collaboration:\n\n"
                          f"Event: {collab.event.name if collab.event else 'Unknown'}\n"
                          f"Partner: {collab.partner.company_name if collab.partner else 'Unknown'}\n"
                          f"Data: {json.dumps(collab_data, indent=2)}"
            }
        ]
        
        try:
            response = self.llm.chat_completion(
                messages,
                temperature=0.6,
                quick_mode=True,
                fallback_response=None
            )
            
            if response:
                cleaned = response.strip()
                if cleaned.startswith('```'):
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
                    if json_match:
                        cleaned = json_match.group(1)
                    else:
                        cleaned = cleaned.replace('```json', '').replace('```', '').strip()
                
                result = json.loads(cleaned)
                result['ai_powered'] = True
                return result
                
        except Exception as e:
            logger.error(f"Error in AI collaboration optimization: {e}")
        
        return self._rule_based_optimize_collaboration(collab, collab_data)
    
    def _rule_based_optimize_collaboration(self, collab: EventCollaboration, collab_data: Dict) -> Dict:
        """Rule-based collaboration optimization"""
        optimizations = []
        
        # Check visibility
        if not collab.show_on_event_page:
            optimizations.append({
                "change": "Enable visibility on event page",
                "reason": "Partner not currently visible to attendees",
                "expected_impact": "Increased partner satisfaction and engagement"
            })
        
        # Check engagement
        if collab.engagement_metrics:
            clicks = collab.engagement_metrics.get('clicks', 0)
            if clicks < 10 and collab.show_on_event_page:
                optimizations.append({
                    "change": "Improve partner logo placement or prominence",
                    "reason": "Low click-through rate detected",
                    "expected_impact": "Better partner visibility and engagement"
                })
        
        # Check contribution score
        if collab.contribution_score and collab.contribution_score < 0.4:
            optimizations.append({
                "change": "Review partnership terms and deliverables",
                "reason": "Lower than expected contribution score",
                "expected_impact": "Improved partnership value and ROI"
            })
        
        # Status check
        assessment = "Collaboration functioning normally"
        if collab.contribution_score and collab.contribution_score > 0.7:
            assessment = "High-performing collaboration - maintain current approach"
        elif not optimizations:
            assessment = "Collaboration is optimized - no immediate changes needed"
        else:
            assessment = f"Found {len(optimizations)} optimization opportunities"
        
        return {
            "status": "needs_optimization" if optimizations else "optimal",
            "optimizations": optimizations,
            "overall_assessment": assessment,
            "ai_powered": False
        }
    
    # ==================== NATURAL LANGUAGE QUERY PROCESSING ====================
    
    def process_natural_language_query(self, query: str, organizer_id: int) -> Dict:
        """
        Process natural language queries about partners and collaborations
        Falls back to pattern matching if AI unavailable
        
        Args:
            query: User's question or request
            organizer_id: Organizer making the request
        
        Returns:
            dict: Response with action and data
        """
        if not self.llm.is_enabled():
            logger.info("AI unavailable, using pattern-based query processing")
            return self._process_query_with_patterns(query, organizer_id)
        
        messages = [
            self.llm.build_system_message(
                "You help manage event partners and collaborations. Determine user intent and respond with ONLY valid JSON, no markdown. "
                "Possible intents: 'create_partner', 'find_partners', 'analyze_partner', 'suggest_collaborations', "
                "'optimize_collaboration', 'list_partners', 'performance_report', 'help'. "
                "Format: {\"intent\": \"<intent>\", \"params\": {<extracted_params>}, \"message\": \"<user_friendly_message>\"}"
            ),
            {"role": "user", "content": query}
        ]
        
        try:
            response = self.llm.chat_completion(
                messages,
                temperature=0.3,
                quick_mode=True,
                fallback_response=None
            )
            
            if response:
                cleaned = response.strip()
                if cleaned.startswith('```'):
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
                    if json_match:
                        cleaned = json_match.group(1)
                    else:
                        cleaned = cleaned.replace('```json', '').replace('```', '').strip()
                
                result = json.loads(cleaned)
                if 'intent' in result:
                    return result
                    
        except Exception as e:
            logger.error(f"Error processing NL query: {e}")
        
        return self._process_query_with_patterns(query, organizer_id)
    
    def _process_query_with_patterns(self, query: str, organizer_id: int) -> Dict:
        """Pattern-based query processing fallback"""
        query_lower = query.lower()
        
        # Partner creation patterns
        if any(word in query_lower for word in ['create partner', 'add partner', 'new partner']):
            return {
                "intent": "create_partner",
                "params": {},
                "message": "I can help you create a new partner. Please provide the partner details."
            }
        
        # Finding partners patterns
        elif any(word in query_lower for word in ['find partner', 'suggest partner', 'match partner', 'recommend partner']):
            return {
                "intent": "find_partners",
                "params": {},
                "message": "I'll help you find suitable partners. Which event are you looking for partners for?"
            }
        
        # Analysis patterns
        elif any(word in query_lower for word in ['analyze', 'performance', 'how is', 'stats']):
            return {
                "intent": "analyze_partner",
                "params": {},
                "message": "I can analyze partner performance. Which partner would you like me to analyze?"
            }
        
        # Collaboration patterns
        elif any(word in query_lower for word in ['collaboration', 'collaborate', 'work with']):
            if 'suggest' in query_lower or 'recommend' in query_lower:
                return {
                    "intent": "suggest_collaborations",
                    "params": {},
                    "message": "I can suggest collaborations for your events. Which event should I analyze?"
                }
            else:
                return {
                    "intent": "optimize_collaboration",
                    "params": {},
                    "message": "I can help optimize collaborations. Which collaboration needs improvement?"
                }
        
        # List patterns
        elif any(word in query_lower for word in ['list', 'show all', 'view partners']):
            return {
                "intent": "list_partners",
                "params": {},
                "message": "I'll show you all your partners and their collaborations."
            }
        
        # Report patterns
        elif any(word in query_lower for word in ['report', 'summary', 'overview']):
            return {
                "intent": "performance_report",
                "params": {},
                "message": "I can generate a comprehensive partner performance report."
            }
        
        # Default help
        else:
            return {
                "intent": "help",
                "params": {},
                "message": "I can help you create partners, find suitable collaborations, analyze performance, and optimize partnerships. What would you like to do?"
            }
    
    # ==================== TREND ANALYSIS & INSIGHTS ====================
    
    def identify_partnership_trends(self, organizer_id: int) -> Dict:
        """
        Identify trends in partnerships and collaborations
        
        Args:
            organizer_id: Organizer to analyze
        
        Returns:
            dict: Trend analysis and insights
        """
        organizer = Organizer.query.get(organizer_id)
        if not organizer:
            return {"error": "Organizer not found"}
        
        # Gather trend data
        trends_data = self._calculate_partnership_trends(organizer)
        
        # Generate insights
        if self.llm.is_enabled():
            insights = self._ai_analyze_trends(trends_data)
        else:
            insights = self._fallback_analyze_trends(trends_data)
        
        return {
            "organizer_id": organizer_id,
            "trends": trends_data,
            "insights": insights,
            "generated_at": datetime.utcnow().isoformat(),
            "ai_powered": self.llm.is_enabled()
        }
    
    def _calculate_partnership_trends(self, organizer: Organizer) -> Dict:
        """Calculate partnership trend statistics"""
        now = datetime.utcnow()
        
        # Time periods
        last_month = now - timedelta(days=30)
        last_quarter = now - timedelta(days=90)
        last_year = now - timedelta(days=365)
        
        # Partner growth
        total_partners = len([p for p in organizer.partners if p.is_active])
        partners_last_month = len([p for p in organizer.partners 
                                   if p.is_active and p.created_at >= last_month])
        partners_last_quarter = len([p for p in organizer.partners 
                                    if p.is_active and p.created_at >= last_quarter])
        
        # Collaboration trends
        all_collabs = []
        for partner in organizer.partners:
            all_collabs.extend(partner.collaborations)
        
        active_collabs = len([c for c in all_collabs if c.is_active])
        collabs_last_month = len([c for c in all_collabs 
                                 if c.created_at >= last_month and c.is_active])
        
        # Collaboration type distribution
        collab_type_dist = {}
        for collab in [c for c in all_collabs if c.is_active]:
            ctype = collab.collaboration_type.value
            collab_type_dist[ctype] = collab_type_dist.get(ctype, 0) + 1
        
        # Performance trends
        recent_contributions = [c.contribution_score for c in all_collabs 
                               if c.contribution_score and c.created_at >= last_quarter]
        avg_recent_contribution = (sum(recent_contributions) / len(recent_contributions) 
                                  if recent_contributions else 0)
        
        # Most active partners
        partner_activity = []
        for partner in organizer.partners:
            if partner.is_active:
                active_count = len([c for c in partner.collaborations if c.is_active])
                if active_count > 0:
                    partner_activity.append({
                        "partner_name": partner.company_name,
                        "active_collaborations": active_count,
                        "performance_score": partner.performance_score or 0.5
                    })
        
        partner_activity.sort(key=lambda x: x['active_collaborations'], reverse=True)
        
        return {
            "total_partners": total_partners,
            "new_partners_last_month": partners_last_month,
            "new_partners_last_quarter": partners_last_quarter,
            "partner_growth_rate": round(partners_last_quarter / max(total_partners, 1) * 100, 2),
            "active_collaborations": active_collabs,
            "new_collaborations_last_month": collabs_last_month,
            "collaboration_type_distribution": collab_type_dist,
            "avg_contribution_score_recent": round(avg_recent_contribution, 2),
            "top_partners": partner_activity[:5]
        }
    
    def _ai_analyze_trends(self, trends_data: Dict) -> str:
        """AI-powered trend analysis"""
        messages = [
            self.llm.build_system_message(
                "You analyze partnership trends for event organizers. Provide 3-4 key insights "
                "about growth, performance, and opportunities. Be specific and actionable."
            ),
            {
                "role": "user",
                "content": f"Analyze these partnership trends:\n\n{json.dumps(trends_data, indent=2)}"
            }
        ]
        
        try:
            response = self.llm.chat_completion(
                messages,
                temperature=0.7,
                max_tokens=250,
                quick_mode=True,
                fallback_response=None
            )
            
            if response:
                return response
                
        except Exception as e:
            logger.error(f"Error in AI trend analysis: {e}")
        
        return self._fallback_analyze_trends(trends_data)
    
    def _fallback_analyze_trends(self, trends_data: Dict) -> str:
        """Rule-based trend analysis"""
        insights = []
        
        # Growth insights
        if trends_data['new_partners_last_month'] > 2:
            insights.append(f"Strong partner growth with {trends_data['new_partners_last_month']} new partners added last month.")
        elif trends_data['total_partners'] < 3:
            insights.append("Limited partner network. Consider expanding partnerships to diversify event support.")
        
        # Collaboration insights
        if trends_data['active_collaborations'] > 10:
            insights.append(f"Highly active partnership ecosystem with {trends_data['active_collaborations']} ongoing collaborations.")
        
        # Performance insights
        if trends_data['avg_contribution_score_recent'] > 0.6:
            insights.append(f"Strong partnership performance with {trends_data['avg_contribution_score_recent']:.2f} average contribution score.")
        elif trends_data['avg_contribution_score_recent'] < 0.4 and trends_data['avg_contribution_score_recent'] > 0:
            insights.append("Partnership performance below optimal levels. Review collaboration strategies and partner selection.")
        
        # Type distribution insights
        collab_types = trends_data['collaboration_type_distribution']
        if len(collab_types) == 1:
            insights.append("Consider diversifying collaboration types to maximize partnership value.")
        
        return " ".join(insights) if insights else "Establish more partnerships to enable meaningful trend analysis."
    
    # ==================== BULK OPERATIONS ====================
    
    def bulk_analyze_partners(self, organizer_id: int) -> Dict:
        """
        Analyze all partners for an organizer at once
        
        Args:
            organizer_id: Organizer whose partners to analyze
        
        Returns:
            dict: Bulk analysis results
        """
        organizer = Organizer.query.get(organizer_id)
        if not organizer:
            return {"error": "Organizer not found"}
        
        partners = [p for p in organizer.partners if p.is_active]
        
        if not partners:
            return {
                "organizer_id": organizer_id,
                "total_partners": 0,
                "message": "No active partners to analyze"
            }
        
        analyses = []
        high_performers = []
        needs_attention = []
        
        for partner in partners:
            stats = self._calculate_partner_stats(partner)
            
            analysis = {
                "partner_id": partner.id,
                "partner_name": partner.company_name,
                "performance_score": stats['performance_score'],
                "total_collaborations": stats['total_collaborations'],
                "active_collaborations": stats['active_collaborations']
            }
            
            analyses.append(analysis)
            
            # Categorize partners
            if stats['performance_score'] > 0.7:
                high_performers.append(analysis)
            elif stats['performance_score'] < 0.4:
                needs_attention.append(analysis)
        
        return {
            "organizer_id": organizer_id,
            "total_partners": len(partners),
            "analyses": analyses,
            "high_performers": high_performers,
            "needs_attention": needs_attention,
            "summary": {
                "high_performers_count": len(high_performers),
                "needs_attention_count": len(needs_attention),
                "average_performance": round(sum(a['performance_score'] for a in analyses) / len(analyses), 2)
            },
            "generated_at": datetime.utcnow().isoformat()
        }
    
    # ==================== VALIDATION & UTILITIES ====================
    
    def validate_partner_data(self, partner_data: Dict) -> Dict:
        """
        Validate partner data before creation/update
        
        Args:
            partner_data: Partner information to validate
        
        Returns:
            dict: Validation result with suggestions
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": []
        }
        
        # Required fields
        if 'company_name' not in partner_data or not partner_data['company_name']:
            result["valid"] = False
            result["errors"].append("Company name is required")
        elif len(partner_data['company_name']) < 2:
            result["valid"] = False
            result["errors"].append("Company name must be at least 2 characters")
        
        # Optional but recommended fields
        if 'company_description' not in partner_data or not partner_data['company_description']:
            result["suggestions"].append("Adding a description helps attract better collaborations")
        
        if 'website_url' not in partner_data or not partner_data['website_url']:
            result["suggestions"].append("Including a website URL increases partner credibility")
        
        if 'logo_url' not in partner_data or not partner_data['logo_url']:
            result["suggestions"].append("Upload a logo for better visual presentation")
        
        # Contact information
        if 'contact_email' not in partner_data and 'contact_person' not in partner_data:
            result["warnings"].append("No contact information provided - this may limit communication")
        
        return result
    
    def suggest_collaboration_terms(self, event_id: int, partner_id: int) -> Optional[Dict]:
        """
        Suggest appropriate collaboration terms
        
        Args:
            event_id: Event for collaboration
            partner_id: Partner to collaborate with
        
        Returns:
            dict: Suggested terms
        """
        event = Event.query.get(event_id)
        partner = Partner.query.get(partner_id)
        
        if not event or not partner:
            return None
        
        # Base suggestions
        terms = {
            "suggested_collaboration_type": "Partner",
            "deliverables": [
                "Logo placement on event materials",
                "Social media mentions"
            ],
            "duration": "Event duration plus 7 days pre-promotion",
            "visibility": "Standard partner visibility on event page"
        }
        
        # Adjust based on partner history
        past_collabs = [c for c in partner.collaborations if c.is_active]
        if len(past_collabs) > 5:
            terms["suggested_collaboration_type"] = "Official Partner"
            terms["deliverables"].extend([
                "Featured placement in promotional materials",
                "Speaking opportunity or booth space"
            ])
            terms["visibility"] = "Premium placement"
        
        # Adjust based on event category
        if event.event_category:
            if event.event_category.name.lower() in ['conference', 'seminar', 'workshop']:
                terms["deliverables"].append("Materials distribution opportunity")
        
        return terms
    
    def find_similar_partners(self, partner_id: int, limit: int = 5) -> List[Partner]:
        """
        Find similar partners based on profile and performance
        
        Args:
            partner_id: Reference partner
            limit: Maximum results
        
        Returns:
            list: Similar partners
        """
        partner = Partner.query.get(partner_id)
        if not partner:
            return []
        
        # Get all partners from same organizer
        all_partners = Partner.query.filter(
            Partner.organizer_id == partner.organizer_id,
            Partner.id != partner_id,
            Partner.is_active == True
        ).all()
        
        similar = []
        
        for p in all_partners:
            similarity_score = 0.0
            
            # Compare performance scores
            if partner.performance_score and p.performance_score:
                perf_diff = abs(partner.performance_score - p.performance_score)
                similarity_score += (1 - perf_diff) * 0.4
            
            # Compare collaboration counts
            partner_collabs = len([c for c in partner.collaborations if c.is_active])
            p_collabs = len([c for c in p.collaborations if c.is_active])
            
            if partner_collabs > 0 or p_collabs > 0:
                max_collabs = max(partner_collabs, p_collabs)
                min_collabs = min(partner_collabs, p_collabs)
                similarity_score += (min_collabs / max_collabs) * 0.3
            
            # Compare collaboration types
            partner_types = set(c.collaboration_type for c in partner.collaborations if c.is_active)
            p_types = set(c.collaboration_type for c in p.collaborations if c.is_active)
            
            if partner_types and p_types:
                type_overlap = len(partner_types.intersection(p_types)) / len(partner_types.union(p_types))
                similarity_score += type_overlap * 0.3
            
            if similarity_score > 0.3:  # Threshold for similarity
                similar.append((p, similarity_score))
        
        # Sort by similarity and return top matches
        similar.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in similar[:limit]]
    
    def get_partner_recommendations_summary(self, organizer_id: int) -> Dict:
        """
        Get summary of all active recommendations for an organizer
        
        Args:
            organizer_id: Organizer to check
        
        Returns:
            dict: Summary of recommendations
        """
        now = datetime.utcnow()
        
        # Get active recommendations
        recommendations = AIPartnerMatchRecommendation.query.filter(
            AIPartnerMatchRecommendation.organizer_id == organizer_id,
            AIPartnerMatchRecommendation.is_active == True,
            AIPartnerMatchRecommendation.expires_at > now
        ).all()
        
        # Get active insights
        insights = AIPartnerInsight.query.join(Partner).filter(
            Partner.organizer_id == organizer_id,
            AIPartnerInsight.is_active == True,
            AIPartnerInsight.is_read == False
        ).all()
        
        # Categorize recommendations
        high_priority = [r for r in recommendations if r.match_score > 0.8]
        pending_review = [r for r in recommendations if not r.is_viewed]
        
        # Categorize insights
        critical_insights = [i for i in insights if i.priority == 'critical']
        high_priority_insights = [i for i in insights if i.priority == 'high']
        
        return {
            "total_recommendations": len(recommendations),
            "high_priority_matches": len(high_priority),
            "pending_review": len(pending_review),
            "total_insights": len(insights),
            "critical_insights": len(critical_insights),
            "high_priority_insights": len(high_priority_insights),
            "recommendations": [r.as_dict() for r in recommendations[:10]],  # Top 10
            "insights": [i.as_dict() for i in insights[:10]],  # Top 10
            "generated_at": datetime.utcnow().isoformat()
        }


# Singleton instance
partner_assistant = PartnerAssistant()