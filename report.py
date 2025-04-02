from flask import jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, TicketType, Transaction, Scan, Event, User

def get_event_report(event_id):
    """Generates a comprehensive report for a specific event with data structured for graphs."""
    report = {}

    # 1. Ticket Sales Quantity
    total_tickets_sold = Ticket.query.filter_by(event_id=event_id).count()
    report['total_tickets_sold'] = total_tickets_sold

    tickets_by_type_query = db.session.query(TicketType.type_name, db.func.count(Ticket.id)).\
        join(Ticket, Ticket.ticket_type_id == TicketType.id).\
        filter(Ticket.event_id == event_id).\
        group_by(TicketType.type_name).all()

    report['tickets_sold_by_type'] = {type_name.value: count for type_name, count in tickets_by_type_query}
    report['tickets_sold_by_type_for_graph'] = {
        'labels': [item.value for item, count in tickets_by_type_query],
        'data': [count for item, count in tickets_by_type_query]
    }

    # 2. Number of Attendees (based on scans)
    number_of_attendees = Scan.query.join(Ticket, Scan.ticket_id == Ticket.id).\
        filter(Ticket.event_id == event_id).distinct(Scan.ticket_id).count()
    report['number_of_attendees'] = number_of_attendees

    attendees_by_type_query = db.session.query(TicketType.type_name, db.func.count(Scan.id)).\
        join(Ticket, Scan.ticket_id == Ticket.id).\
        join(TicketType, Ticket.ticket_type_id == TicketType.id).\
        filter(Ticket.event_id == event_id).\
        group_by(TicketType.type_name).all()

    report['attendees_by_ticket_type'] = {type_name.value: count for type_name, count in attendees_by_type_query}
    report['attendees_by_ticket_type_for_graph'] = {
        'labels': [item.value for item, count in attendees_by_type_query],
        'data': [count for item, count in attendees_by_type_query]
    }

    # 3. Revenue Generated
    total_revenue_query = db.session.query(db.func.sum(Transaction.amount_paid)).\
        join(Ticket, Ticket.transaction_id == Transaction.id).\
        filter(Ticket.event_id == event_id, Transaction.payment_status == 'COMPLETED').scalar()
    total_revenue = float(total_revenue_query) if total_revenue_query else 0.0
    report['total_revenue'] = total_revenue

    revenue_by_type_query = db.session.query(TicketType.type_name, db.func.sum(Transaction.amount_paid)).\
        join(Ticket, Ticket.ticket_type_id == TicketType.id).\
        join(Transaction, Ticket.transaction_id == Transaction.id).\
        filter(Ticket.event_id == event_id, Transaction.payment_status == 'COMPLETED').\
        group_by(TicketType.type_name).all()

    report['revenue_by_ticket_type'] = {
        type_name.value: float(revenue) if revenue else 0.0
        for type_name, revenue in revenue_by_type_query
    }
    report['revenue_by_ticket_type_for_graph'] = {
        'labels': [item.value for item, revenue in revenue_by_type_query],
        'data': [float(revenue) if revenue else 0.0 for item, revenue in revenue_by_type_query]
    }

    # 4. Payment Method Usage
    payment_method_usage_query = db.session.query(Transaction.payment_method, db.func.count(Transaction.id)).\
        join(Ticket, Ticket.transaction_id == Transaction.id).\
        filter(Ticket.event_id == event_id, Transaction.payment_status == 'COMPLETED').\
        group_by(Transaction.payment_method).all()

    report['payment_method_usage'] = {method.value: count for method, count in payment_method_usage_query}
    report['payment_method_usage_for_graph'] = {
        'labels': [method.value for method, count in payment_method_usage_query],
        'data': [count for method, count in payment_method_usage_query]
    }

    return report

class ReportResource(Resource):
    @jwt_required()
    def get(self, event_id):
        """Retrieve a report for a specific event (Only the event organizer can access)."""
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        event = Event.query.get(event_id)

        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can access event reports"}, 403

        if not event:
            return {"message": "Event not found"}, 404

        if event.user_id != user.id:
            return {"message": "You are not authorized to view the report for this event"}, 403

        report_data = get_event_report(event_id)
        return report_data, 200

def register_report_resources(api):
    """Registers the ReportResource routes with Flask-RESTful API."""
    api.add_resource(ReportResource, "/event/<int:event_id>/report")

