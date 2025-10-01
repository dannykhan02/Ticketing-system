from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from ai.ai_assistant import AIAssistant
from model import db, User, AIConversation, AIActionLog, AIActionStatus, AIManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIChatResource(Resource):
    """Main AI chat interface"""
    
    def __init__(self):
        self.assistant = AIAssistant()
    
    @jwt_required()
    def post(self):
        """Process a user query through the AI assistant"""
        try:
            user_id = get_jwt_identity()
            user = User.query.get(user_id)
            
            if not user:
                return {"error": "User not found"}, 404
            
            if not user.ai_enabled:
                return {"error": "AI features are disabled for your account"}, 403
            
            data = request.get_json()
            query = data.get('query')
            session_id = data.get('session_id')
            
            if not query:
                return {"error": "Query is required"}, 400
            
            # Process the query
            result = self.assistant.process_query(
                user_id=user_id,
                query=query,
                session_id=session_id
            )
            
            return result, 200 if result.get('success') else 400
            
        except Exception as e:
            logger.error(f"Error in AI chat: {e}")
            return {"error": "An internal error occurred processing your request"}, 500


class AIConversationListResource(Resource):
    """Get user's conversation history"""
    
    @jwt_required()
    def get(self):
        """Retrieve all conversations for the logged-in user"""
        try:
            user_id = get_jwt_identity()
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            
            conversations = AIManager.get_user_conversations(
                user_id=user_id,
                page=page,
                per_page=per_page
            )
            
            return {
                "conversations": [conv.as_dict() for conv in conversations.items],
                "total": conversations.total,
                "page": conversations.page,
                "pages": conversations.pages
            }, 200
            
        except Exception as e:
            logger.error(f"Error fetching conversations: {e}")
            return {"error": "An internal error occurred"}, 500


class AIConversationDetailResource(Resource):
    """Get details of a specific conversation"""
    
    @jwt_required()
    def get(self, conversation_id):
        """Get messages from a specific conversation"""
        try:
            user_id = get_jwt_identity()
            
            conversation = AIConversation.query.filter_by(
                id=conversation_id,
                user_id=user_id
            ).first()
            
            if not conversation:
                return {"error": "Conversation not found"}, 404
            
            messages = [msg.as_dict() for msg in conversation.messages]
            
            return {
                "conversation": conversation.as_dict(),
                "messages": messages
            }, 200
            
        except Exception as e:
            logger.error(f"Error fetching conversation details: {e}")
            return {"error": "An internal error occurred"}, 500
    
    @jwt_required()
    def delete(self, conversation_id):
        """Delete/deactivate a conversation"""
        try:
            user_id = get_jwt_identity()
            
            conversation = AIConversation.query.filter_by(
                id=conversation_id,
                user_id=user_id
            ).first()
            
            if not conversation:
                return {"error": "Conversation not found"}, 404
            
            conversation.is_active = False
            db.session.commit()
            
            return {"message": "Conversation deleted successfully"}, 200
            
        except Exception as e:
            logger.error(f"Error deleting conversation: {e}")
            db.session.rollback()
            return {"error": "An internal error occurred"}, 500


class AIActionConfirmResource(Resource):
    """Confirm or reject AI-suggested actions"""
    
    @jwt_required()
    def post(self, action_id):
        """Confirm an action that requires user approval"""
        try:
            user_id = get_jwt_identity()
            data = request.get_json()
            confirmed = data.get('confirmed', False)
            
            action = AIActionLog.query.filter_by(
                id=action_id,
                user_id=user_id,
                requires_confirmation=True
            ).first()
            
            if not action:
                return {"error": "Action not found or doesn't require confirmation"}, 404
            
            if action.action_status != AIActionStatus.PENDING:
                return {"error": "Action has already been processed"}, 400
            
            if confirmed:
                # Execute the action
                assistant = AIAssistant()
                result = assistant.execute_confirmed_action(action)
                return result, 200 if result.get('success') else 400
            else:
                # Reject the action
                action.action_status = AIActionStatus.CANCELLED
                action.result_message = "User declined the action"
                db.session.commit()
                
                return {"message": "Action cancelled successfully"}, 200
            
        except Exception as e:
            logger.error(f"Error confirming action: {e}")
            db.session.rollback()
            return {"error": "An internal error occurred"}, 500


class AIPendingActionsResource(Resource):
    """Get all pending actions requiring confirmation"""
    
    @jwt_required()
    def get(self):
        """Retrieve pending actions for the logged-in user"""
        try:
            user_id = get_jwt_identity()
            
            pending_actions = AIActionLog.query.filter_by(
                user_id=user_id,
                action_status=AIActionStatus.PENDING,
                requires_confirmation=True
            ).order_by(AIActionLog.created_at.desc()).limit(10).all()
            
            return {
                "pending_actions": [action.as_dict() for action in pending_actions]
            }, 200
            
        except Exception as e:
            logger.error(f"Error fetching pending actions: {e}")
            return {"error": "An internal error occurred"}, 500


class AIInsightsResource(Resource):
    """Get AI-generated insights for organizers"""
    
    @jwt_required()
    def get(self):
        """Retrieve AI insights for the logged-in organizer"""
        try:
            user_id = get_jwt_identity()
            user = User.query.get(user_id)
            
            if not user or user.role.value != 'ORGANIZER':
                return {"error": "Only organizers can view AI insights"}, 403
            
            from model import Organizer, AIInsight
            organizer = Organizer.query.filter_by(user_id=user_id).first()
            
            if not organizer:
                return {"error": "Organizer profile not found"}, 404
            
            # Get active insights
            insights = AIInsight.query.filter_by(
                organizer_id=organizer.id,
                is_active=True
            ).order_by(AIInsight.generated_at.desc()).limit(20).all()
            
            return {
                "insights": [insight.as_dict() for insight in insights]
            }, 200
            
        except Exception as e:
            logger.error(f"Error fetching insights: {e}")
            return {"error": "An internal error occurred"}, 500


def register_ai_resources(api):
    """Register all AI routes with Flask-RESTful API"""
    api.add_resource(AIChatResource, '/ai/chat')
    api.add_resource(AIConversationListResource, '/ai/conversations')
    api.add_resource(AIConversationDetailResource, '/ai/conversations/<int:conversation_id>')
    api.add_resource(AIActionConfirmResource, '/ai/actions/<int:action_id>/confirm')
    api.add_resource(AIPendingActionsResource, '/ai/actions/pending')
    api.add_resource(AIInsightsResource, '/ai/insights')