"""
AI Category Assistant - Helps with category creation, updates, and management
Enhanced with graceful degradation and better error handling
"""

from typing import Dict, Optional, List
import logging
from ai.llm_client import llm_client
from model import Category, db, Event
from datetime import datetime
from sqlalchemy import func
import json
import re

logger = logging.getLogger(__name__)


class CategoryAssistant:
    """AI assistant for category management operations with fallback logic"""
    
    def __init__(self):
        self.llm = llm_client
    
    def suggest_category_from_description(self, description: str) -> Optional[Dict]:
        """
        Suggest category name and details based on a description
        Falls back to rule-based suggestions if AI is unavailable
        
        Args:
            description: User's description of what they want
        
        Returns:
            dict: Suggested category details or None
        """
        if not self.llm.is_enabled():
            logger.info("AI unavailable, using rule-based category suggestion")
            return self._fallback_category_suggestion(description)
        
        messages = [
            self.llm.build_system_message(
                "You are helping create event categories. Suggest a concise category name "
                "and description based on user input. Respond ONLY with valid JSON format with keys: "
                "'name' (2-3 words max), 'description' (1-2 sentences), 'keywords' (array of 3-5 keywords). "
                "Do not include any markdown formatting or code blocks."
            ),
            {
                "role": "user",
                "content": f"Create a category for: {description}"
            }
        ]
        
        try:
            response = self.llm.chat_completion(
                messages, 
                temperature=0.7,
                quick_mode=True,  # Don't retry extensively for suggestions
                fallback_response=None
            )
            
            if response:
                # Clean response - remove markdown if present
                cleaned = response.strip()
                if cleaned.startswith('```'):
                    # Extract JSON from code block
                    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
                    if json_match:
                        cleaned = json_match.group(1)
                    else:
                        cleaned = cleaned.replace('```json', '').replace('```', '').strip()
                
                result = json.loads(cleaned)
                
                # Validate structure
                if 'name' in result and 'description' in result:
                    logger.info("AI category suggestion generated successfully")
                    return result
                else:
                    logger.warning("AI response missing required fields, using fallback")
                    return self._fallback_category_suggestion(description)
                    
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return self._fallback_category_suggestion(description)
        except Exception as e:
            logger.error(f"Error suggesting category: {e}")
            return self._fallback_category_suggestion(description)
        
        return self._fallback_category_suggestion(description)
    
    def _fallback_category_suggestion(self, description: str) -> Dict:
        """Rule-based fallback for category suggestions"""
        # Extract potential category name (first few words)
        words = description.strip().split()
        name = ' '.join(words[:3]).title()
        
        # Generate basic keywords
        keywords = [w.lower() for w in words[:5] if len(w) > 3]
        
        return {
            "name": name,
            "description": description[:200],  # Truncate to reasonable length
            "keywords": keywords[:5],
            "source": "fallback"  # Indicate this was a fallback suggestion
        }
    
    def enhance_category_description(self, name: str, current_description: str = None) -> Optional[str]:
        """
        Enhance or generate a category description using AI
        Returns original or basic description if AI unavailable
        
        Args:
            name: Category name
            current_description: Existing description to enhance
        
        Returns:
            str: Enhanced description or fallback
        """
        if not self.llm.is_enabled():
            logger.info("AI unavailable, using fallback description")
            return self._fallback_description(name, current_description)
        
        if current_description:
            prompt = f"Enhance this category description. Category: '{name}'. Current: '{current_description}'. Make it engaging and informative in 2-3 sentences."
        else:
            prompt = f"Write an engaging 2-3 sentence description for an event category named '{name}'."
        
        messages = [
            self.llm.build_system_message("You write clear, engaging event category descriptions."),
            {"role": "user", "content": prompt}
        ]
        
        enhanced = self.llm.chat_completion(
            messages, 
            temperature=0.7, 
            max_tokens=150,
            quick_mode=True,
            fallback_response=None
        )
        
        return enhanced if enhanced else self._fallback_description(name, current_description)
    
    def _fallback_description(self, name: str, current_description: str = None) -> str:
        """Generate basic description when AI is unavailable"""
        if current_description:
            return current_description
        return f"Events and activities related to {name.lower()}."
    
    def suggest_keywords(self, category_name: str, description: str = None) -> Optional[List[str]]:
        """
        Generate relevant keywords for better event matching
        Falls back to basic keyword extraction if AI unavailable
        
        Args:
            category_name: Name of category
            description: Category description
        
        Returns:
            list: Keywords or fallback list
        """
        if not self.llm.is_enabled():
            logger.info("AI unavailable, using fallback keyword extraction")
            return self._fallback_keywords(category_name, description)
        
        context = f"Category: {category_name}"
        if description:
            context += f"\nDescription: {description}"
        
        messages = [
            self.llm.build_system_message(
                "Generate 5-10 relevant keywords for event categorization. "
                "Return ONLY a comma-separated list of keywords, no other text."
            ),
            {"role": "user", "content": context}
        ]
        
        response = self.llm.chat_completion(
            messages, 
            temperature=0.5, 
            max_tokens=100,
            quick_mode=True,
            fallback_response=None
        )
        
        if response:
            # Clean and parse keywords
            keywords = [k.strip().lower() for k in response.split(',')]
            keywords = [k for k in keywords if k and len(k) > 2]  # Filter short/empty
            return keywords[:10]  # Limit to 10
        
        return self._fallback_keywords(category_name, description)
    
    def _fallback_keywords(self, category_name: str, description: str = None) -> List[str]:
        """Extract basic keywords when AI is unavailable"""
        keywords = set()
        
        # Add words from category name
        name_words = [w.lower() for w in category_name.split() if len(w) > 2]
        keywords.update(name_words)
        
        # Add words from description
        if description:
            desc_words = [w.lower().strip('.,!?') for w in description.split() if len(w) > 3]
            keywords.update(desc_words[:7])
        
        return list(keywords)[:10]
    
    def suggest_similar_categories(self, category_name: str) -> List[Category]:
        """
        Find similar existing categories to avoid duplicates
        Uses database queries, no AI required
        
        Args:
            category_name: Name to check
        
        Returns:
            list: Similar categories
        """
        try:
            all_categories = Category.query.all()
            similar = []
            
            name_lower = category_name.lower()
            for cat in all_categories:
                cat_name_lower = cat.name.lower()
                # Check for substring matches or very similar names
                if (name_lower in cat_name_lower or 
                    cat_name_lower in name_lower or
                    self._calculate_similarity(name_lower, cat_name_lower) > 0.7):
                    similar.append(cat)
            
            return similar
        except Exception as e:
            logger.error(f"Error finding similar categories: {e}")
            return []
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Simple Jaccard similarity for strings"""
        set1 = set(str1.split())
        set2 = set(str2.split())
        
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        return intersection / union if union > 0 else 0.0
    
    def validate_category_update(self, category: Category, updates: Dict) -> Dict:
        """
        Validate and suggest improvements for category updates
        Database-driven validation, no AI required
        
        Args:
            category: Category being updated
            updates: Proposed updates
        
        Returns:
            dict: Validation result with suggestions
        """
        result = {
            "valid": True,
            "warnings": [],
            "suggestions": []
        }
        
        try:
            # Check if renaming would create duplicates
            if 'name' in updates and updates['name'] != category.name:
                similar = self.suggest_similar_categories(updates['name'])
                if similar:
                    result["warnings"].append(
                        f"Similar categories exist: {', '.join(c.name for c in similar[:3])}"
                    )
            
            # Check impact of changes
            event_count = len(category.events) if hasattr(category, 'events') else 0
            if event_count > 0:
                result["warnings"].append(
                    f"This category has {event_count} events. Changes will affect all of them."
                )
            
            # Suggest description enhancement if not provided
            if 'description' not in updates and not category.description:
                result["suggestions"].append(
                    "Consider adding a description to help users find relevant events."
                )
            
            # Validate name length
            if 'name' in updates:
                if len(updates['name']) < 3:
                    result["valid"] = False
                    result["warnings"].append("Category name must be at least 3 characters long.")
                elif len(updates['name']) > 100:
                    result["valid"] = False
                    result["warnings"].append("Category name must be less than 100 characters.")
        
        except Exception as e:
            logger.error(f"Error validating category update: {e}")
            result["warnings"].append("Could not complete all validation checks.")
        
        return result
    
    def generate_category_insights(self, category_id: int) -> Optional[Dict]:
        """
        Generate insights about a category's performance
        Provides basic stats always, AI insights when available
        
        Args:
            category_id: Category to analyze
        
        Returns:
            dict: Insights with stats
        """
        try:
            category = Category.query.get(category_id)
            if not category:
                return None
            
            # Gather statistics (always available)
            total_events = len(category.events) if hasattr(category, 'events') else 0
            
            future_events = 0
            past_events = 0
            if total_events > 0:
                future_events = Event.query.filter(
                    Event.category_id == category_id,
                    Event.date >= datetime.utcnow().date()
                ).count()
                past_events = total_events - future_events
            
            stats = {
                "total_events": total_events,
                "future_events": future_events,
                "past_events": past_events,
                "popularity_score": getattr(category, 'popularity_score', 0),
                "trending_score": getattr(category, 'trending_score', 0)
            }
            
            # Try to generate AI insights
            insights_text = None
            if self.llm.is_enabled():
                messages = [
                    self.llm.build_system_message(
                        "Analyze category performance data and provide 2-3 concise, actionable insights."
                    ),
                    {
                        "role": "user",
                        "content": f"Category: {category.name}\nStats: {json.dumps(stats)}\n\n"
                                  f"Provide key insights and recommendations."
                    }
                ]
                
                insights_text = self.llm.chat_completion(
                    messages, 
                    temperature=0.7, 
                    max_tokens=200,
                    quick_mode=True,
                    fallback_response=None
                )
            
            # Generate fallback insights if AI unavailable
            if not insights_text:
                insights_text = self._generate_fallback_insights(category.name, stats)
            
            return {
                "stats": stats,
                "insights": insights_text,
                "generated_at": datetime.utcnow().isoformat(),
                "ai_powered": self.llm.is_enabled()
            }
        
        except Exception as e:
            logger.error(f"Error generating category insights: {e}")
            return None
    
    def _generate_fallback_insights(self, category_name: str, stats: Dict) -> str:
        """Generate basic insights when AI is unavailable"""
        insights = []
        
        total = stats.get('total_events', 0)
        future = stats.get('future_events', 0)
        past = stats.get('past_events', 0)
        
        if total == 0:
            insights.append(f"No events in the '{category_name}' category yet. Consider promoting this category to attract event organizers.")
        elif future == 0 and past > 0:
            insights.append(f"All {total} events in this category are in the past. Encourage new event creation.")
        elif future > past:
            insights.append(f"Strong upcoming activity with {future} future events scheduled.")
        
        if stats.get('trending_score', 0) > 0.7:
            insights.append("This category is currently trending. Consider featuring it prominently.")
        
        if not insights:
            insights.append(f"Category has {total} total events with {future} upcoming.")
        
        return " ".join(insights)
    
    def process_natural_language_query(self, query: str, user_id: int) -> Dict:
        """
        Process natural language queries about categories
        Falls back to pattern matching if AI unavailable
        
        Args:
            query: User's question or request
            user_id: User making the request
        
        Returns:
            dict: Response with action and data
        """
        if not self.llm.is_enabled():
            logger.info("AI unavailable, using pattern-based query processing")
            return self._process_query_with_patterns(query, user_id)
        
        # Analyze intent with AI
        messages = [
            self.llm.build_system_message(
                "You help with event category management. Determine user intent and respond with ONLY valid JSON, no markdown. "
                "Possible intents: 'create', 'update', 'delete', 'list', 'search', 'analyze', 'help'. "
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
                # Clean response
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
                else:
                    logger.warning("AI response missing intent, using pattern matching")
                    return self._process_query_with_patterns(query, user_id)
                    
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI query response: {e}")
            return self._process_query_with_patterns(query, user_id)
        except Exception as e:
            logger.error(f"Error processing NL query: {e}")
            return self._process_query_with_patterns(query, user_id)
        
        return self._process_query_with_patterns(query, user_id)
    
    def _process_query_with_patterns(self, query: str, user_id: int) -> Dict:
        """Pattern-based query processing fallback"""
        query_lower = query.lower()
        
        # Create patterns
        if any(word in query_lower for word in ['create', 'add', 'new', 'make']):
            return {
                "intent": "create",
                "params": {},
                "message": "I can help you create a new category. Please provide the category details."
            }
        
        elif any(word in query_lower for word in ['update', 'edit', 'change', 'modify']):
            return {
                "intent": "update",
                "params": {},
                "message": "I can help you update a category. Which category would you like to modify?"
            }
        
        elif any(word in query_lower for word in ['delete', 'remove']):
            return {
                "intent": "delete",
                "params": {},
                "message": "I can help you delete a category. Which one would you like to remove?"
            }
        
        elif any(word in query_lower for word in ['list', 'show', 'display', 'all']):
            return {
                "intent": "list",
                "params": {},
                "message": "I'll show you all available categories."
            }
        
        elif any(word in query_lower for word in ['search', 'find', 'look']):
            return {
                "intent": "search",
                "params": {},
                "message": "What category are you looking for?"
            }
        
        elif any(word in query_lower for word in ['analyze', 'stats', 'insights', 'performance']):
            return {
                "intent": "analyze",
                "params": {},
                "message": "I can provide insights about a category. Which one would you like to analyze?"
            }
        
        else:
            return {
                "intent": "help",
                "params": {},
                "message": "I can help you create, update, delete, list, search, or analyze categories. What would you like to do?"
            }


# Singleton instance
category_assistant = CategoryAssistant()