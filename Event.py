import json
from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime, timedelta
from model import (db, Event, User, UserRole, Organizer, Category, Partner, 
                   EventCollaboration, CollaborationType, CollaborationManager)
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import cloudinary.uploader
import logging
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy import func, distinct

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
                        'created_at': event.created_at.isoformat() if hasattr(event, 'created_at') else None
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
        """Create a new event (Only organizers can create events)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user or user.role != UserRole.ORGANIZER:
                return {"message": "Only organizers can create events"}, 403

            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found"}, 404

            data = request.form
            files = request.files

            # Validate required fields (updated with city)
            required_fields = ["name", "description", "date", "start_time", "city", "location"]
            for field in required_fields:
                if field not in data:
                    return {"message": f"Missing field: {field}"}, 400

            # Handle file upload if provided
            image_url = None
            if 'file' in files:
                file = files['file']
                if file and file.filename != '':
                    if not allowed_file(file.filename):
                        return {"message": "Invalid file type. Allowed types: PNG, JPG, JPEG, GIF, WEBP"}, 400

                    try:
                        upload_result = cloudinary.uploader.upload(
                            file,
                            folder="event_images",
                            resource_type="auto"
                        )
                        image_url = upload_result.get('secure_url')
                    except Exception as e:
                        logger.error(f"Error uploading event image: {str(e)}")
                        return {"message": "Failed to upload event image"}, 500

            # Parse dates and times
            event_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            start_time = datetime.strptime(data["start_time"], "%H:%M").time()

            end_time = None
            if "end_time" in data and data["end_time"]:
                end_time = datetime.strptime(data["end_time"], "%H:%M").time()

            # Handle amenities
            amenities = []
            if "amenities" in data:
                try:
                    # Parse amenities from form data (could be JSON string or comma-separated)
                    amenities_data = data["amenities"]
                    if amenities_data.startswith('[') and amenities_data.endswith(']'):
                        # JSON format
                        amenities = json.loads(amenities_data)
                    else:
                        # Comma-separated format
                        amenities = [amenity.strip() for amenity in amenities_data.split(',') if amenity.strip()]
                except (json.JSONDecodeError, AttributeError):
                    return {"message": "Invalid amenities format. Use JSON array or comma-separated values"}, 400

            # Get category_id if provided
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
                category_id=category_id
            )

            # Validate time (handles overnight events and "Till Late")
            event.validate_datetime()

            db.session.add(event)
            db.session.commit()
            return {"message": "Event created successfully", "event": event.as_dict(), "id": event.id}, 201

        except ValueError as e:
            return {"error": str(e)}, 400
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}, 500

    @jwt_required()
    def put(self, event_id):
        """Update an existing event. Only the event's creator (organizer) can update it."""
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
        
        try:
            if "application/json" in content_type:
                data = request.get_json()
            elif "multipart/form-data" in content_type:
                data = request.form
            else:
                return {"error": "Unsupported Content-Type"}, 415

            if not data:
                return {"error": "No data provided"}, 400

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
                    amenities_data = data["amenities"]
                    if isinstance(amenities_data, str):
                        if amenities_data.startswith('[') and amenities_data.endswith(']'):
                            # JSON format
                            amenities = json.loads(amenities_data)
                        else:
                            # Comma-separated format
                            amenities = [amenity.strip() for amenity in amenities_data.split(',') if amenity.strip()]
                    elif isinstance(amenities_data, list):
                        amenities = amenities_data
                    else:
                        amenities = []
                    
                    event.amenities = event.validate_amenities(amenities)
                except (json.JSONDecodeError, ValueError) as e:
                    return {"error": f"Invalid amenities format: {str(e)}"}, 400

            # Handle file if present
            if "file" in request.files:
                file = request.files["file"]
                if file and allowed_file(file.filename):
                    upload_result = cloudinary.uploader.upload(
                        file,
                        folder="event_images",
                        resource_type="auto"
                    )
                    event.image = upload_result.get("secure_url")

            db.session.commit()
            return {"message": "Update successful", "event": event.as_dict()}, 200

        except Exception as e:
            db.session.rollback()
            return {"error": f"An error occurred: {str(e)}"}, 500


    @jwt_required()
    def delete(self, event_id):
        """Delete an event (Only the event creator can delete it)."""
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            event = Event.query.get(event_id)
            if not event:
                return {"error": "Event not found"}, 404

            organizer = Organizer.query.filter_by(user_id=user.id).first()

            is_organizer = organizer and event.organizer_id == organizer.id
            is_admin = user.role.value == UserRole.ADMIN.value

            if not (is_organizer or is_admin):
                return {"message": "Only the event creator (organizer) or Admin can delete this event"}, 403

            db.session.delete(event)
            db.session.commit()
            return {"message": "Event deleted successfully"}, 200
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting event id {event_id}: {str(e)}", exc_info=True)
            return {"error": "An unexpected error occurred during event deletion."}, 500


# Consolidated Partner Management Resource
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

            # ✅ Pagination & sorting params
            page = request.args.get('page', 1, type=int)
            per_page = min(request.args.get('per_page', 10, type=int), 50)
            sort_by = request.args.get('sort_by', 'company_name')  # company_name, created_at, total_collaborations, active_status
            sort_order = request.args.get('sort_order', 'asc').lower()  # asc, desc
            search = request.args.get('search')  # search by company name

            if event_id:
                return self._get_event_collaborations(organizer, event_id, page, per_page)
            elif partner_id:
                return self._get_partner_details(organizer, partner_id, page, per_page)
            else:
                return self._get_organizer_partners(organizer, page, per_page, sort_by, sort_order, search)

        except Exception as e:
            logger.error(f"Error in PartnerManagementResource GET: {str(e)}")
            return {"message": "Error processing request"}, 500

    def _get_event_collaborations(self, organizer, event_id, page, per_page):
        """Get collaborations for a specific event (Organizer only, paginated)."""
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404

        collaborations = EventCollaboration.query.filter_by(event_id=event.id).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return {
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
        }, 200

    def _get_partner_details(self, organizer, partner_id, page, per_page):
        """Get specific partner with their collaboration history (Organizer only, paginated)."""
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404

        collaborations = EventCollaboration.query.filter_by(partner_id=partner.id).paginate(
            page=page, per_page=per_page, error_out=False
        )

        partner_data = partner.as_dict()
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

    def _get_organizer_partners(self, organizer, page, per_page, sort_by, sort_order, search):
        """Get all partners for the current organizer (paginated, filter + sort)."""
        include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'

        query = Partner.query.filter_by(organizer_id=organizer.id)
        if not include_inactive:
            query = query.filter_by(is_active=True)

        if search:
            query = query.filter(Partner.company_name.ilike(f"%{search}%"))

        partners = query.paginate(page=page, per_page=per_page, error_out=False)

        partners_data = []
        for partner in partners.items:
            partner_dict = partner.as_dict()

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

            # Add count of collaborations for sorting
            partner_dict['total_collaborations'] = EventCollaboration.query.filter_by(
                partner_id=partner.id
            ).count()

            partners_data.append(partner_dict)

        # Sorting (applies within this page only)
        reverse = sort_order == 'desc'
        if sort_by == 'created_at':
            partners_data.sort(key=lambda x: x['created_at'], reverse=reverse)
        elif sort_by == 'total_collaborations':
            partners_data.sort(key=lambda x: x.get('total_collaborations', 0), reverse=reverse)
        elif sort_by == 'active_status':
            partners_data.sort(key=lambda x: x['is_active'], reverse=reverse)
        else:  # default company_name
            partners_data.sort(key=lambda x: x['company_name'].lower(), reverse=reverse)

        return {
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
        }, 200

    @jwt_required()
    def post(self, event_id=None):
        """
        Organizer-only endpoints:
        - POST /partners -> Create new partner (form-data + file upload)
        - POST /partners/events/<event_id> -> Add collaboration to event
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user or user.role != UserRole.ORGANIZER:
                return {"message": "Only organizers can create partners or collaborations"}, 403

            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer:
                return {"message": "Organizer profile not found"}, 404

            # ✅ If event_id exists → handle collaboration (JSON body expected)
            if event_id:
                data = request.get_json()
                if not data:
                    return {"message": "No data provided"}, 400
                return self._add_event_collaboration(organizer, event_id, data)

            # ✅ Otherwise → handle partner creation (form-data + file)
            return self._create_partner(organizer, request.form, request.files)

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in PartnerManagementResource POST: {str(e)}")
            return {"message": "Error processing request"}, 500


    def _create_partner(self, organizer, data, files):
        """Create a new partner company (with Cloudinary logo upload)."""

        if "company_name" not in data:
            return {"message": "Company name is required"}, 400

        existing = Partner.query.filter_by(
            organizer_id=organizer.id,
            company_name=data["company_name"],
            is_active=True
        ).first()
        if existing:
            return {"message": "Partner with this company name already exists"}, 409

        # ✅ Handle file upload (Cloudinary)
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

        # ✅ Create partner record
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
            return {
                "message": "Partner created successfully",
                "partner": partner.as_dict()
            }, 201
        except SQLAlchemyError as e:
            db.session.rollback()
            return {"message": f"Database error: {str(e)}"}, 500
        
    def _add_event_collaboration(self, organizer, event_id, data):
        """Add a collaboration to an event (Organizer only)."""
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404

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
            return {"message": "Collaboration already exists"}, 409

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
            "message": "Collaboration added successfully",
            "collaboration": collaboration.as_dict()
        }, 201

    @jwt_required()
    def put(self, partner_id=None, event_id=None, collaboration_id=None):
        """
        Organizer-only endpoints:
        - PUT /partners/<id> -> Update partner
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

            data = request.get_json()
            if not data:
                return {"message": "No data provided"}, 400

            if collaboration_id:
                return self._update_collaboration(organizer, event_id, collaboration_id, data)
            elif partner_id:
                return self._update_partner(organizer, partner_id, data)
            else:
                return {"message": "Invalid endpoint"}, 400

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in PartnerManagementResource PUT: {str(e)}")
            return {"message": "Error processing request"}, 500

    def _update_partner(self, organizer, partner_id, data):
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404

        updatable_fields = [
            'company_name', 'company_description', 'logo_url',
            'website_url', 'contact_email', 'contact_person'
        ]

        if 'company_name' in data and data['company_name'] != partner.company_name:
            existing = Partner.query.filter_by(
                organizer_id=organizer.id,
                company_name=data['company_name'],
                is_active=True
            ).filter(Partner.id != partner_id).first()
            if existing:
                return {"message": "Partner with this company name already exists"}, 409

        for field in updatable_fields:
            if field in data:
                setattr(partner, field, data[field])

        partner.updated_at = datetime.utcnow()
        db.session.commit()

        return {
            "message": "Partner updated successfully",
            "partner": partner.as_dict()
        }, 200

    def _update_collaboration(self, organizer, event_id, collaboration_id, data):
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404

        collaboration = EventCollaboration.query.filter_by(
            id=collaboration_id,
            event_id=event.id
        ).first()
        if not collaboration:
            return {"message": "Collaboration not found"}, 404

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
            "message": "Collaboration updated successfully",
            "collaboration": collaboration.as_dict()
        }, 200

    @jwt_required()
    def delete(self, partner_id=None, event_id=None, collaboration_id=None):
        """
        Organizer-only endpoints:
        - DELETE /partners/<id> -> Deactivate partner
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
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404

        partner.is_active = False
        active_collaborations = EventCollaboration.query.filter_by(
            partner_id=partner.id,
            is_active=True
        ).all()
        for c in active_collaborations:
            c.is_active = False

        db.session.commit()

        return {
            "message": "Partner deactivated successfully",
            "deactivated_collaborations": len(active_collaborations)
        }, 200

    def _remove_collaboration(self, organizer, event_id, collaboration_id):
        event = Event.query.filter_by(id=event_id, organizer_id=organizer.id).first()
        if not event:
            return {"message": "Event not found or access denied"}, 404

        collaboration = EventCollaboration.query.filter_by(
            id=collaboration_id,
            event_id=event.id
        ).first()
        if not collaboration:
            return {"message": "Collaboration not found"}, 404

        collaboration.is_active = False
        db.session.commit()

        return {"message": "Collaboration removed successfully"}, 200


class AdminPartnerOverviewResource(Resource):
    """Admin-only resource for comprehensive partner and collaboration oversight."""

    @jwt_required()
    def get(self, overview_type='partners', entity_id=None):
        """
        Get comprehensive admin overview:
        - GET /admin/partners -> All partners overview (paginated + sorting)
        - GET /admin/partners/<partner_id> -> Single partner detail
        - GET /admin/partners/collaborations -> All collaborations overview (paginated + sorting)
        - GET /admin/partners/collaborations/event/<event_id> -> All collabs for specific event
        - GET /admin/partners/recent -> Recent collaborations
        - GET /admin/partners/inactive -> Inactive partners + collaborations
        - GET /admin/partners/analytics -> Partnership analytics
        """
        try:
            identity = get_jwt_identity()
            user = User.query.get(identity)

            if not user or user.role != UserRole.ADMIN:
                return {"message": "Admin access required"}, 403

            if overview_type == 'partners':
                if entity_id:
                    return self._get_partner_detail(entity_id)
                return self._get_partners_overview()

            elif overview_type == 'collaborations':
                if entity_id:
                    return self._get_event_collaborations(entity_id)
                return self._get_collaborations_overview()

            elif overview_type == 'recent':
                return self._get_recent_collaborations()

            elif overview_type == 'inactive':
                return self._get_inactive_overview()

            elif overview_type == 'analytics':
                return self._get_partnership_analytics()

            else:
                return {"message": "Invalid overview type"}, 400

        except Exception as e:
            logger.error(f"Error in AdminPartnerOverviewResource: {str(e)}")
            return {"message": "Error fetching admin overview"}, 500

    # ───── PARTNERS OVERVIEW WITH PAGINATION + SORTING ───── #

    def _get_partners_overview(self):
        """Get overview of all partners with pagination + sorting."""

        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 12, type=int), 50)
        sort_by = request.args.get('sort_by', 'id')  # default sort
        order = request.args.get('order', 'asc')

        query = Partner.query

        # Apply sorting
        if sort_by == 'name':
            query = query.order_by(Partner.company_name.asc() if order == 'asc' else Partner.company_name.desc())
        elif sort_by == 'active':
            query = query.order_by(Partner.is_active.asc() if order == 'asc' else Partner.is_active.desc())
        else:
            query = query.order_by(Partner.id.asc() if order == 'asc' else Partner.id.desc())

        partners = query.paginate(page=page, per_page=per_page, error_out=False)

        return {
            "partners": [
                {
                    **partner.as_dict(),
                    "collaborations_count": EventCollaboration.query.filter_by(partner_id=partner.id).count(),
                    "active": partner.is_active
                } for partner in partners.items
            ],
            "total": partners.total,
            "pages": partners.pages,
            "current_page": partners.page,
            "per_page": partners.per_page,
            "has_next": partners.has_next,
            "has_prev": partners.has_prev,
            "sort_by": sort_by,
            "order": order
        }, 200

    # ───── SINGLE PARTNER DETAIL ───── #

    def _get_partner_detail(self, partner_id):
        """Get full detail for one partner, including all collaborations."""
        partner = Partner.query.get(partner_id)
        if not partner:
            return {"message": "Partner not found"}, 404

        collaborations = (
            EventCollaboration.query.filter_by(partner_id=partner.id).join(Event).all()
        )

        return {
            "partner": partner.as_dict(),
            "collaborations": [
                {
                    **collab.as_dict(),
                    "event_title": collab.event.name,
                    "event_date": collab.event.date.isoformat() if collab.event.date else None,
                    "organizer_name": collab.event.organizer.company_name if collab.event.organizer else None,
                } for collab in collaborations
            ],
            "collaborations_count": len(collaborations)
        }, 200

    # ───── COLLABORATIONS OVERVIEW WITH PAGINATION + SORTING ───── #

    def _get_collaborations_overview(self):
        """Get overview of all collaborations with pagination + sorting."""

        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 12, type=int), 50)
        sort_by = request.args.get('sort_by', 'id')
        order = request.args.get('order', 'asc')

        query = EventCollaboration.query.join(Event).join(Partner)

        # Apply sorting
        if sort_by == 'event_date':
            query = query.order_by(Event.date.asc() if order == 'asc' else Event.date.desc())
        elif sort_by == 'partner_name':
            query = query.order_by(Partner.company_name.asc() if order == 'asc' else Partner.company_name.desc())
        elif sort_by == 'created_at':
            query = query.order_by(EventCollaboration.created_at.asc() if order == 'asc' else EventCollaboration.created_at.desc())
        else:
            query = query.order_by(EventCollaboration.id.asc() if order == 'asc' else EventCollaboration.id.desc())

        collaborations = query.paginate(page=page, per_page=per_page, error_out=False)

        return {
            "collaborations": [
                {
                    **collab.as_dict(),
                    "event_title": collab.event.name,
                    "partner_name": collab.partner.company_name if collab.partner else None,
                    "event_date": collab.event.date.isoformat() if collab.event.date else None
                } for collab in collaborations.items
            ],
            "total": collaborations.total,
            "pages": collaborations.pages,
            "current_page": collaborations.page,
            "per_page": collaborations.per_page,
            "has_next": collaborations.has_next,
            "has_prev": collaborations.has_prev,
            "sort_by": sort_by,
            "order": order
        }, 200

    # ───── EVENT COLLABS, RECENT, INACTIVE, ANALYTICS ───── #

    def _get_event_collaborations(self, event_id):
        """Get all collaborations for a given event (with partner details)."""
        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404

        collaborations = EventCollaboration.query.filter_by(event_id=event.id).join(Partner).all()

        return {
            "event": event.as_dict(),
            "collaborations": [
                {
                    **collab.as_dict(),
                    "partner": collab.partner.as_dict() if collab.partner else None
                } for collab in collaborations
            ],
            "total": len(collaborations)
        }, 200

    def _get_recent_collaborations(self, limit=10):
        """Get most recent collaborations (not paginated)."""
        collaborations = (
            EventCollaboration.query.order_by(EventCollaboration.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "recent_collaborations": [
                {
                    **collab.as_dict(),
                    "event_title": collab.event.name,
                    "partner_name": collab.partner.company_name if collab.partner else None
                } for collab in collaborations
            ]
        }, 200

    def _get_inactive_overview(self):
        """List inactive partners + inactive collaborations."""
        inactive_partners = Partner.query.filter_by(is_active=False).all()
        inactive_collabs = EventCollaboration.query.filter_by(is_active=False).all()

        return {
            "inactive_partners": [p.as_dict() for p in inactive_partners],
            "inactive_collaborations": [c.as_dict() for c in inactive_collabs],
            "totals": {
                "inactive_partners": len(inactive_partners),
                "inactive_collaborations": len(inactive_collabs)
            }
        }, 200

    def _get_partnership_analytics(self):
        """Generate basic analytics about partners and collaborations."""
        total_partners = Partner.query.count()
        total_collaborations = EventCollaboration.query.count()
        active_partners = Partner.query.filter_by(is_active=True).count()
        inactive_partners = Partner.query.filter_by(is_active=False).count()

        return {
            "analytics": {
                "total_partners": total_partners,
                "active_partners": active_partners,
                "inactive_partners": inactive_partners,
                "total_collaborations": total_collaborations,
                "avg_collaborations_per_partner": (
                    total_collaborations / total_partners if total_partners else 0
                )
            }
        }, 200



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
            per_page = min(request.args.get('per_page', 12, type=int), 50)  # Cap at 50 for performance

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

class CategoryResource(Resource):
    def get(self):
        """Get all categories"""
        categories = Category.query.all()
        return {
            'categories': [category.as_dict() for category in categories]
        }, 200

    @jwt_required()
    def post(self):
        """Create a new category (Admin only)"""
        current_user = User.query.get(get_jwt_identity())
        if not current_user or current_user.role != UserRole.ADMIN:
            return {"message": "Only admins can create categories"}, 403

        data = request.get_json()
        if not data or 'name' not in data:
            return {"message": "Category name is required"}, 400

        try:
            category = Category(
                name=data['name'],
                description=data.get('description')
            )
            db.session.add(category)
            db.session.commit()
            return category.as_dict(), 201
        except Exception as e:
            db.session.rollback()
            return {"message": str(e)}, 400

def register_event_resources(api):
    """Registers the EventResource routes with Flask-RESTful API."""
    
    # --- Event Routes ---
    api.add_resource(EventResource, "/events", "/events/<int:event_id>")
    api.add_resource(EventsByLocationResource, "/events/city/<string:city>")
    api.add_resource(CitiesResource, "/cities")
    api.add_resource(StatsResource, "/api/stats")
    api.add_resource(OrganizerEventsResource, "/api/organizer/events")
    api.add_resource(CategoryResource, "/categories")
    api.add_resource(EventLikeResource, "/events/<int:event_id>/like", endpoint="like_event")
    api.add_resource(EventLikeResource, "/events/<int:event_id>/unlike", endpoint="unlike_event")

    # --- Partner Management Routes ---
    api.add_resource(
        PartnerManagementResource, 
        '/api/partners',                                    # GET (list), POST (create)
        '/api/partners/<int:partner_id>',                  # GET (details), PUT (update), DELETE (deactivate)
        '/api/partners/events/<int:event_id>',             # GET (event collaborations), POST (add collaboration)
        '/api/partners/events/<int:event_id>/collaborations/<int:collaboration_id>',  # PUT (update), DELETE (remove)
    )

    # --- Admin Partner Overview Routes ---
    api.add_resource(
        AdminPartnerOverviewResource,
        '/api/admin/partners',                               # GET partners overview
        '/api/admin/partners/<int:entity_id>',               # GET single partner profile
        '/api/admin/partners/collaborations',                # GET all collaborations overview
        '/api/admin/partners/collaborations/event/<int:entity_id>',  # GET collaborations for specific event
        '/api/admin/partners/recent',                        # GET recent collaborations
        '/api/admin/partners/inactive',                      # GET inactive partners + collaborations
        '/api/admin/partners/analytics'                      # GET partnership analytics
    )

    # --- Public Collaborations Routes ---
    api.add_resource(
        PublicEventCollaborationsResource,
        '/api/public/collaborations'   # GET active collaborations across events
    )
