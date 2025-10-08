"""
Enhanced Category Resource with AI Co-pilot
Improved UX with explicit action buttons and clearer workflows
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
        
        if include_insights:
            try:
                from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
                try:
                    verify_jwt_in_request(optional=True)
                    user_id = get_jwt_identity()
                except:
                    user_id = None
                
                if user_id:
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
        
        action = data.get('action', 'create')  # 'suggest', 'create', 'save_suggested'
        
        # ACTION: Get AI Suggestion
        if action == 'suggest':
            description = data.get('description')
            if not description:
                return {"message": "Description is required for AI suggestions"}, 400
            
            suggestion = category_assistant.suggest_category_from_description(description)
            
            if suggestion:
                return {
                    "action": "suggestion_generated",
                    "suggestion": {
                        "name": suggestion.get('name'),
                        "description": suggestion.get('description'),
                        "keywords": suggestion.get('keywords', []),
                        "ai_generated": suggestion.get('source') != 'fallback'
                    },
                    "next_actions": {
                        "save": "POST /categories with action='save_suggested' and suggested data",
                        "modify": "Edit the suggestion and POST with action='create'",
                        "regenerate": "POST again with action='suggest' and modified description"
                    }
                }, 200
            else:
                return {"message": "Could not generate suggestion"}, 500
        
        # ACTION: Save AI Suggested Category
        elif action == 'save_suggested':
            if 'name' not in data:
                return {"message": "Category name is required"}, 400
            
            # Check for similar categories first
            similar = category_assistant.suggest_similar_categories(data['name'])
            if similar and not data.get('confirm_despite_similar', False):
                return {
                    "action": "similar_categories_found",
                    "similar_categories": [cat.as_dict() for cat in similar[:5]],
                    "warning": "Similar categories exist. Review them before creating.",
                    "next_actions": {
                        "create_anyway": "POST with action='save_suggested' and confirm_despite_similar=true",
                        "cancel": "Choose a different name or use existing category"
                    }
                }, 409
            
            try:
                category = Category(name=data['name'])
                category.description = data.get('description', '')
                category.ai_description_enhanced = True
                
                if 'keywords' in data:
                    category.ai_suggested_keywords = data['keywords']
                
                db.session.add(category)
                db.session.commit()
                
                return {
                    "action": "category_created",
                    "message": "Category created successfully with AI assistance",
                    "category": category.as_dict(),
                    "ai_assisted": True
                }, 201
                
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error creating category: {e}")
                return {"message": str(e)}, 400
        
        # ACTION: Direct Create (without AI)
        elif action == 'create':
            if 'name' not in data:
                return {"message": "Category name is required"}, 400
            
            try:
                category = Category(name=data['name'])
                
                if 'description' in data:
                    category.description = data['description']
                
                db.session.add(category)
                db.session.commit()
                
                return {
                    "action": "category_created",
                    "message": "Category created successfully",
                    "category": category.as_dict()
                }, 201
                
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error creating category: {e}")
                return {"message": str(e)}, 400
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["suggest", "save_suggested", "create"]
            }, 400


class CategoryDetailResource(Resource):
    """Handle individual category operations"""
    
    def get(self, category_id):
        """Get category details with optional AI insights"""
        category = Category.query.get(category_id)
        if not category:
            return {"message": "Category not found"}, 404
        
        include_insights = request.args.get('include_insights', 'false').lower() == 'true'
        
        result = category.as_dict()
        
        if include_insights:
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
        
        action = data.get('action', 'update')  # 'update', 'enhance_description', 'update_keywords', 'validate'
        
        # ACTION: Validate Updates
        if action == 'validate':
            validation = category_assistant.validate_category_update(category, data)
            
            return {
                "action": "validation_complete",
                "validation": validation,
                "current_category": category.as_dict(),
                "proposed_changes": data,
                "next_actions": {
                    "save": "PUT with action='save_validated' to apply changes",
                    "cancel": "Discard changes"
                }
            }, 200
        
        # ACTION: Enhance Description with AI
        elif action == 'enhance_description':
            enhanced = category_assistant.enhance_category_description(
                category.name,
                category.description
            )
            
            if enhanced:
                return {
                    "action": "description_enhanced",
                    "current_description": category.description,
                    "enhanced_description": enhanced,
                    "next_actions": {
                        "save": "PUT with action='save_enhanced_description' and description field",
                        "regenerate": "PUT again with action='enhance_description'",
                        "cancel": "Keep current description"
                    }
                }, 200
            else:
                return {"message": "Could not enhance description"}, 500
        
        # ACTION: Save Enhanced Description
        elif action == 'save_enhanced_description':
            if 'description' not in data:
                return {"message": "Description is required"}, 400
            
            try:
                category.description = data['description']
                category.ai_description_enhanced = True
                db.session.commit()
                
                return {
                    "action": "description_saved",
                    "message": "Description updated successfully",
                    "category": category.as_dict()
                }, 200
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error saving description: {e}")
                return {"message": str(e)}, 400
        
        # ACTION: Update Keywords with AI
        elif action == 'update_keywords':
            keywords = category_assistant.suggest_keywords(
                category.name,
                category.description
            )
            
            if keywords:
                return {
                    "action": "keywords_generated",
                    "current_keywords": category.ai_suggested_keywords or [],
                    "suggested_keywords": keywords,
                    "next_actions": {
                        "save": "PUT with action='save_keywords' and keywords array",
                        "regenerate": "PUT again with action='update_keywords'",
                        "cancel": "Keep current keywords"
                    }
                }, 200
            else:
                return {"message": "Could not generate keywords"}, 500
        
        # ACTION: Save Keywords
        elif action == 'save_keywords':
            if 'keywords' not in data:
                return {"message": "Keywords are required"}, 400
            
            try:
                category.ai_suggested_keywords = data['keywords']
                db.session.commit()
                
                return {
                    "action": "keywords_saved",
                    "message": "Keywords updated successfully",
                    "category": category.as_dict()
                }, 200
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error saving keywords: {e}")
                return {"message": str(e)}, 400
        
        # ACTION: Direct Update
        elif action == 'update' or action == 'save_validated':
            try:
                # Check for duplicate names
                if 'name' in data and data['name'] != category.name:
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
                    # Only mark as AI enhanced if explicitly stated
                    if data.get('ai_enhanced', False):
                        category.ai_description_enhanced = True
                    else:
                        category.ai_description_enhanced = False
                
                if 'keywords' in data:
                    category.ai_suggested_keywords = data['keywords']
                
                db.session.commit()
                
                return {
                    "action": "category_updated",
                    "message": "Category updated successfully",
                    "category": category.as_dict()
                }, 200
                
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating category: {e}")
                return {"message": str(e)}, 400
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": [
                    "update", "validate", "enhance_description", 
                    "save_enhanced_description", "update_keywords", "save_keywords"
                ]
            }, 400
    
    @jwt_required()
    def delete(self, category_id):
        """Delete category (Admin only) with AI impact analysis"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can delete categories"}, 403
        
        category = Category.query.get(category_id)
        if not category:
            return {"message": "Category not found"}, 404
        
        action = request.args.get('action', 'check_impact')
        
        # ACTION: Check Deletion Impact
        if action == 'check_impact':
            event_count = len(category.events) if hasattr(category, 'events') else 0
            
            impact = {
                "action": "impact_analyzed",
                "category": category.as_dict(),
                "impact": {
                    "affected_events": event_count,
                    "has_events": event_count > 0
                }
            }
            
            # Add AI insights
            insights = category_assistant.generate_category_insights(category_id)
            if insights:
                impact['ai_analysis'] = {
                    "stats": insights.get('stats', {}),
                    "insights": insights.get('insights', '')
                }
            
            if event_count > 0:
                impact['warning'] = f"This category has {event_count} events. Deleting it will remove the category from all these events."
                impact['next_actions'] = {
                    "delete": "DELETE with action='confirm_delete' to proceed",
                    "cancel": "Keep the category"
                }
            else:
                impact['next_actions'] = {
                    "delete": "DELETE with action='confirm_delete' to proceed",
                    "cancel": "Keep the category"
                }
            
            return impact, 200
        
        # ACTION: Confirm and Delete
        elif action == 'confirm_delete':
            try:
                category_name = category.name
                db.session.delete(category)
                db.session.commit()
                
                return {
                    "action": "category_deleted",
                    "message": "Category deleted successfully",
                    "deleted_category": {
                        "id": category_id,
                        "name": category_name
                    }
                }, 200
                
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error deleting category: {e}")
                return {"message": str(e)}, 400
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["check_impact", "confirm_delete"]
            }, 400


class CategoryInsightsResource(Resource):
    """Get and regenerate AI insights for a category"""
    
    @jwt_required()
    def get(self, category_id):
        """Get AI-generated insights for a category"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can view insights"}, 403
        
        category = Category.query.get(category_id)
        if not category:
            return {"message": "Category not found"}, 404
        
        # Check for cached insights
        cached_insight = AICategoryInsight.query.filter_by(
            category_id=category_id,
            is_active=True
        ).order_by(AICategoryInsight.generated_at.desc()).first()
        
        if cached_insight:
            return {
                "action": "cached_insights_retrieved",
                "insights": cached_insight.as_dict(),
                "category": category.as_dict(),
                "next_actions": {
                    "regenerate": "POST to /categories/{id}/insights with action='regenerate'",
                    "use_cached": "Use these insights as-is"
                }
            }, 200
        else:
            # Generate new insights
            insights = category_assistant.generate_category_insights(category_id)
            
            if not insights:
                return {"message": "Could not generate insights"}, 500
            
            return {
                "action": "new_insights_generated",
                "insights": insights,
                "category": category.as_dict(),
                "next_actions": {
                    "regenerate": "POST to /categories/{id}/insights with action='regenerate'"
                }
            }, 200
    
    @jwt_required()
    def post(self, category_id):
        """Regenerate insights for a category"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can regenerate insights"}, 403
        
        category = Category.query.get(category_id)
        if not category:
            return {"message": "Category not found"}, 404
        
        data = request.get_json() or {}
        action = data.get('action', 'regenerate')
        
        if action == 'regenerate':
            # Force fresh insights generation
            insights = category_assistant.generate_category_insights(category_id)
            
            if not insights:
                return {"message": "Could not regenerate insights"}, 500
            
            # Optionally save to database
            if data.get('save_to_db', False):
                try:
                    # Deactivate old insights
                    AICategoryInsight.query.filter_by(
                        category_id=category_id
                    ).update({"is_active": False})
                    
                    # Save new insight
                    new_insight = AICategoryInsight(
                        category_id=category_id,
                        insights_text=insights.get('insights', ''),
                        stats=insights.get('stats', {}),
                        ai_powered=insights.get('ai_powered', False)
                    )
                    
                    db.session.add(new_insight)
                    db.session.commit()
                    
                    return {
                        "action": "insights_regenerated_and_saved",
                        "message": "Insights regenerated and saved successfully",
                        "insights": new_insight.as_dict(),
                        "category": category.as_dict()
                    }, 200
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Error saving insights: {e}")
                    # Return insights anyway
                    return {
                        "action": "insights_regenerated",
                        "message": "Insights regenerated (not saved to database)",
                        "insights": insights,
                        "category": category.as_dict(),
                        "error": str(e)
                    }, 200
            else:
                return {
                    "action": "insights_regenerated",
                    "message": "Insights regenerated successfully",
                    "insights": insights,
                    "category": category.as_dict(),
                    "next_actions": {
                        "save": "POST with action='regenerate' and save_to_db=true"
                    }
                }, 200
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["regenerate"]
            }, 400


class CategoryAIAssistResource(Resource):
    """AI co-pilot endpoint for natural language category management"""
    
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
        
        # Enhance response with actionable next steps
        intent = result.get('intent')
        
        if intent == 'create':
            result['next_actions'] = {
                "suggest": "POST /categories with action='suggest' and description",
                "create_directly": "POST /categories with action='create', name, and description"
            }
        elif intent == 'update':
            result['next_actions'] = {
                "enhance_description": "PUT /categories/{id} with action='enhance_description'",
                "update_keywords": "PUT /categories/{id} with action='update_keywords'",
                "direct_update": "PUT /categories/{id} with action='update' and changes"
            }
        elif intent == 'delete':
            result['next_actions'] = {
                "check_impact": "DELETE /categories/{id} with action='check_impact'",
                "confirm_delete": "DELETE /categories/{id} with action='confirm_delete'"
            }
        elif intent == 'analyze':
            result['next_actions'] = {
                "get_insights": "GET /categories/{id}/insights",
                "regenerate": "POST /categories/{id}/insights with action='regenerate'"
            }
        
        return result, 200


# Update your register function
def register_category_resources(api):
    """Registers the CategoryResource routes with Flask-RESTful API."""
    
    api.add_resource(CategoryResource, "/categories")
    api.add_resource(CategoryDetailResource, "/categories/<int:category_id>")
    api.add_resource(CategoryInsightsResource, "/categories/<int:category_id>/insights")
    api.add_resource(CategoryAIAssistResource, "/categories/ai/assist")