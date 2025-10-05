"""
Enhanced Category Resource with AI Co-pilot
Add this to your Event.py file
"""

from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import Category, User, UserRole, db, AICategoryInsight
from ai.category_assistant import category_assistant
import logging

logger = logging.getLogger(__name__)


class CategoryResource(Resource):
    def get(self):
        """Get all categories with optional AI insights"""
        include_insights = request.args.get('include_insights', 'false').lower() == 'true'
        
        categories = Category.query.all()
        result = {'categories': [category.as_dict() for category in categories]}
        
        # Add AI insights if requested and user is authenticated
        if include_insights:
            try:
                # Check if user is authenticated (optional for public endpoint)
                from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
                try:
                    verify_jwt_in_request(optional=True)
                    user_id = get_jwt_identity()
                except:
                    user_id = None
                
                if user_id:
                    # Add AI insights for each category
                    for cat_dict in result['categories']:
                        insights = AICategoryInsight.query.filter_by(
                            category_id=cat_dict['id'],
                            is_active=True
                        ).order_by(AICategoryInsight.generated_at.desc()).first()
                        
                        if insights:
                            cat_dict['latest_insight'] = insights.as_dict()
            except Exception as e:
                logger.error(f"Error adding insights: {e}")
        
        return result, 200

    @jwt_required()
    def post(self):
        """Create a new category (Admin only) with AI assistance"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can create categories"}, 403

        data = request.get_json()
        if not data:
            return {"message": "No data provided"}, 400
        
        # Check if AI assistance is requested
        use_ai = data.get('use_ai', False)
        
        # Handle natural language creation
        if use_ai and 'description' in data and 'name' not in data:
            # User provided description, let AI suggest category
            suggestion = category_assistant.suggest_category_from_description(
                data['description']
            )
            
            if suggestion:
                return {
                    "message": "AI suggestion generated",
                    "suggestion": suggestion,
                    "requires_confirmation": True
                }, 200
        
        # Normal category creation
        if 'name' not in data:
            return {"message": "Category name is required"}, 400
        
        try:
            # Check for similar categories
            if use_ai:
                similar = category_assistant.suggest_similar_categories(data['name'])
                if similar:
                    return {
                        "message": "Similar categories found",
                        "similar_categories": [cat.as_dict() for cat in similar],
                        "suggestion": "Consider using an existing category or choose a more distinct name"
                    }, 409
            
            # Create category
            category = Category(name=data['name'])
            
            # Handle description
            if 'description' in data:
                category.description = data['description']
            elif use_ai:
                # Generate AI description
                ai_description = category_assistant.enhance_category_description(data['name'])
                if ai_description:
                    category.description = ai_description
                    category.ai_description_enhanced = True
            
            # Generate AI keywords
            if use_ai:
                keywords = category_assistant.suggest_keywords(
                    category.name,
                    category.description
                )
                if keywords:
                    category.ai_suggested_keywords = keywords
            
            db.session.add(category)
            db.session.commit()
            
            response = category.as_dict()
            if use_ai:
                response['ai_assisted'] = True
            
            return response, 201
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating category: {e}")
            return {"message": str(e)}, 400


class CategoryDetailResource(Resource):
    """Handle individual category operations"""
    
    def get(self, category_id):
        """Get category details with AI insights"""
        category = Category.query.get(category_id)
        if not category:
            return {"message": "Category not found"}, 404
        
        include_insights = request.args.get('include_insights', 'false').lower() == 'true'
        
        result = category.as_dict()
        
        if include_insights:
            # Get AI insights
            insights_data = category_assistant.generate_category_insights(category_id)
            if insights_data:
                result['ai_insights'] = insights_data
        
        return result, 200
    
    @jwt_required()
    def put(self, category_id):
        """Update category (Admin only) with AI validation and assistance"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can update categories"}, 403
        
        category = Category.query.get(category_id)
        if not category:
            return {"message": "Category not found"}, 404
        
        data = request.get_json()
        if not data:
            return {"message": "No data provided"}, 400
        
        use_ai = data.get('use_ai', False)
        confirmed = request.args.get('confirm', 'false').lower() == 'true'
        
        try:
            # AI validation of updates (if not confirmed)
            if use_ai and not confirmed:
                validation = category_assistant.validate_category_update(category, data)
                
                # If there are warnings or suggestions, return them for user confirmation
                if validation['warnings'] or validation['suggestions']:
                    return {
                        "message": "Update validation",
                        "validation": validation,
                        "requires_confirmation": True,
                        "updates": data,
                        "note": "Add '?confirm=true' to query string to proceed with update"
                    }, 200
                
                # If validation failed (invalid data), reject immediately
                if not validation['valid']:
                    return {
                        "message": "Validation failed",
                        "validation": validation
                    }, 400
            
            # Apply updates
            if 'name' in data:
                # Additional check for duplicate names
                existing = Category.query.filter(
                    Category.name == data['name'],
                    Category.id != category_id
                ).first()
                
                if existing:
                    return {
                        "message": "A category with this name already exists",
                        "existing_category": existing.as_dict()
                    }, 409
                
                category.name = data['name']
            
            if 'description' in data:
                category.description = data['description']
                category.ai_description_enhanced = False
            elif use_ai and data.get('enhance_description', False):
                # AI enhance existing description
                enhanced = category_assistant.enhance_category_description(
                    category.name,
                    category.description
                )
                if enhanced:
                    category.description = enhanced
                    category.ai_description_enhanced = True
            
            # Update AI keywords if requested
            if use_ai and data.get('update_keywords', False):
                keywords = category_assistant.suggest_keywords(
                    category.name,
                    category.description
                )
                if keywords:
                    category.ai_suggested_keywords = keywords
            
            # Handle AI-assisted updates (natural language)
            if use_ai and 'ai_instructions' in data:
                # Process natural language update instructions
                instructions = data['ai_instructions']
                
                # Get AI suggestions for the instructions
                suggestion = category_assistant.suggest_category_from_description(
                    f"Update {category.name}: {instructions}"
                )
                
                if suggestion and not confirmed:
                    return {
                        "message": "AI update suggestion generated",
                        "current": category.as_dict(),
                        "suggested_changes": suggestion,
                        "requires_confirmation": True,
                        "note": "Review changes and add '?confirm=true' to apply"
                    }, 200
                
                # If confirmed, apply AI suggestions
                if suggestion and confirmed:
                    if 'name' in suggestion:
                        category.name = suggestion['name']
                    if 'description' in suggestion:
                        category.description = suggestion['description']
                        category.ai_description_enhanced = True
                    if 'keywords' in suggestion:
                        category.ai_suggested_keywords = suggestion['keywords']
            
            db.session.commit()
            
            response = {
                "message": "Category updated successfully",
                "category": category.as_dict()
            }
            
            if use_ai:
                response['ai_assisted'] = True
            
            return response, 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating category: {e}")
            return {"message": str(e)}, 400
    
    @jwt_required()
    def delete(self, category_id):
        """Delete category (Admin only) with AI impact analysis"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can delete categories"}, 403
        
        category = Category.query.get(category_id)
        if not category:
            return {"message": "Category not found"}, 404
        
        use_ai = request.args.get('use_ai', 'false').lower() == 'true'
        confirmed = request.args.get('confirm', 'false').lower() == 'true'
        
        try:
            # Check impact
            event_count = len(category.events) if hasattr(category, 'events') else 0
            
            if event_count > 0 and not confirmed:
                impact_message = {
                    "message": "Deletion will affect existing events",
                    "impact": {
                        "affected_events": event_count,
                        "warning": f"This category has {event_count} events. "
                                 "Deleting it will remove the category from all these events."
                    },
                    "requires_confirmation": True,
                    "note": "Add '?confirm=true' to query string to proceed with deletion"
                }
                
                # Add AI-generated impact analysis if requested
                if use_ai:
                    insights = category_assistant.generate_category_insights(category_id)
                    if insights:
                        impact_message['ai_analysis'] = {
                            "stats": insights.get('stats', {}),
                            "recommendation": "Review the category's usage before deletion"
                        }
                
                return impact_message, 200
            
            # Delete category
            db.session.delete(category)
            db.session.commit()
            
            return {
                "message": "Category deleted successfully",
                "deleted_category": {
                    "id": category_id,
                    "name": category.name
                }
            }, 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting category: {e}")
            return {"message": str(e)}, 400


class CategoryAIAssistResource(Resource):
    """AI co-pilot endpoint for category management"""
    
    @jwt_required()
    def post(self):
        """Process natural language queries about categories"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user:
            return {"message": "User not found"}, 404
        
        data = request.get_json()
        query = data.get('query')
        
        if not query:
            return {"message": "Query is required"}, 400
        
        # Process query
        result = category_assistant.process_natural_language_query(
            query,
            current_user.id
        )
        
        return result, 200


class CategoryInsightsResource(Resource):
    """Get AI insights for a category"""
    
    @jwt_required()
    def get(self, category_id):
        """Get AI-generated insights for a category"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can view insights"}, 403
        
        category = Category.query.get(category_id)
        if not category:
            return {"message": "Category not found"}, 404
        
        insights = category_assistant.generate_category_insights(category_id)
        
        if not insights:
            return {"message": "Could not generate insights"}, 500
        
        return insights, 200


# Update your register function
def register_catergory_resources(api):
    """Registers the CategoryResource routes with Flask-RESTful API."""
    
    api.add_resource(CategoryResource, "/categories")
    api.add_resource(CategoryDetailResource, "/categories/<int:category_id>")
    api.add_resource(CategoryAIAssistResource, "/categories/ai/assist")
    api.add_resource(CategoryInsightsResource, "/categories/<int:category_id>/insights")