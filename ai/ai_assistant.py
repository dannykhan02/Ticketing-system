from flask_jwt_extended import get_jwt_identity
from model import (db, User, AIManager, AIIntentType, AIConversation, 
                   Event, TicketType, Transaction, PaymentStatus, Organizer)
from ai.intent_classifier import IntentClassifier
from ai.action_executor import ActionExecutor
from ai.context_manager import ContextManager
from ai.response_formatter import ResponseFormatter
from ai.llm_client import llm_client  # Use centralized client
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class AIAssistant:
    """Main AI Assistant orchestrator"""
    
    def __init__(self):
        self.intent_classifier = IntentClassifier()
        self.action_executor = ActionExecutor()
        self.context_manager = ContextManager()
        self.response_formatter = ResponseFormatter()
        self.llm = llm_client  # Use singleton instance
        
        logger.info(f"AI Assistant initialized - LLM enabled: {self.llm.is_enabled()}")
    
    def process_query(self, user_id: int, query: str, session_id: str = None):
        """Main entry point for processing user queries"""
        try:
            conversation = self._get_or_create_conversation(user_id, session_id)
            
            AIManager.add_message(conversation_id=conversation.id, role='user', content=query)
            
            intent, confidence, params = self.intent_classifier.classify(query)
            context = self.context_manager.get_context(conversation.id)
            
            response = self._handle_intent(intent, query, params, context, user_id, conversation.id)
            formatted_response = self.response_formatter.format(response, intent)
            
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
            logger.error(f"Error processing query: {e}", exc_info=True)
            AIManager.log_error(user_id, "query_processing", str(e), {"query": query})
            return {
                "success": False,
                "error": "I encountered an error processing your request. Please try again."
            }
    
    def _get_or_create_conversation(self, user_id: int, session_id: str = None):
        """Get existing or create new conversation"""
        if session_id:
            conv = AIConversation.query.filter_by(
                user_id=user_id, session_id=session_id, is_active=True
            ).first()
            if conv:
                return conv
        
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
        filters = [Event.date >= datetime.utcnow().date()]
        
        if params.get('city'):
            filters.append(Event.city.ilike(f"%{params['city']}%"))
        
        if params.get('category'):
            from model import Category
            cat = Category.query.filter_by(name=params['category']).first()
            if cat:
                filters.append(Event.category_id == cat.id)
        
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
            return {"message": "Only organizers can create events. Would you like to upgrade your account?"}
        
        action_log = AIManager.log_action(
            user_id=user_id,
            action_type=AIIntentType.CREATE_EVENT,
            action_description=f"Create event: {params.get('name', 'New Event')}",
            request_data=params,
            conversation_id=conversation_id,
            requires_confirmation=True
        )
        
        details = "\n".join([
            f"• {k.title()}: {v}" 
            for k, v in params.items() 
            if k in ['name', 'date', 'city', 'location']
        ])
        
        return {
            "message": f"I can create an event with these details:\n{details}\n\nShould I proceed?",
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
        
        previous_state = {k: getattr(event, k) for k in ['name', 'description', 'date', 'location']}
        previous_state['date'] = str(previous_state['date'])
        
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
        
        updates = "\n".join([f"• {k.title()}: {v}" for k, v in params.items() 
                            if k in ['name', 'description', 'location']])
        
        return {
            "message": f"Update '{event.name}' with:\n{updates}\n\nApply these changes?",
            "requires_confirmation": True,
            "action_id": action_log.id
        }
    
    def _handle_analyze_sales(self, query, params, context, user_id, conversation_id):
        """Handle sales analysis queries"""
        organizer = Organizer.query.filter_by(user_id=user_id).first()
        if not organizer:
            return {"message": "You need an organizer account to view sales analytics."}
        
        days = params.get('days', 30)
        start_date = datetime.utcnow() - timedelta(days=days)
        
        transactions = Transaction.query.filter(
            Transaction.organizer_id == organizer.id,
            Transaction.payment_status == PaymentStatus.COMPLETED,
            Transaction.timestamp >= start_date
        ).all()
        
        if not transactions:
            return {"message": f"No sales data found for the last {days} days."}
        
        total_revenue = sum(float(t.amount_paid) for t in transactions)
        total_tickets = len(transactions)
        avg = total_revenue / total_tickets if total_tickets > 0 else 0
        
        return {
            "message": f"Sales Summary (Last {days} Days):",
            "data": {
                "total_revenue": round(total_revenue, 2),
                "total_tickets": total_tickets,
                "average_transaction": round(avg, 2),
                "period": f"{days} days"
            }
        }
    
    def _handle_generate_report(self, query, params, context, user_id, conversation_id):
        """Handle report generation requests"""
        organizer = Organizer.query.filter_by(user_id=user_id).first()
        if not organizer:
            return {"message": "Only organizers can generate reports."}
        
        return {
            "message": "I can generate:\n• Event summaries\n• Revenue analysis\n• Sales breakdown\n• Attendee demographics\n\nWhich type?"
        }
    
    def _handle_inventory_check(self, query, params, context, user_id, conversation_id):
        """Check ticket inventory status"""
        organizer = Organizer.query.filter_by(user_id=user_id).first()
        if not organizer:
            return {"message": "You need an organizer account to check inventory."}
        
        low_threshold = 10
        events = Event.query.filter_by(organizer_id=organizer.id).all()
        low_inventory = []
        
        for event in events:
            if event.date < datetime.utcnow().date():
                continue
            for tt in event.ticket_types:
                if tt.quantity <= low_threshold:
                    low_inventory.append({
                        "event": event.name,
                        "ticket_type": tt.type_name.value,
                        "remaining": tt.quantity
                    })
        
        if not low_inventory:
            return {"message": "All ticket inventories look healthy!"}
        
        return {
            "message": f"⚠️ Low inventory alert for {len(low_inventory)} ticket type(s):",
            "data": {"low_inventory": low_inventory}
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
        """Handle general queries using LLM"""
        if not self.llm.is_enabled():
            return {
                "message": "I can help with:\n• Managing events\n• Analyzing sales\n• Checking inventory\n• Generating reports\n• Pricing recommendations\n\nWhat would you like to do?"
            }
        
        # Build context messages
        messages = [self.llm.build_system_message()]
        
        for msg in context[-5:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        messages.append({"role": "user", "content": query})
        
        # Use centralized LLM client
        response = self.llm.chat_completion(messages)
        
        if response:
            return {"message": response, "llm_used": True}
        
        # Fallback if LLM fails
        return {
            "message": "I'm having trouble connecting right now. Please try again or rephrase your question.",
            "llm_used": False
        }
    
    def execute_confirmed_action(self, action):
        """Execute an action that was confirmed by the user"""
        return self.action_executor.execute(action)