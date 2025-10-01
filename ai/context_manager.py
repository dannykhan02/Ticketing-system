from model import AIMessage, AIConversation
from datetime import datetime, timedelta

class ContextManager:
    """Manages conversation context for AI assistant"""
    
    def __init__(self, max_messages=10):
        self.max_messages = max_messages
    
    def get_context(self, conversation_id: int) -> list:
        """
        Get recent conversation context
        Returns list of messages in format: [{"role": "user/assistant", "content": "..."}]
        """
        messages = AIMessage.query.filter_by(
            conversation_id=conversation_id
        ).order_by(AIMessage.timestamp.desc()).limit(self.max_messages).all()
        
        # Reverse to get chronological order
        messages = reversed(messages)
        
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat()
            }
            for msg in messages
        ]
    
    def get_context_summary(self, conversation_id: int) -> dict:
        """Get a summary of conversation context for LLM"""
        conversation = AIConversation.query.get(conversation_id)
        if not conversation:
            return {}
        
        return {
            "conversation_id": conversation_id,
            "session_id": conversation.session_id,
            "message_count": conversation.message_count,
            "started_at": conversation.started_at.isoformat(),
            "intent_type": conversation.intent_type.value if conversation.intent_type else None
        }
    
    def get_user_history_summary(self, user_id: int, days: int = 7) -> dict:
        """Get summary of user's recent AI interactions"""
        from model import AIActionLog
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        # Get recent actions
        recent_actions = AIActionLog.query.filter(
            AIActionLog.user_id == user_id,
            AIActionLog.created_at >= cutoff
        ).all()
        
        # Summarize
        action_counts = {}
        for action in recent_actions:
            action_type = action.action_type.value
            action_counts[action_type] = action_counts.get(action_type, 0) + 1
        
        return {
            "total_actions": len(recent_actions),
            "action_breakdown": action_counts,
            "period_days": days
        }
    
    def should_suggest_proactive_help(self, conversation_id: int) -> bool:
        """Determine if AI should offer proactive suggestions"""
        messages = AIMessage.query.filter_by(
            conversation_id=conversation_id
        ).order_by(AIMessage.timestamp.desc()).limit(5).all()
        
        # If user asked same type of question 3+ times, suggest better approach
        intents = [msg.detected_intent for msg in messages if msg.detected_intent]
        if len(intents) >= 3 and len(set(intents)) == 1:
            return True
        
        return False