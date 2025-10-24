import json
from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime, timedelta
from model import (db, Event, User, UserRole, Organizer, Category, Partner, 
                   EventCollaboration, CollaborationType, CollaborationManager,
                   AIEventDraft, AIEventManager)
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import cloudinary.uploader
import logging
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy import func, distinct

# Import the comprehensive event assistant
from ai.event_assistant import comprehensive_event_assistant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class EventResource(Resource):

    def get(self, event_id=None):
        """Retrieve an event by ID or return events based on user role and permissions with advanced filtering."""
        # Check if user is authenticated (optional authentication)
        user = None
        try:
            from flask_jwt_extended import verify_jwt_in_request
            verify_jwt_in_request(optional=True)  # Optional authentication
            identity = get_jwt_identity()
            if identity:
                user = User.query.get(identity)
        except:
            # No authentication or invalid token - continue as public user
            pass

        # Check if collaborators should be included in response
        include_collaborators = request.args.get('include_collaborators', 'false').lower() == 'true'

        if event_id:
            try:
                event = Event.query.get(event_id)
                if not event:
                    return {"message": "Event not found"}, 404
                
                # If user is an organizer, check if they own the event
                if user and user.role == UserRole.ORGANIZER:
                    organizer = Organizer.query.filter_by(user_id=user.id).first()
                    if organizer and event.organizer_id != organizer.id:
                        return {"error": "Access denied. You can only view your own events"}, 403
                
                # Return event with or without collaborators based on request
                if include_collaborators:
                    return event.as_dict_with_collaborators(), 200
                else:
                    return event.as_dict(), 200
            except (OperationalError, SQLAlchemyError) as e:
                logger.error(f"Database error: {str(e)}")
                return {"message": "Database connection error"}, 500

        # Get query parameters
        page = request.args.get('page', 1, type=int)
        # Increased default per_page for better infinite scroll experience and capped for performance
        per_page = min(request.args.get('per_page', 12, type=int), 50)  # Cap at 50 for performance
        show_all = request.args.get('show_all', 'false').lower() == 'true'
        
        # Determine if this is a dashboard request (admin/organizer) or public view
        is_dashboard = request.args.get('dashboard', 'false').lower() == 'true'
        
        # Filter parameters (only apply advanced filters for dashboard views)
        category_id = request.args.get('category_id', type=int) if is_dashboard else None
        category_name = request.args.get('category_name', type=str) if is_dashboard else None
        organizer_company = request.args.get('organizer_company', type=str) if is_dashboard else None
        start_date = request.args.get('start_date', type=str) if is_dashboard else None
        end_date = request.args.get('end_date', type=str) if is_dashboard else None
        
        # Basic filters available for both public and dashboard views
        search_query = request.args.get('search', type=str)    # General search in name/description
        basic_category = request.args.get('category', type=str) if not is_dashboard else None  # Public category filter
        time_filter = request.args.get('time_filter', 'upcoming', type=str)  # upcoming, today, past, all
        featured_only = request.args.get('featured', 'false').lower() == 'true'  # Show only featured events
        location_filter = request.args.get('location', type=str)  # Filter by venue/location
        city_filter = request.args.get('city', type=str)  # Filter by city
        amenity_filter = request.args.get('amenity', type=str)  # Filter by specific amenity
        
        # Sorting
        sort_by = request.args.get('sort_by', 'date', type=str)  # date, name, created_at, featured
        sort_order = request.args.get('sort_order', 'asc', type=str)  # asc, desc

        try:
            # Base query with joins for filtering
            query = Event.query.join(Organizer).join(Category, Event.category_id == Category.id, isouter=True)

            # Role-based access control and dashboard-specific filtering
            if is_dashboard:
                # Dashboard view - apply role-based access and advanced filters
                if user and user.role == UserRole.ORGANIZER and not show_all:
                    organizer = Organizer.query.filter_by(user_id=user.id).first()
                    if not organizer:
                        return {"error": "Organizer profile not found"}, 404
                    
                    query = query.filter(Event.organizer_id == organizer.id)
                elif user and user.role == UserRole.ADMIN:
                    # Admin can see all events in dashboard
                    pass
                else:
                    # Non-admin/organizer shouldn't access dashboard view
                    return {"error": "Access denied to dashboard view"}, 403

                # Apply advanced dashboard filters
                if category_id:
                    query = query.filter(Event.category_id == category_id)
                
                if category_name:
                    query = query.filter(Category.name.ilike(f'%{category_name}%'))
                
                if organizer_company:
                    query = query.filter(Organizer.company_name.ilike(f'%{organizer_company}%'))
                
                # Date range filtering for dashboard
                if start_date:
                    try:
                        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                        query = query.filter(Event.date >= start_date_obj)
                    except ValueError:
                        return {"error": "Invalid start_date format. Use YYYY-MM-DD"}, 400
                
                if end_date:
                    try:
                        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                        query = query.filter(Event.date <= end_date_obj)
                    except ValueError:
                        return {"error": "Invalid end_date format. Use YYYY-MM-DD"}, 400
            else:
                # Public view - show all public events with basic filters only
                # Add any public event visibility filters here (e.g., published events only)
                # query = query.filter(Event.is_published == True)  # Uncomment if you have this field
                
                # Basic category filter for public view
                if basic_category:
                    query = query.filter(Category.name.ilike(f'%{basic_category}%'))

            # Time-based filtering (available for both public and dashboard views)
            current_date = datetime.now().date()
            if time_filter == 'upcoming':
                query = query.filter(Event.date >= current_date)
            elif time_filter == 'today':
                query = query.filter(Event.date == current_date)
            elif time_filter == 'past':
                query = query.filter(Event.date < current_date)
            # 'all' shows all events regardless of date
            
            # General search in event name, description, location, and city
            if search_query:
                search_pattern = f'%{search_query}%'
                query = query.filter(
                    db.or_(
                        Event.name.ilike(search_pattern),
                        Event.description.ilike(search_pattern),
                        Event.location.ilike(search_pattern),
                        Event.city.ilike(search_pattern)
                    )
                )

            # Featured events filter
            if featured_only:
                query = query.filter(Event.featured == True)
            
            # Location filter (venue/specific location)
            if location_filter:
                query = query.filter(Event.location.ilike(f'%{location_filter}%'))
            
            # City filter
            if city_filter:
                query = query.filter(Event.city.ilike(f'%{city_filter}%'))
            
            # Amenity filter
            if amenity_filter:
                # Use JSON contains for amenity filtering
                query = query.filter(
                    func.json_contains(Event.amenities, f'["{amenity_filter}"]')
                )

            # Sorting
            if sort_by == 'name':
                if sort_order.lower() == 'desc':
                    query = query.order_by(Event.name.desc())
                else:
                    query = query.order_by(Event.name.asc())
            elif sort_by == 'featured':
                # Sort by featured first, then by date
                if sort_order.lower() == 'desc':
                    query = query.order_by(Event.featured.desc(), Event.date.desc())
                else:
                    query = query.order_by(Event.featured.desc(), Event.date.asc())
            elif sort_by == 'created_at':
                if hasattr(Event, 'created_at'):
                    if sort_order.lower() == 'desc':
                        query = query.order_by(Event.created_at.desc())
                    else:
                        query = query.order_by(Event.created_at.asc())
                else:
                    # Fallback to date if created_at doesn't exist
                    if sort_order.lower() == 'desc':
                        query = query.order_by(Event.date.desc())
                    else:
                        query = query.order_by(Event.date.asc())
            else:  # Default to date
                if sort_order.lower() == 'desc':
                    query = query.order_by(Event.date.desc())
                else:
                    query = query.order_by(Event.date.asc())

            # Paginate results
            events = query.paginate(page=page, per_page=per_page, error_out=False)

            if not events.items:
                return {
                    'events': [],
                    'total': 0,
                    'pages': 0,
                    'current_page': page,
                    'per_page': per_page,
                    'has_next': False,
                    'has_prev': False,
                    'filters_applied': self._get_applied_filters_summary(
                        category_id, category_name, organizer_company, 
                        start_date, end_date, search_query, basic_category, 
                        time_filter, is_dashboard, featured_only, location_filter,
                        city_filter, amenity_filter
                    ),
                    'available_filters': self._get_available_filters(user, is_dashboard),
                    'view_type': 'dashboard' if is_dashboard else 'public'
                }

            # Format events data - include collaborators if requested
            events_data = []
            for event in events.items:
                if include_collaborators:
                    event_dict = event.as_dict_with_collaborators()
                else:
                    event_dict = {
                        'id': event.id,
                        'name': event.name,
                        'description': event.description,
                        'date': event.date.isoformat(),
                        'start_time': event.start_time.isoformat(),
                        'end_time': event.end_time.isoformat() if event.end_time else None,
                        'city': event.city,
                        'location': event.location,
                        'amenities': event.amenities or [],
                        'image': event.image,
                        'category': event.event_category.name if event.event_category else None,
                        'category_id': event.category_id,
                        'featured': event.featured,
                        'organizer': {
                            'id': event.organizer.id,
                            'company_name': event.organizer.company_name,
                            'company_logo': event.organizer.company_logo,
                            'media': event.organizer.social_media_links,
                            'address': event.organizer.address,
                            'website': event.organizer.website,
                            'company_description': event.organizer.company_description
                        },
                        'likes_count': event.likes.count(),
                        'created_at': event.created_at.isoformat() if hasattr(event, 'created_at') else None,
                        'ai_assisted_creation': getattr(event, 'ai_assisted_creation', False),
                        'ai_confidence_score': getattr(event, 'ai_confidence_score', None)
                    }
                events_data.append(event_dict)

            return {
                'events': events_data,
                'total': events.total,
                'pages': events.pages,
                'current_page': events.page,
                'per_page': events.per_page,
                'has_next': events.has_next,
                'has_prev': events.has_prev,
                'filters_applied': self._get_applied_filters_summary(
                    category_id, category_name, organizer_company, 
                    start_date, end_date, search_query, basic_category,
                    time_filter, is_dashboard, featured_only, location_filter,
                    city_filter, amenity_filter
                ),
                'available_filters': self._get_available_filters(user, is_dashboard),
                'view_type': 'dashboard' if is_dashboard else 'public'
            }, 200

        except (OperationalError, SQLAlchemyError) as e:
            logger.error(f"Database error: {str(e)}")
            return {"message": "Database connection error"}, 500
        except Exception as e:
            logger.error(f"Error fetching events: {str(e)}")
            return {"message": "Error fetching events"}, 500

    def _get_applied_filters_summary(self, category_id, category_name, organizer_company, 
                                   start_date, end_date, search_query, basic_category, 
                                   time_filter, is_dashboard, featured_only, location_filter,
                                   city_filter, amenity_filter):
        """Return a summary of applied filters for frontend display."""
        filters = {}
        
        if is_dashboard:
            # Dashboard-specific filters
            if category_id:
                filters['category_id'] = category_id
            if category_name:
                filters['category_name'] = category_name
            if organizer_company:
                filters['organizer_company'] = organizer_company
            if start_date:
                filters['start_date'] = start_date
            if end_date:
                filters['end_date'] = end_date
        else:
            # Public view filters
            if basic_category:
                filters['category'] = basic_category
        
        # Common filters
        if search_query:
            filters['search'] = search_query
        if time_filter and time_filter != 'upcoming':  # Don't show default
            filters['time_filter'] = time_filter
        if featured_only:
            filters['featured'] = featured_only
        if location_filter:
            filters['location'] = location_filter
        if city_filter:
            filters['city'] = city_filter
        if amenity_filter:
            filters['amenity'] = amenity_filter
            
        return filters

    def _get_available_filters(self, user, is_dashboard):
        """Return available filter options based on user role and view type."""
        try:
            filters = {
                'categories': [],
                'cities': [],
                'amenities': [],
                'time_filters': [
                    {'value': 'upcoming', 'label': 'Upcoming Events'},
                    {'value': 'today', 'label': 'Today'},
                    {'value': 'past', 'label': 'Past Events'},
                    {'value': 'all', 'label': 'All Events'}
                ],
                'sort_options': [
                    {'value': 'date', 'label': 'Date'},
                    {'value': 'name', 'label': 'Name'},
                    {'value': 'featured', 'label': 'Featured First'},
                    {'value': 'created_at', 'label': 'Recently Added'}
                ]
            }

            # Get available categories
            categories = Category.query.all()
            filters['categories'] = [{'id': cat.id, 'name': cat.name} for cat in categories]

            # Get available cities
            cities = db.session.query(distinct(Event.city)).filter(Event.city.isnot(None)).all()
            filters['cities'] = [city[0] for city in cities if city[0]]

            # Get available amenities (from all events)
            amenities_query = db.session.query(Event.amenities).filter(Event.amenities.isnot(None)).all()
            all_amenities = set()
            for amenity_list in amenities_query:
                if amenity_list[0]:  # Check if amenities is not None
                    all_amenities.update(amenity_list[0])
            filters['amenities'] = sorted(list(all_amenities))

            if is_dashboard:
                # Dashboard-specific filters
                filters['organizers'] = []
                filters['date_range'] = {'min_date': None, 'max_date': None}
                
                # Get available organizers based on role
                if user and user.role == UserRole.ADMIN:
                    organizers = Organizer.query.all()
                    filters['organizers'] = [
                        {'id': org.id, 'company_name': org.company_name} 
                        for org in organizers
                    ]
                elif user and user.role == UserRole.ORGANIZER:
                    # Organizer only sees their own company
                    organizer = Organizer.query.filter_by(user_id=user.id).first()
                    if organizer:
                        filters['organizers'] = [
                            {'id': organizer.id, 'company_name': organizer.company_name}
                        ]

                # Get date range from existing events
                date_range = db.session.query(
                    db.func.min(Event.date).label('min_date'),
                    db.func.max(Event.date).label('max_date')
                ).first()
                
                if date_range and date_range.min_date and date_range.max_date:
                    filters['date_range']['min_date'] = date_range.min_date.isoformat()
                    filters['date_range']['max_date'] = date_range.max_date.isoformat()

            return filters

        except Exception as e:
            logger.error(f"Error getting available filters: {str(e)}")
            return {
                'categories': [],
                'cities': [],
                'amenities': [],
                'time_filters': [],
                'organizers': [] if is_dashboard else None,
                'date_range': {'min_date': None, 'max_date': None} if is_dashboard else None
            }

    
    @jwt_required()
    def post(self):
        """Create a new event with AI assistance (Only organizers can create events)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user or user.role != UserRole.ORGANIZER:
                return {"message": "Only organizers can create events"}, 403

            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found"}, 404

            content_type = request.content_type or ""
            
            # Check if this is an AI-assisted creation request
            use_ai_assistant = request.args.get('ai_assistant', 'true').lower() == 'true'
            conversational_input = request.args.get('conversational_input', None)
            
            # Handle AI-assisted conversational creation
            if use_ai_assistant and conversational_input:
                return self._handle_ai_assisted_creation(organizer.id, conversational_input, user.id)
            
            # Handle traditional form-based creation (with optional AI enhancement)
            if "multipart/form-data" in content_type:
                return self._handle_form_based_creation(organizer, request)
            elif "application/json" in content_type:
                return self._handle_json_creation(organizer, request.get_json())
            else:
                return {"error": "Unsupported Content-Type. Use multipart/form-data or application/json"}, 415

        except Exception as e:
            logger.error(f"Error in event creation: {e}")
            return {"error": f"An error occurred: {str(e)}"}, 500

    def _handle_ai_assisted_creation(self, organizer_id: int, conversational_input: str, user_id: int):
        """Handle AI-assisted event creation from conversational input"""
        try:
            # Get context if available
            context = {
                "previous_events": self._get_organizer_previous_events(organizer_id),
                "organizer_preferences": self._get_organizer_preferences(organizer_id)
            }
            
            # Use the comprehensive event assistant
            result = comprehensive_event_assistant.create_event_conversational(
                organizer_id=organizer_id,
                user_input=conversational_input,
                context=context
            )
            
            if result.get('success'):
                return {
                    "message": "AI-assisted event creation started",
                    "draft_created": True,
                    "draft_id": result['draft_id'],
                    "conversational_response": result['conversational_response'],
                    "suggestions": result['suggestions'],  # <-- Now contains actual event fields
                    "strategic_recommendations": result.get('strategic_recommendations', {}),  # <-- Strategic suggestions here
                    "completion_status": result['completion_status'],
                    "next_steps": result['next_steps'],
                    "ai_confidence": result.get('ai_confidence', 0.5)
                }, 201
            else:
                return {
                    "message": "AI-assisted creation failed",
                    "error": result.get('error', 'Unknown error'),
                    "fallback_available": result.get('fallback_available', False)
                }, 400
                
        except Exception as e:
            logger.error(f"AI-assisted creation failed: {e}")
            return {
                "message": "AI service temporarily unavailable",
                "error": str(e)
            }, 503

    def _handle_form_based_creation(self, organizer, request):
        """Handle traditional form-based event creation with optional AI enhancement"""
        data = request.form
        files = request.files

        # Check if we should use AI to enhance the creation
        enhance_with_ai = data.get('enhance_with_ai', 'false').lower() == 'true'
        
        if enhance_with_ai:
            return self._handle_ai_enhanced_form_creation(organizer, data, files)
        else:
            return self._handle_manual_form_creation(organizer, data, files)

    def _handle_ai_enhanced_form_creation(self, organizer, data, files):
        """Handle form-based creation with AI enhancement"""
        try:
            # Extract user input for AI processing
            user_input = {
                "name": data.get("name"),
                "description": data.get("description"),
                "date": data.get("date"),
                "start_time": data.get("start_time"),
                "city": data.get("city"),
                "location": data.get("location"),
                "category_id": data.get("category_id"),
                "raw_text": f"Create event: {data.get('name', '')}. {data.get('description', '')}"
            }
            
            # Use AI to enhance the event data
            context = {
                "previous_events": self._get_organizer_previous_events(organizer.id),
                "form_data": data
            }
            
            ai_result = comprehensive_event_assistant.create_event_conversational(
                organizer_id=organizer.id,
                user_input=user_input['raw_text'],
                context=context
            )
            
            if ai_result.get('success'):
                # Use AI-enhanced data but allow manual overrides
                draft = AIEventDraft.query.get(ai_result['draft_id'])
                
                # Apply manual overrides from form data
                if data.get("name"):
                    draft.suggested_name = data["name"]
                    draft.name_source = 'user'
                    draft.name_confidence = 1.0
                
                if data.get("description"):
                    draft.suggested_description = data["description"]
                    draft.description_source = 'user'
                    draft.description_confidence = 1.0
                
                # Handle file upload
                image_url = self._handle_file_upload(files.get('file'))
                if image_url:
                    draft.suggested_image_url = image_url
                
                db.session.commit()
                
                # Publish the enhanced draft
                event = AIEventManager.publish_draft(draft.id)
                
                return {
                    "message": "Event created successfully with AI enhancement",
                    "event": event.as_dict(),
                    "id": event.id,
                    "ai_assisted": True,
                    "ai_confidence": event.ai_confidence_score,
                    "ai_generated_fields": event.ai_generated_fields
                }, 201
            else:
                # Fall back to manual creation if AI fails
                return self._handle_manual_form_creation(organizer, data, files)
                
        except Exception as e:
            logger.error(f"AI-enhanced creation failed, falling back to manual: {e}")
            return self._handle_manual_form_creation(organizer, data, files)

    def _handle_manual_form_creation(self, organizer, data, files):
        """Handle traditional manual form-based creation"""
        # Validate required fields
        required_fields = ["name", "description", "date", "start_time", "city", "location"]
        for field in required_fields:
            if field not in data:
                return {"message": f"Missing field: {field}"}, 400

        # Handle file upload
        image_url = self._handle_file_upload(files.get('file'))

        # Parse dates and times
        try:
            event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            
            end_time = None
            if "end_time" in data and data["end_time"]:
                end_time = datetime.strptime(data["end_time"], "%H:%M").time()
        except ValueError as e:
            return {"error": f"Invalid date/time format: {str(e)}"}, 400

        # Handle amenities
        amenities = self._parse_amenities(data.get("amenities"))

        # Validate category
        category_id = data.get('category_id')
        if category_id:
            category = Category.query.get(category_id)
            if not category:
                return {"message": "Invalid category ID"}, 400

        # Create Event instance
        event = Event(
            name=data["name"],
            description=data["description"],
            date=event_date,
            start_time=start_time,
            end_time=end_time,
            city=data["city"],
            location=data["location"],
            amenities=amenities,
            image=image_url,
            organizer_id=organizer.id,
            category_id=category_id,
            ai_assisted_creation=False  # Manual creation
        )

        try:
            event.validate_datetime()
            db.session.add(event)
            db.session.commit()
            
            return {
                "message": "Event created successfully",
                "event": event.as_dict(),
                "id": event.id,
                "ai_assisted": False
            }, 201
            
        except ValueError as e:
            db.session.rollback()
            return {"error": str(e)}, 400
        except Exception as e:
            db.session.rollback()
            return {"error": f"Failed to create event: {str(e)}"}, 500

    def _handle_json_creation(self, organizer, data):
        """Handle JSON-based event creation"""
        if not data:
            return {"error": "No data provided"}, 400

        # Similar to form-based but without file handling
        required_fields = ["name", "description", "date", "start_time", "city", "location"]
        for field in required_fields:
            if field not in data:
                return {"message": f"Missing field: {field}"}, 400

        # Parse dates and times
        try:
            event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            
            end_time = None
            if "end_time" in data and data["end_time"]:
                end_time = datetime.strptime(data["end_time"], "%H:%M").time()
        except ValueError as e:
            return {"error": f"Invalid date/time format: {str(e)}"}, 400

        # Handle amenities
        amenities = self._parse_amenities(data.get("amenities"))

        # Validate category
        category_id = data.get('category_id')
        if category_id:
            category = Category.query.get(category_id)
            if not category:
                return {"message": "Invalid category ID"}, 400

        # Create Event instance
        event = Event(
            name=data["name"],
            description=data["description"],
            date=event_date,
            start_time=start_time,
            end_time=end_time,
            city=data["city"],
            location=data["location"],
            amenities=amenities,
            image=data.get('image'),  # URL from JSON
            organizer_id=organizer.id,
            category_id=category_id,
            ai_assisted_creation=data.get('ai_assisted', False)
        )

        try:
            event.validate_datetime()
            db.session.add(event)
            db.session.commit()
            
            return {
                "message": "Event created successfully",
                "event": event.as_dict(),
                "id": event.id,
                "ai_assisted": event.ai_assisted_creation
            }, 201
            
        except ValueError as e:
            db.session.rollback()
            return {"error": str(e)}, 400
        except Exception as e:
            db.session.rollback()
            return {"error": f"Failed to create event: {str(e)}"}, 500

    @jwt_required()
    def put(self, event_id):
        """Update an existing event with AI assistance. Only the event's creator (organizer) can update it."""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        event = Event.query.get(event_id)
        organizer = Organizer.query.filter_by(user_id=user.id).first()

        if not user:
            return {"error": "User not found"}, 404

        if not event:
            return {"error": "Event not found"}, 404

        if user.role != UserRole.ORGANIZER or event.organizer_id != organizer.id:
            return {"message": "Only the event creator (organizer) can update this event"}, 403

        content_type = request.content_type or ""
        
        # Check if this is an AI-assisted update
        use_ai_assistant = request.args.get('ai_assistant', 'false').lower() == 'true'
        conversational_update = request.args.get('conversational_input', None)
        
        if use_ai_assistant and conversational_update:
            return self._handle_ai_assisted_update(event, conversational_update, user.id)
        
        try:
            if "application/json" in content_type:
                data = request.get_json()
            elif "multipart/form-data" in content_type:
                data = request.form
            else:
                return {"error": "Unsupported Content-Type"}, 415

            if not data:
                return {"error": "No data provided"}, 400

            # Check if we should use AI to optimize the update
            optimize_with_ai = data.get('optimize_with_ai', 'false').lower() == 'true'
            
            if optimize_with_ai:
                return self._handle_ai_optimized_update(event, data, request.files)
            else:
                return self._handle_manual_update(event, data, request.files)

        except Exception as e:
            db.session.rollback()
            return {"error": f"An error occurred: {str(e)}"}, 500

    def _handle_ai_assisted_update(self, event, conversational_input, user_id):
        """Handle AI-assisted event updates from natural language"""
        try:
            # Use AI to process the update request
            update_result = comprehensive_event_assistant.process_event_update_request(
                event_id=event.id,
                update_request=conversational_input,
                user_id=user_id
            )
            
            if 'error' in update_result:
                return {"error": update_result['error']}, 400
            
            # Apply the proposed updates if confirmed or auto-confirmed
            updates_proposed = update_result.get('updates_proposed', {})
            requires_confirmation = update_result.get('confirmation_required', True)
            
            if requires_confirmation:
                return {
                    "message": "AI update proposal ready",
                    "updates_proposed": updates_proposed,
                    "summary": update_result.get('summary'),
                    "requires_confirmation": True,
                    "current_event_state": event.as_dict()
                }, 200
            else:
                # Auto-apply the updates
                return self._apply_ai_updates(event, updates_proposed, user_id)
                
        except Exception as e:
            logger.error(f"AI-assisted update failed: {e}")
            return {
                "error": "AI update service unavailable",
                "message": "Please update manually"
            }, 503

    def _handle_ai_optimized_update(self, event, data, files):
        """Handle update with AI optimization suggestions"""
        try:
            # Get current event state for AI analysis
            current_state = event.as_dict()
            
            # Use AI to suggest optimizations
            optimization_suggestions = comprehensive_event_assistant._generate_comprehensive_suggestions(
                # Convert event to draft-like structure for analysis
                self._event_to_draft_like(event),
                {"basic_info": data}
            )
            
            # Apply manual updates first
            updated_event = self._apply_manual_updates(event, data, files)
            
            return {
                "message": "Event updated successfully with AI optimization suggestions",
                "event": updated_event.as_dict(),
                "optimization_suggestions": optimization_suggestions,
                "ai_optimized": True
            }, 200
            
        except Exception as e:
            logger.error(f"AI-optimized update failed: {e}")
            # Fall back to manual update
            return self._handle_manual_update(event, data, files)

    def _handle_manual_update(self, event, data, files):
        """Handle traditional manual update"""
        # Parse and update fields
        if "date" in data:
            try:
                event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
                if event_date < datetime.utcnow().date():
                    return {"error": "Event date cannot be in the past"}, 400
                event.date = event_date
            except ValueError:
                return {"error": "Invalid date format. Use YYYY-MM-DD"}, 400

        if "start_time" in data:
            try:
                event.start_time = datetime.strptime(data["start_time"], "%H:%M").time()
            except ValueError:
                return {"error": "Invalid start_time format. Use HH:MM"}, 400

        if "end_time" in data:
            try:
                event.end_time = datetime.strptime(data["end_time"], "%H:%M").time()
            except ValueError:
                return {"error": "Invalid end_time format. Use HH:MM"}, 400
        else:
            event.end_time = None

        # Validate time logic
        if event.start_time and event.end_time:
            start_datetime = datetime.combine(event.date, event.start_time)
            end_datetime = datetime.combine(event.date, event.end_time)

            if end_datetime <= start_datetime:
                end_datetime += timedelta(days=1)
            if start_datetime >= end_datetime:
                return {"error": "Start time must be before end time"}, 400

        # Update basic fields
        event.name = data.get("name", event.name)
        event.description = data.get("description", event.description)
        event.city = data.get("city", event.city)
        event.location = data.get("location", event.location)
        event.category_id = data.get("category_id", event.category_id)

        # Handle amenities update
        if "amenities" in data:
            try:
                amenities = self._parse_amenities(data["amenities"])
                event.amenities = event.validate_amenities(amenities)
            except (json.JSONDecodeError, ValueError) as e:
                return {"error": f"Invalid amenities format: {str(e)}"}, 400

        # Handle file if present
        if "file" in files:
            file = files["file"]
            if file and allowed_file(file.filename):
                upload_result = cloudinary.uploader.upload(
                    file,
                    folder="event_images",
                    resource_type="auto"
                )
                event.image = upload_result.get("secure_url")

        db.session.commit()
        return {"message": "Update successful", "event": event.as_dict()}, 200

    def _apply_ai_updates(self, event, updates, user_id):
        """Apply AI-proposed updates to an event"""
        try:
            for field, value in updates.items():
                if field == 'date':
                    event.date = datetime.strptime(value, "%Y-%m-%d").date()
                elif field == 'start_time':
                    event.start_time = datetime.strptime(value, "%H:%M").time()
                elif field == 'end_time':
                    event.end_time = datetime.strptime(value, "%H:%M").time()
                elif field == 'name':
                    event.name = value
                elif field == 'description':
                    event.description = value
                elif field == 'city':
                    event.city = value
                elif field == 'location':
                    event.location = value
                elif field == 'category_id':
                    event.category_id = value
                elif field == 'amenities':
                    event.amenities = self._parse_amenities(value)

            # Validate the updated event
            event.validate_datetime()
            db.session.commit()

            # Log the AI-assisted update
            from model import AIManager, AIIntentType
            AIManager.log_action(
                user_id=user_id,
                action_type=AIIntentType.UPDATE_EVENT,
                action_description=f"AI-assisted update applied to event: {event.name}",
                target_table='event',
                target_id=event.id,
                request_data=updates
            )

            return {
                "message": "Event updated successfully with AI assistance",
                "event": event.as_dict(),
                "ai_assisted": True
            }, 200

        except Exception as e:
            db.session.rollback()
            return {"error": f"Failed to apply AI updates: {str(e)}"}, 500

    # ===== HELPER METHODS =====

    def _handle_file_upload(self, file):
        """Handle file upload to cloudinary"""
        if file and file.filename != '':
            if not allowed_file(file.filename):
                raise ValueError("Invalid file type. Allowed types: PNG, JPG, JPEG, GIF, WEBP")

            try:
                upload_result = cloudinary.uploader.upload(
                    file,
                    folder="event_images",
                    resource_type="auto"
                )
                return upload_result.get('secure_url')
            except Exception as e:
                logger.error(f"Error uploading event image: {str(e)}")
                raise ValueError("Failed to upload event image")
        return None

    def _parse_amenities(self, amenities_data):
        """Parse amenities from various formats"""
        if not amenities_data:
            return []
            
        try:
            if isinstance(amenities_data, str):
                if amenities_data.startswith('[') and amenities_data.endswith(']'):
                    # JSON format
                    return json.loads(amenities_data)
                else:
                    # Comma-separated format
                    return [amenity.strip() for amenity in amenities_data.split(',') if amenity.strip()]
            elif isinstance(amenities_data, list):
                return amenities_data
            else:
                return []
        except (json.JSONDecodeError, AttributeError):
            raise ValueError("Invalid amenities format. Use JSON array or comma-separated values")

    def _get_organizer_previous_events(self, organizer_id):
        """Get organizer's previous events for context"""
        events = Event.query.filter_by(organizer_id=organizer_id).all()
        return [{
            'name': event.name,
            'category': event.event_category.name if event.event_category else None,
            'date': event.date.isoformat(),
            'attendance': event.likes.count()
        } for event in events]

    def _get_organizer_preferences(self, organizer_id):
        """Get organizer preferences for context"""
        organizer = Organizer.query.get(organizer_id)
        if not organizer:
            return {}
            
        return {
            'company_name': organizer.company_name,
            'preferred_categories': [cat.name for cat in organizer.events[:3] if cat.event_category],
            'typical_audience_size': len(organizer.events) > 0  # Simplified
        }

    def _event_to_draft_like(self, event):
        """Convert event to draft-like structure for AI analysis"""
        class DraftLike:
            def __init__(self, event):
                self.suggested_name = event.name
                self.suggested_description = event.description
                self.suggested_date = event.date
                self.suggested_start_time = event.start_time
                self.suggested_end_time = event.end_time
                self.suggested_city = event.city
                self.suggested_location = event.location
                self.suggested_category_id = event.category_id
                self.suggested_amenities = event.amenities or []
                self.organizer_id = event.organizer_id
                
            def as_dict(self):
                return {
                    'name': self.suggested_name,
                    'description': self.suggested_description,
                    'date': self.suggested_date.isoformat() if self.suggested_date else None,
                    'start_time': self.suggested_start_time.isoformat() if self.suggested_start_time else None,
                    'city': self.suggested_city,
                    'location': self.suggested_location,
                    'category_id': self.suggested_category_id,
                    'amenities': self.suggested_amenities
                }
        
        return DraftLike(event)

    def _apply_manual_updates(self, event, data, files):
        """Apply manual updates to event and return updated event"""
        # This is a simplified version of the manual update logic
        # In practice, you'd want to reuse the existing manual update logic
        if 'name' in data:
            event.name = data['name']
        if 'description' in data:
            event.description = data['description']
        if 'city' in data:
            event.city = data['city']
        if 'location' in data:
            event.location = data['location']
        if 'category_id' in data:
            event.category_id = data['category_id']
            
        # Handle file upload
        if 'file' in files:
            image_url = self._handle_file_upload(files['file'])
            if image_url:
                event.image = image_url
                
        db.session.commit()
        return event

# ... (rest of your existing resource classes remain unchanged - EventsByLocationResource, CitiesResource, StatsResource, EventLikeResource, OrganizerEventsResource)


class EventsByLocationResource(Resource):
    """Resource for getting events by city and location with amenities."""

    def get(self, city):
        """Get events by city with optional location and amenity filters."""
        try:
            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = min(request.args.get('per_page', 20, type=int), 50)
            location = request.args.get('location', type=str)  # Specific venue/location filter
            amenity = request.args.get('amenity', type=str)  # Specific amenity filter
            time_filter = request.args.get('time_filter', 'upcoming', type=str)
            sort_by = request.args.get('sort_by', 'date', type=str)
            sort_order = request.args.get('sort_order', 'asc', type=str)
            include_collaborators = request.args.get('include_collaborators', 'false').lower() == 'true'

            # Base query filtered by city
            query = Event.query.filter(Event.city.ilike(f'%{city}%'))

            # Apply time filter
            current_date = datetime.now().date()
            if time_filter == 'upcoming':
                query = query.filter(Event.date >= current_date)
            elif time_filter == 'today':
                query = query.filter(Event.date == current_date)
            elif time_filter == 'past':
                query = query.filter(Event.date < current_date)

            # Apply location filter if provided
            if location:
                query = query.filter(Event.location.ilike(f'%{location}%'))

            # Apply amenity filter if provided
            if amenity:
                query = query.filter(
                    func.json_contains(Event.amenities, f'["{amenity}"]')
                )

            # Apply sorting
            if sort_by == 'name':
                if sort_order.lower() == 'desc':
                    query = query.order_by(Event.name.desc())
                else:
                    query = query.order_by(Event.name.asc())
            else:  # Default to date
                if sort_order.lower() == 'desc':
                    query = query.order_by(Event.date.desc())
                else:
                    query = query.order_by(Event.date.asc())

            # Paginate results
            events = query.paginate(page=page, per_page=per_page, error_out=False)

            # Get unique locations and amenities for this city
            city_events = Event.query.filter(Event.city.ilike(f'%{city}%')).all()
            locations = list(set([event.location for event in city_events if event.location]))
            all_amenities = set()
            for event in city_events:
                if event.amenities:
                    all_amenities.update(event.amenities)

            # Format events data
            events_data = []
            for event in events.items:
                if include_collaborators:
                    event_dict = event.as_dict_with_collaborators()
                else:
                    event_dict = {
                        'id': event.id,
                        'name': event.name,
                        'description': event.description,
                        'date': event.date.isoformat(),
                        'start_time': event.start_time.isoformat(),
                        'end_time': event.end_time.isoformat() if event.end_time else None,
                        'city': event.city,
                        'location': event.location,
                        'amenities': event.amenities or [],
                        'image': event.image,
                        'category': event.event_category.name if event.event_category else None,
                        'featured': event.featured,
                        'organizer': {
                            'id': event.organizer.id,
                            'company_name': event.organizer.company_name,
                            'company_logo': event.organizer.company_logo if hasattr(event.organizer, 'company_logo') else None,
                            'company_description': event.organizer.company_description
                        },
                        'likes_count': event.likes.count(),
                    }
                events_data.append(event_dict)

            return {
                'city': city,
                'events': events_data,
                'pagination': {
                    'total': events.total,
                    'pages': events.pages,
                    'current_page': events.page,
                    'per_page': events.per_page,
                    'has_next': events.has_next,
                    'has_prev': events.has_prev
                },
                'available_filters': {
                    'locations': sorted(locations),
                    'amenities': sorted(list(all_amenities)),
                    'time_filters': ['upcoming', 'today', 'past', 'all']
                },
                'filters_applied': {
                    'city': city,
                    'location': location,
                    'amenity': amenity,
                    'time_filter': time_filter
                }
            }, 200

        except Exception as e:
            logger.error(f"Error fetching events for city {city}: {str(e)}")
            return {"message": "Error fetching events by location"}, 500

class CitiesResource(Resource):
    """Resource for getting available cities and their event counts."""

    def get(self):
        """Get all cities with event counts."""
        try:
            # Get cities with event counts
            cities_query = db.session.query(
                Event.city,
                func.count(Event.id).label('event_count')
            ).filter(
                Event.city.isnot(None),
                Event.date >= datetime.now().date()  # Only upcoming events
            ).group_by(Event.city).all()

            cities = []
            for city, count in cities_query:
                if city:  # Ensure city is not None or empty
                    # Get sample amenities for this city (top 5 most common)
                    city_amenities_query = db.session.query(Event.amenities).filter(
                        Event.city.ilike(f'%{city}%'),
                        Event.amenities.isnot(None)
                    ).all()
                    
                    amenities_count = {}
                    for amenity_list in city_amenities_query:
                        if amenity_list[0]:
                            for amenity in amenity_list[0]:
                                amenities_count[amenity] = amenities_count.get(amenity, 0) + 1
                    
                    top_amenities = sorted(amenities_count.items(), key=lambda x: x[1], reverse=True)[:5]
                    
                    cities.append({
                        'city': city,
                        'event_count': count,
                        'top_amenities': [amenity for amenity, _ in top_amenities]
                    })

            # Sort by event count descending
            cities.sort(key=lambda x: x['event_count'], reverse=True)

            return {
                'cities': cities,
                'total_cities': len(cities)
            }, 200

        except Exception as e:
            logger.error(f"Error fetching cities: {str(e)}")
            return {"message": "Error fetching cities"}, 500

class StatsResource(Resource):
    """Resource for getting platform statistics."""

    def get(self):
        """Get platform statistics including venues, events, cities, and featured venues."""
        try:
            current_date = datetime.now().date()
            
            # Count unique venues (locations) - treating each unique location as a venue
            total_venues_query = db.session.query(
                func.count(distinct(Event.location))
            ).filter(Event.location.isnot(None)).scalar()

            # Count total events (all events regardless of date)
            total_events = Event.query.count()

            # Count active cities (cities with upcoming events)
            active_cities_query = db.session.query(
                func.count(distinct(Event.city))
            ).filter(
                Event.city.isnot(None),
                Event.date >= current_date
            ).scalar()

            # Count featured venues (unique locations that have featured events)
            featured_venues_query = db.session.query(
                func.count(distinct(Event.location))
            ).filter(
                Event.featured == True,
                Event.location.isnot(None)
            ).scalar()

            stats = {
                "total_venues": total_venues_query or 0,
                "total_events": total_events or 0,
                "active_cities": active_cities_query or 0,
                "featured_venues": featured_venues_query or 0
            }

            logger.info(f"Platform stats retrieved: {stats}")
            return stats, 200

        except (OperationalError, SQLAlchemyError) as e:
            logger.error(f"Database error while fetching stats: {str(e)}")
            return {"message": "Database connection error"}, 500
        except Exception as e:
            logger.error(f"Error fetching platform stats: {str(e)}")
            return {"message": "Error fetching platform statistics"}, 500

class EventLikeResource(Resource):
    """Resource for handling event likes."""

    @jwt_required()
    def post(self, event_id):
        """Like an event."""
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        event = Event.query.get(event_id)

        if not event:
            return {"message": "Event not found"}, 404

        if user in event.likes:
            return {"message": "You have already liked this event"}, 400

        event.likes.append(user)
        db.session.commit()
        return {"message": "Event liked successfully", "likes_count": event.likes.count()}, 200

    @jwt_required()
    def delete(self, event_id):
        """Unlike an event."""
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        event = Event.query.get(event_id)

        if not event:
            return {"message": "Event not found"}, 404

        if user not in event.likes:
            return {"message": "You have not liked this event"}, 400

        event.likes.remove(user)
        db.session.commit()
        return {"message": "Event unliked successfully", "likes_count": event.likes.count()}, 200

class OrganizerEventsResource(Resource):
    @jwt_required()
    def get(self):
        """Retrieve events created by the logged-in organizer."""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        include_collaborators = request.args.get('include_collaborators', 'false').lower() == 'true'

        if not user or user.role.value != UserRole.ORGANIZER.value:
            return {"message": "Only organizers can access their events"}, 403

        organizer = Organizer.query.filter_by(user_id=user.id).first()

        if organizer:
            events = Event.query.filter_by(organizer_id=organizer.id).all()
            logger.info(f"Fetched events for organizer_id {organizer.id}: {len(events)} events")
            
            if include_collaborators:
                event_list = [event.as_dict_with_collaborators() for event in events]
            else:
                event_list = [event.as_dict() for event in events]
            
            return event_list, 200
        else:
            logger.warning(f"User {current_user_id} has ORGANIZER role but no Organizer profile found.")
            return {"message": "Organizer profile not found for this user."}, 404

class EventDraftResource(Resource):
    """Resource for managing AI event drafts"""
    
    @jwt_required()
    def get(self, draft_id=None):
        """Get event drafts for organizer or specific draft"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can access drafts"}, 403
            
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
            
        if draft_id:
            # Get specific draft
            draft = AIEventDraft.query.get(draft_id)
            if not draft or draft.organizer_id != organizer.id:
                return {"message": "Draft not found"}, 404
                
            return {
                "draft": draft.as_dict(),
                "review": comprehensive_event_assistant.review_draft(draft_id),
                "completion_status": comprehensive_event_assistant._get_completion_status(draft)
            }, 200
        else:
            # Get all drafts for organizer
            status = request.args.get('status', None)
            drafts = comprehensive_event_assistant.get_organizer_drafts(organizer.id, status)
            return {"drafts": drafts}, 200
    
    @jwt_required()
    def post(self, draft_id):
        """Update a specific field in a draft"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can update drafts"}, 403
            
        data = request.get_json()
        field_name = data.get('field_name')
        value = data.get('value')
        regenerate = data.get('regenerate', False)
        
        if not field_name:
            return {"error": "field_name is required"}, 400
            
        result = comprehensive_event_assistant.update_draft_field(
            draft_id, field_name, value, regenerate
        )
        
        if result['success']:
            return result, 200
        else:
            return {"error": result.get('error', 'Update failed')}, 400
    
    @jwt_required()
    def delete(self, draft_id):
        """Delete a draft"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can delete drafts"}, 403
            
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
            
        result = comprehensive_event_assistant.delete_draft(draft_id, organizer.id)
        
        if result['success']:
            return {"message": result['message']}, 200
        else:
            return {"error": result.get('error', 'Deletion failed')}, 400

class EventPublishResource(Resource):
    """Resource for publishing event drafts"""
    
    @jwt_required()
    def post(self, draft_id):
        """Publish an event draft"""
        identity = get_jwt_identity()
        user = User.query.get(identity)
        
        if not user or user.role != UserRole.ORGANIZER:
            return {"message": "Only organizers can publish events"}, 403
            
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found"}, 404
            
        result = comprehensive_event_assistant.publish_draft(draft_id, organizer.id)
        
        if result['success']:
            return {
                "message": result['message'],
                "event": result['event'],
                "event_id": result['event_id'],
                "ai_assisted": result.get('ai_assisted', True)
            }, 201
        else:
            return {
                "error": result.get('error', 'Publication failed'),
                "missing_fields": result.get('missing_fields', [])
            }, 400

def register_event_resources(api):
    """Registers the EventResource routes with Flask-RESTful API."""
    
    # --- Event Routes ---
    api.add_resource(EventResource, "/events", "/events/<int:event_id>")
    api.add_resource(EventsByLocationResource, "/events/city/<string:city>")
    api.add_resource(CitiesResource, "/cities")
    api.add_resource(StatsResource, "/api/stats")
    api.add_resource(OrganizerEventsResource, "/api/organizer/events")
    api.add_resource(EventLikeResource, "/events/<int:event_id>/like", endpoint="like_event")
    api.add_resource(EventLikeResource, "/events/<int:event_id>/unlike", endpoint="unlike_event")
    
    # --- AI Event Assistant Routes ---
    api.add_resource(EventDraftResource, "/events/drafts", "/events/drafts/<int:draft_id>")
    api.add_resource(EventPublishResource, "/events/drafts/<int:draft_id>/publish")