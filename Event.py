import json
from flask import request, jsonify
from flask_restful import Resource
from datetime import datetime, timedelta
from model import db, Event, User, UserRole, Organizer, Category
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
import cloudinary.uploader
import logging
from sqlalchemy.exc import OperationalError, SQLAlchemyError

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
                
                return event.as_dict(), 200
            except (OperationalError, SQLAlchemyError) as e:
                logger.error(f"Database error: {str(e)}")
                return {"message": "Database connection error"}, 500

        # Get query parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 7, type=int)
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
        location_filter = request.args.get('location', type=str)  # Filter by location
        
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
            
            # General search in event name, description, and location
            if search_query:
                search_pattern = f'%{search_query}%'
                query = query.filter(
                    db.or_(
                        Event.name.ilike(search_pattern),
                        Event.description.ilike(search_pattern),
                        Event.location.ilike(search_pattern)
                    )
                )

            # Featured events filter
            if featured_only:
                query = query.filter(Event.featured == True)
            
            # Location filter
            if location_filter:
                query = query.filter(Event.location.ilike(f'%{location_filter}%'))

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
                    'filters_applied': self._get_applied_filters_summary(
                        category_id, category_name, organizer_company, 
                        start_date, end_date, search_query, basic_category, 
                        time_filter, is_dashboard, featured_only, location_filter
                    )
                }

            return {
                'events': [{
                    'id': event.id,
                    'name': event.name,
                    'description': event.description,
                    'date': event.date.isoformat(),
                    'start_time': event.start_time.isoformat(),
                    'end_time': event.end_time.isoformat() if event.end_time else None,
                    'location': event.location,
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
                } for event in events.items],
                'total': events.total,
                'pages': events.pages,
                'current_page': events.page,
                'filters_applied': self._get_applied_filters_summary(
                    category_id, category_name, organizer_company, 
                    start_date, end_date, search_query, basic_category,
                    time_filter, is_dashboard, featured_only, location_filter
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
                                   time_filter, is_dashboard, featured_only, location_filter):
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
            
        return filters

    def _get_available_filters(self, user, is_dashboard):
        """Return available filter options based on user role and view type."""
        try:
            filters = {
                'categories': [],
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

            # Validate required fields
            required_fields = ["name", "description", "date", "start_time", "location"]
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
                location=data["location"],
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

            event.name = data.get("name", event.name)
            event.description = data.get("description", event.description)
            event.location = data.get("location", event.location)
            event.category_id = data.get("category_id", event.category_id)

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

        if not user or user.role.value != UserRole.ORGANIZER.value:
            return {"message": "Only organizers can access their events"}, 403

        organizer = Organizer.query.filter_by(user_id=user.id).first()

        if organizer:
            events = Event.query.filter_by(organizer_id=organizer.id).all()
            logger.info(f"Fetched events for organizer_id {organizer.id}: {len(events)} events")
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
    api.add_resource(EventResource, "/events", "/events/<int:event_id>")
    api.add_resource(OrganizerEventsResource, "/api/organizer/events")
    api.add_resource(CategoryResource, "/categories")
    api.add_resource(EventLikeResource, "/events/<int:event_id>/like", endpoint="like_event")
    api.add_resource(EventLikeResource, "/events/<int:event_id>/unlike", endpoint="unlike_event")
