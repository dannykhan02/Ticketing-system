"""
AI Category Assistant - Helps with category creation, updates, and management
"""

from typing import Dict, Optional, List
import logging
from ai.llm_client import llm_client
from model import Category, db, Event
from datetime import datetime
from sqlalchemy import func

logger = logging.getLogger(__name__)


class CategoryAssistant:
    """AI assistant for category management operations"""
    
    def __init__(self):
        self.llm = llm_client
    
    def suggest_category_from_description(self, description: str) -> Optional[Dict]:
        """
        Suggest category name and details based on a description
        
        Args:
            description: User's description of what they want
        
        Returns:
            dict: Suggested category details or None
        """
        if not self.llm.is_enabled():
            return None
        
        messages = [
            self.llm.build_system_message(
                "You are helping create event categories. Suggest a concise category name "
                "and description based on user input. Respond in JSON format with keys: "
                "'name' (2-3 words max), 'description' (1-2 sentences), 'keywords' (array of 3-5 keywords)."
            ),
            {
                "role": "user",
                "content": f"Create a category for: {description}"
            }
        ]
        
        try:
            response = self.llm.chat_completion(messages, temperature=0.7)
            if response:
                import json
                # Try to parse JSON response
                result = json.loads(response)
                return result
        except Exception as e:
            logger.error(f"Error suggesting category: {e}")
        
        return None
    
    def enhance_category_description(self, name: str, current_description: str = None) -> Optional[str]:
        """
        Enhance or generate a category description using AI
        
        Args:
            name: Category name
            current_description: Existing description to enhance
        
        Returns:
            str: Enhanced description or None
        """
        if not self.llm.is_enabled():
            return None
        
        if current_description:
            prompt = f"Enhance this category description. Category: '{name}'. Current: '{current_description}'. Make it engaging and informative in 2-3 sentences."
        else:
            prompt = f"Write an engaging 2-3 sentence description for an event category named '{name}'."
        
        messages = [
            self.llm.build_system_message("You write clear, engaging event category descriptions."),
            {"role": "user", "content": prompt}
        ]
        
        return self.llm.chat_completion(messages, temperature=0.7, max_tokens=150)
    
    def suggest_keywords(self, category_name: str, description: str = None) -> Optional[List[str]]:
        """
        Generate relevant keywords for better event matching
        
        Args:
            category_name: Name of category
            description: Category description
        
        Returns:
            list: Keywords or None
        """
        if not self.llm.is_enabled():
            return None
        
        context = f"Category: {category_name}"
        if description:
            context += f"\nDescription: {description}"
        
        messages = [
            self.llm.build_system_message(
                "Generate 5-10 relevant keywords for event categorization. "
                "Return only a comma-separated list of keywords."
            ),
            {"role": "user", "content": context}
        ]
        
        response = self.llm.chat_completion(messages, temperature=0.5, max_tokens=100)
        if response:
            keywords = [k.strip() for k in response.split(',')]
            return keywords[:10]  # Limit to 10
        
        return None
    
    def suggest_similar_categories(self, category_name: str) -> List[Category]:
        """
        Find similar existing categories to avoid duplicates
        
        Args:
            category_name: Name to check
        
        Returns:
            list: Similar categories
        """
        # Simple similarity check - can be enhanced with embeddings
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
        
        # Check if renaming would create duplicates
        if 'name' in updates and updates['name'] != category.name:
            similar = self.suggest_similar_categories(updates['name'])
            if similar:
                result["warnings"].append(
                    f"Similar categories exist: {', '.join(c.name for c in similar)}"
                )
        
        # Check impact of changes
        event_count = len(category.events)
        if event_count > 0:
            result["warnings"].append(
                f"This category has {event_count} events. Changes will affect all of them."
            )
        
        # Suggest description enhancement if not provided
        if 'description' not in updates and not category.description:
            result["suggestions"].append(
                "Consider adding a description to help users find relevant events."
            )
        
        return result
    
    def generate_category_insights(self, category_id: int) -> Optional[Dict]:
        """
        Generate AI insights about a category's performance
        
        Args:
            category_id: Category to analyze
        
        Returns:
            dict: Insights or None
        """
        category = Category.query.get(category_id)
        if not category:
            return None
        
        # Gather statistics
        total_events = len(category.events)
        future_events = Event.query.filter(
            Event.category_id == category_id,
            Event.date >= datetime.utcnow().date()
        ).count()
        
        past_events = total_events - future_events
        
        # Get average ticket sales (if you have ticket/transaction data)
        # This is a placeholder - adjust based on your actual schema
        
        stats = {
            "total_events": total_events,
            "future_events": future_events,
            "past_events": past_events,
            "popularity_score": category.popularity_score,
            "trending_score": category.trending_score
        }
        
        if not self.llm.is_enabled():
            return {"stats": stats, "insights": None}
        
        # Generate AI insights
        messages = [
            self.llm.build_system_message(
                "Analyze category performance data and provide actionable insights."
            ),
            {
                "role": "user",
                "content": f"Category: {category.name}\nStats: {stats}\n\n"
                          f"Provide 2-3 key insights and recommendations."
            }
        ]
        
        insights_text = self.llm.chat_completion(messages, temperature=0.7, max_tokens=200)
        
        return {
            "stats": stats,
            "insights": insights_text,
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def process_natural_language_query(self, query: str, user_id: int) -> Dict:
        """
        Process natural language queries about categories
        
        Args:
            query: User's question or request
            user_id: User making the request
        
        Returns:
            dict: Response with action and data
        """
        if not self.llm.is_enabled():
            return {
                "action": "error",
                "message": "AI features are not enabled."
            }
        
        # Analyze intent
        messages = [
            self.llm.build_system_message(
                "You help with event category management. Determine user intent and respond with JSON. "
                "Possible intents: 'create', 'update', 'delete', 'list', 'search', 'analyze', 'help'. "
                "Format: {\"intent\": \"<intent>\", \"params\": {<extracted_params>}, \"message\": \"<user_friendly_message>\"}"
            ),
            {"role": "user", "content": query}
        ]
        
        try:
            response = self.llm.chat_completion(messages, temperature=0.3)
            if response:
                import json
                result = json.loads(response)
                return result
        except Exception as e:
            logger.error(f"Error processing NL query: {e}")
        
        return {
            "action": "error",
            "message": "I couldn't understand your request. Please try rephrasing."
        }


# Singleton instance
category_assistant = CategoryAssistant()