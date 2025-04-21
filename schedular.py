# from apscheduler.schedulers.background import BackgroundScheduler
# from datetime import datetime
# from model import db, Event
# from app2 import app
# from report import get_event_report
# import logging

# # Configure logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# def generate_reports_for_all_events():
#     with app.app_context():
#         events = get_all_events()
#         if not events:
#             logger.info("ℹ️ No events found for report generation.")
#         for event in events:
#             try:
#                 get_event_report(event.id)
#                 db.session.commit()  # Ensure it's here if not inside get_event_report
#                 logger.info(f"✅ Report generated for Event ID {event.id} at {datetime.now()}")
#             except Exception as e:
#                 db.session.rollback()
#                 logger.error(f"❌ Error generating report for Event ID {event.id}", exc_info=True)

# def get_all_events():
#     """Helper function to get all events."""
#     return Event.query.all()

# def start_scheduler():
#     scheduler = BackgroundScheduler()
#     scheduler.add_job(func=generate_reports_for_all_events, trigger='interval', days=2, id="generate_reports", next_run_time=datetime.now())
#     scheduler.start()
#     logger.info("🕒 Scheduler started (every 2 days)")

#     # Shut down the scheduler when the app stops
#     import atexit
#     atexit.register(lambda: scheduler.shutdown())

# def register_scheduler():
#     """Initializes and starts the background scheduler."""
#     start_scheduler()
