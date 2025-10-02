from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from model import (db, User, AIManager, AIIntentType, AIConversation, AIActionStatus,
                   Event, TicketType, Transaction, PaymentStatus, Organizer, AIMessage)
from ai.intent_classifier import IntentClassifier
from ai.action_executor import ActionExecutor
from ai.context_manager import ContextManager
from ai.response_formatter import ResponseFormatter
from datetime import datetime, timedelta
import os
import logging
import openai

logger = logging.getLogger(__name__)

class AIAssistant:
    """Main AI Assistant orchestrator"""
    
    def __init__(self):
        # Import Config here to avoid circular import
        from config import Config
        
        self.intent_classifier = IntentClassifier()
        self.action_executor = ActionExecutor()
        self.context_manager = ContextManager()
        self.response_formatter = ResponseFormatter()
        
        # Initialize OpenAI with config
        self.openai_api_key = Config.OPENAI_API_KEY
        self.ai_provider = Config.AI_PROVIDER
        self.ai_model = Config.AI_MODEL
        self.ai_temperature = Config.AI_TEMPERATURE
        self.ai_max_tokens = Config.AI_MAX_TOKENS
        self.ai_timeout = Config.AI_TIMEOUT
        self.llm_enabled = Config.ENABLE_AI_FEATURES and bool(self.openai_api_key)
        
        # Configure OpenAI client if available
        if self.llm_enabled:
            openai.api_key = self.openai_api_key
            logger.info(f"AI Assistant initialized with provider: {self.ai_provider}, model: {self.ai_model}")
        else:
            logger.warning("AI Assistant initialized without LLM support - OpenAI API key not configured")
    
    def process_query(self, user_id: int, query: str, session_id: str = None):
        """Main entry point for processing user queries"""
        try:
            # 1. Get or create conversation
            conversation = self._get_or_create_conversation(user_id, session_id)
            
            # 2. Add user message
            AIManager.add_message(
                conversation_id=conversation.id,
                role='user',
                content=query
            )
            
            # 3. Classify intent
            intent, confidence, params = self.intent_classifier.classify(query)
            
            # 4. Get conversation context
            context = self.context_manager.get_context(conversation.id)
            
            # 5. Handle the intent
            response = self._handle_intent(
                intent=intent,
                query=query,
                params=params,
                context=context,
                user_id=user_id,
                conversation_id=conversation.id
            )
            
            # 6. Format response
            formatted_response = self.response_formatter.format(response, intent)
            
            # 7. Add assistant message
            AIManager.add_message(
                conversation_id=conversation.id,
                role='assistant',
                content=formatted_response['message'],
                detected_intent=intent
            )
            
            return {
                "success": True,
                "response": formatted_response['message'],
                "intent": intent.value,
                "confidence": confidence,
                "session_id": conversation.session_id,
                "requires_confirmation": response.get('requires_confirmation', False),
                "action_id": response.get('action_id'),
                "metadata": formatted_response.get('metadata')
            }
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            AIManager.log_error(user_id, "query_processing", str(e), {"query": query})
            return {
                "success": False,
                "error": "I encountered an error processing your request. Please try again."
            }
    
    def _get_or_create_conversation(self, user_id: int, session_id: str = None):
        """Get existing or create new conversation"""
        if session_id:
            conversation = AIConversation.query.filter_by(
                user_id=user_id,
                session_id=session_id,
                is_active=True
            ).first()
            if conversation:
                return conversation
        
        # Create new conversation
        import uuid
        return AIManager.create_conversation(
            user_id=user_id,
            session_id=session_id or str(uuid.uuid4())
        )
    
    def _handle_intent(self, intent: AIIntentType, query: str, params: dict,
                      context: list, user_id: int, conversation_id: int):
        """Route to appropriate handler based on intent"""
        
        handlers = {
            AIIntentType.SEARCH_EVENTS: self._handle_search_events,
            AIIntentType.CREATE_EVENT: self._handle_create_event,
            AIIntentType.UPDATE_EVENT: self._handle_update_event,
            AIIntentType.ANALYZE_SALES: self._handle_analyze_sales,
            AIIntentType.GENERATE_REPORT: self._handle_generate_report,
            AIIntentType.INVENTORY_CHECK: self._handle_inventory_check,
            AIIntentType.PRICING_RECOMMENDATION: self._handle_pricing_recommendation,
            AIIntentType.GENERAL_QUERY: self._handle_general_query,
        }
        
        handler = handlers.get(intent, self._handle_general_query)
        return handler(query, params, context, user_id, conversation_id)
    
    def _handle_search_events(self, query, params, context, user_id, conversation_id):
        """Handle event search queries"""
        from datetime import datetime
        
        # Build query filters
        filters = []
        filters.append(Event.date >= datetime.utcnow().date())
        
        if params.get('city'):
            filters.append(Event.city.ilike(f"%{params['city']}%"))
        
        if params.get('category'):
            from model import Category
            category = Category.query.filter_by(name=params['category']).first()
            if category:
                filters.append(Event.category_id == category.id)
        
        events = Event.query.filter(*filters).order_by(Event.date.asc()).limit(10).all()
        
        if not events:
            return {"message": "I couldn't find any events matching your criteria."}
        
        return {
            "message": f"I found {len(events)} events:",
            "data": {
                "events": [
                    {
                        "id": e.id,
                        "name": e.name,
                        "date": e.date.strftime('%B %d, %Y'),
                        "city": e.city,
                        "location": e.location
                    } for e in events
                ]
            }
        }
    
    def _handle_create_event(self, query, params, context, user_id, conversation_id):
        """Handle event creation - requires confirmation"""
        user = User.query.get(user_id)
        
        if user.role.value != 'ORGANIZER':
            return {
                "message": "Only organizers can create events. Would you like to upgrade your account to an organizer?"
            }
        
        # Log action requiring confirmation
        action_log = AIManager.log_action(
            user_id=user_id,
            action_type=AIIntentType.CREATE_EVENT,
            action_description=f"Create event: {params.get('name', 'New Event')}",
            request_data=params,
            conversation_id=conversation_id,
            requires_confirmation=True
        )
        
        return {
            "message": f"I can create an event with these details:\n" +
                      f"• Name: {params.get('name', 'Not specified')}\n" +
                      f"• Date: {params.get('date', 'Not specified')}\n" +
                      f"• City: {params.get('city', 'Not specified')}\n" +
                      f"• Location: {params.get('location', 'Not specified')}\n\n" +
                      f"Should I proceed with creating this event?",
            "requires_confirmation": True,
            "action_id": action_log.id,
            "params": params
        }
    
    def _handle_update_event(self, query, params, context, user_id, conversation_id):
        """Handle event updates"""
        event_id = params.get('event_id')
        if not event_id:
            return {"message": "Please specify which event you want to update."}
        
        event = Event.query.get(event_id)
        if not event:
            return {"message": f"Event with ID {event_id} not found."}
        
        organizer = Organizer.query.filter_by(user_id=user_id).first()
        if not organizer or event.organizer_id != organizer.id:
            return {"message": "You can only update your own events."}
        
        # Store previous state for rollback
        previous_state = {
            "name": event.name,
            "description": event.description,
            "date": str(event.date),
            "location": event.location
        }
        
        action_log = AIManager.log_action(
            user_id=user_id,
            action_type=AIIntentType.UPDATE_EVENT,
            action_description=f"Update event: {event.name}",
            request_data=params,
            previous_state=previous_state,
            conversation_id=conversation_id,
            requires_confirmation=True
        )
        action_log.event_id = event_id
        db.session.commit()
        
        update_fields = []
        for key in ['name', 'description', 'location']:
            if key in params:
                update_fields.append(f"• {key.title()}: {params[key]}")
        
        return {
            "message": f"I can update the event '{event.name}' with:\n" +
                      "\n".join(update_fields) +
                      "\n\nShould I apply these changes?",
            "requires_confirmation": True,
            "action_id": action_log.id
        }
    
    def _handle_analyze_sales(self, query, params, context, user_id, conversation_id):
        """Handle sales analysis queries"""
        organizer = Organizer.query.filter_by(user_id=user_id).first()
        if not organizer:
            return {"message": "You need an organizer account to view sales analytics."}
        
        # Determine time period
        days = params.get('days', 30)
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Get transactions
        transactions = Transaction.query.filter(
            Transaction.organizer_id == organizer.id,
            Transaction.payment_status == PaymentStatus.COMPLETED,
            Transaction.timestamp >= start_date
        ).all()
        
        if not transactions:
            return {"message": f"No sales data found for the last {days} days."}
        
        total_revenue = sum(float(t.amount_paid) for t in transactions)
        total_tickets = len(transactions)
        avg_transaction = total_revenue / total_tickets if total_tickets > 0 else 0
        
        return {
            "message": f"Sales Summary (Last {days} Days):",
            "data": {
                "total_revenue": round(total_revenue, 2),
                "total_tickets": total_tickets,
                "average_transaction": round(avg_transaction, 2),
                "period": f"{days} days"
            }
        }
    
    def _handle_generate_report(self, query, params, context, user_id, conversation_id):
        """Handle report generation requests"""
        organizer = Organizer.query.filter_by(user_id=user_id).first()
        if not organizer:
            return {"message": "Only organizers can generate reports."}
        
        return {
            "message": "I can generate various reports for you:\n" +
                      "• Event summary reports\n" +
                      "• Revenue analysis\n" +
                      "• Ticket sales breakdown\n" +
                      "• Attendee demographics\n\n" +
                      "Which type of report would you like?"
        }
    
    def _handle_inventory_check(self, query, params, context, user_id, conversation_id):
        """Check ticket inventory status"""
        organizer = Organizer.query.filter_by(user_id=user_id).first()
        if not organizer:
            return {"message": "You need an organizer account to check inventory."}
        
        # Get all events with low inventory
        low_inventory_threshold = 10
        
        events = Event.query.filter_by(organizer_id=organizer.id).all()
        low_inventory_tickets = []
        
        for event in events:
            if event.date < datetime.utcnow().date():
                continue
                
            for ticket_type in event.ticket_types:
                if ticket_type.quantity <= low_inventory_threshold:
                    low_inventory_tickets.append({
                        "event": event.name,
                        "ticket_type": ticket_type.type_name.value,
                        "remaining": ticket_type.quantity
                    })
        
        if not low_inventory_tickets:
            return {"message": "All your ticket inventories look healthy! No low stock alerts."}
        
        return {
            "message": f"⚠️ Low inventory alert for {len(low_inventory_tickets)} ticket type(s):",
            "data": {"low_inventory": low_inventory_tickets}
        }
    
    def _handle_pricing_recommendation(self, query, params, context, user_id, conversation_id):
        """Provide pricing recommendations"""
        from ai.pricing_optimizer import PricingOptimizer
        
        optimizer = PricingOptimizer()
        recommendations = optimizer.get_recommendations(user_id)
        
        if not recommendations:
            return {"message": "No pricing recommendations available at this time."}
        
        return {
            "message": "Here are my pricing recommendations:",
            "data": {"recommendations": recommendations}
        }
    
    def _handle_general_query(self, query, params, context, user_id, conversation_id):
        """Handle general queries"""
        # If LLM is available, use it
        if self.llm_enabled:
            return self._llm_response(query, context, user_id)
        
        # Otherwise, provide helpful fallback
        return {
            "message": "I'm here to help you with:\n" +
                      "• Managing your events\n" +
                      "• Analyzing sales data\n" +
                      "• Checking ticket inventory\n" +
                      "• Generating reports\n" +
                      "• Getting pricing recommendations\n\n" +
                      "What would you like to do?"
        }
    
    def _llm_response(self, query: str, context: list, user_id: int) -> dict:
        """Generate response using OpenAI LLM"""
        try:
            # Build messages for OpenAI
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an AI assistant for a ticketing system. "
                        "Help users manage events, analyze sales, check inventory, and optimize pricing. "
                        "Be concise, helpful, and professional."
                    )
                }
            ]
            
            # Add conversation context
            for msg in context[-5:]:  # Last 5 messages for context
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            
            # Add current query
            messages.append({
                "role": "user",
                "content": query
            })
            
            # Call OpenAI API
            response = openai.ChatCompletion.create(
                model=self.ai_model,
                messages=messages,
                temperature=self.ai_temperature,
                max_tokens=self.ai_max_tokens,
                timeout=self.ai_timeout
            )
            
            ai_message = response.choices[0].message.content
            
            return {
                "message": ai_message,
                "llm_used": True,
                "model": self.ai_model
            }
            
        except openai.error.Timeout:
            logger.error("OpenAI API timeout")
            return {
                "message": "I'm taking longer than usual to respond. Please try again.",
                "llm_used": False
            }
        except openai.error.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            return {
                "message": "I'm having trouble connecting to my AI services. Please try again shortly.",
                "llm_used": False
            }
        except Exception as e:
            logger.error(f"Error in LLM response: {e}")
            return {
                "message": "I understand your question, but I'm having technical difficulties. Please try rephrasing or contact support.",
                "llm_used": False
            }
    
    def execute_confirmed_action(self, action):
        """Execute an action that was confirmed by the user"""
        return self.action_executor.execute(action)