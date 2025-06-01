from flask import jsonify, request, Response, send_file
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, TicketType, Transaction, Scan, Event, User, Report, Organizer
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import SQLAlchemyError
import logging
from pdf_utils import generate_graph_image, generate_pdf_with_graph
from email_utils import send_email_with_attachment
import os
from datetime import datetime, time
import csv
from io import StringIO

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_date_param(date_str, param_name):
    """
    Parses a date string into a datetime object.
    Logs a warning if the format is invalid.
    """
    if date_str:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            logger.warning(f"Invalid {param_name} format: {date_str}. Expected YYYY-MM-DD.")
    return None

def get_event_report(event_id, save_to_history=True, start_date=None, end_date=None):
    """
    Generates a comprehensive report for a specific event with data structured for graphs,
    optionally filtered by a date range.
    """
    report = {}

    event = Event.query.get(event_id)
    if not event:
        return {"message": "Event not found"}, 404

    if not start_date or not end_date:
        return {"message": "Both start_date and end_date are required for report generation."}, 400

    if start_date > end_date:
        return {"message": "Start date cannot be after end date."}, 400

    report['event_id'] = event_id
    report['event_name'] = event.name
    report['event_date'] = event.date.strftime('%Y-%m-%d') if event.date else "N/A"
    report['event_location'] = event.location
    report['event_description'] = event.description
    report['filter_start_date'] = start_date.strftime('%Y-%m-%d')
    report['filter_end_date'] = end_date.strftime('%Y-%m-%d')

    adjusted_end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    ticket_base_query = Ticket.query.filter(Ticket.event_id == event_id)
    transaction_base_query = Transaction.query.join(Ticket, Ticket.transaction_id == Transaction.id)\
                                .filter(Ticket.event_id == event_id, Transaction.payment_status == 'COMPLETED')

    ticket_base_query = ticket_base_query.filter(Ticket.purchase_date >= start_date, Ticket.purchase_date <= adjusted_end_date)
    transaction_base_query = transaction_base_query.filter(Transaction.timestamp >= start_date, Transaction.timestamp <= adjusted_end_date)

    total_tickets_sold = ticket_base_query.count()
    report['total_tickets_sold'] = total_tickets_sold

    tickets_by_type_query = db.session.query(TicketType.type_name, db.func.count(Ticket.id)).\
        join(Ticket, Ticket.ticket_type_id == TicketType.id).\
        filter(Ticket.event_id == event_id,
               Ticket.purchase_date >= start_date,
               Ticket.purchase_date <= adjusted_end_date).\
        group_by(TicketType.type_name).all()

    report['tickets_sold_by_type'] = {str(type_name): count for type_name, count in tickets_by_type_query}
    report['tickets_sold_by_type_for_graph'] = {
        'labels': [str(type_name) for type_name, count in tickets_by_type_query],
        'data': [count for type_name, count in tickets_by_type_query]
    }

    number_of_attendees = Scan.query.join(Ticket, Scan.ticket_id == Ticket.id).\
        filter(Ticket.event_id == event_id,
               Scan.scanned_at >= start_date,
               Scan.scanned_at <= adjusted_end_date).\
        distinct(Scan.ticket_id).count()
    report['number_of_attendees'] = number_of_attendees

    attendees_by_type_query = db.session.query(TicketType.type_name, db.func.count(db.distinct(Scan.ticket_id))).\
        join(Ticket, Scan.ticket_id == Ticket.id).\
        join(TicketType, Ticket.ticket_type_id == TicketType.id).\
        filter(Ticket.event_id == event_id,
               Scan.scanned_at >= start_date,
               Scan.scanned_at <= adjusted_end_date).\
        group_by(TicketType.type_name).all()

    report['attendees_by_ticket_type'] = {str(type_name): count for type_name, count in attendees_by_type_query}
    report['attendees_by_ticket_type_for_graph'] = {
        'labels': [str(type_name) for type_name, count in attendees_by_type_query],
        'data': [count for type_name, count in attendees_by_type_query]
    }

    total_revenue_query = transaction_base_query.with_entities(db.func.sum(Transaction.amount_paid)).scalar()
    total_revenue = float(total_revenue_query) if total_revenue_query else 0.0
    report['total_revenue'] = total_revenue

    revenue_by_type_query = db.session.query(TicketType.type_name, db.func.sum(Transaction.amount_paid)).\
        join(Ticket, Ticket.ticket_type_id == TicketType.id).\
        join(Transaction, Ticket.transaction_id == Transaction.id).\
        filter(Ticket.event_id == event_id,
               Transaction.payment_status == 'COMPLETED',
               Transaction.timestamp >= start_date,
               Transaction.timestamp <= adjusted_end_date).\
        group_by(TicketType.type_name).all()

    report['revenue_by_ticket_type'] = {
        str(type_name): float(revenue) if revenue else 0.0
        for type_name, revenue in revenue_by_type_query
    }
    report['revenue_by_ticket_type_for_graph'] = {
        'labels': [str(type_name) for type_name, revenue in revenue_by_type_query],
        'data': [float(revenue) if revenue else 0.0 for type_name, revenue in revenue_by_type_query]
    }

    payment_method_usage_query = db.session.query(Transaction.payment_method, db.func.count(Transaction.id)).\
        join(Ticket, Ticket.transaction_id == Transaction.id).\
        filter(Ticket.event_id == event_id,
               Transaction.payment_status == 'COMPLETED',
               Transaction.timestamp >= start_date,
               Transaction.timestamp <= adjusted_end_date).\
        group_by(Transaction.payment_method).all()

    report['payment_method_usage'] = {str(method): count for method, count in payment_method_usage_query}
    report['payment_method_usage_for_graph'] = {
        'labels': [str(method) for method, count in payment_method_usage_query],
        'data': [count for method, count in payment_method_usage_query]
    }

    if save_to_history:
        try:
            new_event_report = Report(
                event_id=event_id,
                total_tickets_sold=report['total_tickets_sold'],
                total_revenue=report['total_revenue'],
                report_data=report
            )
            db.session.add(new_event_report)

            for type_name, count in tickets_by_type_query:
                revenue = dict(revenue_by_type_query).get(type_name, 0.0)
                ticket_type = TicketType.query.filter_by(type_name=type_name).first()

                if not ticket_type:
                    continue

                new_ticket_type_report = Report(
                    event_id=event_id,
                    ticket_type_id=ticket_type.id,
                    total_tickets_sold=count,
                    total_revenue=float(revenue) if revenue else 0.0,
                    report_data={
                        "ticket_type": str(type_name),
                        "total_tickets_sold": count,
                        "total_revenue": float(revenue) if revenue else 0.0,
                    }
                )
                db.session.add(new_ticket_type_report)

            db.session.commit()
            logger.info(f"Report history saved for event {event_id} with date range {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}.")
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error saving report history for event {event_id}: {e}")

    if save_to_history:
        send_report_to_organizer_with_pdf(report)

    return report

def send_report_to_organizer_with_pdf(report):
    """Sends the generated report as a PDF attachment to the event organizer."""
    event_id = report['event_id']
    event = Event.query.get(event_id)
    organizer_user = event.organizer.user
    if not organizer_user or not organizer_user.email:
        logger.warning(f"No organizer email found for event: {event.name} (Event ID: {event_id})")
        return

    graph_path = f"/tmp/event_report_{event.id}_graph_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
    generated_graph_path = generate_graph_image(report, graph_path)
    if not generated_graph_path:
        logger.error(f"Failed to generate graph image for event {event.id}. Email will be sent without graph.")
        graph_path = None

    pdf_path = f"/tmp/event_report_{event.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    generated_pdf_path = generate_pdf_with_graph(report, event_id, pdf_path, generated_graph_path if generated_graph_path else "")
    if not generated_pdf_path:
        logger.error(f"Failed to generate PDF for event {event.id}. Email will not be sent with attachment.")
        pdf_path = None

    event_date = event.date.strftime('%A, %B %d, %Y') if event.date else "Date not available"
    start_time = event.start_time.strftime('%H:%M:%S') if event.start_time else "Start time not available"
    end_time = event.end_time.strftime('%H:%M:%S') if event.end_time else "Till Late"

    email_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');

            body {{
                font-family: 'Poppins', Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 0;
                background-color: #f5f5f5;
            }}
            .email-container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }}
            .email-header {{
                background: linear-gradient(135deg, #6a3093 0%, #4a154b 100%);
                color: white;
                padding: 25px 15px;
                text-align: center;
            }}
            .email-header h1 {{
                margin: 0;
                font-size: 24px;
                letter-spacing: 0.5px;
            }}
            .email-body {{
                padding: 25px 20px;
            }}
            .event-details {{
                margin-bottom: 25px;
                border-bottom: 1px solid #eee;
                padding-bottom: 20px;
            }}
            .event-property {{
                display: flex;
                margin-bottom: 12px;
                align-items: flex-start;
                gap: 10px;
            }}
            .property-label {{
                font-weight: 600;
                min-width: 100px;
                color: #4a154b;
                flex-shrink: 0;
            }}
            .property-value {{
                flex: 1;
                word-wrap: break-word;
                overflow-wrap: break-word;
            }}
            .highlight {{
                background-color: #f6f3ff;
                padding: 15px;
                border-radius: 8px;
                margin: 15px 0;
                border-left: 4px solid #4a154b;
            }}
            .footer {{
                margin-top: 30px;
                text-align: center;
                color: #777;
                font-size: 14px;
                padding-top: 20px;
                border-top: 1px solid #eee;
            }}
            .section-title {{
                position: relative;
                padding-left: 15px;
                margin-top: 30px;
                color: #4a154b;
                font-weight: 600;
            }}
            .section-title:before {{
                content: '';
                position: absolute;
                left: 0;
                top: 0;
                height: 100%;
                width: 5px;
                background: linear-gradient(135deg, #6a3093 0%, #4a154b 100%);
                border-radius: 5px;
            }}

            /* Mobile Responsive Styles */
            @media only screen and (max-width: 480px) {{
                .email-body {{
                    padding: 20px 15px;
                }}
                .event-property {{
                    flex-direction: column;
                    gap: 2px;
                    margin-bottom: 15px;
                    padding-bottom: 10px;
                    border-bottom: 1px solid #f0f0f0;
                }}
                .property-label {{
                    min-width: auto;
                    margin-bottom: 3px;
                    font-size: 14px;
                }}
                .property-value {{
                    font-size: 14px;
                    margin-left: 0;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="email-container">
            <div class="email-header">
                <h1>📊 Event Report</h1>
            </div>
            <div class="email-body">
                <p>Dear {organizer_user.full_name if hasattr(organizer_user, 'full_name') and organizer_user.full_name else organizer_user.email},</p>

                <div class="highlight">
                    <h2>📊 Your Event Report is Ready!</h2>
                </div>

                <div class="event-details">
                    <h3 class="section-title">📌 Event Details</h3>

                    <div class="event-property">
                        <div class="property-label">Event:</div>
                        <div class="property-value">{event.name}</div>
                    </div>

                    <div class="event-property">
                        <div class="property-label">Location:</div>
                        <div class="property-value">{event.location}</div>
                    </div>

                    <div class="event-property">
                        <div class="property-label">Date:</div>
                        <div class="property-value">{event_date}</div>
                    </div>

                    <div class="event-property">
                        <div class="property-label">Time:</div>
                        <div class="property-value">{start_time} - {end_time}</div>
                    </div>

                    <div class="event-property">
                        <div class="property-label">Description:</div>
                        <div class="property-value">{event.description}</div>
                    </div>
                </div>

                <h3 class="section-title">📌 Overall Summary</h3>
                <div class="event-property">
                    <div class="property-label">Total Tickets Sold:</div>
                    <div class="property-value">{report['total_tickets_sold']}</div>
                </div>

                <div class="event-property">
                    <div class="property-label">Total Revenue:</div>
                    <div class="property-value">${report['total_revenue']:.2f}</div>
                </div>

                <div class="event-property">
                    <div class="property-label">Number of Attendees:</div>
                    <div class="property-value">{report['number_of_attendees']}</div>
                </div>

                <h3 class="section-title">🎟️ Ticket Sales by Type</h3>
                {f"<div>{''.join([f'<p>- {ticket_type}: {count} tickets</p>' for ticket_type, count in report['tickets_sold_by_type'].items()])}</div>" if report.get('tickets_sold_by_type') else "<p>No ticket sales data available.</p>"}

                <h3 class="section-title">💰 Revenue by Ticket Type</h3>
                {f"<div>{''.join([f'<p>- {ticket_type}: ${revenue:.2f}</p>' for ticket_type, revenue in report['revenue_by_ticket_type'].items()])}</div>" if report.get('revenue_by_ticket_type') else "<p>No revenue data available.</p>"}

                <div class="footer">
                    <p>Regards,</p>
                    <p>Your Event System Team</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        send_email_with_attachment(
            recipient=organizer_user.email,
            subject=f"📊 Event Report - {event.name}",
            body=email_body,
            attachment_path=pdf_path
        )
        logger.info(f"Report email (with PDF if generated) sent to {organizer_user.email}")
    except Exception as e:
        logger.error(f"Failed to send report email for event {event.name}: {e}")
    finally:
        if graph_path and os.path.exists(graph_path):
            os.remove(graph_path)
            logger.debug(f"Cleaned up graph file: {graph_path}")
        if pdf_path and os.path.exists(pdf_path):
            os.remove(pdf_path)
            logger.debug(f"Cleaned up PDF file: {pdf_path}")

class ReportResource(Resource):
    @jwt_required()
    def get(self, event_id):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        event = Event.query.get(event_id)

        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can access event reports"}, 403

        if not event:
            return {"message": "Event not found"}, 404

        if not event.organizer or event.organizer.user_id != user.id:
            return {"message": "You are not authorized to view the report for this event"}, 403

        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        start_date = parse_date_param(start_date_str, 'start_date')
        end_date = parse_date_param(end_date_str, 'end_date')

        if not start_date:
            return {"message": "Missing or invalid 'start_date' query parameter. Use YYYY-MM-DD."}, 400
        if not end_date:
            return {"message": "Missing or invalid 'end_date' query parameter. Use YYYY-MM-DD."}, 400

        if start_date > end_date:
            return {"message": "Start date cannot be after end date."}, 400

        report_data_or_error = get_event_report(event_id, save_to_history=True, start_date=start_date, end_date=end_date)

        if isinstance(report_data_or_error, tuple) and len(report_data_or_error) == 2:
            return report_data_or_error

        return report_data_or_error, 200

class ReportHistoryResource(Resource):
    @jwt_required()
    def get(self, event_id):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        event = Event.query.get(event_id)

        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can access event reports history"}, 403

        if not event:
            return {"message": "Event not found"}, 404

        if not event.organizer or event.organizer.user_id != user.id:
            return {"message": "You are not authorized to view the report history for this event"}, 403

        historical_reports = Report.query.filter_by(event_id=event_id)\
                                     .order_by(Report.timestamp.desc())\
                                     .all()

        return jsonify([report.as_dict() for report in historical_reports])

class ReportDeleteResource(Resource):
    @jwt_required()
    def delete(self, report_id):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can delete historical reports"}, 403

        try:
            report_to_delete = Report.query.get(report_id)

            if not report_to_delete:
                return {"message": "Report not found"}, 404

            event = Event.query.get(report_to_delete.event_id)
            if not event or not event.organizer or event.organizer.user_id != user.id:
                return {"message": "You are not authorized to delete this report"}, 403

            db.session.delete(report_to_delete)
            db.session.commit()
            return {"message": "Report deleted successfully"}, 200
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error deleting report (ID: {report_id}): {e}")
            return {"message": "An error occurred while deleting the report"}, 500

class ReportDownloadPDFResource(Resource):
    @jwt_required()
    def get(self, event_id):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        event = Event.query.get(event_id)

        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can download event reports"}, 403

        if not event:
            return {"message": "Event not found"}, 404

        if not event.organizer or event.organizer.user_id != user.id:
            return {"message": "You are not authorized to download the report for this event"}, 403

        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        start_date = parse_date_param(start_date_str, 'start_date')
        end_date = parse_date_param(end_date_str, 'end_date')

        if not start_date or not end_date:
            return {"message": "Both 'start_date' and 'end_date' query parameters are required for PDF download. Use YYYY-MM-DD."}, 400

        if start_date > end_date:
            return {"message": "Start date cannot be after end date."}, 400

        report_data_or_error = get_event_report(event_id, save_to_history=False, start_date=start_date, end_date=end_date)

        if isinstance(report_data_or_error, tuple) and len(report_data_or_error) == 2:
            return report_data_or_error

        report_data = report_data_or_error

        unique_timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
        graph_path = f"/tmp/event_report_{event_id}_graph_{unique_timestamp}.png"
        pdf_path = f"/tmp/event_report_{event_id}_{unique_timestamp}.pdf"

        try:
            generated_graph_path = generate_graph_image(report_data, graph_path)
            generated_pdf_path = generate_pdf_with_graph(report_data, event_id, pdf_path, generated_graph_path if generated_graph_path else "")

            if not generated_pdf_path or not os.path.exists(generated_pdf_path):
                logger.error(f"PDF file was not successfully generated for event {event_id}.")
                return {"message": "Failed to generate PDF report"}, 500

            return send_file(generated_pdf_path, as_attachment=True, download_name=f"event_report_{event.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf", mimetype='application/pdf')
        except Exception as e:
            logger.error(f"Error generating or sending PDF report for event {event_id}: {e}")
            return {"message": "Failed to generate or send PDF report"}, 500
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            if os.path.exists(graph_path):
                os.remove(graph_path)

class ReportResendEmailResource(Resource):
    @jwt_required()
    def post(self, event_id):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        event = Event.query.get(event_id)

        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can resend event reports"}, 403

        if not event:
            return {"message": "Event not found"}, 404

        if not event.organizer or event.organizer.user_id != user.id:
            return {"message": "You are not authorized to resend the report for this event"}, 403

        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        start_date = parse_date_param(start_date_str, 'start_date')
        end_date = parse_date_param(end_date_str, 'end_date')

        if not start_date or not end_date:
            return {"message": "Both 'start_date' and 'end_date' query parameters are required to resend email. Use YYYY-MM-DD."}, 400

        if start_date > end_date:
            return {"message": "Start date cannot be after end date."}, 400

        try:
            report_data_or_error = get_event_report(event_id, save_to_history=False, start_date=start_date, end_date=end_date)
            if isinstance(report_data_or_error, tuple) and len(report_data_or_error) == 2:
                return report_data_or_error

            send_report_to_organizer_with_pdf(report_data_or_error)
            return {"message": "Report email resent successfully"}, 200
        except Exception as e:
            logger.error(f"Error resending report email for event {event_id}: {e}")
            return {"message": "Failed to resend report email"}, 500

def generate_csv_report(report_data):
    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(["Event ID", report_data.get('event_id', 'N/A')])
    writer.writerow(["Event Name", report_data.get('event_name', 'N/A')])
    writer.writerow(["Event Date", report_data.get('event_date', 'N/A')])
    writer.writerow(["Event Location", report_data.get('event_location', 'N/A')])
    writer.writerow(["Report Start Date Filter", report_data.get('filter_start_date', 'N/A')])
    writer.writerow(["Report End Date Filter", report_data.get('filter_end_date', 'N/A')])
    writer.writerow([])

    writer.writerow(["Overall Summary"])
    writer.writerow(["Total Tickets Sold", report_data.get('total_tickets_sold', 0)])
    writer.writerow(["Total Revenue", f"{report_data.get('total_revenue', 0.0):.2f}"])
    writer.writerow(["Number of Attendees", report_data.get('number_of_attendees', 0)])
    writer.writerow([])

    writer.writerow(["Ticket Sales by Type"])
    writer.writerow(["Ticket Type", "Tickets Sold"])
    for ticket_type, count in report_data.get('tickets_sold_by_type', {}).items():
        writer.writerow([ticket_type, count])
    writer.writerow([])

    writer.writerow(["Revenue by Ticket Type"])
    writer.writerow(["Ticket Type", "Revenue"])
    for ticket_type, revenue in report_data.get('revenue_by_ticket_type', {}).items():
        writer.writerow([ticket_type, f"{revenue:.2f}"])
    writer.writerow([])

    writer.writerow(["Attendees by Ticket Type"])
    writer.writerow(["Ticket Type", "Attendees"])
    for ticket_type, attendees in report_data.get('attendees_by_ticket_type', {}).items():
        writer.writerow([ticket_type, attendees])
    writer.writerow([])

    writer.writerow(["Payment Method Usage"])
    writer.writerow(["Payment Method", "Count"])
    for method, count in report_data.get('payment_method_usage', {}).items():
        writer.writerow([method, count])
    writer.writerow([])

    return output.getvalue()

class ReportExportCSVResource(Resource):
    @jwt_required()
    def get(self, event_id):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        event = Event.query.get(event_id)

        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can export event reports"}, 403

        if not event:
            return {"message": "Event not found"}, 404

        if not event.organizer or event.organizer.user_id != user.id:
            return {"message": "You are not authorized to export the report for this event"}, 403

        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        start_date = parse_date_param(start_date_str, 'start_date')
        end_date = parse_date_param(end_date_str, 'end_date')

        if not start_date or not end_date:
            return {"message": "Both 'start_date' and 'end_date' query parameters are required for CSV export. Use YYYY-MM-DD."}, 400

        if start_date > end_date:
            return {"message": "Start date cannot be after end date."}, 400

        report_data_or_error = get_event_report(event_id, save_to_history=False, start_date=start_date, end_date=end_date)
        if isinstance(report_data_or_error, tuple) and len(report_data_or_error) == 2:
            return report_data_or_error

        report_data = report_data_or_error

        try:
            csv_content = generate_csv_report(report_data)
            return Response(
                csv_content,
                mimetype="text/csv",
                headers={"Content-disposition": f"attachment; filename=event_report_{event.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"}
            )
        except Exception as e:
            logger.error(f"Error generating CSV report for event {event_id}: {e}")
            return {"message": "Failed to generate CSV report"}, 500

class OrganizerSummaryReportResource(Resource):
    @jwt_required()
    def get(self):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)

        if not user or user.role.value != "ORGANIZER":
            return {"message": "Only organizers can access summary reports"}, 403

        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found for this user"}, 404

        total_tickets_sold_org = 0
        total_revenue_org = 0.0
        events_summary = []

        organizer_events = Event.query.filter_by(organizer_id=organizer.id).all()

        for event in organizer_events:
            event_total_tickets = Ticket.query.filter_by(event_id=event.id).count()
            event_total_revenue_query = db.session.query(db.func.sum(Transaction.amount_paid)).\
                join(Ticket, Ticket.transaction_id == Transaction.id).\
                filter(Ticket.event_id == event.id, Transaction.payment_status == 'COMPLETED').scalar()
            event_total_revenue = float(event_total_revenue_query) if event_total_revenue_query else 0.0

            total_tickets_sold_org += event_total_tickets
            total_revenue_org += event_total_revenue

            events_summary.append({
                "event_id": event.id,
                "event_name": event.name,
                "date": event.date.strftime('%Y-%m-%d') if event.date else "N/A",
                "location": event.location,
                "tickets_sold": event_total_tickets,
                "revenue": event_total_revenue
            })

        return {
            "organizer_id": organizer.id,
            "organizer_name": user.full_name if hasattr(user, 'full_name') and user.full_name else user.email,
            "total_tickets_sold_across_all_events": total_tickets_sold_org,
            "total_revenue_across_all_events": f"{total_revenue_org:.2f}",
            "events_summary": events_summary
        }, 200

def register_report_resources(api):
    api.add_resource(ReportResource, '/reports/events/<int:event_id>')
    api.add_resource(ReportHistoryResource, '/reports/events/<int:event_id>/history')
    api.add_resource(ReportDeleteResource, '/reports/<int:report_id>')
    api.add_resource(ReportDownloadPDFResource, '/reports/events/<int:event_id>/download/pdf')
    api.add_resource(ReportResendEmailResource, '/reports/events/<int:event_id>/resend-email')
    api.add_resource(ReportExportCSVResource, '/reports/events/<int:event_id>/export/csv')
    api.add_resource(OrganizerSummaryReportResource, '/reports/organizer/summary')
