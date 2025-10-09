"""
Enhanced Partner Management Resource with AI Co-pilot
Comprehensive AI assistance for partner creation, collaboration management, and optimization
Following the pattern of CategoryResource with explicit action buttons and clearer workflows
"""

import json
import logging
from datetime import datetime
from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
import cloudinary.uploader
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from model import (
    db, Event, User, UserRole, Organizer, Partner,
    EventCollaboration, CollaborationType, AIPartnerInsight,
    AIPartnerMatchRecommendation
)
from ai.partner_assistant import partner_assistant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


class PartnerManagementResource(Resource):
    """Resource for managing partners and event collaborations (Organizer only)."""

    @jwt_required()
    def get(self, partner_id=None, event_id=None):
        """
        Organizer-only endpoints:
        - GET /partners -> Get all partners for current organizer (paginated, filter, sort)
        - GET /partners/<id> -> Get specific partner with collaborations (paginated)
        - GET /partners/events/<event_id> -> Get collaborations for specific event (paginated)
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)
            if not user or user.role != UserRole.ORGANIZER:
                return {"message": "Only organizers can access partner management"}, 403
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found"}, 404
            
            # Pagination & sorting params
            page = request.args.get('page', 1, type=int)
            per_page = min(request.args.get('per_page', 10, type=int), 50)
            sort_by = request.args.get('sort_by', 'company_name')
            sort_order = request.args.get('sort_order', 'asc').lower()
            search = request.args.get('search')
            include_ai_insights = request.args.get('include_ai_insights', 'false').lower() == 'true'
            
            if event_id:
                return self._get_event_collaborations(organizer, event_id, page, per_page, include_ai_insights)
            elif partner_id:
                return self._get_partner_details(organizer, partner_id, page, per_page, include_ai_insights)
            else:
                return self._get_organizer_partners(organizer, page, per_page, sort_by, sort_order, search, include_ai_insights)
        except Exception as e:
            logger.error(f"Error in PartnerManagementResource GET: {str(e)}")
            return {"message": "Error processing request"}, 500

    def _get_event_collaborations(self, organizer, event_id, page, per_page, include_ai_insights):
        """Get collaborations for a specific event with AI recommendations."""
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404
        
        collaborations = EventCollaboration.query.filter_by(event_id=event.id).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        result = {
            'event_id': event.id,
            'event_name': event.name,
            'collaborations': [c.as_dict() for c in collaborations.items],
            'pagination': {
                'total': collaborations.total,
                'pages': collaborations.pages,
                'current_page': collaborations.page,
                'per_page': collaborations.per_page,
                'has_next': collaborations.has_next,
                'has_prev': collaborations.has_prev
            }
        }
        
        # Add AI recommendations for new partners
        if include_ai_insights:
            try:
                suggestions = partner_assistant.suggest_collaborations_for_event(event_id, limit=5)
                if suggestions:
                    result['ai_recommendations'] = {
                        'suggested_partners': suggestions,
                        'message': 'AI has identified potential partner matches for this event',
                        'next_actions': {
                            'add_collaboration': 'POST /partners/events/{event_id} with partner_id',
                            'view_partner': 'GET /partners/{partner_id} for more details'
                        }
                    }
            except Exception as e:
                logger.error(f"Error generating AI recommendations: {e}")
        
        return result, 200

    def _get_partner_details(self, organizer, partner_id, page, per_page, include_ai_insights):
        """Get specific partner with their collaboration history and AI analysis."""
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404
        
        collaborations = EventCollaboration.query.filter_by(partner_id=partner.id).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Get partner data safely, handling missing columns
        try:
            partner_data = partner.as_dict()
        except Exception as e:
            logger.error(f"Error getting partner data: {e}")
            # Fallback to manual data extraction
            partner_data = {
                'id': partner.id,
                'organizer_id': partner.organizer_id,
                'company_name': partner.company_name,
                'company_description': getattr(partner, 'company_description', ''),
                'logo_url': getattr(partner, 'logo_url', ''),
                'website_url': getattr(partner, 'website_url', ''),
                'contact_email': getattr(partner, 'contact_email', ''),
                'contact_person': getattr(partner, 'contact_person', ''),
                'is_active': getattr(partner, 'is_active', True),
                'created_at': getattr(partner, 'created_at', datetime.utcnow()),
                'updated_at': getattr(partner, 'updated_at', datetime.utcnow())
            }
        
        partner_data['collaborations'] = [
            {
                **c.as_dict(),
                'event_name': c.event.name if c.event else None,
                'event_date': c.event.date.isoformat() if c.event and c.event.date else None
            }
            for c in collaborations.items
        ]
        partner_data['collaboration_stats'] = {
            'total_collaborations': collaborations.total,
            'active_collaborations': len([c for c in collaborations.items if c.is_active]),
            'collaboration_types': list(set([c.collaboration_type.value for c in collaborations.items]))
        }
        
        # Add AI insights
        if include_ai_insights:
            try:
                # Get performance analysis
                performance = partner_assistant.analyze_partner_performance(partner_id)
                if performance:
                    partner_data['ai_performance_analysis'] = performance
                
                # Get latest insights from database
                try:
                    latest_insight = AIPartnerInsight.query.filter_by(
                        partner_id=partner_id,
                        is_active=True
                    ).order_by(AIPartnerInsight.created_at.desc()).first()
                    
                    if latest_insight:
                        partner_data['latest_ai_insight'] = latest_insight.as_dict()
                except Exception as e:
                    logger.error(f"Error getting latest insight: {e}")
                
                # Find similar partners
                try:
                    similar = partner_assistant.find_similar_partners(partner_id, limit=3)
                    if similar:
                        partner_data['similar_partners'] = [
                            {
                                'id': p.id,
                                'company_name': p.company_name,
                                'performance_score': getattr(p, 'performance_score', 0)
                            }
                            for p in similar
                        ]
                except Exception as e:
                    logger.error(f"Error finding similar partners: {e}")
                
                partner_data['ai_actions'] = {
                    'enhance_description': 'POST /partners/{id}/ai/enhance-description',
                    'analyze_performance': 'POST /partners/{id}/ai/analyze',
                    'get_optimization': 'GET /partners/{id}/ai/optimize'
                }
            except Exception as e:
                logger.error(f"Error adding AI insights: {e}")
        
        return {
            'partner': partner_data,
            'pagination': {
                'total': collaborations.total,
                'pages': collaborations.pages,
                'current_page': collaborations.page,
                'per_page': collaborations.per_page,
                'has_next': collaborations.has_next,
                'has_prev': collaborations.has_prev
            }
        }, 200

    def _get_organizer_partners(self, organizer, page, per_page, sort_by, sort_order, search, include_ai_insights):
        """Get all partners for the current organizer with AI trends."""
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
        
        # Use a raw query to avoid issues with missing columns
        try:
            # First try to get partners with the standard query
            query = Partner.query.filter_by(organizer_id=organizer.id)
            
            if not include_inactive:
                query = query.filter_by(is_active=True)
            
            if search:
                query = query.filter(Partner.company_name.ilike(f"%{search}%"))
            
            partners = query.paginate(page=page, per_page=per_page, error_out=False)
            
            partners_data = []
            for partner in partners.items:
                try:
                    # Try to get partner data with as_dict()
                    partner_dict = partner.as_dict()
                except Exception as e:
                    logger.error(f"Error getting partner dict: {e}")
                    # Fallback to manual data extraction
                    partner_dict = {
                        'id': partner.id,
                        'organizer_id': partner.organizer_id,
                        'company_name': partner.company_name,
                        'company_description': getattr(partner, 'company_description', ''),
                        'logo_url': getattr(partner, 'logo_url', ''),
                        'website_url': getattr(partner, 'website_url', ''),
                        'contact_email': getattr(partner, 'contact_email', ''),
                        'contact_person': getattr(partner, 'contact_person', ''),
                        'is_active': getattr(partner, 'is_active', True),
                        'created_at': getattr(partner, 'created_at', datetime.utcnow()),
                        'updated_at': getattr(partner, 'updated_at', datetime.utcnow())
                    }
                
                recent_collaborations = EventCollaboration.query.filter_by(
                    partner_id=partner.id,
                    is_active=True
                ).order_by(EventCollaboration.created_at.desc()).limit(3).all()
                
                partner_dict['recent_collaborations'] = [
                    {
                        'event_id': c.event_id,
                        'event_name': c.event.name if c.event else None,
                        'collaboration_type': c.collaboration_type.value,
                        'created_at': c.created_at.isoformat()
                    }
                    for c in recent_collaborations
                ]
                
                partner_dict['total_collaborations'] = EventCollaboration.query.filter_by(
                    partner_id=partner.id
                ).count()
                partners_data.append(partner_dict)
            
            # Sorting
            reverse = sort_order == 'desc'
            if sort_by == 'created_at':
                partners_data.sort(key=lambda x: x['created_at'], reverse=reverse)
            elif sort_by == 'total_collaborations':
                partners_data.sort(key=lambda x: x.get('total_collaborations', 0), reverse=reverse)
            elif sort_by == 'performance_score':
                partners_data.sort(key=lambda x: x.get('performance_score', 0), reverse=reverse)
            elif sort_by == 'active_status':
                partners_data.sort(key=lambda x: x['is_active'], reverse=reverse)
            else:
                partners_data.sort(key=lambda x: x['company_name'].lower(), reverse=reverse)
            
            result = {
                'partners': partners_data,
                'pagination': {
                    'total': partners.total,
                    'pages': partners.pages,
                    'current_page': partners.page,
                    'per_page': partners.per_page,
                    'has_next': partners.has_next,
                    'has_prev': partners.has_prev
                },
                'organizer_id': organizer.id,
                'filters': {
                    'include_inactive': include_inactive,
                    'sort_by': sort_by,
                    'sort_order': sort_order,
                    'search': search
                }
            }
            
            # Add AI insights for overview
            if include_ai_insights:
                try:
                    # Get partnership trends
                    trends = partner_assistant.identify_partnership_trends(organizer.id)
                    if trends:
                        result['ai_trends'] = trends
                    
                    # Get recommendations summary
                    recommendations_summary = partner_assistant.get_partner_recommendations_summary(organizer.id)
                    if recommendations_summary:
                        result['ai_recommendations_summary'] = recommendations_summary
                    
                    result['ai_actions'] = {
                        'bulk_analyze': 'POST /partners/ai/bulk-analyze',
                        'get_trends': 'GET /partners/ai/trends',
                        'natural_query': 'POST /partners/ai/assist with query'
                    }
                except Exception as e:
                    logger.error(f"Error adding AI insights: {e}")
            
            return result, 200
        except Exception as e:
            logger.error(f"Error in _get_organizer_partners: {str(e)}")
            # Fallback to a simpler query if the main one fails
            try:
                # Use raw SQL to avoid SQLAlchemy issues with missing columns
                sql = """
                SELECT id, organizer_id, company_name, company_description, logo_url, 
                       website_url, contact_email, contact_person, is_active, 
                       created_at, updated_at
                FROM partners 
                WHERE organizer_id = :organizer_id
                """
                if not include_inactive:
                    sql += " AND is_active = true"
                if search:
                    sql += " AND company_name ILIKE :search"
                
                sql += " ORDER BY company_name " + ("DESC" if sort_order == 'desc' else "ASC")
                sql += " LIMIT :limit OFFSET :offset"
                
                result = db.session.execute(
                    text(sql),
                    {
                        'organizer_id': organizer.id,
                        'search': f"%{search}%",
                        'limit': per_page,
                        'offset': (page - 1) * per_page
                    }
                )
                
                partners_data = []
                for row in result:
                    partner_dict = {
                        'id': row[0],
                        'organizer_id': row[1],
                        'company_name': row[2],
                        'company_description': row[3] or '',
                        'logo_url': row[4] or '',
                        'website_url': row[5] or '',
                        'contact_email': row[6] or '',
                        'contact_person': row[7] or '',
                        'is_active': row[8],
                        'created_at': row[9].isoformat() if row[9] else None,
                        'updated_at': row[10].isoformat() if row[10] else None
                    }
                    
                    # Get collaborations count
                    collab_count = db.session.execute(
                        text("SELECT COUNT(*) FROM event_collaborations WHERE partner_id = :partner_id"),
                        {'partner_id': row[0]}
                    ).scalar()
                    
                    partner_dict['total_collaborations'] = collab_count or 0
                    partners_data.append(partner_dict)
                
                # Get total count for pagination
                count_sql = """
                SELECT COUNT(*) FROM partners 
                WHERE organizer_id = :organizer_id
                """
                if not include_inactive:
                    count_sql += " AND is_active = true"
                if search:
                    count_sql += " AND company_name ILIKE :search"
                
                total = db.session.execute(
                    text(count_sql),
                    {
                        'organizer_id': organizer.id,
                        'search': f"%{search}%"
                    }
                ).scalar()
                
                total_pages = (total + per_page - 1) // per_page
                
                return {
                    'partners': partners_data,
                    'pagination': {
                        'total': total,
                        'pages': total_pages,
                        'current_page': page,
                        'per_page': per_page,
                        'has_next': page < total_pages,
                        'has_prev': page > 1
                    },
                    'organizer_id': organizer.id,
                    'filters': {
                        'include_inactive': include_inactive,
                        'sort_by': sort_by,
                        'sort_order': sort_order,
                        'search': search
                    }
                }, 200
            except Exception as e2:
                logger.error(f"Error in fallback query: {str(e2)}")
                return {"message": "Error fetching partners. Please contact support."}, 500

    @jwt_required()
    def post(self, event_id=None):
        """
        Organizer-only endpoints:
        - POST /partners -> Create new partner (form-data + file upload) with AI assistance
        - POST /partners/events/<event_id> -> Add collaboration to event with AI validation
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)
            if not user or user.role != UserRole.ORGANIZER:
                return {"message": "Only organizers can create partners or collaborations"}, 403
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found"}, 404
            
            # If event_id exists → handle collaboration (JSON body expected)
            if event_id:
                data = request.get_json()
                if not data:
                    return {"message": "No data provided"}, 400
                return self._add_event_collaboration(organizer, event_id, data)
            
            # Otherwise → handle partner creation with AI assistance
            return self._create_partner(organizer, request.form, request.files)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in PartnerManagementResource POST: {str(e)}")
            return {"message": "Error processing request"}, 500

    def _create_partner(self, organizer, data, files):
        """Create a new partner company with AI assistance."""
        action = data.get('action', 'create')
        
        # ACTION: Get AI Suggestion
        if action == 'suggest':
            description = data.get('description')
            if not description:
                return {"message": "Description is required for AI suggestions"}, 400
            
            suggestion = partner_assistant.suggest_partner_from_description(
                organizer.id,
                description
            )
            
            if suggestion:
                return {
                    "action": "suggestion_generated",
                    "suggestion": {
                        "company_name": suggestion.get('company_name'),
                        "company_description": suggestion.get('company_description'),
                        "suggested_collaboration_types": suggestion.get('suggested_collaboration_types', []),
                        "target_audience": suggestion.get('target_audience'),
                        "ai_generated": suggestion.get('source') != 'fallback'
                    },
                    "next_actions": {
                        "create": "POST /partners with action='create' and partner details",
                        "modify": "Edit the suggestion and POST with action='create'",
                        "regenerate": "POST again with action='suggest' and modified description"
                    }
                }, 200
            else:
                return {"message": "Could not generate suggestion"}, 500
        
        # ACTION: Validate Partner Data
        elif action == 'validate':
            if "company_name" not in data:
                return {"message": "Company name is required for validation"}, 400
            
            validation = partner_assistant.validate_partner_data({
                "company_name": data.get("company_name"),
                "company_description": data.get("company_description"),
                "website_url": data.get("website_url"),
                "contact_email": data.get("contact_email"),
                "contact_person": data.get("contact_person"),
                "logo_url": "file" in files
            })
            
            return {
                "action": "validation_complete",
                "validation": validation,
                "next_actions": {
                    "create": "POST with action='create' if validation passes",
                    "modify": "Fix issues and validate again"
                }
            }, 200
        
        # ACTION: Create Partner
        elif action == 'create':
            if "company_name" not in data:
                return {"message": "Company name is required"}, 400
            
            # Check for existing partner
            existing = Partner.query.filter_by(
                organizer_id=organizer.id,
                company_name=data["company_name"],
                is_active=True
            ).first()
            
            if existing:
                # Check for similar partners
                try:
                    similar = partner_assistant.find_similar_partners(existing.id, limit=3)
                except Exception as e:
                    logger.error(f"Error finding similar partners: {e}")
                    similar = []
                
                return {
                    "message": "Partner with this company name already exists",
                    "existing_partner": existing.as_dict(),
                    "similar_partners": [
                        {"id": p.id, "company_name": p.company_name}
                        for p in similar
                    ] if similar else [],
                    "next_actions": {
                        "update_existing": f"PUT /partners/{existing.id}",
                        "use_different_name": "POST with different company_name"
                    }
                }, 409
            
            # Handle file upload (Cloudinary)
            logo_url = None
            if "file" in files:
                file = files["file"]
                if file and file.filename != "":
                    if not allowed_file(file.filename):
                        return {
                            "message": "Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP"
                        }, 400
                    try:
                        upload_result = cloudinary.uploader.upload(
                            file,
                            folder="partner_logos",
                            resource_type="auto"
                        )
                        logo_url = upload_result.get("secure_url")
                    except Exception as e:
                        logger.error(f"Error uploading partner logo: {str(e)}")
                        return {"message": "Failed to upload partner logo"}, 500
            
            # Create partner record
            partner = Partner(
                organizer_id=organizer.id,
                company_name=data["company_name"],
                company_description=data.get("company_description"),
                logo_url=logo_url,
                website_url=data.get("website_url"),
                contact_email=data.get("contact_email"),
                contact_person=data.get("contact_person")
            )
            
            try:
                db.session.add(partner)
                db.session.commit()
                
                # Optionally enhance description with AI
                enhanced_description = None
                if data.get('enhance_with_ai', 'false').lower() == 'true':
                    try:
                        enhanced_description = partner_assistant.enhance_partner_description(partner.id)
                    except Exception as e:
                        logger.error(f"Error enhancing description: {e}")
                
                response = {
                    "action": "partner_created",
                    "message": "Partner created successfully",
                    "partner": partner.as_dict(),
                    "ai_actions": {
                        "enhance_description": f"POST /partners/{partner.id}/ai/enhance-description",
                        "analyze": f"POST /partners/{partner.id}/ai/analyze"
                    }
                }
                
                if enhanced_description:
                    response["ai_enhanced_description"] = enhanced_description
                
                return response, 201
            except SQLAlchemyError as e:
                db.session.rollback()
                return {"message": f"Database error: {str(e)}"}, 500
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["suggest", "validate", "create"]
            }, 400

    def _add_event_collaboration(self, organizer, event_id, data):
        """Add a collaboration to an event with AI validation."""
        action = data.get('action', 'add')
        
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404
        
        # ACTION: Get AI Suggestions
        if action == 'suggest':
            try:
                suggestions = partner_assistant.suggest_collaborations_for_event(event_id, limit=5)
            except Exception as e:
                logger.error(f"Error getting suggestions: {e}")
                suggestions = []
            
            if suggestions:
                return {
                    "action": "suggestions_generated",
                    "event": {
                        "id": event.id,
                        "name": event.name
                    },
                    "suggested_partners": suggestions,
                    "next_actions": {
                        "add": "POST with action='add', partner_id, and collaboration details",
                        "view_partner": "GET /partners/{partner_id} for more details"
                    }
                }, 200
            else:
                return {"message": "No suitable partners found"}, 404
        
        # ACTION: Suggest Collaboration Terms
        elif action == 'suggest_terms':
            if 'partner_id' not in data:
                return {"message": "Partner ID is required"}, 400
            
            try:
                terms = partner_assistant.suggest_collaboration_terms(event_id, data['partner_id'])
            except Exception as e:
                logger.error(f"Error suggesting terms: {e}")
                terms = None
            
            if terms:
                return {
                    "action": "terms_suggested",
                    "suggested_terms": terms,
                    "next_actions": {
                        "add_with_terms": "POST with action='add' and suggested terms",
                        "modify_terms": "Adjust terms and POST with action='add'"
                    }
                }, 200
            else:
                return {"message": "Could not generate terms"}, 500
        
        # ACTION: Add Collaboration
        elif action == 'add':
            if 'partner_id' not in data:
                return {"message": "Partner ID is required"}, 400
            
            partner = Partner.query.filter_by(
                id=data['partner_id'],
                organizer_id=organizer.id,
                is_active=True
            ).first()
            
            if not partner:
                return {"message": "Partner not found or inactive"}, 404
            
            existing = EventCollaboration.query.filter_by(
                event_id=event.id,
                partner_id=partner.id,
                is_active=True
            ).first()
            
            if existing:
                return {
                    "message": "Collaboration already exists",
                    "existing_collaboration": existing.as_dict(),
                    "next_actions": {
                        "update": f"PUT /partners/events/{event_id}/collaborations/{existing.id}",
                        "optimize": f"GET /partners/events/{event_id}/collaborations/{existing.id}/ai/optimize"
                    }
                }, 409
            
            try:
                collaboration_type = CollaborationType(data.get('collaboration_type', 'PARTNER'))
            except ValueError:
                valid_types = [ct.value for ct in CollaborationType]
                return {"message": f"Invalid collaboration type. Valid options: {valid_types}"}, 400
            
            collaboration = EventCollaboration(
                event_id=event.id,
                partner_id=partner.id,
                collaboration_type=collaboration_type,
                description=data.get('description'),
                display_order=data.get('display_order', 0),
                show_on_event_page=data.get('show_on_event_page', True)
            )
            
            db.session.add(collaboration)
            db.session.commit()
            
            return {
                "action": "collaboration_added",
                "message": "Collaboration added successfully",
                "collaboration": collaboration.as_dict(),
                "ai_actions": {
                    "optimize": f"GET /partners/events/{event_id}/collaborations/{collaboration.id}/ai/optimize",
                    "analyze": f"POST /partners/events/{event_id}/collaborations/{collaboration.id}/ai/analyze"
                }
            }, 201
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["suggest", "suggest_terms", "add"]
            }, 400

    @jwt_required()
    def put(self, partner_id=None, event_id=None, collaboration_id=None):
        """
        Organizer-only endpoints:
        - PUT /partners/<id> -> Update partner (form-data + file upload) with AI assistance
        - PUT /partners/events/<event_id>/collaborations/<collaboration_id> -> Update collaboration
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)
            if not user or user.role != UserRole.ORGANIZER:
                return {"message": "Only organizers can update partners or collaborations"}, 403
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found"}, 404
            
            if collaboration_id:
                data = request.get_json()
                if not data:
                    return {"message": "No data provided"}, 400
                return self._update_collaboration(organizer, event_id, collaboration_id, data)
            elif partner_id:
                return self._update_partner(organizer, partner_id, request.form, request.files)
            else:
                return {"message": "Invalid endpoint"}, 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in PartnerManagementResource PUT: {str(e)}")
            return {"message": "Error processing request"}, 500

    def _update_partner(self, organizer, partner_id, data, files):
        """Update partner details with AI assistance."""
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404
        
        action = data.get('action', 'update')
        
        # ACTION: Enhance Description
        if action == 'enhance_description':
            try:
                enhanced = partner_assistant.enhance_partner_description(partner_id)
            except Exception as e:
                logger.error(f"Error enhancing description: {e}")
                enhanced = None
            
            if enhanced:
                return {
                    "action": "description_enhanced",
                    "current_description": partner.company_description,
                    "enhanced_description": enhanced,
                    "next_actions": {
                        "save": f"PUT /partners/{partner_id} with action='save_enhanced_description'",
                        "regenerate": f"PUT /partners/{partner_id} with action='enhance_description'",
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
                partner.company_description = data['description']
                
                # Check if ai_description_enhanced column exists before trying to update it
                try:
                    partner.ai_description_enhanced = True
                except AttributeError:
                    # Column doesn't exist, just log the error
                    logger.warning("ai_description_enhanced column does not exist, skipping update")
                
                partner.updated_at = datetime.utcnow()
                db.session.commit()
                
                return {
                    "action": "description_saved",
                    "message": "Enhanced description saved successfully",
                    "partner": partner.as_dict()
                }, 200
            except Exception as e:
                db.session.rollback()
                return {"message": f"Error saving description: {str(e)}"}, 400
        
        # ACTION: Validate Updates
        elif action == 'validate':
            try:
                validation = partner_assistant.validate_partner_data({
                    "company_name": data.get("company_name", partner.company_name),
                    "company_description": data.get("company_description", partner.company_description),
                    "website_url": data.get("website_url", partner.website_url),
                    "contact_email": data.get("contact_email", partner.contact_email),
                    "contact_person": data.get("contact_person", partner.contact_person)
                })
            except Exception as e:
                logger.error(f"Error validating partner data: {e}")
                validation = {"valid": False, "errors": [str(e)]}
            
            return {
                "action": "validation_complete",
                "validation": validation,
                "current_partner": partner.as_dict(),
                "proposed_changes": dict(data),
                "next_actions": {
                    "save": f"PUT /partners/{partner_id} with action='update'",
                    "cancel": "Discard changes"
                }
            }, 200
        
        # ACTION: Update Partner
        elif action == 'update':
            updatable_fields = [
                "company_name", "company_description", "website_url",
                "contact_email", "contact_person"
            ]
            
            # Handle logo file upload
            if "file" in files:
                file = files["file"]
                if file and file.filename != "":
                    if not allowed_file(file.filename):
                        return {"message": "Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WEBP"}, 400
                    try:
                        upload_result = cloudinary.uploader.upload(
                            file,
                            folder="partner_logos",
                            resource_type="auto"
                        )
                        partner.logo_url = upload_result.get("secure_url")
                    except Exception as e:
                        logger.error(f"Error uploading partner logo: {str(e)}")
                        return {"message": "Failed to upload partner logo"}, 500
            
            # Prevent duplicate company names
            if "company_name" in data and data["company_name"] != partner.company_name:
                existing = Partner.query.filter_by(
                    organizer_id=organizer.id,
                    company_name=data["company_name"],
                    is_active=True
                ).filter(Partner.id != partner_id).first()
                
                if existing:
                    return {
                        "message": "Partner with this company name already exists",
                        "existing_partner": existing.as_dict()
                    }, 409
            
            # Update text fields
            for field in updatable_fields:
                if field in data:
                    setattr(partner, field, data[field])
            
            partner.updated_at = datetime.utcnow()
            db.session.commit()
            
            return {
                "action": "partner_updated",
                "message": "Partner updated successfully",
                "partner": partner.as_dict(),
                "ai_actions": {
                    "enhance_description": f"PUT /partners/{partner_id} with action='enhance_description'",
                    "analyze": f"POST /partners/{partner_id}/ai/analyze"
                }
            }, 200
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["update", "validate", "enhance_description", "save_enhanced_description"]
            }, 400

    def _update_collaboration(self, organizer, event_id, collaboration_id, data):
        """Update collaboration details with AI optimization."""
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404
        
        collaboration = EventCollaboration.query.filter_by(
            id=collaboration_id,
            event_id=event.id
        ).first()
        
        if not collaboration:
            return {"message": "Collaboration not found"}, 404
        
        action = data.get('action', 'update')
        
        # ACTION: Get AI Optimization Suggestions
        if action == 'optimize':
            try:
                optimization = partner_assistant.optimize_collaboration(collaboration_id)
            except Exception as e:
                logger.error(f"Error optimizing collaboration: {e}")
                optimization = None
            
            if optimization:
                return {
                    "action": "optimization_suggested",
                    "current_collaboration": collaboration.as_dict(),
                    "optimization": optimization,
                    "next_actions": {
                        "apply": f"PUT /partners/events/{event_id}/collaborations/{collaboration_id} with action='update'",
                        "cancel": "Keep current settings"
                    }
                }, 200
            else:
                return {"message": "Could not generate optimization suggestions"}, 500
        
        # ACTION: Update Collaboration
        elif action == 'update':
            updatable_fields = [
                'collaboration_type', 'description', 'display_order', 'show_on_event_page'
            ]
            
            for field in updatable_fields:
                if field in data:
                    if field == 'collaboration_type':
                        try:
                            collaboration.collaboration_type = CollaborationType(data[field])
                        except ValueError:
                            valid_types = [ct.value for ct in CollaborationType]
                            return {"message": f"Invalid collaboration type. Valid options: {valid_types}"}, 400
                    else:
                        setattr(collaboration, field, data[field])
            
            db.session.commit()
            
            return {
                "action": "collaboration_updated",
                "message": "Collaboration updated successfully",
                "collaboration": collaboration.as_dict(),
                "ai_actions": {
                    "optimize": f"PUT /partners/events/{event_id}/collaborations/{collaboration_id} with action='optimize'"
                }
            }, 200
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["update", "optimize"]
            }, 400

    @jwt_required()
    def delete(self, partner_id=None, event_id=None, collaboration_id=None):
        """
        Organizer-only endpoints:
        - DELETE /partners/<id> -> Deactivate partner with impact analysis
        - DELETE /partners/events/<event_id>/collaborations/<collaboration_id> -> Remove collaboration
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)
            if not user or user.role != UserRole.ORGANIZER:
                return {"message": "Only organizers can delete partners or collaborations"}, 403
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found"}, 404
            
            if collaboration_id:
                return self._remove_collaboration(organizer, event_id, collaboration_id)
            elif partner_id:
                return self._deactivate_partner(organizer, partner_id)
            else:
                return {"message": "Invalid endpoint"}, 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in PartnerManagementResource DELETE: {str(e)}")
            return {"message": "Error processing request"}, 500

    def _deactivate_partner(self, organizer, partner_id):
        """Deactivate a partner with impact analysis."""
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404
        
        action = request.args.get('action', 'check_impact')
        
        # ACTION: Check Impact
        if action == 'check_impact':
            active_collaborations = EventCollaboration.query.filter_by(
                partner_id=partner.id,
                is_active=True
            ).all()
            
            # Get AI analysis
            try:
                performance = partner_assistant.analyze_partner_performance(partner_id)
            except:
                performance = None
            
            impact = {
                "action": "impact_analyzed",
                "partner": partner.as_dict(),
                "impact": {
                    "active_collaborations": len(active_collaborations),
                    "affected_events": [
                        {
                            "event_id": c.event_id,
                            "event_name": c.event.name if c.event else "Unknown"
                        }
                        for c in active_collaborations
                    ],
                    "total_collaborations": len(partner.collaborations)
                }
            }
            
            if performance:
                impact['ai_analysis'] = {
                    "performance_score": performance.get('statistics', {}).get('performance_score', 0),
                    "insights": performance.get('insights', ''),
                    "recommendations": performance.get('recommendations', [])
                }
            
            if len(active_collaborations) > 0:
                impact['warning'] = f"This partner has {len(active_collaborations)} active collaborations. Deactivating will affect these events."
            
            impact['next_actions'] = {
                "deactivate": f"DELETE /partners/{partner_id}?action=confirm_deactivate",
                "cancel": "Keep the partner active"
            }
            
            return impact, 200
        
        # ACTION: Confirm Deactivation
        elif action == 'confirm_deactivate':
            partner.is_active = False
            active_collaborations = EventCollaboration.query.filter_by(
                partner_id=partner.id,
                is_active=True
            ).all()
            
            for c in active_collaborations:
                c.is_active = False
            
            db.session.commit()
            
            return {
                "action": "partner_deactivated",
                "message": "Partner deactivated successfully",
                "deactivated_collaborations": len(active_collaborations),
                "partner_id": partner_id
            }, 200
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["check_impact", "confirm_deactivate"]
            }, 400

    def _remove_collaboration(self, organizer, event_id, collaboration_id):
        """Remove (deactivate) a collaboration with AI impact assessment."""
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404
        
        collaboration = EventCollaboration.query.filter_by(
            id=collaboration_id,
            event_id=event.id
        ).first()
        
        if not collaboration:
            return {"message": "Collaboration not found"}, 404
        
        action = request.args.get('action', 'check_impact')
        
        # ACTION: Check Impact
        if action == 'check_impact':
            # Get optimization analysis
            try:
                optimization = partner_assistant.optimize_collaboration(collaboration_id)
            except:
                optimization = None
            
            impact = {
                "action": "impact_analyzed",
                "collaboration": collaboration.as_dict(),
                "event": {
                    "id": event.id,
                    "name": event.name
                },
                "partner": {
                    "id": collaboration.partner.id,
                    "name": collaboration.partner.company_name
                } if collaboration.partner else None
            }
            
            if optimization:
                impact['ai_analysis'] = {
                    "status": optimization.get('status'),
                    "assessment": optimization.get('overall_assessment'),
                    "suggestions": optimization.get('optimizations', [])
                }
                
                if optimization.get('status') == 'optimal':
                    impact['warning'] = "This collaboration is performing well. Consider keeping it active."
            
            impact['next_actions'] = {
                "remove": f"DELETE /partners/events/{event_id}/collaborations/{collaboration_id}?action=confirm_remove",
                "optimize_instead": f"PUT /partners/events/{event_id}/collaborations/{collaboration_id} with action='optimize'",
                "cancel": "Keep the collaboration active"
            }
            
            return impact, 200
        
        # ACTION: Confirm Removal
        elif action == 'confirm_remove':
            collaboration.is_active = False
            db.session.commit()
            
            return {
                "action": "collaboration_removed",
                "message": "Collaboration removed successfully",
                "collaboration_id": collaboration_id
            }, 200
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["check_impact", "confirm_remove"]
            }, 400


class PartnerAIAssistResource(Resource):
    """AI Co-pilot endpoint for natural language partner management"""
    
    @jwt_required()
    def post(self):
        """Process natural language queries about partners and collaborations"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can use AI assistance"}, 403
        
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
        
        data = request.get_json()
        query = data.get('query')
        
        if not query:
            return {"message": "Query is required"}, 400
        
        # Process query
        try:
            result = partner_assistant.process_natural_language_query(query, organizer.id)
        except Exception as e:
            logger.error(f"Error processing natural language query: {e}")
            return {"message": "Error processing query"}, 500
        
        # Enhance response with actionable next steps
        intent = result.get('intent')
        params = result.get('params', {})
        
        if intent == 'create_partner':
            result['next_actions'] = {
                "suggest": "POST /partners with action='suggest' and description",
                "create_directly": "POST /partners with action='create' and partner details"
            }
        
        elif intent == 'find_partners':
            result['next_actions'] = {
                "search": "GET /partners?search={query}",
                "ai_match": "POST /partners/events/{event_id} with action='suggest'"
            }
        
        elif intent == 'analyze_partner':
            result['next_actions'] = {
                "view_analysis": "POST /partners/{id}/ai/analyze",
                "view_details": "GET /partners/{id}?include_ai_insights=true"
            }
        
        elif intent == 'suggest_collaborations':
            result['next_actions'] = {
                "get_suggestions": "POST /partners/events/{event_id} with action='suggest'",
                "suggest_terms": "POST /partners/events/{event_id} with action='suggest_terms'"
            }
        
        elif intent == 'optimize_collaboration':
            result['next_actions'] = {
                "get_optimization": "PUT /partners/events/{event_id}/collaborations/{id} with action='optimize'",
                "analyze": "POST /partners/events/{event_id}/collaborations/{id}/ai/analyze"
            }
        
        elif intent == 'list_partners':
            result['next_actions'] = {
                "list_with_insights": "GET /partners?include_ai_insights=true",
                "get_trends": "GET /partners/ai/trends"
            }
        
        elif intent == 'performance_report':
            result['next_actions'] = {
                "bulk_analyze": "POST /partners/ai/bulk-analyze",
                "get_trends": "GET /partners/ai/trends"
            }
        
        return result, 200


class PartnerAnalysisResource(Resource):
    """AI-powered partner analysis and insights"""
    
    @jwt_required()
    def post(self, partner_id):
        """Generate comprehensive AI analysis for a partner"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can analyze partners"}, 403
        
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
        
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404
        
        data = request.get_json() or {}
        action = data.get('action', 'analyze')
        
        # ACTION: Performance Analysis
        if action == 'analyze':
            try:
                analysis = partner_assistant.analyze_partner_performance(partner_id)
            except Exception as e:
                logger.error(f"Error analyzing partner performance: {e}")
                analysis = None
            
            if analysis:
                return {
                    "action": "analysis_complete",
                    "analysis": analysis,
                    "next_actions": {
                        "save": "POST with action='save_analysis' to store in database",
                        "regenerate": "POST with action='analyze' to refresh analysis"
                    }
                }, 200
            else:
                return {"message": "Could not generate analysis"}, 500
        
        # ACTION: Save Analysis
        elif action == 'save_analysis':
            try:
                analysis = partner_assistant.analyze_partner_performance(partner_id)
            except Exception as e:
                logger.error(f"Error analyzing partner performance: {e}")
                analysis = None
            
            if analysis:
                return {
                    "action": "analysis_saved",
                    "message": "Analysis saved successfully",
                    "analysis": analysis
                }, 200
            else:
                return {"message": "Could not save analysis"}, 500
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["analyze", "save_analysis"]
            }, 400
    
    @jwt_required()
    def get(self, partner_id):
        """Get latest AI insights for a partner"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can view insights"}, 403
        
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
        
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404
        
        # Get latest insights
        try:
            latest_insight = AIPartnerInsight.query.filter_by(
                partner_id=partner_id,
                is_active=True
            ).order_by(AIPartnerInsight.created_at.desc()).first()
        except Exception as e:
            logger.error(f"Error getting latest insight: {e}")
            latest_insight = None
        
        if latest_insight:
            return {
                "action": "insights_retrieved",
                "insights": latest_insight.as_dict(),
                "partner": partner.as_dict(),
                "next_actions": {
                    "regenerate": f"POST /partners/{partner_id}/ai/analyze"
                }
            }, 200
        else:
            return {
                "message": "No insights available",
                "next_actions": {
                    "generate": f"POST /partners/{partner_id}/ai/analyze"
                }
            }, 404


class PartnerEnhanceResource(Resource):
    """AI enhancement for partner descriptions"""
    
    @jwt_required()
    def post(self, partner_id):
        """Enhance partner description with AI"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can enhance partners"}, 403
        
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
        
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404
        
        data = request.get_json() or {}
        action = data.get('action', 'enhance')
        
        # ACTION: Enhance Description
        if action == 'enhance':
            try:
                enhanced = partner_assistant.enhance_partner_description(partner_id)
            except Exception as e:
                logger.error(f"Error enhancing description: {e}")
                enhanced = None
            
            if enhanced:
                return {
                    "action": "description_enhanced",
                    "current_description": partner.company_description,
                    "enhanced_description": enhanced,
                    "next_actions": {
                        "save": f"POST /partners/{partner_id}/ai/enhance-description with action='save'",
                        "regenerate": f"POST /partners/{partner_id}/ai/enhance-description",
                        "cancel": "Keep current description"
                    }
                }, 200
            else:
                return {"message": "Could not enhance description"}, 500
        
        # ACTION: Save Enhanced Description
        elif action == 'save':
            if 'description' not in data:
                return {"message": "Description is required"}, 400
            
            try:
                partner.company_description = data['description']
                
                # Check if ai_description_enhanced column exists before trying to update it
                try:
                    partner.ai_description_enhanced = True
                except AttributeError:
                    # Column doesn't exist, just log the error
                    logger.warning("ai_description_enhanced column does not exist, skipping update")
                
                partner.updated_at = datetime.utcnow()
                db.session.commit()
                
                return {
                    "action": "description_saved",
                    "message": "Enhanced description saved successfully",
                    "partner": partner.as_dict()
                }, 200
            except Exception as e:
                db.session.rollback()
                return {"message": f"Error saving description: {str(e)}"}, 400
        
        else:
            return {
                "message": "Invalid action",
                "valid_actions": ["enhance", "save"]
            }, 400


class PartnerTrendsResource(Resource):
    """Partnership trends and analytics"""
    
    @jwt_required()
    def get(self):
        """Get partnership trends for the organizer"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can view trends"}, 403
        
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
        
        try:
            trends = partner_assistant.identify_partnership_trends(organizer.id)
        except Exception as e:
            logger.error(f"Error identifying partnership trends: {e}")
            trends = None
        
        if trends:
            return {
                "action": "trends_analyzed",
                "trends": trends,
                "next_actions": {
                    "bulk_analyze": "POST /partners/ai/bulk-analyze",
                    "view_recommendations": "GET /partners/ai/recommendations"
                }
            }, 200
        else:
            return {"message": "Could not generate trends analysis"}, 500


class PartnerBulkAnalysisResource(Resource):
    """Bulk analysis for all partners"""
    
    @jwt_required()
    def post(self):
        """Analyze all partners at once"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can perform bulk analysis"}, 403
        
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
        
        try:
            analysis = partner_assistant.bulk_analyze_partners(organizer.id)
        except Exception as e:
            logger.error(f"Error in bulk analysis: {e}")
            analysis = None
        
        if analysis:
            return {
                "action": "bulk_analysis_complete",
                "analysis": analysis,
                "next_actions": {
                    "view_high_performers": "Filter analyses by high_performers",
                    "address_concerns": "Review partners in needs_attention list"
                }
            }, 200
        else:
            return {"message": "Could not perform bulk analysis"}, 500


class PartnerRecommendationsResource(Resource):
    """AI recommendations summary"""
    
    @jwt_required()
    def get(self):
        """Get summary of all AI recommendations"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can view recommendations"}, 403
        
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
        
        try:
            summary = partner_assistant.get_partner_recommendations_summary(organizer.id)
        except Exception as e:
            logger.error(f"Error getting partner recommendations: {e}")
            summary = None
        
        if summary:
            return {
                "action": "recommendations_retrieved",
                "summary": summary,
                "next_actions": {
                    "view_partner": "GET /partners/{id}?include_ai_insights=true",
                    "act_on_recommendation": "POST /partners/events/{event_id} with recommended partner_id"
                }
            }, 200
        else:
            return {"message": "No recommendations available"}, 404


class CollaborationOptimizeResource(Resource):
    """AI optimization for collaborations"""
    
    @jwt_required()
    def get(self, event_id, collaboration_id):
        """Get AI optimization suggestions for a collaboration"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can optimize collaborations"}, 403
        
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
        
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404
        
        collaboration = EventCollaboration.query.filter_by(
            id=collaboration_id,
            event_id=event.id
        ).first()
        
        if not collaboration:
            return {"message": "Collaboration not found"}, 404
        
        try:
            optimization = partner_assistant.optimize_collaboration(collaboration_id)
        except Exception as e:
            logger.error(f"Error optimizing collaboration: {e}")
            optimization = None
        
        if optimization:
            return {
                "action": "optimization_generated",
                "current_collaboration": collaboration.as_dict(),
                "optimization": optimization,
                "next_actions": {
                    "apply": f"PUT /partners/events/{event_id}/collaborations/{collaboration_id} with suggested changes",
                    "regenerate": f"GET /partners/events/{event_id}/collaborations/{collaboration_id}/ai/optimize"
                }
            }, 200
        else:
            return {"message": "Could not generate optimization"}, 500


class PublicEventCollaborationsResource(Resource):
    """Public API for viewing active collaborations across multiple events."""

    @jwt_required()
    def get(self):
        """Get active collaborations for multiple events (all logged-in users) with pagination."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)
            if not user:
                return {"message": "Authentication required"}, 401
            
            # Get query parameters
            event_ids = request.args.get('event_ids')
            organizer_id = request.args.get('organizer_id')
            
            # Pagination params
            page = request.args.get('page', 1, type=int)
            per_page = min(request.args.get('per_page', 12, type=int), 50)
            
            query = EventCollaboration.query.filter_by(is_active=True).join(Event).join(Partner)
            
            # Filter by specific events
            if event_ids:
                try:
                    event_id_list = [int(id.strip()) for id in event_ids.split(',')]
                    query = query.filter(EventCollaboration.event_id.in_(event_id_list))
                except ValueError:
                    return {"message": "Invalid event IDs format"}, 400
            
            # Filter by organizer
            if organizer_id:
                try:
                    organizer_id = int(organizer_id)
                    query = query.filter(Event.organizer_id == organizer_id)
                except ValueError:
                    return {"message": "Invalid organizer ID"}, 400
            
            # Paginate collaborations
            collaborations = query.paginate(page=page, per_page=per_page, error_out=False)
            
            if not collaborations.items:
                return {
                    'events': [],
                    'total': 0,
                    'pages': 0,
                    'current_page': page,
                    'per_page': per_page,
                    'has_next': False,
                    'has_prev': False
                }, 200
            
            # Group collaborations by event
            events_data = {}
            for collab in collaborations.items:
                event_id = collab.event_id
                if event_id not in events_data:
                    events_data[event_id] = {
                        'event_id': event_id,
                        'event_name': collab.event.name,
                        'organizer_name': collab.event.organizer.company_name if collab.event.organizer else None,
                        'collaborations': []
                    }
                
                # Include partner details along with collaboration
                collab_data = collab.as_dict()
                collab_data["partner"] = collab.partner.as_dict() if collab.partner else None
                events_data[event_id]['collaborations'].append(collab_data)
            
            return {
                'events': list(events_data.values()),
                'total': collaborations.total,
                'pages': collaborations.pages,
                'current_page': collaborations.page,
                'per_page': collaborations.per_page,
                'has_next': collaborations.has_next,
                'has_prev': collaborations.has_prev,
                'total_collaborations': collaborations.total
            }, 200
        except Exception as e:
            logger.error(f"Error fetching public collaborations: {str(e)}")
            return {"message": "Error fetching collaborations"}, 500


def register_organizer_and_public_partner_resources(api):
    """Register organizer and public partner resources with Flask-RESTful API."""
    
    # Core partner management
    api.add_resource(
        PartnerManagementResource,
        '/api/partners',
        '/api/partners/<int:partner_id>',
        '/api/partners/events/<int:event_id>',
        '/api/partners/events/<int:event_id>/collaborations/<int:collaboration_id>',
    )
    
    # AI assistance endpoints
    api.add_resource(
        PartnerAIAssistResource,
        '/api/partners/ai/assist'
    )
    
    api.add_resource(
        PartnerAnalysisResource,
        '/api/partners/<int:partner_id>/ai/analyze'
    )
    
    api.add_resource(
        PartnerEnhanceResource,
        '/api/partners/<int:partner_id>/ai/enhance-description'
    )
    
    api.add_resource(
        PartnerTrendsResource,
        '/api/partners/ai/trends'
    )
    
    api.add_resource(
        PartnerBulkAnalysisResource,
        '/api/partners/ai/bulk-analyze'
    )
    
    api.add_resource(
        PartnerRecommendationsResource,
        '/api/partners/ai/recommendations'
    )
    
    api.add_resource(
        CollaborationOptimizeResource,
        '/api/partners/events/<int:event_id>/collaborations/<int:collaboration_id>/ai/optimize'
    )
    
    # Public endpoint
    api.add_resource(
        PublicEventCollaborationsResource,
        '/api/public/collaborations'
    )