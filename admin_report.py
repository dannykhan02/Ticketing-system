# from flask import jsonify, request, Response, send_file
# from flask_restful import Resource
# from flask_jwt_extended import jwt_required, get_jwt_identity
# from sqlalchemy import func
# from datetime import datetime
# import logging
# from typing import Dict, List, Optional, Any
# from dataclasses import dataclass

# # Your application-specific imports
# from model import User, Event, Organizer, Report, db, Currency, ExchangeRate
# from pdf_utils import CSVExporter
# from pdf_utils import PDFReportGenerator
# from email_utils import send_email_with_attachment

# logger = logging.getLogger(__name__)

# @dataclass
# class AdminReportConfig:
#     """Configuration for admin report generation"""
#     include_charts: bool = True
#     include_email: bool = False
#     format_type: str = 'json'
#     currency_conversion: bool = True
#     target_currency_id: Optional[int] = None
#     group_by_organizer: bool = True
#     use_latest_rates: bool = True

# class AdminReportService:
#     @staticmethod
#     def format_report_data_for_frontend(report_data, config):
#         """Format report data to ensure frontend compatibility"""

#         # Ensure events is a list and contains the required fields
#         if 'events' not in report_data:
#             report_data['events'] = []

#         # Format each event to ensure numeric values and required fields
#         formatted_events = []
#         for event in report_data.get('events', []):
#             formatted_event = {
#                 'event_id': event.get('event_id', ''),
#                 'event_name': event.get('event_name', 'Unknown Event'),
#                 'event_date': event.get('event_date', ''),
#                 'location': event.get('location', 'N/A'),
#                 'revenue': float(event.get('revenue', 0)),
#                 'attendees': int(event.get('attendees', 0)),
#                 'tickets_sold': int(event.get('tickets_sold', 0)),
#             }
#             formatted_events.append(formatted_event)

#         # Ensure currency symbol is present
#         if 'currency_symbol' not in report_data:
#             report_data['currency_symbol'] = '$'

#         # Add summary statistics
#         report_data['summary'] = {
#             'total_events': len(formatted_events),
#             'total_revenue': sum(event['revenue'] for event in formatted_events),
#             'total_attendees': sum(event['attendees'] for event in formatted_events),
#             'total_tickets_sold': sum(event['tickets_sold'] for event in formatted_events),
#         }

#         report_data['events'] = formatted_events
#         return report_data

#     @staticmethod
#     def validate_admin_access(user: User) -> bool:
#         """Validate that the user has admin access"""
#         return user and user.role.value == "ADMIN"

#     @staticmethod
#     def get_organizer_by_id(organizer_id: int) -> Optional[User]:
#         """Get organizer user by ID"""
#         try:
#             return User.query.filter_by(id=organizer_id, role='ORGANIZER').first()
#         except Exception as e:
#             logger.error(f"Database error fetching organizer {organizer_id}: {e}")
#             return None

#     @staticmethod
#     def get_events_by_organizer(organizer_id: int) -> List[Event]:
#         """Get all events for a specific organizer"""
#         try:
#             query = Event.query.join(Organizer).filter(Organizer.user_id == organizer_id)
#             return query.all()
#         except Exception as e:
#             logger.error(f"Database error fetching events for organizer {organizer_id}: {e}")
#             return []

#     @staticmethod
#     def get_reports_by_organizer(organizer_id: int) -> List[Report]:
#         """Get all reports for a specific organizer"""
#         try:
#             query = Report.query.filter_by(organizer_id=organizer_id)
#             return query.order_by(Report.timestamp.desc()).all()
#         except Exception as e:
#             logger.error(f"Database error fetching reports for organizer {organizer_id}: {e}")
#             return []

#     @staticmethod
#     def get_reports_by_event(event_id: int) -> List[Report]:
#         """Get all reports for a specific event"""
#         try:
#             query = Report.query.filter_by(event_id=event_id)
#             return query.order_by(Report.timestamp.desc()).all()
#         except Exception as e:
#             logger.error(f"Database error fetching reports for event {event_id}: {e}")
#             return []

#     @staticmethod
#     def aggregate_organizer_reports(reports: List[Report], target_currency_id: Optional[int] = None, use_latest_rates: bool = True) -> Dict[str, Any]:
#         """Aggregate multiple reports for an organizer with currency conversion support"""
#         if not reports:
#             return {
#                 "total_tickets_sold": 0,
#                 "total_revenue": 0.0,
#                 "total_attendees": 0,
#                 "event_count": 0,
#                 "report_count": 0,
#                 "currency": None,
#                 "events": []
#             }

#         total_tickets = sum(report.total_tickets_sold for report in reports)
#         total_attendees = sum(report.number_of_attendees or 0 for report in reports)
#         total_revenue = 0.0
#         currency_info = {}
#         target_currency = None

#         if target_currency_id:
#             target_currency = Currency.query.get(target_currency_id)
#             if target_currency:
#                 currency_info = {
#                     "currency": target_currency.code.value,
#                     "currency_symbol": target_currency.symbol
#                 }
#         elif reports and reports[0].base_currency:
#             base_currency = reports[0].base_currency
#             currency_info = {
#                 "currency": base_currency.code.value,
#                 "currency_symbol": base_currency.symbol
#             }
#         else:
#             currency_info = {
#                 "currency": "USD",
#                 "currency_symbol": "$"
#             }

#         for report in reports:
#             if target_currency:
#                 converted_revenue = report.get_revenue_in_currency(target_currency_id)
#                 total_revenue += float(converted_revenue)
#             else:
#                 total_revenue += float(report.total_revenue)

#         unique_events = list(set(report.event_id for report in reports))
#         event_details = []
#         for event_id in unique_events:
#             event_reports = [r for r in reports if r.event_id == event_id]
#             event = Event.query.get(event_id)
#             if event:
#                 event_revenue = 0.0
#                 for r in event_reports:
#                     if target_currency:
#                         event_revenue += float(r.get_revenue_in_currency(target_currency_id))
#                     else:
#                         event_revenue += float(r.total_revenue)
#                 event_tickets = sum(r.total_tickets_sold for r in event_reports)
#                 event_attendees = sum(r.number_of_attendees or 0 for r in event_reports)
#                 event_details.append({
#                     "event_id": event.id,
#                     "event_name": event.name,
#                     "event_date": event.date.isoformat() if event.date else None,
#                     "location": event.location,
#                     "tickets_sold": event_tickets,
#                     "revenue": event_revenue,
#                     "attendees": event_attendees,
#                     "report_count": len(event_reports)
#                 })

#         return {
#             "total_tickets_sold": total_tickets,
#             "total_revenue": total_revenue,
#             "total_attendees": total_attendees,
#             "event_count": len(unique_events),
#             "report_count": len(reports),
#             "currency": currency_info.get("currency"),
#             "currency_symbol": currency_info.get("currency_symbol"),
#             "events": event_details
#         }

#     @staticmethod
#     def aggregate_event_reports(event: Event, reports: List[Report], target_currency_id: Optional[int]) -> Dict[str, Any]:
#         """Aggregate data for a single event"""
#         tickets = sum(r.total_tickets_sold for r in reports)
#         attendees = sum(r.number_of_attendees or 0 for r in reports)
#         revenue = 0.0
#         for r in reports:
#             if target_currency_id:
#                 revenue += float(r.get_revenue_in_currency(target_currency_id))
#             else:
#                 revenue += float(r.total_revenue)

#         currency = "USD"
#         currency_symbol = "$"
#         if target_currency_id:
#             target_currency = Currency.query.get(target_currency_id)
#             if target_currency:
#                 currency = target_currency.code.value
#                 currency_symbol = target_currency.symbol
#         elif reports and reports[0].base_currency:
#             currency = reports[0].base_currency.code.value
#             currency_symbol = reports[0].base_currency.symbol

#         return {
#             "event_id": event.id,
#             "event_name": event.name,
#             "event_date": event.date.isoformat() if event.date else None,
#             "location": event.location,
#             "tickets_sold": tickets,
#             "attendees": attendees,
#             "revenue": revenue,
#             "currency": currency,
#             "currency_symbol": currency_symbol,
#             "report_count": len(reports)
#         }

#     @staticmethod
#     def generate_organizer_summary_report(organizer_id: int, config: AdminReportConfig) -> Dict[str, Any]:
#         """Generate a comprehensive summary report for an organizer"""
#         try:
#             organizer = AdminReportService.get_organizer_by_id(organizer_id)
#             if not organizer:
#                 return {"error": "Organizer not found", "status": 404}

#             reports = AdminReportService.get_reports_by_organizer(organizer_id)
#             aggregated_data = AdminReportService.aggregate_organizer_reports(reports, config.target_currency_id)

#             summary_report = {
#                 "organizer_info": {
#                     "organizer_id": organizer.id,
#                     "organizer_name": organizer.full_name,
#                     "email": organizer.email,
#                     "phone": organizer.phone_number
#                 },
#                 "report_period": {
#                     "days": "All available data"
#                 },
#                 "currency_settings": {
#                     "target_currency_id": config.target_currency_id,
#                     "use_latest_rates": config.use_latest_rates
#                 },
#                 "summary": aggregated_data,
#                 "detailed_reports": [
#                     report.as_dict(target_currency_id=config.target_currency_id) for report in reports
#                 ],
#                 "generation_timestamp": datetime.utcnow().isoformat()
#             }
#             return summary_report
#         except Exception as e:
#             logger.error(f"Error generating organizer summary report: {e}")
#             return {"error": "Failed to generate report", "status": 500}

#     @staticmethod
#     def generate_event_admin_report(event_id: int, organizer_id: int, config: AdminReportConfig) -> Dict[str, Any]:
#         """Generate an admin report for a specific event"""
#         try:
#             event = Event.query.join(Organizer).filter(
#                 Event.id == event_id,
#                 Organizer.user_id == organizer_id
#             ).first()
#             if not event:
#                 return {"error": "Event not found or doesn't belong to organizer", "status": 404}

#             existing_reports = AdminReportService.get_reports_by_event(event_id)
#             fresh_report_data = None
#             try:
#                 if existing_reports:
#                     fresh_summary = AdminReportService.aggregate_event_reports(
#                         event, existing_reports, config.target_currency_id
#                     )
#                     fresh_report_data = {
#                         "event_summary": fresh_summary,
#                         "report_timestamp": datetime.utcnow().isoformat(),
#                         "currency_conversion": {
#                             "target_currency_id": config.target_currency_id,
#                             "use_latest_rates": config.use_latest_rates
#                         },
#                         "currency_info": {
#                             "currency": fresh_summary["currency"],
#                             "currency_symbol": fresh_summary["currency_symbol"]
#                         }
#                     }
#                 else:
#                     currency_code = None
#                     currency_symbol = ""
#                     if config.target_currency_id:
#                         target_currency = Currency.query.get(config.target_currency_id)
#                         if target_currency:
#                             currency_code = target_currency.code.value
#                             currency_symbol = target_currency.symbol
#                     fresh_report_data = {
#                         "event_summary": {
#                             "event_id": event.id,
#                             "event_name": event.name,
#                             "tickets_sold": 0,
#                             "revenue": 0.0,
#                             "attendees": 0,
#                             "currency": currency_code,
#                             "currency_symbol": currency_symbol,
#                         },
#                         "report_timestamp": datetime.utcnow().isoformat(),
#                         "currency_conversion": {
#                             "target_currency_id": config.target_currency_id,
#                             "use_latest_rates": config.use_latest_rates
#                         },
#                         "currency_info": {
#                             "currency": currency_code,
#                             "currency_symbol": currency_symbol
#                         }
#                     }
#             except Exception as e:
#                 logger.warning(f"Could not generate fresh report data: {e}")
#                 currency_code = None
#                 currency_symbol = ""
#                 if config.target_currency_id:
#                     target_currency = Currency.query.get(config.target_currency_id)
#                     if target_currency:
#                         currency_code = target_currency.code.value
#                         currency_symbol = target_currency.symbol
#                 fresh_report_data = {
#                     "error": "Fresh report generation failed",
#                     "details": str(e),
#                     "event_summary": {
#                         "event_id": event.id,
#                         "event_name": event.name,
#                         "tickets_sold": 0,
#                         "revenue": 0.0,
#                         "attendees": 0,
#                         "currency": currency_code,
#                         "currency_symbol": currency_symbol,
#                     },
#                     "currency_info": {
#                         "currency": currency_code,
#                         "currency_symbol": currency_symbol
#                     }
#                 }

#             admin_report = {
#                 "event_info": {
#                     "event_id": event.id,
#                     "event_name": event.name,
#                     "event_date": event.date.isoformat() if event.date else None,
#                     "location": event.location,
#                     "organizer_id": organizer_id,
#                     "organizer_name": event.organizer.user.full_name if event.organizer and event.organizer.user else "N/A"
#                 },
#                 "report_period": {
#                     "days": "All available data"
#                 },
#                 "currency_settings": {
#                     "target_currency_id": config.target_currency_id,
#                     "use_latest_rates": config.use_latest_rates
#                 },
#                 "existing_reports": [
#                     report.as_dict(target_currency_id=config.target_currency_id) for report in existing_reports
#                 ],
#                 "fresh_report_data": fresh_report_data,
#                 "summary": {
#                     "total_stored_reports": len(existing_reports),
#                     "latest_report_date": existing_reports[0].timestamp.isoformat() if existing_reports else None
#                 },
#                 "generation_timestamp": datetime.utcnow().isoformat()
#             }
#             return admin_report
#         except Exception as e:
#             logger.error(f"Error generating event admin report: {e}")
#             return {"error": "Failed to generate event report", "status": 500}

#     @staticmethod
#     def send_report_email(report_data: Dict[str, Any], recipient_email: str) -> bool:
#         """Send report via email with enhanced formatting"""
#         try:
#             is_event_report = 'event_info' in report_data
#             if is_event_report:
#                 report_title = report_data['event_info'].get('event_name', 'Unknown Event')
#                 subject = f"Event Analytics Report - {report_title}"
#                 currency_symbol = report_data['fresh_report_data'].get('currency_info', {}).get('currency_symbol', '$')
#                 total_tickets_sold = report_data['fresh_report_data']['event_summary'].get('tickets_sold', 0)
#                 total_revenue = report_data['fresh_report_data']['event_summary'].get('revenue', 0.0)
#                 number_of_attendees = report_data['fresh_report_data']['event_summary'].get('attendees', 0)
#                 tickets_sold_by_type = {}
#                 revenue_by_ticket_type = {}
#             else:
#                 report_title = report_data['organizer_info'].get('organizer_name', 'Unknown Organizer')
#                 subject = f"Organizer Summary Report - {report_title}"
#                 currency_symbol = report_data['summary'].get('currency_symbol', '$')
#                 total_tickets_sold = report_data['summary'].get('total_tickets_sold', 0)
#                 total_revenue = report_data['summary'].get('total_revenue', 0.0)
#                 number_of_attendees = report_data['summary'].get('total_attendees', 0)
#                 tickets_sold_by_type = {}
#                 revenue_by_ticket_type = {}

#             html_body = f"""
#             <!DOCTYPE html>
#             <html>
#             <head>
#                 <meta charset="UTF-8">
#                 <style>
#                     body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
#                     .header {{ background: linear-gradient(135deg, #2E86AB, #A23B72); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
#                     .content {{ padding: 30px; background: #f9f9f9; }}
#                     .summary-box {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
#                     .metric {{ display: inline-block; margin: 10px 20px; text-align: center; }}
#                     .metric-value {{ font-size: 24px; font-weight: bold; color: #2E86AB; }}
#                     .metric-label {{ font-size: 14px; color: #666; }}
#                     .insights {{ background: #e8f4fd; padding: 15px; border-left: 4px solid #2E86AB; margin: 20px 0; }}
#                     .footer {{ background: #333; color: white; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 8px 8px; }}
#                     table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
#                     th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
#                     th {{ background-color: #2E86AB; color: white; }}
#                     .download-note {{ background: #e8f5e8; border: 1px solid #4caf50; padding: 15px; border-radius: 4px; margin: 20px 0; }}
#                 </style>
#             </head>
#             <body>
#                 <div class="header">
#                     <h1>📊 Admin Report</h1>
#                     <h2>{report_title}</h2>
#                 </div>
#                 <div class="content">
#                     <div class="summary-box">
#                         <h3>📈 Executive Summary</h3>
#                         <div class="metric">
#                             <div class="metric-value">{total_tickets_sold}</div>
#                             <div class="metric-label">Tickets Sold</div>
#                         </div>
#                         <div class="metric">
#                             <div class="metric-value">{currency_symbol}{total_revenue:,.2f}</div>
#                             <div class="metric-label">Total Revenue</div>
#                         </div>
#                         <div class="metric">
#                             <div class="metric-value">{number_of_attendees}</div>
#                             <div class="metric-label">Attendees</div>
#                         </div>
#             """
#             if total_tickets_sold > 0:
#                 attendance_rate = (number_of_attendees / total_tickets_sold * 100)
#                 html_body += f"""
#                         <div class="metric">
#                             <div class="metric-value">{attendance_rate:.1f}%</div>
#                             <div class="metric-label">Attendance Rate</div>
#                         </div>
#                 """
#             html_body += """
#                     </div>
#             """
#             if tickets_sold_by_type:
#                 html_body += """
#                     <div class="summary-box">
#                         <h3>🎫 Ticket Sales Breakdown</h3>
#                         <table>
#                             <tr><th>Ticket Type</th><th>Quantity</th><th>Revenue</th></tr>
#                 """
#                 for ticket_type in tickets_sold_by_type.keys():
#                     quantity = tickets_sold_by_type.get(ticket_type, 0)
#                     revenue = revenue_by_ticket_type.get(ticket_type, 0)
#                     html_body += f"<tr><td>{ticket_type}</td><td>{quantity}</td><td>{currency_symbol}{revenue:,.2f}</td></tr>"
#                 html_body += """
#                         </table>
#                     </div>
#                 """
#             html_body += f"""
#                     <div class="insights">
#                         <h3>💡 Key Insights</h3>
#                         <ul>
#             """
#             if total_tickets_sold > 0:
#                 attendance_rate = (number_of_attendees / total_tickets_sold * 100)
#                 if attendance_rate > 90:
#                     html_body += "<li>Excellent attendance rate! Most ticket holders attended.</li>"
#                 elif attendance_rate > 70:
#                     html_body += "<li>Good attendance rate with room for improvement in no-show reduction.</li>"
#                 else:
#                     html_body += "<li>Low attendance rate suggests potential areas for improvement.</li>"
#             if revenue_by_ticket_type:
#                 max_revenue_type = max(revenue_by_ticket_type.items(), key=lambda x: x[1])[0]
#                 html_body += f"<li>{max_revenue_type} tickets generated the highest revenue.</li>"
#             html_body += """
#                         </ul>
#                     </div>
#                     <div class="download-note">
#                         <h3>📥 Download Reports</h3>
#                         <p><strong>PDF Report:</strong> You can download the detailed PDF report with charts and visualizations directly from your browser</p>
#                         <p><strong>CSV Data Export:</strong> You can download the CSV data export for further analysis and processing directly from your browser</p>
#                     </div>
#                 </div>
#                 <div class="footer">
#                     <p>This report was automatically generated by the Event Management System</p>
#                     <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
#                 </div>
#             </body>
#             </html>
#             """
#             success = send_email_with_attachment(
#                 recipient=recipient_email,
#                 subject=subject,
#                 body=html_body,
#                 is_html=True
#             )
#             return success
#         except Exception as e:
#             logger.error(f"Error sending report email: {e}")
#             return False

# class AdminReportResource(Resource):
#     """Admin report API resource"""
#     @jwt_required()
#     def get(self):
#         """Get admin reports with various filtering options"""
#         current_user_id = get_jwt_identity()
#         user = User.query.get(current_user_id)
#         if not AdminReportService.validate_admin_access(user):
#             return {"message": "Admin access required"}, 403

#         organizer_id = request.args.get('organizer_id', type=int)
#         event_id = request.args.get('event_id', type=int)
#         format_type = request.args.get('format', 'json')
#         target_currency_id = request.args.get('currency_id', type=int)
#         include_charts = request.args.get('include_charts', 'true').lower() == 'true'
#         use_latest_rates = request.args.get('use_latest_rates', 'true').lower() == 'true'
#         send_email = request.args.get('send_email', 'false').lower() == 'true'
#         recipient_email = request.args.get('recipient_email', user.email)

#         config = AdminReportConfig(
#             include_charts=include_charts,
#             include_email=send_email,
#             format_type=format_type,
#             target_currency_id=target_currency_id,
#             use_latest_rates=use_latest_rates
#         )

#         try:
#             if organizer_id and event_id:
#                 report_data = AdminReportService.generate_event_admin_report(
#                     event_id, organizer_id, config
#                 )
#             elif organizer_id:
#                 report_data = AdminReportService.generate_organizer_summary_report(
#                     organizer_id, config
#                 )
#             else:
#                 return {"message": "Please specify organizer_id or both organizer_id and event_id"}, 400

#             if "error" in report_data:
#                 return {"message": report_data["error"]}, report_data.get("status", 500)

#             if format_type.lower() == 'csv':
#                 csv_content = CSVExporter.generate_csv_report(report_data)
#                 response = Response(
#                     csv_content,
#                     mimetype='text/csv',
#                     headers={'Content-Disposition': f'attachment; filename=admin_report_{organizer_id}_{datetime.now().strftime("%Y%m%d")}.csv'}
#                 )
#             elif format_type.lower() == 'pdf':
#                 try:
#                     pdf_buffer = PDFReportGenerator.generate_pdf_report(report_data, config)
#                     response = send_file(
#                         pdf_buffer,
#                         mimetype='application/pdf',
#                         as_attachment=True,
#                         download_name=f'admin_report_{organizer_id}_{datetime.now().strftime("%Y%m%d")}.pdf'
#                     )
#                 except Exception as e:
#                     logger.error(f"PDF generation failed: {e}")
#                     return {"message": "PDF generation failed", "error": str(e)}, 500
#             else:
#                 response = jsonify(report_data)

#             if send_email:
#                 email_success = AdminReportService.send_report_email(report_data, recipient_email)
#                 if not email_success:
#                     logger.error("Failed to send email")

#             return response
#         except Exception as e:
#             logger.error(f"Admin report generation failed: {e}")
#             return {"message": "Report generation failed", "error": str(e)}, 500

# class AdminOrganizerListResource(Resource):
#     """Resource for listing all organizers for admin"""
#     @jwt_required()
#     def get(self):
#         """Get list of all organizers with basic info"""
#         current_user_id = get_jwt_identity()
#         user = User.query.get(current_user_id)
#         if not AdminReportService.validate_admin_access(user):
#             return {"message": "Admin access required"}, 403

#         try:
#             organizers = db.session.query(
#                 User.id,
#                 User.full_name,
#                 User.email,
#                 User.phone_number,
#                 func.count(Event.id).label('event_count'),
#                 func.count(Report.id).label('report_count')
#             ).select_from(User)\
#             .outerjoin(Organizer, User.id == Organizer.user_id)\
#             .outerjoin(Event, Organizer.id == Event.organizer_id)\
#             .outerjoin(Report, User.id == Report.organizer_id)\
#             .filter(User.role == 'ORGANIZER')\
#             .group_by(User.id, User.full_name, User.email, User.phone_number)\
#             .all()

#             organizer_list = []
#             for org in organizers:
#                 organizer_list.append({
#                     "organizer_id": org.id,
#                     "name": org.full_name,
#                     "email": org.email,
#                     "phone": org.phone_number,
#                     "event_count": org.event_count,
#                     "report_count": org.report_count
#                 })

#             return {
#                 "organizers": organizer_list,
#                 "total_count": len(organizer_list)
#             }
#         except Exception as e:
#             logger.error(f"Error fetching organizer list: {e}")
#             return {"message": "Failed to fetch organizer list", "error": str(e)}, 500

# class AdminEventListResource(Resource):
#     """Resource for listing events by organizer for admin"""
#     @jwt_required()
#     def get(self, organizer_id):
#         """Get list of events for a specific organizer"""
#         current_user_id = get_jwt_identity()
#         user = User.query.get(current_user_id)
#         if not AdminReportService.validate_admin_access(user):
#             return {"message": "Admin access required"}, 403

#         try:
#             events = db.session.query(
#                 Event.id,
#                 Event.name,
#                 Event.date,
#                 Event.location,
#                 func.count(Report.id).label('report_count')
#             ).select_from(Event)\
#             .join(Organizer, Event.organizer_id == Organizer.id)\
#             .outerjoin(Report, Event.id == Report.event_id)\
#             .filter(Organizer.user_id == organizer_id)\
#             .group_by(Event.id, Event.name, Event.date, Event.location)\
#             .order_by(Event.date.desc())\
#             .all()

#             event_list = []
#             for event in events:
#                 event_list.append({
#                     "event_id": event.id,
#                     "name": event.name,
#                     "event_date": event.date.isoformat() if event.date else None,
#                     "location": event.location,
#                     "report_count": event.report_count
#                 })

#             return {
#                 "organizer_id": organizer_id,
#                 "events": event_list,
#                 "total_count": len(event_list)
#             }
#         except Exception as e:
#             logger.error(f"Error fetching event list for organizer {organizer_id}: {e}")
#             return {"message": "Failed to fetch event list", "error": str(e)}, 500

# def register_admin_report_resources(api):
#     """Register admin report resources with the Flask-RESTful API"""
#     api.add_resource(AdminReportResource, '/admin/reports')
#     api.add_resource(AdminOrganizerListResource, '/admin/organizers')
#     api.add_resource(AdminEventListResource, '/admin/organizers/<int:organizer_id>/events')