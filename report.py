from flask import jsonify, request
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, TicketType, Transaction, Scan, Event, User, Report
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import SQLAlchemyError
import logging
from pdf_utils import generate_graph_image, generate_pdf_with_graph
from email_utils import send_email_with_attachment
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_event_report(event_id):
    """Generates a comprehensive report for a specific event with data structured for graphs."""
    report = {}

    event = Event.query.get(event_id)
    if not event:
        return {"message": "Event not found"}, 404

    report['event_name'] = event.name
    report['event_date'] = event.date.strftime('%Y-%m-%d')  # Assuming event.date is a datetime object
    report['event_location'] = event.location

    # 1. Ticket Sales Quantity
    total_tickets_sold = Ticket.query.filter_by(event_id=event_id).count()
    report['total_tickets_sold'] = total_tickets_sold

    tickets_by_type_query = db.session.query(TicketType.type_name, db.func.count(Ticket.id)).\
        join(Ticket, Ticket.ticket_type_id == TicketType.id).\
        filter(Ticket.event_id == event_id).\
        group_by(TicketType.type_name).all()

    report['tickets_sold_by_type'] = {type_name: count for type_name, count in tickets_by_type_query}
    report['tickets_sold_by_type_for_graph'] = {
        'labels': [type_name for type_name, count in tickets_by_type_query],
        'data': [count for type_name, count in tickets_by_type_query]
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

    report['attendees_by_ticket_type'] = {type_name: count for type_name, count in attendees_by_type_query}
    report['attendees_by_ticket_type_for_graph'] = {
        'labels': [type_name for type_name, count in attendees_by_type_query],
        'data': [count for type_name, count in attendees_by_type_query]
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
        type_name: float(revenue) if revenue else 0.0
        for type_name, revenue in revenue_by_type_query
    }
    report['revenue_by_ticket_type_for_graph'] = {
        'labels': [type_name for type_name, revenue in revenue_by_type_query],
        'data': [float(revenue) if revenue else 0.0 for type_name, revenue in revenue_by_type_query]
    }

    # 4. Payment Method Usage
    payment_method_usage_query = db.session.query(Transaction.payment_method, db.func.count(Transaction.id)).\
        join(Ticket, Ticket.transaction_id == Transaction.id).\
        filter(Ticket.event_id == event_id, Transaction.payment_status == 'COMPLETED').\
        group_by(Transaction.payment_method).all()

    report['payment_method_usage'] = {method: count for method, count in payment_method_usage_query}
    report['payment_method_usage_for_graph'] = {
        'labels': [method for method, count in payment_method_usage_query],
        'data': [count for method, count in payment_method_usage_query]
    }

    # Save/update reports for each ticket type
    for type_name, count in tickets_by_type_query:
        revenue = dict(revenue_by_type_query).get(type_name, 0.0)

        ticket_type = TicketType.query.filter_by(type_name=type_name).first()

        if not ticket_type:
            continue  # Skip if ticket type not found

        # Check if a report already exists
        report_entry = Report.query.filter_by(event_id=event_id, ticket_type_id=ticket_type.id).first()

        if report_entry:
            # Update existing
            report_entry.total_tickets_sold = count
            report_entry.total_revenue = float(revenue) if revenue else 0.0
        else:
            # Create new report
            new_report = Report(
                event_id=event_id,
                ticket_type_id=ticket_type.id,
                total_tickets_sold=count,
                total_revenue=float(revenue) if revenue else 0.0
            )
            db.session.add(new_report)

    db.session.commit()

    # Send report to organizer
    send_report_to_organizer_with_pdf(report)

    return report

def send_report_to_organizer_with_pdf(report):
    event = Event.query.get(report['event_id'])
    organizer = event.organizer.user
    if not organizer or not organizer.email:
        logger.warning(f"No organizer email for event: {event.name}")
        return

    # 1. Generate graph image
    graph_path = f"/tmp/event_report_{event.id}_graph.png"
    generate_graph_image(report, graph_path)

    # 2. Generate PDF file
    pdf_path = f"/tmp/event_report_{event.id}.pdf"
    generate_pdf_with_graph(report, pdf_path, graph_path)

    # 3. Create email body
    body = f"""
    Hello {organizer.full_name if hasattr(organizer, 'full_name') else organizer.email},

    Attached is the latest sales report for your event: {event.name}.

    Ticket Type: {report['ticket_type']['type_name']}
    Total Sold: {report['total_tickets_sold']}
    Revenue: ${report['total_revenue']:.2f}

    Regards,
    Your Event System Team
    """

    # 4. Send the email with the PDF
    try:
        send_email_with_attachment(
            recipient=organizer.email,
            subject=f"📊 Event Report - {event.name}",
            body=body,
            attachment_path=pdf_path
        )
        logger.info(f"Report sent with PDF to {organizer.email}")
    except Exception as e:
        logger.error(f"Failed to send PDF report email: {e}")
    finally:
        # Optional: Clean up PDF and graph files
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if os.path.exists(graph_path):
            os.remove(graph_path)

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

        if event.organizer_id != user.id:
            return {"message": "You are not authorized to view the report for this event"}, 403

        report_data = get_event_report(event_id)
        return report_data, 200

def register_report_resources(api):
    """Registers the ReportResource routes with Flask-RESTful API."""
    api.add_resource(ReportResource, "/event/<int:event_id>/report")
