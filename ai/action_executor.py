from model import (db, Event, TicketType, AIActionLog, AIActionStatus, AIIntentType,
                   Organizer, User, Partner, EventCollaboration, CollaborationType,
                   TicketTypeEnum, Category)
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ActionExecutor:
    """Executes AI-triggered actions after confirmation"""
    
    def execute(self, action: AIActionLog) -> dict:
        """Execute a confirmed action"""
        try:
            if action.action_status != AIActionStatus.PENDING:
                return {
                    "success": False,
                    "error": "Action has already been processed"
                }
            
            # Mark as in progress
            action.action_status = AIActionStatus.IN_PROGRESS
            db.session.commit()
            
            # Route to appropriate executor
            executors = {
                AIIntentType.CREATE_EVENT: self._execute_create_event,
                AIIntentType.UPDATE_EVENT: self._execute_update_event,
                AIIntentType.DELETE_EVENT: self._execute_delete_event,
                AIIntentType.CREATE_TICKETS: self._execute_create_tickets,
                AIIntentType.UPDATE_TICKETS: self._execute_update_tickets,
                AIIntentType.MANAGE_PARTNERS: self._execute_manage_partners,
            }
            
            executor = executors.get(action.action_type)
            if not executor:
                action.action_status = AIActionStatus.FAILED
                action.error_message = f"No executor for action type: {action.action_type.value}"
                db.session.commit()
                return {"success": False, "error": action.error_message}
            
            # Execute
            result = executor(action)
            
            if result.get('success'):
                action.action_status = AIActionStatus.COMPLETED
                action.result_message = result.get('message', 'Action completed successfully')
                action.executed_data = result.get('data')
                action.executed_at = datetime.utcnow()
            else:
                action.action_status = AIActionStatus.FAILED
                action.error_message = result.get('error', 'Execution failed')
            
            db.session.commit()
            return result
            
        except Exception as e:
            logger.error(f"Error executing action {action.id}: {e}")
            action.action_status = AIActionStatus.FAILED
            action.error_message = str(e)
            db.session.commit()
            return {"success": False, "error": str(e)}
    
    def _execute_create_event(self, action: AIActionLog) -> dict:
        """Create an event from AI action"""
        try:
            params = action.request_data
            user = User.query.get(action.user_id)
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            
            if not organizer:
                return {"success": False, "error": "Organizer profile not found"}
            
            # Validate required fields
            required = ['name', 'description', 'date', 'start_time', 'city', 'location']
            missing = [f for f in required if not params.get(f)]
            if missing:
                return {"success": False, "error": f"Missing required fields: {', '.join(missing)}"}
            
            # Parse dates and times
            try:
                event_date = datetime.strptime(params['date'], '%Y-%m-%d').date()
                start_time = datetime.strptime(params['start_time'], '%H:%M').time()
                end_time = None
                if params.get('end_time'):
                    end_time = datetime.strptime(params['end_time'], '%H:%M').time()
            except ValueError as e:
                return {"success": False, "error": f"Invalid date/time format: {e}"}
            
            # Get category if specified
            category_id = params.get('category_id')
            if params.get('category_name') and not category_id:
                category = Category.query.filter_by(name=params['category_name']).first()
                if category:
                    category_id = category.id
            
            # Create event
            event = Event(
                name=params['name'],
                description=params.get('description', f"Event: {params['name']}"),
                date=event_date,
                start_time=start_time,
                end_time=end_time,
                city=params['city'],
                location=params['location'],
                amenities=params.get('amenities', []),
                image=params.get('image'),
                organizer_id=organizer.id,
                category_id=category_id
            )
            
            db.session.add(event)
            db.session.flush()  # Get event ID
            
            # Link action to event
            action.event_id = event.id
            action.target_table = 'event'
            action.target_id = event.id
            
            db.session.commit()
            
            return {
                "success": True,
                "message": f"Event '{event.name}' created successfully!",
                "data": {
                    "event_id": event.id,
                    "event": event.as_dict()
                }
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating event: {e}")
            return {"success": False, "error": str(e)}
    
    def _execute_update_event(self, action: AIActionLog) -> dict:
        """Update an event from AI action"""
        try:
            params = action.request_data
            event = Event.query.get(action.event_id)
            
            if not event:
                return {"success": False, "error": "Event not found"}
            
            # Verify ownership
            user = User.query.get(action.user_id)
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer or event.organizer_id != organizer.id:
                return {"success": False, "error": "Unauthorized to update this event"}
            
            # Update fields
            updated_fields = []
            if 'name' in params:
                event.name = params['name']
                updated_fields.append('name')
            if 'description' in params:
                event.description = params['description']
                updated_fields.append('description')
            if 'location' in params:
                event.location = params['location']
                updated_fields.append('location')
            if 'city' in params:
                event.city = params['city']
                updated_fields.append('city')
            if 'date' in params:
                event.date = datetime.strptime(params['date'], '%Y-%m-%d').date()
                updated_fields.append('date')
            
            db.session.commit()
            
            return {
                "success": True,
                "message": f"Event updated successfully. Changed: {', '.join(updated_fields)}",
                "data": {"event": event.as_dict()}
            }
            
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}
    
    def _execute_delete_event(self, action: AIActionLog) -> dict:
        """Delete an event"""
        try:
            event = Event.query.get(action.event_id)
            if not event:
                return {"success": False, "error": "Event not found"}
            
            user = User.query.get(action.user_id)
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            if not organizer or event.organizer_id != organizer.id:
                return {"success": False, "error": "Unauthorized"}
            
            event_name = event.name
            db.session.delete(event)
            db.session.commit()
            
            return {
                "success": True,
                "message": f"Event '{event_name}' deleted successfully"
            }
            
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}
    
    def _execute_create_tickets(self, action: AIActionLog) -> dict:
        """Create ticket types"""
        try:
            params = action.request_data
            event = Event.query.get(params.get('event_id'))
            
            if not event:
                return {"success": False, "error": "Event not found"}
            
            # Validate ticket type enum
            type_name = params.get('type_name', 'REGULAR').upper()
            try:
                ticket_type_enum = TicketTypeEnum[type_name]
            except KeyError:
                return {"success": False, "error": f"Invalid ticket type: {type_name}"}
            
            # Create ticket
            ticket_type = TicketType(
                event_id=event.id,
                type_name=ticket_type_enum,
                price=params.get('price', 1000),
                quantity=params.get('quantity', 100)
            )
            
            db.session.add(ticket_type)
            db.session.flush()
            
            action.ticket_type_id = ticket_type.id
            db.session.commit()
            
            return {
                "success": True,
                "message": f"Ticket type '{type_name}' created successfully",
                "data": {"ticket_type": ticket_type.as_dict()}
            }
            
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}
    
    def _execute_update_tickets(self, action: AIActionLog) -> dict:
        """Update ticket pricing/quantity"""
        try:
            params = action.request_data
            ticket_type = TicketType.query.get(action.ticket_type_id)
            
            if not ticket_type:
                return {"success": False, "error": "Ticket type not found"}
            
            updated = []
            if 'price' in params:
                ticket_type.price = params['price']
                updated.append(f"price to {params['price']}")
            if 'quantity' in params:
                ticket_type.quantity = params['quantity']
                updated.append(f"quantity to {params['quantity']}")
            
            db.session.commit()
            
            return {
                "success": True,
                "message": f"Ticket updated: {', '.join(updated)}",
                "data": {"ticket_type": ticket_type.as_dict()}
            }
            
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}
    
    def _execute_manage_partners(self, action: AIActionLog) -> dict:
        """Manage partners and collaborations"""
        try:
            params = action.request_data
            operation = params.get('operation', 'create')  # create, add_collaboration, remove
            
            if operation == 'create':
                return self._create_partner(action, params)
            elif operation == 'add_collaboration':
                return self._add_collaboration(action, params)
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _create_partner(self, action: AIActionLog, params: dict) -> dict:
        """Create a new partner"""
        try:
            user = User.query.get(action.user_id)
            organizer = Organizer.query.filter_by(user_id=user.id).first()
            
            if not organizer:
                return {"success": False, "error": "Organizer profile required"}
            
            partner = Partner(
                organizer_id=organizer.id,
                company_name=params['company_name'],
                company_description=params.get('company_description'),
                website_url=params.get('website_url'),
                contact_email=params.get('contact_email')
            )
            
            db.session.add(partner)
            db.session.flush()
            
            action.partner_id = partner.id
            db.session.commit()
            
            return {
                "success": True,
                "message": f"Partner '{partner.company_name}' created successfully",
                "data": {"partner": partner.as_dict()}
            }
            
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}
    
    def _add_collaboration(self, action: AIActionLog, params: dict) -> dict:
        """Add event collaboration"""
        try:
            collaboration = EventCollaboration(
                event_id=params['event_id'],
                partner_id=params['partner_id'],
                collaboration_type=CollaborationType(params.get('collaboration_type', 'PARTNER')),
                description=params.get('description')
            )
            
            db.session.add(collaboration)
            db.session.commit()
            
            return {
                "success": True,
                "message": "Collaboration added successfully",
                "data": {"collaboration": collaboration.as_dict()}
            }
            
        except Exception as e:
            db.session.rollback()
            return {"success": False, "error": str(e)}