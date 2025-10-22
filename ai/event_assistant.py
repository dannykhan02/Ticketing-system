"""
COMPREHENSIVE EVENT LLM ASSISTANT
AI-powered event creation, management, and optimization
Unified assistant handling complete event lifecycle with intelligent suggestions
"""

from typing import Dict, Optional, List, Any, Tuple
import logging
from datetime import datetime, date, time, timedelta
import json
import re
from decimal import Decimal
from functools import wraps, lru_cache
import time

from ai.llm_client import llm_client
from model import (
    db, Event, AIEventDraft, AIEventAssistanceLog, Category, Organizer,
    AIEventManager, AIManager, AIIntentType, AIActionStatus, TicketType,
    TicketTypeEnum, Partner, EventCollaboration, CollaborationType,
    AIAnalyticsCache, AIInsight, AIPricingRecommendation, CollaborationManager,
    Currency, ExchangeRate, Report, Transaction, User
)

logger = logging.getLogger(__name__)


class ComprehensiveEventAssistant:
    """
    Comprehensive AI assistant for complete event lifecycle management
    Handles creation, optimization, partnerships, ticketing, and analytics
    """
    
    def __init__(self):
        self.llm = llm_client
        self.required_fields = [
            'name', 'description', 'date', 'start_time', 'city', 'location'
        ]
        self.optimization_fields = [
            'category_id', 'amenities', 'end_time', 'image', 'ticket_strategy'
        ]
        
    # ===== RATE LIMITING & CACHING =====
    
    def rate_limit(max_per_minute: int = 30):
        """Decorator for rate limiting method calls"""
        def decorator(func):
            calls = []
            @wraps(func)
            def wrapper(self, *args, **kwargs):
                now = time.time()
                # Clean old calls
                calls[:] = [call for call in calls if now - call < 60]
                if len(calls) >= max_per_minute:
                    raise Exception(f"Rate limit exceeded: {max_per_minute} calls per minute")
                calls.append(now)
                return func(self, *args, **kwargs)
            return wrapper
        return decorator
    
    @lru_cache(maxsize=100)
    def _cached_category_suggestions(self, description: str) -> Optional[Dict]:
        """Cached category suggestions for similar descriptions"""
        from .category_assistant import category_assistant
        return category_assistant.suggest_category_from_description(description)
    
    # ===== COMPREHENSIVE EVENT CREATION =====
    
    @rate_limit(max_per_minute=20)
    def create_event_conversational(self, organizer_id: int, user_input: str, 
                                  context: Dict = None) -> Dict:
        """
        Complete conversational event creation with context awareness
        
        Args:
            organizer_id: Organizer creating the event
            user_input: Natural language event description
            context: Additional context (previous events, preferences, etc.)
            
        Returns:
            dict: Complete creation result with draft and suggestions
        """
        try:
            # Step 1: Extract and structure data
            extraction_result = self._comprehensive_data_extraction(user_input, context)
            
            # Step 2: Create enhanced draft
            draft = self._create_enhanced_draft(organizer_id, extraction_result, context)
            
            # Step 3: Generate intelligent suggestions
            suggestions = self._generate_comprehensive_suggestions(draft, extraction_result)
            
            # Step 4: Create initial ticket strategy
            ticket_strategy = self._suggest_initial_ticket_strategy(draft)
            
            # Step 5: Partner recommendations
            partner_recommendations = self._suggest_initial_partners(draft)
            
            # Step 6: Generate natural response
            response = self._generate_conversational_response(
                draft, suggestions, ticket_strategy, partner_recommendations
            )
            
            # Log the creation
            AIManager.log_action(
                user_id=Organizer.query.get(organizer_id).user_id,
                action_type=AIIntentType.CREATE_EVENT,
                action_description=f"Started comprehensive event creation: {draft.suggested_name}",
                target_table='ai_event_drafts',
                target_id=draft.id
            )
            
            return {
                "success": True,
                "draft_id": draft.id,
                "draft_summary": self._get_draft_summary(draft),
                "suggestions": suggestions,
                "ticket_strategy": ticket_strategy,
                "partner_recommendations": partner_recommendations,
                "conversational_response": response,
                "completion_status": self._get_completion_status(draft),
                "next_steps": self._get_creation_next_steps(draft, suggestions),
                "ai_confidence": self._calculate_overall_confidence(draft)
            }
            
        except Exception as e:
            logger.error(f"Comprehensive event creation failed: {e}")
            return self._handle_creation_error(e, user_input, organizer_id)
    
    def _comprehensive_data_extraction(self, user_input: str, context: Dict = None) -> Dict:
        """Advanced data extraction with context awareness"""
        if not self.llm.is_enabled():
            return self._advanced_fallback_extraction(user_input, context)
        
        context_str = json.dumps(context, default=str) if context else "No context"
        
        messages = [
            self.llm.build_system_message(
                "You are an expert event data extractor with context awareness. "
                "Extract ALL possible event details and infer missing information from context. "
                "Consider: event type, audience, budget, goals, timing preferences. "
                "Respond with comprehensive JSON including: "
                "basic_info: {name, description, date, times, location, city}, "
                "categorization: {primary_category, secondary_categories, tags, audience_type}, "
                "logistics: {expected_attendance, budget_range, complexity_level}, "
                "preferences: {format_preference, timing_preference, location_preference}, "
                "inferred_details: {seasonality, competition_analysis, opportunity_areas}"
            ),
            {
                "role": "user",
                "content": f"User input: {user_input}\nContext: {context_str}"
            }
        ]
        
        try:
            response = self.llm.chat_completion(
                messages,
                temperature=0.4,
                max_tokens=500,
                quick_mode=False,
                fallback_response=None
            )
            
            if response:
                cleaned = self._clean_json_response(response)
                extracted = json.loads(cleaned)
                return self._validate_and_enrich_extraction(extracted, context)
                
        except Exception as e:
            logger.error(f"Advanced extraction failed: {e}")
        
        return self._advanced_fallback_extraction(user_input, context)
    
    def _advanced_fallback_extraction(self, user_input: str, context: Dict = None) -> Dict:
        """Sophisticated fallback extraction with pattern matching"""
        extracted = {
            "basic_info": {},
            "categorization": {},
            "logistics": {},
            "preferences": {},
            "inferred_details": {}
        }
        
        text_lower = user_input.lower()
        
        # Enhanced basic info extraction
        extracted["basic_info"] = self._extract_basic_info_advanced(user_input)
        
        # Categorization
        extracted["categorization"] = self._categorize_event_advanced(text_lower)
        
        # Logistics inference
        extracted["logistics"] = self._infer_logistics(text_lower, context)
        
        # Preferences detection
        extracted["preferences"] = self._detect_preferences(text_lower)
        
        return extracted
    
    def _extract_basic_info_advanced(self, text: str) -> Dict:
        """Advanced pattern-based basic info extraction"""
        info = {}
        
        # Date extraction with multiple formats
        date_patterns = [
            r'(\d{4}-\d{2}-\d{2})',
            r'(\d{1,2}/\d{1,2}/\d{4})',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',
            r'(?:on|date)\s+(\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                info['date'] = match.group(1)
                break
        
        # Time extraction
        time_pattern = r'(\d{1,2}):(\d{2})\s*(?:(am|pm|AM|PM))?\b'
        times = re.findall(time_pattern, text)
        if times:
            info['start_time'] = f"{times[0][0]}:{times[0][1]}{times[0][2] or ''}"
            if len(times) > 1:
                info['end_time'] = f"{times[1][0]}:{times[1][1]}{times[1][2] or ''}"
        
        # Location extraction with common venues
        nairobi_venues = ['kicc', 'carnivore', 'sarit', 'village market', 'two rivers', 'westgate']
        for venue in nairobi_venues:
            if venue in text.lower():
                info['city'] = 'Nairobi'
                info['location'] = venue.title()
                break
        
        return info
    
    def _create_enhanced_draft(self, organizer_id: int, extraction_result: Dict, context: Dict) -> AIEventDraft:
        """Create a draft with comprehensive AI enhancements"""
        basic_info = extraction_result.get('basic_info', {})
        
        # Create initial draft
        draft = AIEventManager.create_draft_from_conversation(
            organizer_id=organizer_id,
            user_input=basic_info,
            conversation_id=context.get('conversation_id') if context else None
        )
        
        # Apply comprehensive enhancements
        draft = self._apply_ai_enhancements(draft, extraction_result, context)
        
        return draft
    
    def _apply_ai_enhancements(self, draft: AIEventDraft, extraction_result: Dict, context: Dict) -> AIEventDraft:
        """Apply all AI enhancements to the draft"""
        
        # Name generation and enhancement
        if not draft.suggested_name or draft.name_confidence < 0.7:
            name_result = self._generate_optimized_event_name(draft, extraction_result)
            draft.suggested_name = name_result['name']
            draft.name_confidence = name_result['confidence']
            draft.name_source = 'ai_enhanced'
        
        # Description enhancement
        if not draft.suggested_description or draft.description_confidence < 0.6:
            desc_result = self._generate_comprehensive_description(draft, extraction_result)
            draft.suggested_description = desc_result['description']
            draft.description_confidence = desc_result['confidence']
            draft.description_source = 'ai_enhanced'
        
        # Category optimization
        if not draft.suggested_category_id or draft.category_confidence < 0.8:
            category_result = self._optimize_category_selection(draft, extraction_result)
            if category_result:
                draft.suggested_category_id = category_result['category_id']
                draft.category_confidence = category_result['confidence']
                draft.category_source = 'ai_optimized'
        
        # Smart amenities suggestion
        amenities_result = self._suggest_contextual_amenities(draft, extraction_result, context)
        draft.suggested_amenities = amenities_result
        
        # Timing optimization
        if draft.suggested_date and not draft.suggested_start_time:
            timing_result = self._optimize_event_timing(draft, extraction_result)
            if timing_result:
                draft.suggested_start_time = timing_result['start_time']
                draft.suggested_end_time = timing_result.get('end_time')
        
        draft.updated_at = datetime.utcnow()
        draft.ai_iterations += 1
        db.session.commit()
        
        return draft
    
    # ===== INTELLIGENT SUGGESTION SYSTEMS =====
    
    def _generate_comprehensive_suggestions(self, draft: AIEventDraft, extraction_result: Dict) -> Dict:
        """Generate comprehensive suggestions for event improvement"""
        suggestions = {
            "immediate_actions": [],
            "optimization_opportunities": [],
            "risk_mitigations": [],
            "growth_opportunities": [],
            "competitive_advantages": []
        }
        
        # Immediate actions (missing required fields)
        missing_fields = self._identify_missing_required_fields(draft)
        if missing_fields:
            suggestions["immediate_actions"].extend([
                f"Provide {field.replace('_', ' ')}" for field in missing_fields
            ])
        
        # Optimization opportunities
        optimization_ops = self._identify_optimization_opportunities(draft, extraction_result)
        suggestions["optimization_opportunities"].extend(optimization_ops)
        
        # Risk analysis
        risks = self._analyze_potential_risks(draft, extraction_result)
        suggestions["risk_mitigations"].extend(risks)
        
        # Growth opportunities
        growth_ops = self._identify_growth_opportunities(draft, extraction_result)
        suggestions["growth_opportunities"].extend(growth_ops)
        
        # Competitive advantages
        advantages = self._identify_competitive_advantages(draft, extraction_result)
        suggestions["competitive_advantages"].extend(advantages)
        
        return suggestions
    
    def _identify_optimization_opportunities(self, draft: AIEventDraft, extraction_result: Dict) -> List[str]:
        """Identify opportunities for event optimization"""
        opportunities = []
        
        # Pricing optimization
        if not hasattr(draft, 'ticket_strategy') or not draft.ticket_strategy:
            opportunities.append("Implement tiered ticket pricing strategy")
        
        # Timing optimization
        if draft.suggested_date:
            days_until = (draft.suggested_date - date.today()).days
            if days_until > 60:
                opportunities.append("Consider early bird pricing for long lead times")
            elif days_until < 14:
                opportunities.append("Implement last-minute promotion strategy")
        
        # Category optimization
        categorization = extraction_result.get('categorization', {})
        if len(categorization.get('secondary_categories', [])) < 2:
            opportunities.append("Add secondary categories to reach broader audience")
        
        return opportunities
    
    def _analyze_potential_risks(self, draft: AIEventDraft, extraction_result: Dict) -> List[str]:
        """Analyze and suggest risk mitigations"""
        risks = []
        
        # Date risks
        if draft.suggested_date:
            if (draft.suggested_date - date.today()).days < 7:
                risks.append("Short timeline: Consider aggressive marketing or extend date")
            
            # Check for holiday conflicts
            if self._is_holiday_period(draft.suggested_date):
                risks.append("Event during holiday period: Plan for potential lower attendance")
        
        # Location risks
        if draft.suggested_city == 'Nairobi' and not draft.suggested_location:
            risks.append("Nairobi location not specified: Choose venue for better planning")
        
        # Competition analysis
        similar_events = self._find_competing_events(draft)
        if similar_events:
            risks.append(f"Found {len(similar_events)} similar events: Differentiate your offering")
        
        return risks
    
    # ===== TICKETING & PRICING INTELLIGENCE =====
    
    def _suggest_initial_ticket_strategy(self, draft: AIEventDraft) -> Dict:
        """Suggest comprehensive ticket strategy"""
        strategy = {
            "ticket_tiers": [],
            "pricing_strategy": {},
            "sales_forecast": {},
            "recommendations": []
        }
        
        # Base ticket tiers based on event type
        base_tiers = self._get_base_ticket_tiers(draft)
        strategy["ticket_tiers"] = base_tiers
        
        # Pricing strategy
        strategy["pricing_strategy"] = self._suggest_pricing_strategy(draft, base_tiers)
        
        # Sales forecast
        strategy["sales_forecast"] = self._generate_sales_forecast(draft, base_tiers)
        
        # Recommendations
        strategy["recommendations"] = self._generate_ticket_recommendations(draft, base_tiers)
        
        return strategy
    
    def _get_base_ticket_tiers(self, draft: AIEventDraft) -> List[Dict]:
        """Get appropriate ticket tiers for event type"""
        tiers = []
        category = Category.query.get(draft.suggested_category_id) if draft.suggested_category_id else None
        category_name = category.name.lower() if category else ""
        
        if 'conference' in category_name or 'business' in category_name:
            tiers = [
                {"type": "EARLY_BIRD", "name": "Early Bird", "percentage": 0.2, "description": "Limited early pricing"},
                {"type": "REGULAR", "name": "General Admission", "percentage": 0.6, "description": "Standard pricing"},
                {"type": "VIP", "name": "VIP Access", "percentage": 0.15, "description": "Premium experience"},
                {"type": "VVIP", "name": "VVIP", "percentage": 0.05, "description": "Ultimate experience"}
            ]
        elif 'concert' in category_name or 'music' in category_name:
            tiers = [
                {"type": "REGULAR", "name": "General Admission", "percentage": 0.7, "description": "Standard access"},
                {"type": "VIP", "name": "VIP Experience", "percentage": 0.25, "description": "Premium viewing"},
                {"type": "VVIP", "name": "VVIP", "percentage": 0.05, "description": "Backstage access"}
            ]
        else:
            # Default tiers
            tiers = [
                {"type": "REGULAR", "name": "General Admission", "percentage": 0.8, "description": "Standard access"},
                {"type": "VIP", "name": "VIP", "percentage": 0.2, "description": "Enhanced experience"}
            ]
        
        return tiers
    
    def _suggest_pricing_strategy(self, draft: AIEventDraft, tiers: List[Dict]) -> Dict:
        """Suggest pricing strategy with market analysis"""
        strategy = {
            "base_price_range": {},
            "dynamic_pricing": False,
            "discount_strategy": {},
            "currency_recommendation": "KES"
        }
        
        category = Category.query.get(draft.suggested_category_id) if draft.suggested_category_id else None
        
        # Market-based pricing
        if category:
            market_data = self._get_market_pricing_data(category.name)
            strategy["base_price_range"] = market_data.get('price_range', {"min": 1000, "max": 5000})
        
        # Dynamic pricing recommendation
        if draft.suggested_date:
            days_until = (draft.suggested_date - date.today()).days
            strategy["dynamic_pricing"] = days_until > 30
        
        # Discount strategy
        strategy["discount_strategy"] = {
            "early_bird_days": 30,
            "group_discount_threshold": 5,
            "last_minute_discount_days": 7
        }
        
        return strategy
    
    # ===== PARTNERSHIP INTELLIGENCE =====
    
    def _suggest_initial_partners(self, draft: AIEventDraft) -> Dict:
        """Suggest potential partners and collaborations"""
        recommendations = {
            "strategic_partners": [],
            "media_partners": [],
            "venue_partners": [],
            "sponsorship_opportunities": []
        }
        
        organizer = Organizer.query.get(draft.organizer_id)
        if not organizer:
            return recommendations
        
        # Strategic partners
        strategic_partners = self._find_strategic_partners(draft, organizer)
        recommendations["strategic_partners"] = strategic_partners
        
        # Media partners
        media_partners = self._find_media_partners(draft, organizer)
        recommendations["media_partners"] = media_partners
        
        # Venue partners (if location not set)
        if not draft.suggested_location and draft.suggested_city:
            venue_suggestions = self._suggest_venues(draft)
            recommendations["venue_partners"] = venue_suggestions
        
        # Sponsorship opportunities
        sponsorship_ops = self._identify_sponsorship_opportunities(draft)
        recommendations["sponsorship_opportunities"] = sponsorship_ops
        
        return recommendations
    
    def _find_strategic_partners(self, draft: AIEventDraft, organizer: Organizer) -> List[Dict]:
        """Find strategic partners for the event"""
        partners = []
        
        # Get organizer's existing partners
        existing_partners = Partner.query.filter_by(
            organizer_id=organizer.id,
            is_active=True
        ).all()
        
        for partner in existing_partners:
            match_score = self._calculate_partner_match_score(partner, draft)
            if match_score > 0.6:  # Good match threshold
                partners.append({
                    "partner_id": partner.id,
                    "company_name": partner.company_name,
                    "match_score": match_score,
                    "collaboration_type": "Strategic Partner",
                    "potential_value": partner.ai_partnership_score or 0.5
                })
        
        return sorted(partners, key=lambda x: x['match_score'], reverse=True)[:5]
    
    # ===== ANALYTICS & INSIGHTS =====
    
    def generate_event_insights(self, event_id: int, analysis_type: str = "comprehensive") -> Dict:
        """Generate comprehensive insights for an event"""
        event = Event.query.get(event_id)
        if not event:
            return {"error": "Event not found"}
        
        # Check cache first
        cache_key = f"event_insights_{event_id}_{analysis_type}"
        cached = AIManager.get_cached_analytics(cache_key)
        if cached:
            return cached
        
        insights = {
            "performance_metrics": {},
            "audience_insights": {},
            "financial_analysis": {},
            "optimization_opportunities": {},
            "predictive_analytics": {}
        }
        
        # Performance metrics
        insights["performance_metrics"] = self._calculate_performance_metrics(event)
        
        # Audience insights
        insights["audience_insights"] = self._analyze_audience_behavior(event)
        
        # Financial analysis
        insights["financial_analysis"] = self._analyze_financial_performance(event)
        
        # Optimization opportunities
        insights["optimization_opportunities"] = self._identify_event_optimizations(event)
        
        # Predictive analytics
        insights["predictive_analytics"] = self._generate_predictive_insights(event)
        
        # Cache the results
        AIManager.cache_analytics(
            cache_key=cache_key,
            query_type=f"event_insights_{analysis_type}",
            result_data=insights,
            expires_in_hours=24,
            event_id=event_id
        )
        
        return insights
    
    def _calculate_performance_metrics(self, event: Event) -> Dict:
        """Calculate comprehensive performance metrics"""
        metrics = {
            "attendance_metrics": {},
            "engagement_metrics": {},
            "conversion_metrics": {},
            "financial_metrics": {}
        }
        
        # Attendance metrics
        total_tickets = sum(t.quantity for t in event.tickets)
        scanned_tickets = sum(t.quantity for t in event.tickets if t.scanned)
        
        metrics["attendance_metrics"] = {
            "total_tickets": total_tickets,
            "scanned_tickets": scanned_tickets,
            "attendance_rate": scanned_tickets / total_tickets if total_tickets > 0 else 0,
            "no_show_rate": (total_tickets - scanned_tickets) / total_tickets if total_tickets > 0 else 0
        }
        
        # Financial metrics
        total_revenue = sum(float(t.ticket_type.price) * t.quantity for t in event.tickets)
        avg_ticket_price = total_revenue / total_tickets if total_tickets > 0 else 0
        
        metrics["financial_metrics"] = {
            "total_revenue": total_revenue,
            "average_ticket_price": avg_ticket_price,
            "revenue_per_attendee": total_revenue / scanned_tickets if scanned_tickets > 0 else 0
        }
        
        return metrics
    
    # ===== CONVERSATIONAL INTERFACE =====
    
    def _generate_conversational_response(self, draft: AIEventDraft, suggestions: Dict,
                                        ticket_strategy: Dict, partner_recommendations: Dict) -> str:
        """Generate natural, conversational response for the user"""
        
        if not self.llm.is_enabled():
            return self._fallback_conversational_response(draft, suggestions)
        
        context = {
            "draft_summary": self._get_draft_summary(draft),
            "suggestions": suggestions,
            "ticket_strategy_preview": {k: v for k, v in ticket_strategy.items() if k != 'ticket_tiers'},
            "partner_count": len(partner_recommendations.get('strategic_partners', [])),
            "completion_status": self._get_completion_status(draft)
        }
        
        messages = [
            self.llm.build_system_message(
                "You are an enthusiastic event planning assistant. Generate a warm, engaging response "
                "that summarizes the event creation progress, highlights key suggestions, and guides "
                "the user on next steps. Be encouraging and professional."
            ),
            {
                "role": "user",
                "content": f"Event creation progress: {json.dumps(context, default=str)}. "
                          f"Generate a conversational response that guides the user forward."
            }
        ]
        
        try:
            response = self.llm.chat_completion(
                messages,
                temperature=0.8,
                max_tokens=300,
                quick_mode=True,
                fallback_response=None
            )
            return response if response else self._fallback_conversational_response(draft, suggestions)
            
        except Exception as e:
            logger.error(f"Conversational response generation failed: {e}")
            return self._fallback_conversational_response(draft, suggestions)
    
    # ===== HELPER METHODS =====
    
    def _get_draft_summary(self, draft: AIEventDraft) -> Dict:
        """Get clean draft summary for responses"""
        return {
            "name": draft.suggested_name,
            "description_preview": (draft.suggested_description[:100] + "...") 
                if draft.suggested_description and len(draft.suggested_description) > 100 
                else draft.suggested_description,
            "date": draft.suggested_date.isoformat() if draft.suggested_date else None,
            "city": draft.suggested_city,
            "location": draft.suggested_location,
            "category": Category.query.get(draft.suggested_category_id).name 
                if draft.suggested_category_id else None
        }
    
    def _get_completion_status(self, draft: AIEventDraft) -> Dict:
        """Get detailed completion status"""
        missing_fields = self._identify_missing_required_fields(draft)
        total_fields = len(self.required_fields)
        completed_fields = total_fields - len(missing_fields)
        
        return {
            "percent_complete": (completed_fields / total_fields) * 100,
            "completed_fields": completed_fields,
            "total_fields": total_fields,
            "missing_fields": missing_fields,
            "ready_to_publish": len(missing_fields) == 0
        }
    
    def _calculate_overall_confidence(self, draft: AIEventDraft) -> float:
        """Calculate overall AI confidence score"""
        confidences = []
        
        if draft.name_confidence:
            confidences.append(draft.name_confidence)
        if draft.description_confidence:
            confidences.append(draft.description_confidence)
        if draft.category_confidence:
            confidences.append(draft.category_confidence)
        
        return sum(confidences) / len(confidences) if confidences else 0.5
    
    def _identify_missing_required_fields(self, draft: AIEventDraft) -> List[str]:
        """Identify missing required fields"""
        missing = []
        
        field_mapping = {
            'name': 'suggested_name',
            'description': 'suggested_description',
            'date': 'suggested_date',
            'start_time': 'suggested_start_time',
            'city': 'suggested_city',
            'location': 'suggested_location'
        }
        
        for required, attr in field_mapping.items():
            if not getattr(draft, attr, None):
                missing.append(required)
        
        return missing
    
    def _clean_json_response(self, response: str) -> str:
        """Clean JSON response from markdown"""
        cleaned = response.strip()
        if cleaned.startswith('```'):
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
            if json_match:
                cleaned = json_match.group(1)
            else:
                cleaned = cleaned.replace('```json', '').replace('```', '').strip()
        return cleaned
    
    def _fallback_conversational_response(self, draft: AIEventDraft, suggestions: Dict) -> str:
        """Fallback conversational response"""
        parts = ["Great progress on your event!"]
        
        if draft.suggested_name:
            parts.append(f"Your event '{draft.suggested_name}' is taking shape.")
        
        missing = self._identify_missing_required_fields(draft)
        if missing:
            parts.append(f"To complete your event, I need: {', '.join(missing)}.")
        
        if suggestions.get('immediate_actions'):
            parts.append("Here are some suggestions to improve your event.")
        
        parts.append("Let me know what you'd like to work on next!")
        
        return " ".join(parts)
    
    def _handle_creation_error(self, error: Exception, user_input: str, organizer_id: int) -> Dict:
        """Handle creation errors gracefully"""
        error_id = f"event_creation_{int(datetime.utcnow().timestamp())}"
        logger.error(f"Creation Error {error_id}: {str(error)}")
        
        # Create basic draft as fallback
        try:
            draft = AIEventManager.create_draft_from_conversation(
                organizer_id=organizer_id,
                user_input={"raw_text": user_input}
            )
            
            return {
                "success": False,
                "error": "We encountered a technical issue",
                "error_id": error_id,
                "draft_id": draft.id,
                "recovery_suggestion": "I've saved your progress. Please try updating the fields manually.",
                "fallback_available": True
            }
        except:
            return {
                "success": False,
                "error": "We encountered a technical issue",
                "error_id": error_id,
                "recovery_suggestion": "Please try again or contact support if the issue persists."
            }
    
    # ===== BATCH OPERATIONS & MANAGEMENT =====
    
    def get_organizer_event_portfolio(self, organizer_id: int) -> Dict:
        """Get comprehensive portfolio view of organizer's events"""
        try:
            organizer = Organizer.query.get(organizer_id)
            if not organizer:
                return {"error": "Organizer not found"}
            
            # Get all events and drafts
            events = Event.query.filter_by(organizer_id=organizer_id).all()
            drafts = AIEventDraft.query.filter_by(organizer_id=organizer_id).all()
            
            # Calculate metrics
            total_revenue = sum(
                sum(float(t.ticket_type.price) * t.quantity for t in event.tickets)
                for event in events
            )
            
            total_attendees = sum(
                sum(t.quantity for t in event.tickets if t.scanned)
                for event in events
            )
            
            ai_assisted_events = [e for e in events if e.ai_assisted_creation]
            
            portfolio = {
                "summary": {
                    "total_events": len(events),
                    "total_drafts": len(drafts),
                    "total_revenue": total_revenue,
                    "total_attendees": total_attendees,
                    "ai_assisted_events": len(ai_assisted_events),
                    "ai_adoption_rate": len(ai_assisted_events) / len(events) if events else 0
                },
                "event_breakdown": {
                    "by_category": self._categorize_events(events),
                    "by_status": self._categorize_drafts(drafts),
                    "revenue_trends": self._calculate_revenue_trends(events)
                },
                "recommendations": self._generate_portfolio_recommendations(events, drafts)
            }
            
            return portfolio
            
        except Exception as e:
            logger.error(f"Portfolio analysis failed: {e}")
            return {"error": "Could not generate portfolio analysis"}
    
    def _generate_portfolio_recommendations(self, events: List[Event], drafts: List[AIEventDraft]) -> List[str]:
        """Generate portfolio-level recommendations"""
        recommendations = []
        
        # Analyze event frequency
        if len(events) > 0:
            avg_events_per_month = len(events) / 12  # Assuming 12 month history
            if avg_events_per_month < 1:
                recommendations.append("Consider increasing event frequency to build audience loyalty")
            elif avg_events_per_month > 4:
                recommendations.append("High event frequency detected. Ensure quality isn't compromised")
        
        # Draft analysis
        if drafts:
            inactive_drafts = [d for d in drafts if d.draft_status == 'in_progress']
            if len(inactive_drafts) > 3:
                recommendations.append(f"You have {len(inactive_drafts)} incomplete drafts. Consider reviewing or cleaning them up")
        
        # Category diversification
        categories = set(e.category_id for e in events if e.category_id)
        if len(categories) < 2 and len(events) > 3:
            recommendations.append("Consider diversifying into new event categories to reach broader audiences")
        
        return recommendations


# ===== COMPREHENSIVE USAGE EXAMPLES =====

"""
# Example 1: Complete Event Creation
assistant = ComprehensiveEventAssistant()

result = assistant.create_event_conversational(
    organizer_id=123,
    user_input="I want to create a tech conference in Nairobi for software developers. About 200 people, sometime in March 2024. Focus on AI and web development.",
    context={"previous_events": ["AI Summit 2023"], "preferences": {"format": "conference"}}
)

# Example 2: Portfolio Analysis
portfolio = assistant.get_organizer_event_portfolio(organizer_id=123)

# Example 3: Event Insights
insights = assistant.generate_event_insights(event_id=456, analysis_type="comprehensive")
"""

# Singleton instance
comprehensive_event_assistant = ComprehensiveEventAssistant()