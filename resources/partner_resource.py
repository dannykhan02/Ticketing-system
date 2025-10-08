import json
import logging
from datetime import datetime
from flask import request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
import cloudinary.uploader
from sqlalchemy.exc import SQLAlchemyError

from model import (
    db, Event, User, UserRole, Organizer, Partner, 
    EventCollaboration, CollaborationType
)

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

            # If event_id exists → handle collaboration (JSON body expected)
            if event_id:
                data = request.get_json()
                if not data:
                    return {"message": "No data provided"}, 400
                return self._add_event_collaboration(organizer, event_id, data)

            # Otherwise → handle partner creation (form-data + file)
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
        - PUT /partners/<id> -> Update partner (form-data + file upload)
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
                # collaboration updates still use JSON body
                data = request.get_json()
                if not data:
                    return {"message": "No data provided"}, 400
                return self._update_collaboration(organizer, event_id, collaboration_id, data)

            elif partner_id:
                # partner updates now use form-data + file (like POST)
                return self._update_partner(organizer, partner_id, request.form, request.files)

            else:
                return {"message": "Invalid endpoint"}, 400

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in PartnerManagementResource PUT: {str(e)}")
            return {"message": "Error processing request"}, 500

    def _update_partner(self, organizer, partner_id, data, files):
        """Update partner details (with optional logo upload)."""
        partner = Partner.query.filter_by(id=partner_id, organizer_id=organizer.id).first()
        if not partner:
            return {"message": "Partner not found"}, 404

        updatable_fields = [
            "company_name", "company_description", "website_url",
            "contact_email", "contact_person"
        ]

        # Handle logo file upload (Cloudinary)
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
                return {"message": "Partner with this company name already exists"}, 409

        # Update text fields
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
        """Update collaboration details."""
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
        """Deactivate a partner and all their collaborations."""
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
        """Remove (deactivate) a collaboration."""
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

    def _get_partners_overview(self):
        """Get overview of all partners with pagination + sorting."""
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 12, type=int), 50)
        sort_by = request.args.get('sort_by', 'id')
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


def register_partner_resources(api):
    """Register all partner-related resources with Flask-RESTful API."""
    
    # --- Partner Management Routes (Organizer) ---
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