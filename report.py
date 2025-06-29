import matplotlib
matplotlib.use('Agg')  # Set the backend to 'Agg' to avoid GUI issues

from flask import jsonify, request, Response, send_file
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, TicketType, Transaction, Scan, Event, User, Report, Organizer
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import SQLAlchemyError
import logging
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_agg import FigureCanvasAgg
import seaborn as sns
import pandas as pd
from email_utils import send_email_with_attachment
import os
from datetime import datetime, time
import csv
from io import StringIO, BytesIO
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from contextlib import contextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ReportConfig:
    """Configuration for report generation"""
    include_charts: bool = True
    include_email: bool = True
    chart_dpi: int = 300
    chart_style: str = 'seaborn-v0_8'
    pdf_pagesize: tuple = A4

class DateUtils:
    """Utility class for date operations"""

    @staticmethod
    def parse_date_param(date_str: str, param_name: str) -> Optional[datetime]:
        """Parse a date string into a datetime object with proper error handling"""
        if not date_str:
            return None

        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            logger.warning(f"Invalid {param_name} format: {date_str}. Expected YYYY-MM-DD.")
            return None

    @staticmethod
    def adjust_end_date(end_date: datetime) -> datetime:
        """Adjust end date to include the entire day"""
        if isinstance(end_date, datetime):
            return end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            # If it's a date object, combine it with time to make it a datetime
            return datetime.combine(end_date, time(23, 59, 59, 999999))

class ChartGenerator:
    """Handles chart generation for reports"""

    def __init__(self, config: ReportConfig):
        self.config = config
        self._setup_matplotlib()

    def _setup_matplotlib(self):
        """Configure matplotlib settings"""
        plt.style.use(self.config.chart_style)
        sns.set_palette("husl")

    @contextmanager
    def _chart_context(self, figsize: Tuple[int, int] = (10, 8)):
        """Context manager for chart creation"""
        fig, ax = plt.subplots(figsize=figsize)
        try:
            yield fig, ax
        finally:
            plt.close(fig)

    def create_pie_chart(self, data: Dict[str, int], title: str) -> Optional[str]:
        """Create a pie chart for ticket distribution"""
        if not data:
            return None

        try:
            with self._chart_context() as (fig, ax):
                labels = list(data.keys())
                sizes = list(data.values())
                colors = plt.cm.Set3(range(len(labels)))

                wedges, texts, autotexts = ax.pie(
                    sizes, labels=labels, autopct='%1.1f%%',
                    colors=colors, startangle=90,
                    explode=[0.05] * len(labels)
                )

                for autotext in autotexts:
                    autotext.set_color('white')
                    autotext.set_fontweight('bold')

                ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
                plt.tight_layout()

                chart_path = tempfile.mktemp(suffix='.png')
                plt.savefig(chart_path, dpi=self.config.chart_dpi, bbox_inches='tight')
                return chart_path

        except Exception as e:
            logger.error(f"Error creating pie chart: {e}")
            return None

    def create_bar_chart(self, data: Dict[str, float], title: str, xlabel: str, ylabel: str) -> Optional[str]:
        """Create a bar chart for revenue or other metrics"""
        if not data:
            return None

        try:
            with self._chart_context((12, 8)) as (fig, ax):
                categories = list(data.keys())
                values = list(data.values())

                bars = ax.bar(categories, values, color=plt.cm.viridis(range(len(categories))))

                # Add value labels on bars
                for bar in bars:
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                            f'${height:.2f}' if 'Revenue' in ylabel else f'{height:.0f}',
                            ha='center', va='bottom', fontweight='bold')

                ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
                ax.set_xlabel(xlabel, fontsize=12, fontweight='bold')
                ax.set_ylabel(ylabel, fontsize=12, fontweight='bold')

                plt.xticks(rotation=45, ha='right')
                plt.tight_layout()

                chart_path = tempfile.mktemp(suffix='.png')
                plt.savefig(chart_path, dpi=self.config.chart_dpi, bbox_inches='tight')
                return chart_path

        except Exception as e:
            logger.error(f"Error creating bar chart: {e}")
            return None

    def create_comparison_chart(self, sold_data: Dict[str, int], attended_data: Dict[str, int], title: str) -> Optional[str]:
        """Create a comparison chart for sales vs attendance"""
        if not sold_data or not attended_data:
            return None

        try:
            with self._chart_context((12, 8)) as (fig, ax):
                categories = list(sold_data.keys())
                sold_counts = [sold_data.get(t, 0) for t in categories]
                attended_counts = [attended_data.get(t, 0) for t in categories]

                x = range(len(categories))
                width = 0.35

                bars1 = ax.bar([i - width/2 for i in x], sold_counts, width, label='Tickets Sold', color='skyblue', alpha=0.8)
                bars2 = ax.bar([i + width/2 for i in x], attended_counts, width, label='Attendees', color='lightcoral', alpha=0.8)

                # Add value labels
                for bars in [bars1, bars2]:
                    for bar in bars:
                        height = bar.get_height()
                        ax.text(bar.get_x() + bar.get_width()/2., height,
                                f'{int(height)}', ha='center', va='bottom', fontweight='bold')

                ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
                ax.set_xlabel('Ticket Type', fontsize=12, fontweight='bold')
                ax.set_ylabel('Count', fontsize=12, fontweight='bold')
                ax.set_xticks(x)
                ax.set_xticklabels(categories, rotation=45, ha='right')
                ax.legend()

                plt.tight_layout()

                chart_path = tempfile.mktemp(suffix='.png')
                plt.savefig(chart_path, dpi=self.config.chart_dpi, bbox_inches='tight')
                return chart_path

        except Exception as e:
            logger.error(f"Error creating comparison chart: {e}")
            return None

    def create_all_charts(self, report_data: Dict[str, Any]) -> List[str]:
        """Create all charts for the report"""
        chart_paths = []

        # Tickets sold by type - Pie Chart
        if report_data.get('tickets_sold_by_type'):
            chart_path = self.create_pie_chart(
                report_data['tickets_sold_by_type'],
                'Ticket Sales Distribution by Type'
            )
            if chart_path:
                chart_paths.append(chart_path)

        # Revenue by type - Bar Chart
        if report_data.get('revenue_by_ticket_type'):
            chart_path = self.create_bar_chart(
                report_data['revenue_by_ticket_type'],
                'Revenue by Ticket Type',
                'Ticket Type',
                'Revenue ($)'
            )
            if chart_path:
                chart_paths.append(chart_path)

        # Sales vs Attendance Comparison
        if report_data.get('tickets_sold_by_type') and report_data.get('attendees_by_ticket_type'):
            chart_path = self.create_comparison_chart(
                report_data['tickets_sold_by_type'],
                report_data['attendees_by_ticket_type'],
                'Tickets Sold vs Actual Attendance'
            )
            if chart_path:
                chart_paths.append(chart_path)

        # Payment methods - Bar Chart
        if report_data.get('payment_method_usage'):
            chart_path = self.create_bar_chart(
                report_data['payment_method_usage'],
                'Payment Method Usage',
                'Payment Method',
                'Number of Transactions'
            )
            if chart_path:
                chart_paths.append(chart_path)

        return chart_paths

class PDFReportGenerator:
    """Handles PDF report generation"""

    def __init__(self, config: ReportConfig):
        self.config = config
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#2E86AB')
        )

        self.subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=self.styles['Heading2'],
            fontSize=18,
            spaceAfter=20,
            textColor=colors.HexColor('#A23B72')
        )

        self.header_style = ParagraphStyle(
            'CustomHeader',
            parent=self.styles['Heading3'],
            fontSize=14,
            spaceAfter=12,
            textColor=colors.HexColor('#F18F01')
        )

    def _create_summary_table(self, report_data: Dict[str, Any]) -> Table:
        """Create summary table for the report"""
        attendance_rate = 0
        if report_data.get('total_tickets_sold', 0) > 0:
            attendance_rate = (report_data.get('number_of_attendees', 0) / report_data.get('total_tickets_sold', 1) * 100)

        summary_data = [
            ['Metric', 'Value'],
            ['Total Tickets Sold', str(report_data.get('total_tickets_sold', 0))],
            ['Total Revenue', f"${report_data.get('total_revenue', 0.0):.2f}"],
            ['Total Attendees', str(report_data.get('number_of_attendees', 0))],
            ['Attendance Rate', f"{attendance_rate:.1f}%"],
        ]

        if report_data.get('total_tickets_sold', 0) > 0:
            avg_revenue = (report_data.get('total_revenue', 0.0) / report_data.get('total_tickets_sold', 1))
            summary_data.append(['Average Revenue per Ticket', f"${avg_revenue:.2f}"])

        table = Table(summary_data, colWidths=[3*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E86AB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
        ]))

        return table

    def _create_breakdown_tables(self, report_data: Dict[str, Any]) -> List[Tuple[str, Table]]:
        """Create detailed breakdown tables"""
        tables = []

        # Ticket Sales Breakdown
        if report_data.get('tickets_sold_by_type'):
            ticket_data = [['Ticket Type', 'Quantity Sold', 'Percentage']]
            total_sold = sum(report_data['tickets_sold_by_type'].values())

            for ticket_type, count in report_data['tickets_sold_by_type'].items():
                percentage = (count / total_sold * 100) if total_sold > 0 else 0
                ticket_data.append([str(ticket_type), str(count), f"{percentage:.1f}%"])

            table = self._create_styled_table(ticket_data)
            tables.append(('Ticket Sales Breakdown', table))

        # Revenue Breakdown
        if report_data.get('revenue_by_ticket_type'):
            revenue_data = [['Ticket Type', 'Revenue', 'Percentage']]
            total_revenue = sum(report_data['revenue_by_ticket_type'].values())

            for ticket_type, revenue in report_data['revenue_by_ticket_type'].items():
                percentage = (revenue / total_revenue * 100) if total_revenue > 0 else 0
                revenue_data.append([str(ticket_type), f"${revenue:.2f}", f"{percentage:.1f}%"])

            table = self._create_styled_table(revenue_data)
            tables.append(('Revenue Breakdown', table))

        # Attendance Breakdown
        if report_data.get('attendees_by_ticket_type'):
            attendance_data = [['Ticket Type', 'Attendees', 'Attendance Rate']]

            for ticket_type, attendees in report_data['attendees_by_ticket_type'].items():
                sold = report_data.get('tickets_sold_by_type', {}).get(ticket_type, 0)
                rate = (attendees / sold * 100) if sold > 0 else 0
                attendance_data.append([str(ticket_type), str(attendees), f"{rate:.1f}%"])

            table = self._create_styled_table(attendance_data)
            tables.append(('Attendance Breakdown', table))

        return tables

    def _create_styled_table(self, data: List[List[str]]) -> Table:
        """Create a styled table with consistent formatting"""
        table = Table(data, colWidths=[2.5*inch, 1.5*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#A23B72')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
            ('ALTERNATEROWBACKGROUND', (0, 1), (-1, -1), [colors.lightgrey, colors.white]),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        return table

    def _generate_insights(self, report_data: Dict[str, Any]) -> List[str]:
        """Generate key insights from the report data"""
        insights = []

        total_sold = report_data.get('total_tickets_sold', 0)
        total_attended = report_data.get('number_of_attendees', 0)
        attendance_rate = (total_attended / total_sold * 100) if total_sold > 0 else 0

        insights.append(f"• Overall attendance rate: {attendance_rate:.1f}%")

        if report_data.get('revenue_by_ticket_type'):
            highest_revenue_type = max(
                report_data['revenue_by_ticket_type'].items(),
                key=lambda x: x[1]
            )
            insights.append(
                f"• Highest revenue ticket type: {highest_revenue_type[0]} "
                f"(${highest_revenue_type[1]:.2f})"
            )

        if report_data.get('tickets_sold_by_type'):
            most_popular_type = max(
                report_data['tickets_sold_by_type'].items(),
                key=lambda x: x[1]
            )
            insights.append(
                f"• Most popular ticket type: {most_popular_type[0]} "
                f"({most_popular_type[1]} tickets)"
            )

        if report_data.get('payment_method_usage'):
            preferred_payment = max(
                report_data['payment_method_usage'].items(),
                key=lambda x: x[1]
            )
            insights.append(
                f"• Preferred payment method: {preferred_payment[0]} "
                f"({preferred_payment[1]} transactions)"
            )

        return insights

    def generate_pdf(self, report_data: Dict[str, Any], chart_paths: List[str], output_path: str) -> Optional[str]:
        """Generate comprehensive PDF report"""
        try:
            doc = SimpleDocTemplate(
                output_path, pagesize=self.config.pdf_pagesize,
                rightMargin=72, leftMargin=72,
                topMargin=72, bottomMargin=18
            )

            story = []

            # Title Page
            story.append(Paragraph("EVENT ANALYTICS REPORT", self.title_style))
            story.append(Spacer(1, 20))

            # Event Information
            event_info = f"""
            <para fontSize=14>
            <b>Event:</b> {report_data.get('event_name', 'N/A')}<br/>
            <b>Date:</b> {report_data.get('event_date', 'N/A')}<br/>
            <b>Location:</b> {report_data.get('event_location', 'N/A')}<br/>
            <b>Report Period:</b> {report_data.get('filter_start_date', 'N/A')} to {report_data.get('filter_end_date', 'N/A')}<br/>
            <b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </para>
            """
            story.append(Paragraph(event_info, self.styles['Normal']))
            story.append(Spacer(1, 30))

            # Executive Summary
            story.append(Paragraph("EXECUTIVE SUMMARY", self.subtitle_style))
            story.append(self._create_summary_table(report_data))
            story.append(Spacer(1, 30))

            # Key Insights
            story.append(Paragraph("KEY INSIGHTS", self.header_style))
            insights = self._generate_insights(report_data)
            for insight in insights:
                story.append(Paragraph(insight, self.styles['Normal']))

            story.append(PageBreak())

            # Add charts
            if chart_paths and self.config.include_charts:
                story.append(Paragraph("VISUAL ANALYTICS", self.subtitle_style))

                for i, chart_path in enumerate(chart_paths):
                    if os.path.exists(chart_path):
                        try:
                            img = Image(chart_path, width=6*inch, height=4*inch)
                            story.append(img)
                            story.append(Spacer(1, 20))

                            if (i + 1) % 2 == 0:
                                story.append(PageBreak())
                        except Exception as e:
                            logger.error(f"Error adding chart to PDF: {e}")

            # Detailed breakdown tables
            story.append(Paragraph("DETAILED BREAKDOWN", self.subtitle_style))

            tables = self._create_breakdown_tables(report_data)
            for table_title, table in tables:
                story.append(Paragraph(table_title, self.header_style))
                story.append(table)
                story.append(Spacer(1, 20))

            # Footer
            story.append(Spacer(1, 50))
            footer_text = """
            <para alignment="center" fontSize=10 textColor="grey">
            This report was automatically generated by the Event Management System<br/>
            For questions or support, please contact your system administrator
            </para>
            """
            story.append(Paragraph(footer_text, self.styles['Normal']))

            # Build PDF
            doc.build(story)
            return output_path

        except Exception as e:
            logger.error(f"Error generating PDF report: {e}")
            return None

class DatabaseQueryService:
    """Handles database queries for report generation"""

    @staticmethod
    def get_event_with_validation(event_id: int) -> Optional[Event]:
        """Get event with validation"""
        try:
            return Event.query.get(event_id)
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching event {event_id}: {e}")
            return None

    @staticmethod
    def get_tickets_sold_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get tickets sold by type within date range"""
        try:
            return db.session.query(TicketType.type_name, db.func.count(Ticket.id)).\
                join(Ticket, Ticket.ticket_type_id == TicketType.id).\
                filter(
                    Ticket.event_id == event_id,
                    Ticket.purchase_date >= start_date,
                    Ticket.purchase_date <= end_date
                ).\
                group_by(TicketType.type_name).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching tickets sold by type: {e}")
            return []

    @staticmethod
    def get_revenue_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, float]]:
        """Get revenue by ticket type within date range"""
        try:
            return db.session.query(TicketType.type_name, db.func.sum(Transaction.amount_paid)).\
                join(Ticket, Ticket.ticket_type_id == TicketType.id).\
                join(Transaction, Ticket.transaction_id == Transaction.id).\
                filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                ).\
                group_by(TicketType.type_name).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching revenue by type: {e}")
            return []

    @staticmethod
    def get_attendees_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get attendees by ticket type within date range"""
        try:
            return db.session.query(TicketType.type_name, db.func.count(db.distinct(Scan.ticket_id))).\
                join(Ticket, Scan.ticket_id == Ticket.id).\
                join(TicketType, Ticket.ticket_type_id == TicketType.id).\
                filter(
                    Ticket.event_id == event_id,
                    Scan.scanned_at >= start_date,
                    Scan.scanned_at <= end_date
                ).\
                group_by(TicketType.type_name).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching attendees by type: {e}")
            return []

    @staticmethod
    def get_payment_method_usage(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get payment method usage within date range"""
        try:
            return db.session.query(Transaction.payment_method, db.func.count(Transaction.id)).\
                join(Ticket, Ticket.transaction_id == Transaction.id).\
                filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                ).\
                group_by(Transaction.payment_method).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching payment method usage: {e}")
            return []

    @staticmethod
    def get_total_revenue(event_id: int, start_date: datetime, end_date: datetime) -> float:
        """Get total revenue within date range"""
        try:
            result = db.session.query(db.func.sum(Transaction.amount_paid)).\
                join(Ticket, Ticket.transaction_id == Transaction.id).\
                filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                ).scalar()
            return float(result) if result else 0.0
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching total revenue: {e}")
            return 0.0

    @staticmethod
    def get_total_tickets_sold(event_id: int, start_date: datetime, end_date: datetime) -> int:
        """Get total tickets sold within date range"""
        try:
            return Ticket.query.filter(
                Ticket.event_id == event_id,
                Ticket.purchase_date >= start_date,
                Ticket.purchase_date <= end_date
            ).count()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching total tickets sold: {e}")
            return 0

    @staticmethod
    def get_total_attendees(event_id: int, start_date: datetime, end_date: datetime) -> int:
        """Get total attendees within date range"""
        try:
            return Scan.query.join(Ticket, Scan.ticket_id == Ticket.id).\
                filter(
                    Ticket.event_id == event_id,
                    Scan.scanned_at >= start_date,
                    Scan.scanned_at <= end_date
                ).\
                distinct(Scan.ticket_id).count()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching total attendees: {e}")
            return 0

class EmailService:
    """Handles email functionality for reports"""

    @staticmethod
    def create_email_body(event: Event, report_data: Dict[str, Any], organizer_user: User) -> str:
        """Create HTML email body for the report"""
        event_date = event.date.strftime('%A, %B %d, %Y') if event.date else "Date not available"
        start_time = event.start_time.strftime('%H:%M:%S') if event.start_time else "Start time not available"
        end_time = event.end_time.strftime('%H:%M:%S') if event.end_time else "Till Late"

        organizer_name = (organizer_user.full_name
                        if hasattr(organizer_user, 'full_name') and organizer_user.full_name
                        else organizer_user.email)

        ticket_sales_html = EmailService._format_ticket_sales(report_data.get('tickets_sold_by_type'))
        revenue_html = EmailService._format_revenue_data(report_data.get('revenue_by_ticket_type'))

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                {EmailService._get_email_styles()}
            </style>
        </head>
        <body>
            <div class="email-container">
                <div class="email-header">
                    <h1>📊 Event Report</h1>
                </div>
                <div class="email-body">
                    <p>Dear {organizer_name},</p>
                    <div class="highlight">
                        <h2>📊 Your Event Report is Ready!</h2>
                    </div>
                    <div class="event-details">
                        <h3 class="section-title">📌 Event Details</h3>
                        {EmailService._format_event_details(event, event_date, start_time, end_time)}
                    </div>
                    <h3 class="section-title">📌 Overall Summary</h3>
                    {EmailService._format_summary_data(report_data)}
                    <h3 class="section-title">🎟️ Ticket Sales by Type</h3>
                    {ticket_sales_html}
                    <h3 class="section-title">💰 Revenue by Ticket Type</h3>
                    {revenue_html}
                    <div class="footer">
                        <p>Regards,</p>
                        <p>Your Event System Team</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    @staticmethod
    def _get_email_styles() -> str:
        """Return CSS styles for email"""
        return """
            @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');
            body {
                font-family: 'Poppins', Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 0;
                background-color: #f5f5f5;
            }
            .email-container {
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }
            .email-header {
                background: linear-gradient(135deg, #6a3093 0%, #4a154b 100%);
                color: white;
                padding: 25px 15px;
                text-align: center;
            }
            .email-header h1 {
                margin: 0;
                font-size: 24px;
                letter-spacing: 0.5px;
            }
            .email-body {
                padding: 25px 20px;
            }
            .event-details {
                margin-bottom: 25px;
                border-bottom: 1px solid #eee;
                padding-bottom: 20px;
            }
            .event-property {
                display: flex;
                margin-bottom: 12px;
                align-items: flex-start;
                gap: 10px;
            }
            .property-label {
                font-weight: 600;
                min-width: 100px;
                color: #4a154b;
                flex-shrink: 0;
            }
            .property-value {
                flex: 1;
                word-wrap: break-word;
                overflow-wrap: break-word;
            }
            .highlight {
                background-color: #f6f3ff;
                padding: 15px;
                border-radius: 8px;
                margin: 15px 0;
                border-left: 4px solid #4a154b;
            }
            .footer {
                margin-top: 30px;
                text-align: center;
                color: #777;
                font-size: 14px;
                padding-top: 20px;
                border-top: 1px solid #eee;
            }
            .section-title {
                position: relative;
                padding-left: 15px;
                margin-top: 30px;
                color: #4a154b;
                font-weight: 600;
            }
            .section-title:before {
                content: '';
                position: absolute;
                left: 0;
                top: 0;
                height: 100%;
                width: 5px;
                background: linear-gradient(135deg, #6a3093 0%, #4a154b 100%);
                border-radius: 5px;
            }
            @media only screen and (max-width: 480px) {
                .email-body {
                    padding: 20px 15px;
                }
                .event-property {
                    flex-direction: column;
                    gap: 2px;
                    margin-bottom: 15px;
                    padding-bottom: 10px;
                    border-bottom: 1px solid #f0f0f0;
                }
                .property-label {
                    min-width: auto;
                    margin-bottom: 3px;
                    font-size: 14px;
                }
                .property-value {
                    font-size: 14px;
                    margin-left: 0;
                }
            }
        """

    @staticmethod
    def _format_event_details(event: Event, event_date: str, start_time: str, end_time: str) -> str:
        """Format event details section"""
        return f"""
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
        """

    @staticmethod
    def _format_summary_data(report_data: Dict[str, Any]) -> str:
        """Format summary data section"""
        return f"""
            <div class="event-property">
                <div class="property-label">Total Tickets Sold:</div>
                <div class="property-value">{report_data['total_tickets_sold']}</div>
            </div>
            <div class="event-property">
                <div class="property-label">Total Revenue:</div>
                <div class="property-value">${report_data['total_revenue']:.2f}</div>
            </div>
            <div class="event-property">
                <div class="property-label">Number of Attendees:</div>
                <div class="property-value">{report_data['number_of_attendees']}</div>
            </div>
        """

    @staticmethod
    def _format_ticket_sales(tickets_sold_by_type: Dict[str, int]) -> str:
        """Format ticket sales data"""
        if not tickets_sold_by_type:
            return "<p>No ticket sales data available.</p>"

        items = ''.join([f'<p>- {ticket_type}: {count} tickets</p>'
                        for ticket_type, count in tickets_sold_by_type.items()])
        return f"<div>{items}</div>"

    @staticmethod
    def _format_revenue_data(revenue_by_ticket_type: Dict[str, float]) -> str:
        """Format revenue data"""
        if not revenue_by_ticket_type:
            return "<p>No revenue data available.</p>"

        items = ''.join([f'<p>- {ticket_type}: ${revenue:.2f}</p>'
                        for ticket_type, revenue in revenue_by_ticket_type.items()])
        return f"<div>{items}</div>"

class FileManager:
    """Handles file operations for reports"""

    @staticmethod
    def generate_unique_paths(event_id: int) -> Tuple[str, str]:
        """Generate unique file paths for graph and PDF"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
        graph_path = f"/tmp/event_report_{event_id}_graph_{timestamp}.png"
        pdf_path = f"/tmp/event_report_{event_id}_{timestamp}.pdf"
        return graph_path, pdf_path

    @staticmethod
    def cleanup_files(*file_paths: str) -> None:
        """Clean up temporary files"""
        for file_path in file_paths:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Cleaned up file: {file_path}")
                except OSError as e:
                    logger.warning(f"Failed to clean up file {file_path}: {e}")

class ReportEmailSender:
    """Handles sending report emails with PDF attachments"""

    @staticmethod
    def send_report_to_organizer_with_pdf(report: Dict[str, Any]) -> None:
        """Sends the generated report as a PDF attachment to the event organizer."""
        event_id = report['event_id']
        event = Event.query.get(event_id)

        if not event or not event.organizer or not event.organizer.user:
            logger.warning(f"No organizer found for event: {event_id}")
            return

        organizer_user = event.organizer.user
        if not organizer_user.email:
            logger.warning(f"No organizer email found for event: {event.name} (Event ID: {event_id})")
            return
        graph_path, pdf_path = FileManager.generate_unique_paths(event.id)

        try:
            # Generate graph and PDF
            generated_graph_path = generate_graph_image(report, graph_path)
            if not generated_graph_path:
                logger.error(f"Failed to generate graph image for event {event.id}. Email will be sent without graph.")
                generated_graph_path = ""
            generated_pdf_path = generate_pdf_with_graph(report, event_id, pdf_path, generated_graph_path)
            if not generated_pdf_path:
                logger.error(f"Failed to generate PDF for event {event.id}. Email will not be sent with attachment.")
                pdf_path = None
            # Create and send email
            email_body = EmailService.create_email_body(event, report, organizer_user)

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
            FileManager.cleanup_files(graph_path, pdf_path)

# Helper functions for generating graph images and PDFs
def generate_graph_image(report_data: Dict[str, Any], graph_path: str) -> str:
    """Generate all charts for the report and return the first chart path (for legacy compatibility)."""
    config = ReportConfig()
    chart_generator = ChartGenerator(config)
    chart_paths = chart_generator.create_all_charts(report_data)
    if chart_paths:
        # Optionally, copy or move the first chart to the requested graph_path
        import shutil
        shutil.copy(chart_paths[0], graph_path)
        return graph_path
    return ""

def generate_pdf_with_graph(report_data: Dict[str, Any], event_id: int, pdf_path: str, graph_path: str = "") -> str:
    """Generate a PDF report, optionally including a graph image."""
    config = ReportConfig()
    chart_generator = ChartGenerator(config)
    chart_paths = []
    if graph_path and os.path.exists(graph_path):
        chart_paths.append(graph_path)
    else:
        chart_paths = chart_generator.create_all_charts(report_data)
    pdf_generator = PDFReportGenerator(config)
    generated_pdf = pdf_generator.generate_pdf(report_data, chart_paths, pdf_path)
    return generated_pdf if generated_pdf else ""

class AuthorizationMixin:
    """Mixin class for handling authorization checks"""

    @staticmethod
    def check_organizer_access(user: User) -> bool:
        """Check if user is an organizer"""
        return user and user.role.value == "ORGANIZER"

    @staticmethod
    def check_event_ownership(event: Event, user: User) -> bool:
        """Check if user owns the event"""
        return (event and event.organizer and
                event.organizer.user_id == user.id)

    @staticmethod
    def get_current_user() -> Optional[User]:
        """Get current authenticated user"""
        current_user_id = get_jwt_identity()
        return User.query.get(current_user_id)

class DateValidator:
    """Handles date validation for reports"""

    @staticmethod
    def validate_date_range(start_date_str: str, end_date_str: str) -> Tuple[Optional[datetime], Optional[datetime], Optional[Dict]]:
        """Validate date range parameters"""
        start_date = DateUtils.parse_date_param(start_date_str, 'start_date')
        end_date = DateUtils.parse_date_param(end_date_str, 'end_date')

        if not start_date:
            return None, None, {"message": "Missing or invalid 'start_date' query parameter. Use YYYY-MM-DD.", "status": 400}

        if not end_date:
            return None, None, {"message": "Missing or invalid 'end_date' query parameter. Use YYYY-MM-DD.", "status": 400}

        if start_date > end_date:
            return None, None, {"message": "Start date cannot be after end date.", "status": 400}

        return start_date, end_date, None

class CSVExporter:
    """Handles CSV export functionality"""

    @staticmethod
    def generate_csv_report(report_data: Dict[str, Any]) -> str:
        """Generate CSV content from report data"""
        output = StringIO()
        writer = csv.writer(output)
        # Event information
        CSVExporter._write_event_info(writer, report_data)

        # Summary data
        CSVExporter._write_summary_data(writer, report_data)

        # Detailed breakdowns
        CSVExporter._write_ticket_sales(writer, report_data)
        CSVExporter._write_revenue_data(writer, report_data)
        CSVExporter._write_attendee_data(writer, report_data)
        CSVExporter._write_payment_methods(writer, report_data)
        return output.getvalue()

    @staticmethod
    def _write_event_info(writer, report_data: Dict[str, Any]) -> None:
        """Write event information to CSV"""
        writer.writerow(["Event ID", report_data.get('event_id', 'N/A')])
        writer.writerow(["Event Name", report_data.get('event_name', 'N/A')])
        writer.writerow(["Event Date", report_data.get('event_date', 'N/A')])
        writer.writerow(["Event Location", report_data.get('event_location', 'N/A')])
        writer.writerow(["Report Start Date Filter", report_data.get('filter_start_date', 'N/A')])
        writer.writerow(["Report End Date Filter", report_data.get('filter_end_date', 'N/A')])
        writer.writerow([])

    @staticmethod
    def _write_summary_data(writer, report_data: Dict[str, Any]) -> None:
        """Write summary data to CSV"""
        writer.writerow(["Overall Summary"])
        writer.writerow(["Total Tickets Sold", report_data.get('total_tickets_sold', 0)])
        writer.writerow(["Total Revenue", f"{report_data.get('total_revenue', 0.0):.2f}"])
        writer.writerow(["Number of Attendees", report_data.get('number_of_attendees', 0)])
        writer.writerow([])

    @staticmethod
    def _write_ticket_sales(writer, report_data: Dict[str, Any]) -> None:
        """Write ticket sales data to CSV"""
        writer.writerow(["Ticket Sales by Type"])
        writer.writerow(["Ticket Type", "Tickets Sold"])
        for ticket_type, count in report_data.get('tickets_sold_by_type', {}).items():
            writer.writerow([ticket_type, count])
        writer.writerow([])

    @staticmethod
    def _write_revenue_data(writer, report_data: Dict[str, Any]) -> None:
        """Write revenue data to CSV"""
        writer.writerow(["Revenue by Ticket Type"])
        writer.writerow(["Ticket Type", "Revenue"])
        for ticket_type, revenue in report_data.get('revenue_by_ticket_type', {}).items():
            writer.writerow([ticket_type, f"{revenue:.2f}"])
        writer.writerow([])

    @staticmethod
    def _write_attendee_data(writer, report_data: Dict[str, Any]) -> None:
        """Write attendee data to CSV"""
        writer.writerow(["Attendees by Ticket Type"])
        writer.writerow(["Ticket Type", "Attendees"])
        for ticket_type, attendees in report_data.get('attendees_by_ticket_type', {}).items():
            writer.writerow([ticket_type, attendees])
        writer.writerow([])

    @staticmethod
    def _write_payment_methods(writer, report_data: Dict[str, Any]) -> None:
        """Write payment method data to CSV"""
        writer.writerow(["Payment Method Usage"])
        writer.writerow(["Payment Method", "Count"])
        for method, count in report_data.get('payment_method_usage', {}).items():
            writer.writerow([method, count])
        writer.writerow([])

def get_event_report(event_id, save_to_history=True, start_date=None, end_date=None):
    """
    Generate event report data for the given event and date range.
    Returns a dictionary with report data, or a tuple (error_dict, status_code) on error.
    """
    event = Event.query.get(event_id)
    if not event:
        return {"message": "Event not found"}, 404

    # Use provided date range or default to event date
    if not start_date:
        start_date = event.date if event.date else datetime.now()
    if not end_date:
        end_date = event.date if event.date else datetime.now()
    # Adjust end_date to include the whole day
    end_date = DateUtils.adjust_end_date(end_date)

    # Gather report data using DatabaseQueryService
    tickets_sold_by_type = dict(DatabaseQueryService.get_tickets_sold_by_type(event_id, start_date, end_date))
    revenue_by_ticket_type = dict(DatabaseQueryService.get_revenue_by_type(event_id, start_date, end_date))
    attendees_by_ticket_type = dict(DatabaseQueryService.get_attendees_by_type(event_id, start_date, end_date))
    payment_method_usage = dict(DatabaseQueryService.get_payment_method_usage(event_id, start_date, end_date))
    total_revenue = DatabaseQueryService.get_total_revenue(event_id, start_date, end_date)
    total_tickets_sold = DatabaseQueryService.get_total_tickets_sold(event_id, start_date, end_date)
    number_of_attendees = DatabaseQueryService.get_total_attendees(event_id, start_date, end_date)

    report_data = {
        "event_id": event.id,
        "event_name": event.name,
        "event_date": event.date.strftime('%Y-%m-%d') if event.date else "N/A",
        "event_location": event.location,
        "filter_start_date": start_date.strftime('%Y-%m-%d'),
        "filter_end_date": end_date.strftime('%Y-%m-%d'),
        "total_tickets_sold": total_tickets_sold,
        "total_revenue": total_revenue,
        "number_of_attendees": number_of_attendees,
        "tickets_sold_by_type": tickets_sold_by_type,
        "revenue_by_ticket_type": revenue_by_ticket_type,
        "attendees_by_ticket_type": attendees_by_ticket_type,
        "payment_method_usage": payment_method_usage,
    }

    # Optionally save to history
    if save_to_history:
        try:
            new_report = Report(
                event_id=event.id,
                report_data=report_data,
                timestamp=datetime.now()
            )
            db.session.add(new_report)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to save report to history: {e}")

    return report_data

class ReportResource(Resource, AuthorizationMixin):
    """Resource for generating event reports"""

    @jwt_required()
    def get(self, event_id):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            return {"message": "Only organizers can access event reports"}, 403
        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404
        if not self.check_event_ownership(event, user):
            return {"message": "You are not authorized to view the report for this event"}, 403
        # Validate date parameters
        start_date, end_date, error = DateValidator.validate_date_range(
            request.args.get('start_date'),
            request.args.get('end_date')
        )

        if error:
            return error, error['status']
        # Generate report
        report_data_or_error = get_event_report(
            event_id,
            save_to_history=True,
            start_date=start_date,
            end_date=end_date
        )
        if isinstance(report_data_or_error, tuple) and len(report_data_or_error) == 2:
            return report_data_or_error
        return report_data_or_error, 200

class ReportHistoryResource(Resource, AuthorizationMixin):
    """Resource for managing report history"""

    @jwt_required()
    def get(self, event_id):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            return {"message": "Only organizers can access event reports history"}, 403
        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404
        if not self.check_event_ownership(event, user):
            return {"message": "You are not authorized to view the report history for this event"}, 403
        historical_reports = (Report.query
                            .filter_by(event_id=event_id)
                            .order_by(Report.timestamp.desc())
                            .all())
        return jsonify([report.as_dict() for report in historical_reports])

class ReportDeleteResource(Resource, AuthorizationMixin):
    """Resource for deleting historical reports"""

    @jwt_required()
    def delete(self, report_id):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            return {"message": "Only organizers can delete historical reports"}, 403
        try:
            report_to_delete = Report.query.get(report_id)
            if not report_to_delete:
                return {"message": "Report not found"}, 404
            event = Event.query.get(report_to_delete.event_id)
            if not self.check_event_ownership(event, user):
                return {"message": "You are not authorized to delete this report"}, 403
            db.session.delete(report_to_delete)
            db.session.commit()
            return {"message": "Report deleted successfully"}, 200

        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"Error deleting report (ID: {report_id}): {e}")
            return {"message": "An error occurred while deleting the report"}, 500

class ReportDownloadPDFResource(Resource, AuthorizationMixin):
    """Resource for downloading PDF reports"""

    @jwt_required()
    def get(self, event_id):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            return {"message": "Only organizers can download event reports"}, 403
        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404
        if not self.check_event_ownership(event, user):
            return {"message": "You are not authorized to download the report for this event"}, 403
        # Validate date parameters
        start_date, end_date, error = DateValidator.validate_date_range(
            request.args.get('start_date'),
            request.args.get('end_date')
        )

        if error:
            return error, error['status']
        # Generate report data
        report_data_or_error = get_event_report(
            event_id,
            save_to_history=False,
            start_date=start_date,
            end_date=end_date
        )
        if isinstance(report_data_or_error, tuple):
            return report_data_or_error
        report_data = report_data_or_error
        graph_path, pdf_path = FileManager.generate_unique_paths(event_id)
        try:
            generated_graph_path = generate_graph_image(report_data, graph_path)
            generated_pdf_path = generate_pdf_with_graph(
                report_data,
                event_id,
                pdf_path,
                generated_graph_path if generated_graph_path else ""
            )
            if not generated_pdf_path or not os.path.exists(generated_pdf_path):
                logger.error(f"PDF file was not successfully generated for event {event_id}.")
                return {"message": "Failed to generate PDF report"}, 500
            filename = f"event_report_{event.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
            return send_file(
                generated_pdf_path,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )

        except Exception as e:
            logger.error(f"Error generating or sending PDF report for event {event_id}: {e}")
            return {"message": "Failed to generate or send PDF report"}, 500
        finally:
            FileManager.cleanup_files(pdf_path, graph_path)

class ReportResendEmailResource(Resource, AuthorizationMixin):
    """Resource for resending report emails"""

    @jwt_required()
    def post(self, event_id):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            return {"message": "Only organizers can resend event reports"}, 403
        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404
        if not self.check_event_ownership(event, user):
            return {"message": "You are not authorized to resend the report for this event"}, 403
        # Validate date parameters
        start_date, end_date, error = DateValidator.validate_date_range(
            request.args.get('start_date'),
            request.args.get('end_date')
        )

        if error:
            return error, error['status']
        try:
            report_data_or_error = get_event_report(
                event_id,
                save_to_history=False,
                start_date=start_date,
                end_date=end_date
            )

            if isinstance(report_data_or_error, tuple):
                return report_data_or_error
            ReportEmailSender.send_report_to_organizer_with_pdf(report_data_or_error)
            return {"message": "Report email resent successfully"}, 200

        except Exception as e:
            logger.error(f"Error resending report email for event {event_id}: {e}")
            return {"message": "Failed to resend report email"}, 500

class ReportExportCSVResource(Resource, AuthorizationMixin):
    """Resource for exporting reports as CSV"""

    @jwt_required()
    def get(self, event_id):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            return {"message": "Only organizers can export event reports"}, 403
        event = Event.query.get(event_id)
        if not event:
            return {"message": "Event not found"}, 404
        if not self.check_event_ownership(event, user):
            return {"message": "You are not authorized to export the report for this event"}, 403
        # Validate date parameters
        start_date, end_date, error = DateValidator.validate_date_range(
            request.args.get('start_date'),
            request.args.get('end_date')
        )

        if error:
            return error, error['status']
        report_data_or_error = get_event_report(
            event_id,
            save_to_history=False,
            start_date=start_date,
            end_date=end_date
        )

        if isinstance(report_data_or_error, tuple):
            return report_data_or_error
        try:
            csv_content = CSVExporter.generate_csv_report(report_data_or_error)
            filename = f"event_report_{event.name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"

            return Response(
                csv_content,
                mimetype="text/csv",
                headers={"Content-disposition": f"attachment; filename={filename}"}
            )

        except Exception as e:
            logger.error(f"Error generating CSV report for event {event_id}: {e}")
            return {"message": "Failed to generate CSV report"}, 500

class OrganizerSummaryReportResource(Resource, AuthorizationMixin):
    """Resource for organizer summary reports"""

    @jwt_required()
    def get(self):
        user = self.get_current_user()
        if not self.check_organizer_access(user):
            return {"message": "Only organizers can access summary reports"}, 403
        organizer = Organizer.query.filter_by(user_id=user.id).first()
        if not organizer:
            return {"message": "Organizer profile not found for this user"}, 404
        summary_data = self._calculate_organizer_summary(organizer)
        return summary_data, 200

    def _calculate_organizer_summary(self, organizer: Organizer) -> Dict[str, Any]:
        """Calculate summary data for organizer"""
        total_tickets_sold = 0
        total_revenue = 0.0
        events_summary = []
        organizer_events = Event.query.filter_by(organizer_id=organizer.id).all()
        for event in organizer_events:
            event_tickets = Ticket.query.filter_by(event_id=event.id).count()

            event_revenue_query = (db.session.query(db.func.sum(Transaction.amount_paid))
                                  .join(Ticket, Ticket.transaction_id == Transaction.id)
                                  .filter(Ticket.event_id == event.id,
                                           Transaction.payment_status == 'COMPLETED')
                                  .scalar())

            event_revenue = float(event_revenue_query) if event_revenue_query else 0.0
            total_tickets_sold += event_tickets
            total_revenue += event_revenue
            events_summary.append({
                "event_id": event.id,
                "event_name": event.name,
                "date": event.date.strftime('%Y-%m-%d') if event.date else "N/A",
                "location": event.location,
                "tickets_sold": event_tickets,
                "revenue": event_revenue
            })
        organizer_name = (organizer.user.full_name
                          if hasattr(organizer.user, 'full_name') and organizer.user.full_name
                          else organizer.user.email)
        return {
            "organizer_id": organizer.id,
            "organizer_name": organizer_name,
            "total_tickets_sold_across_all_events": total_tickets_sold,
            "total_revenue_across_all_events": f"{total_revenue:.2f}",
            "events_summary": events_summary
        }

class ReportResourceRegistry:
    """Registry for report-related API resources"""

    @staticmethod
    def register_report_resources(api):
        """Register all report resources with the API"""
        api.add_resource(ReportResource, '/reports/events/<int:event_id>')
        api.add_resource(ReportHistoryResource, '/reports/events/<int:event_id>/history')
        api.add_resource(ReportDeleteResource, '/reports/<int:report_id>')
        api.add_resource(ReportDownloadPDFResource, '/reports/events/<int:event_id>/download/pdf')
        api.add_resource(ReportResendEmailResource, '/reports/events/<int:event_id>/resend-email')
        api.add_resource(ReportExportCSVResource, '/reports/events/<int:event_id>/export/csv')
        api.add_resource(OrganizerSummaryReportResource, '/reports/organizer/summary')

# Legacy function for backward compatibility
def send_report_to_organizer_with_pdf(report):
    """Legacy function - delegates to new ReportEmailSender class"""
    ReportEmailSender.send_report_to_organizer_with_pdf(report)

def generate_csv_report(report_data):
    """Legacy function - delegates to new CSVExporter class"""
    return CSVExporter.generate_csv_report(report_data)

def register_report_resources(api):
    """Legacy function - delegates to new ReportResourceRegistry class"""
    ReportResourceRegistry.register_report_resources(api)
