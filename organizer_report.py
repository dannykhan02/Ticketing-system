import matplotlib
matplotlib.use('Agg')  # Set the backend to 'Agg' to avoid GUI issues
from flask import jsonify, request, Response, send_file
from flask_restful import Resource
from flask_jwt_extended import jwt_required, get_jwt_identity
from model import db, Ticket, TicketType, Transaction, Scan, Event, User, Report, Organizer, Currency, ExchangeRate, UserRole
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, and_, or_
import logging
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import os
from datetime import datetime, date, time, timedelta
import csv
from io import StringIO, BytesIO
import tempfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Union
from contextlib import contextmanager
from decimal import Decimal
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_email_with_attachment(recipient, subject, body, attachments=None, is_html=False):
    """Dummy implementation for sending email with attachments."""
    logger.info(f"Sending email to {recipient} with subject '{subject}' and {len(attachments or [])} attachments.")
    return True

@dataclass
class ReportConfig:
    """Configuration for report generation"""
    include_charts: bool = True
    include_email: bool = True
    chart_dpi: int = 300
    chart_style: str = 'seaborn-v0_8'
    pdf_pagesize: tuple = A4
    default_currency: str = 'USD'

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
            return datetime.combine(end_date, time(23, 59, 59, 999999))

class CurrencyConverter:
    """Handles currency conversion for reports"""
    @staticmethod
    def convert_amount(amount: Decimal, from_currency_id: int, to_currency_id: int) -> Decimal:
        """Convert amount from one currency to another"""
        if from_currency_id == to_currency_id:
            return amount
        rate = ExchangeRate.query.filter_by(
            from_currency_id=from_currency_id,
            to_currency_id=to_currency_id,
            is_active=True
        ).order_by(ExchangeRate.effective_date.desc()).first()
        if rate:
            return amount * rate.rate
        logger.warning(f"No exchange rate found from currency {from_currency_id} to {to_currency_id}")
        return amount

    @staticmethod
    def get_currency_info(currency_id: int) -> Dict[str, str]:
        """Get currency code and symbol"""
        currency = Currency.query.get(currency_id)
        if currency:
            return {
                'code': currency.code.value if currency.code else 'USD',
                'symbol': currency.symbol or '$'
            }
        return {'code': 'USD', 'symbol': '$'}

class DatabaseQueryService:
    """Service for database queries related to reports"""
    @staticmethod
    def get_tickets_sold_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get tickets sold by type within date range"""
        query = (db.session.query(TicketType.type_name, func.count(Ticket.id))
                .join(Ticket, Ticket.ticket_type_id == TicketType.id)
                .join(Transaction, Ticket.transaction_id == Transaction.id)
                .filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                )
                .group_by(TicketType.type_name)
                .all())
        return [(type_name.value if hasattr(type_name, 'value') else str(type_name), count)
                for type_name, count in query]

    @staticmethod
    def get_revenue_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, Decimal]]:
        """Get revenue by ticket type within date range"""
        query = (db.session.query(TicketType.type_name, func.sum(Transaction.amount_paid))
                .join(Ticket, Ticket.ticket_type_id == TicketType.id)
                .join(Transaction, Ticket.transaction_id == Transaction.id)
                .filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                )
                .group_by(TicketType.type_name)
                .all())
        return [(type_name.value if hasattr(type_name, 'value') else str(type_name),
                Decimal(str(revenue)) if revenue else Decimal('0'))
                for type_name, revenue in query]

    @staticmethod
    def get_attendees_by_type(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get attendees by ticket type within date range"""
        query = (db.session.query(TicketType.type_name, func.count(func.distinct(Scan.ticket_id)))
                .join(Ticket, Scan.ticket_id == Ticket.id)
                .join(TicketType, Ticket.ticket_type_id == TicketType.id)
                .filter(
                    Ticket.event_id == event_id,
                    Scan.scanned_at >= start_date,
                    Scan.scanned_at <= end_date
                )
                .group_by(TicketType.type_name)
                .all())
        return [(type_name.value if hasattr(type_name, 'value') else str(type_name), count)
                for type_name, count in query]

    @staticmethod
    def get_payment_method_usage(event_id: int, start_date: datetime, end_date: datetime) -> List[Tuple[str, int]]:
        """Get payment method usage within date range"""
        query = (db.session.query(Transaction.payment_method, func.count(Transaction.id))
                .join(Ticket, Ticket.transaction_id == Transaction.id)
                .filter(
                    Ticket.event_id == event_id,
                    Transaction.payment_status == 'COMPLETED',
                    Transaction.timestamp >= start_date,
                    Transaction.timestamp <= end_date
                )
                .group_by(Transaction.payment_method)
                .all())
        return [(method.value if hasattr(method, 'value') else str(method), count)
                for method, count in query]

    @staticmethod
    def get_total_revenue(event_id: int, start_date: datetime, end_date: datetime) -> Decimal:
        """Get total revenue within date range"""
        result = (db.session.query(func.sum(Transaction.amount_paid))
                 .join(Ticket, Ticket.transaction_id == Transaction.id)
                 .filter(
                     Ticket.event_id == event_id,
                     Transaction.payment_status == 'COMPLETED',
                     Transaction.timestamp >= start_date,
                     Transaction.timestamp <= end_date
                 )
                 .scalar())
        return Decimal(str(result)) if result else Decimal('0')

    @staticmethod
    def get_total_tickets_sold(event_id: int, start_date: datetime, end_date: datetime) -> int:
        """Get total tickets sold within date range"""
        result = (db.session.query(func.count(Ticket.id))
                 .join(Transaction, Ticket.transaction_id == Transaction.id)
                 .filter(
                     Ticket.event_id == event_id,
                     Transaction.payment_status == 'COMPLETED',
                     Transaction.timestamp >= start_date,
                     Transaction.timestamp <= end_date
                 )
                 .scalar())
        return result if result else 0

    @staticmethod
    def get_total_attendees(event_id: int, start_date: datetime, end_date: datetime) -> int:
        """Get total attendees within date range"""
        result = (db.session.query(func.count(func.distinct(Scan.ticket_id)))
                 .join(Ticket, Scan.ticket_id == Ticket.id)
                 .filter(
                     Ticket.event_id == event_id,
                     Scan.scanned_at >= start_date,
                     Scan.scanned_at <= end_date
                 )
                 .scalar())
        return result if result else 0

    @staticmethod
    def get_event_base_currency(event_id: int) -> int:
        """Get the base currency for an event"""
        event = Event.query.get(event_id)
        if event and hasattr(event, 'base_currency_id') and event.base_currency_id:
            return event.base_currency_id
        default_currency = Currency.query.filter_by(code='USD').first()
        return default_currency.id if default_currency else 1

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

    def create_bar_chart(self, data: Dict[str, Union[float, Decimal]], title: str, xlabel: str, ylabel: str, currency_symbol: str = '$') -> Optional[str]:
        """Create a bar chart for revenue or other metrics"""
        if not data:
            return None
        try:
            with self._chart_context((12, 8)) as (fig, ax):
                categories = list(data.keys())
                values = [float(v) for v in data.values()]
                bars = ax.bar(categories, values, color=plt.cm.viridis(range(len(categories))))
                for bar in bars:
                    height = bar.get_height()
                    if 'Revenue' in ylabel:
                        ax.text(bar.get_x() + bar.get_width()/2., height,
                                f'{currency_symbol}{height:.2f}',
                                ha='center', va='bottom', fontweight='bold')
                    else:
                        ax.text(bar.get_x() + bar.get_width()/2., height,
                                f'{height:.0f}',
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
                bars1 = ax.bar([i - width/2 for i in x], sold_counts, width,
                              label='Tickets Sold', color='skyblue', alpha=0.8)
                bars2 = ax.bar([i + width/2 for i in x], attended_counts, width,
                              label='Attendees', color='lightcoral', alpha=0.8)
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
        currency_symbol = report_data.get('currency_symbol', '$')
        if report_data.get('tickets_sold_by_type'):
            chart_path = self.create_pie_chart(
                report_data['tickets_sold_by_type'],
                'Ticket Sales Distribution by Type'
            )
            if chart_path:
                chart_paths.append(chart_path)
        if report_data.get('revenue_by_ticket_type'):
            chart_path = self.create_bar_chart(
                report_data['revenue_by_ticket_type'],
                'Revenue by Ticket Type',
                'Ticket Type',
                f'Revenue ({currency_symbol})',
                currency_symbol
            )
            if chart_path:
                chart_paths.append(chart_path)
        if report_data.get('tickets_sold_by_type') and report_data.get('attendees_by_ticket_type'):
            chart_path = self.create_comparison_chart(
                report_data['tickets_sold_by_type'],
                report_data['attendees_by_ticket_type'],
                'Tickets Sold vs Actual Attendance'
            )
            if chart_path:
                chart_paths.append(chart_path)
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
            attendance_rate = (report_data.get('number_of_attendees', 0) /
                             report_data.get('total_tickets_sold', 1) * 100)
        currency_symbol = report_data.get('currency_symbol', '$')
        summary_data = [
            ['Metric', 'Value'],
            ['Total Tickets Sold', str(report_data.get('total_tickets_sold', 0))],
            ['Total Revenue', f"{currency_symbol}{report_data.get('total_revenue', 0):.2f}"],
            ['Total Attendees', str(report_data.get('number_of_attendees', 0))],
            ['Attendance Rate', f"{attendance_rate:.1f}%"],
        ]
        if report_data.get('total_tickets_sold', 0) > 0:
            avg_revenue = (float(report_data.get('total_revenue', 0)) /
                          report_data.get('total_tickets_sold', 1))
            summary_data.append(['Average Revenue per Ticket', f"{currency_symbol}{avg_revenue:.2f}"])
        if report_data.get('original_currency') and report_data.get('currency') != report_data.get('original_currency'):
            summary_data.append(['Original Currency', report_data.get('original_currency')])
            summary_data.append(['Displayed Currency', report_data.get('currency')])
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

    def _generate_insights(self, report_data: Dict[str, Any]) -> List[str]:
        """Generate insights based on report data"""
        insights = []
        if report_data.get('total_tickets_sold', 0) > 0:
            attendance_rate = (report_data.get('number_of_attendees', 0) /
                             report_data.get('total_tickets_sold', 1) * 100)
            if attendance_rate > 90:
                insights.append("• Excellent attendance rate! Most ticket holders attended the event.")
            elif attendance_rate > 70:
                insights.append("• Good attendance rate with room for improvement in no-show reduction.")
            else:
                insights.append("• Low attendance rate suggests potential areas for improvement.")
        tickets_sold_by_type = report_data.get('tickets_sold_by_type', {})
        revenue_by_ticket_type = report_data.get('revenue_by_ticket_type', {})
        if tickets_sold_by_type and revenue_by_ticket_type:
            max_revenue_type = max(revenue_by_ticket_type.items(), key=lambda x: float(x[1]))[0]
            insights.append(f"• {max_revenue_type} tickets generated the highest revenue for this event.")
            max_sold_type = max(tickets_sold_by_type.items(), key=lambda x: x[1])[0]
            if max_sold_type != max_revenue_type:
                insights.append(f"• {max_sold_type} was the most popular ticket type by volume.")
        payment_methods = report_data.get('payment_method_usage', {})
        if payment_methods:
            preferred_method = max(payment_methods.items(), key=lambda x: x[1])[0]
            insights.append(f"• {preferred_method} was the preferred payment method for this event.")
        return insights

    def _create_breakdown_tables(self, report_data: Dict[str, Any]) -> List[Tuple[str, Table]]:
        """Create detailed breakdown tables"""
        tables = []
        currency_symbol = report_data.get('currency_symbol', '$')
        if report_data.get('tickets_sold_by_type'):
            data = [['Ticket Type', 'Tickets Sold', 'Percentage']]
            total_tickets = sum(report_data['tickets_sold_by_type'].values())
            for ticket_type, count in report_data['tickets_sold_by_type'].items():
                percentage = (count / total_tickets * 100) if total_tickets > 0 else 0
                data.append([ticket_type, str(count), f"{percentage:.1f}%"])
            table = Table(data, colWidths=[2*inch, 1.5*inch, 1*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            tables.append(("Ticket Sales Breakdown", table))
        if report_data.get('revenue_by_ticket_type'):
            data = [['Ticket Type', 'Revenue', 'Percentage']]
            total_revenue = sum(float(v) for v in report_data['revenue_by_ticket_type'].values())
            for ticket_type, revenue in report_data['revenue_by_ticket_type'].items():
                revenue_float = float(revenue)
                percentage = (revenue_float / total_revenue * 100) if total_revenue > 0 else 0
                data.append([ticket_type, f"{currency_symbol}{revenue_float:.2f}", f"{percentage:.1f}%"])
            table = Table(data, colWidths=[2*inch, 1.5*inch, 1*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            tables.append(("Revenue Breakdown", table))
        return tables

    def generate_pdf(self, report_data: Dict[str, Any], chart_paths: List[str], output_path: str) -> Optional[str]:
        """Generate comprehensive PDF report"""
        try:
            doc = SimpleDocTemplate(
                output_path, pagesize=self.config.pdf_pagesize,
                rightMargin=72, leftMargin=72,
                topMargin=72, bottomMargin=18
            )
            story = []
            story.append(Paragraph("EVENT ANALYTICS REPORT", self.title_style))
            story.append(Spacer(1, 20))
            event_info = f"""
            <para fontSize=14>
            <b>Event:</b> {report_data.get('event_name', 'N/A')}<br/>
            <b>Date:</b> {report_data.get('event_date', 'N/A')}<br/>
            <b>Location:</b> {report_data.get('event_location', 'N/A')}<br/>
            <b>Report Period:</b> {report_data.get('filter_start_date', 'N/A')} to {report_data.get('filter_end_date', 'N/A')}<br/>
            <b>Currency:</b> {report_data.get('currency', 'USD')} ({report_data.get('currency_symbol', '$')})<br/>
            <b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </para>
            """
            story.append(Paragraph(event_info, self.styles['Normal']))
            story.append(Spacer(1, 30))
            story.append(Paragraph("EXECUTIVE SUMMARY", self.subtitle_style))
            story.append(self._create_summary_table(report_data))
            story.append(Spacer(1, 30))
            insights = self._generate_insights(report_data)
            if insights:
                story.append(Paragraph("KEY INSIGHTS", self.header_style))
                for insight in insights:
                    story.append(Paragraph(insight, self.styles['Normal']))
                story.append(Spacer(1, 20))
            story.append(PageBreak())
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
            story.append(Paragraph("DETAILED BREAKDOWN", self.subtitle_style))
            tables = self._create_breakdown_tables(report_data)
            for table_title, table in tables:
                story.append(Paragraph(table_title, self.header_style))
                story.append(table)
                story.append(Spacer(1, 20))
            footer_text = """
            <para alignment="center" fontSize=10 textColor="grey">
            This report was automatically generated by the Event Management System<br/>
            For questions or support, please contact your system administrator
            </para>
            """
            story.append(Spacer(1, 50))
            story.append(Paragraph(footer_text, self.styles['Normal']))
            doc.build(story)
            return output_path
        except Exception as e:
            logger.error(f"Error generating PDF report: {e}")
            return None

class FileManager:
    """Handles file operations for reports"""
    @staticmethod
    def generate_unique_paths(event_id: int) -> Tuple[str, str]:
        """Generate unique file paths for graph and PDF"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pdf_path = tempfile.mktemp(suffix=f'_event_{event_id}_{timestamp}.pdf')
        csv_path = tempfile.mktemp(suffix=f'_event_{event_id}_{timestamp}.csv')
        return pdf_path, csv_path

    @staticmethod
    def cleanup_files(file_paths: List[str]):
        """Clean up temporary files"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.warning(f"Failed to remove file {file_path}: {e}")

class CSVReportGenerator:
    """Handles CSV report generation"""
    @staticmethod
    def generate_csv(report_data: Dict[str, Any], output_path: str) -> Optional[str]:
        """Generate CSV report with detailed data"""
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Event Analytics Report'])
                writer.writerow(['Event Name', report_data.get('event_name', 'N/A')])
                writer.writerow(['Report Date', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
                writer.writerow(['Currency', f"{report_data.get('currency', 'USD')} ({report_data.get('currency_symbol', '$')})"])
                writer.writerow([])
                writer.writerow(['SUMMARY'])
                writer.writerow(['Metric', 'Value'])
                writer.writerow(['Total Tickets Sold', report_data.get('total_tickets_sold', 0)])
                writer.writerow(['Total Revenue', f"{report_data.get('currency_symbol', '$')}{report_data.get('total_revenue', 0):.2f}"])
                writer.writerow(['Number of Attendees', report_data.get('number_of_attendees', 0)])
                attendance_rate = 0
                if report_data.get('total_tickets_sold', 0) > 0:
                    attendance_rate = (report_data.get('number_of_attendees', 0) /
                                     report_data.get('total_tickets_sold', 1) * 100)
                writer.writerow(['Attendance Rate (%)', f"{attendance_rate:.1f}"])
                writer.writerow([])
                if report_data.get('tickets_sold_by_type'):
                    writer.writerow(['TICKETS SOLD BY TYPE'])
                    writer.writerow(['Ticket Type', 'Tickets Sold', 'Percentage'])
                    total_tickets = sum(report_data['tickets_sold_by_type'].values())
                    for ticket_type, count in report_data['tickets_sold_by_type'].items():
                        percentage = (count / total_tickets * 100) if total_tickets > 0 else 0
                        writer.writerow([ticket_type, count, f"{percentage:.1f}%"])
                    writer.writerow([])
                if report_data.get('revenue_by_ticket_type'):
                    writer.writerow(['REVENUE BY TICKET TYPE'])
                    writer.writerow(['Ticket Type', 'Revenue', 'Percentage'])
                    total_revenue = sum(float(v) for v in report_data['revenue_by_ticket_type'].values())
                    for ticket_type, revenue in report_data['revenue_by_ticket_type'].items():
                        revenue_float = float(revenue)
                        percentage = (revenue_float / total_revenue * 100) if total_revenue > 0 else 0
                        writer.writerow([ticket_type, f"{report_data.get('currency_symbol', '$')}{revenue_float:.2f}", f"{percentage:.1f}%"])
                    writer.writerow([])
                if report_data.get('payment_method_usage'):
                    writer.writerow(['PAYMENT METHOD USAGE'])
                    writer.writerow(['Payment Method', 'Transactions'])
                    for method, count in report_data['payment_method_usage'].items():
                        writer.writerow([method, count])
                    writer.writerow([])
                if report_data.get('attendees_by_ticket_type'):
                    writer.writerow(['ATTENDANCE BY TICKET TYPE'])
                    writer.writerow(['Ticket Type', 'Attendees'])
                    for ticket_type, attendees in report_data['attendees_by_ticket_type'].items():
                        writer.writerow([ticket_type, attendees])
            return output_path
        except Exception as e:
            logger.error(f"Error generating CSV report: {e}")
            return None

class ReportService:
    """Main service for report generation and management"""
    def __init__(self, config: ReportConfig = None):
        self.config = config or ReportConfig()
        self.chart_generator = ChartGenerator(self.config) if self.config.include_charts else None
        self.pdf_generator = PDFReportGenerator(self.config)
        self.db_service = DatabaseQueryService()
        self.currency_converter = CurrencyConverter()

    def create_report_data(self, event_id: int, start_date: datetime, end_date: datetime,
                          ticket_type_id: Optional[int] = None,
                          target_currency_id: Optional[int] = None) -> Dict[str, Any]:
        """Create comprehensive report data"""
        try:
            event = Event.query.get(event_id)
            if not event:
                raise ValueError(f"Event with ID {event_id} not found")
            base_currency_id = self.db_service.get_event_base_currency(event_id)
            display_currency_id = target_currency_id or base_currency_id
            base_currency_info = self.currency_converter.get_currency_info(base_currency_id)
            display_currency_info = self.currency_converter.get_currency_info(display_currency_id)
            tickets_sold_data = self.db_service.get_tickets_sold_by_type(event_id, start_date, end_date)
            revenue_data = self.db_service.get_revenue_by_type(event_id, start_date, end_date)
            attendees_data = self.db_service.get_attendees_by_type(event_id, start_date, end_date)
            payment_methods = self.db_service.get_payment_method_usage(event_id, start_date, end_date)
            tickets_sold_by_type = dict(tickets_sold_data)
            revenue_by_ticket_type = {}
            attendees_by_ticket_type = dict(attendees_data)
            payment_method_usage = dict(payment_methods)
            total_revenue_base = self.db_service.get_total_revenue(event_id, start_date, end_date)
            total_revenue_display = self.currency_converter.convert_amount(
                total_revenue_base, base_currency_id, display_currency_id
            )
            for ticket_type, revenue in revenue_data:
                converted_revenue = self.currency_converter.convert_amount(
                    revenue, base_currency_id, display_currency_id
                )
                revenue_by_ticket_type[ticket_type] = converted_revenue
            total_tickets_sold = self.db_service.get_total_tickets_sold(event_id, start_date, end_date)
            total_attendees = self.db_service.get_total_attendees(event_id, start_date, end_date)
            report_data = {
                'event_id': event_id,
                'event_name': event.name,
                'event_date': event.event_date.isoformat() if hasattr(event, 'event_date') and event.event_date else 'N/A',
                'event_location': getattr(event, 'location', 'N/A'),
                'filter_start_date': start_date.strftime('%Y-%m-%d'),
                'filter_end_date': end_date.strftime('%Y-%m-%d'),
                'total_tickets_sold': total_tickets_sold,
                'total_revenue': float(total_revenue_display),
                'number_of_attendees': total_attendees,
                'tickets_sold_by_type': tickets_sold_by_type,
                'revenue_by_ticket_type': {k: float(v) for k, v in revenue_by_ticket_type.items()},
                'attendees_by_ticket_type': attendees_by_ticket_type,
                'payment_method_usage': payment_method_usage,
                'currency': display_currency_info['code'],
                'currency_symbol': display_currency_info['symbol'],
                'base_currency': base_currency_info['code'],
                'base_currency_symbol': base_currency_info['symbol'],
            }
            if base_currency_id != display_currency_id:
                report_data['original_revenue'] = float(total_revenue_base)
                report_data['original_currency'] = base_currency_info['code']
            if ticket_type_id:
                ticket_type = TicketType.query.get(ticket_type_id)
                if ticket_type:
                    report_data['ticket_type_id'] = ticket_type_id
                    report_data['ticket_type_name'] = ticket_type.type_name.value if ticket_type.type_name else 'N/A'
                    report_data['report_scope'] = 'ticket_type_summary'
                else:
                    report_data['report_scope'] = 'event_summary'
            else:
                report_data['report_scope'] = 'event_summary'
            return report_data
        except Exception as e:
            logger.error(f"Error creating report data: {e}")
            raise

    def save_report_to_database(self, report_data: Dict[str, Any], organizer_id: int) -> Optional[Report]:
        """Save report to database using the Report model"""
        try:
            base_currency = Currency.query.filter_by(code=report_data.get('base_currency', 'USD')).first()
            base_currency_id = base_currency.id if base_currency else 1
            report = Report(
                organizer_id=organizer_id,
                event_id=report_data['event_id'],
                ticket_type_id=report_data.get('ticket_type_id'),
                base_currency_id=base_currency_id,
                report_scope=report_data.get('report_scope', 'event_summary'),
                total_tickets_sold=report_data.get('total_tickets_sold', 0),
                total_revenue=Decimal(str(report_data.get('total_revenue', 0))),
                number_of_attendees=report_data.get('number_of_attendees', 0),
                report_data=report_data,
                report_date=datetime.now().date()
            )
            db.session.add(report)
            db.session.commit()
            logger.info(f"Report saved to database with ID: {report.id}")
            return report
        except Exception as e:
            logger.error(f"Error saving report to database: {e}")
            db.session.rollback()
            return None

    def generate_complete_report(self, event_id: int, organizer_id: int, start_date: datetime,
                              end_date: datetime, ticket_type_id: Optional[int] = None,
                              target_currency_id: Optional[int] = None,
                              send_email: bool = False, recipient_email: str = None) -> Dict[str, Any]:
        """Generate complete report with PDF, CSV, charts and optional email"""
        chart_paths = []
        pdf_path = None
        csv_path = None
        try:
            report_data = self.create_report_data(event_id, start_date, end_date, ticket_type_id, target_currency_id)
            saved_report = self.save_report_to_database(report_data, organizer_id)
            if saved_report:
                report_data['database_id'] = saved_report.id
            pdf_path, csv_path = FileManager.generate_unique_paths(event_id)
            if self.config.include_charts and self.chart_generator:
                chart_paths = self.chart_generator.create_all_charts(report_data)
            pdf_path = self.pdf_generator.generate_pdf(report_data, chart_paths, pdf_path)
            csv_path = CSVReportGenerator.generate_csv(report_data, csv_path)
            email_sent = False
            if send_email and recipient_email and self.config.include_email:
                email_sent = self._send_report_email(
                    report_data, pdf_path, csv_path, recipient_email
                )
            return {
                'success': True,
                'report_data': report_data,
                'pdf_path': pdf_path,
                'csv_path': csv_path,
                'chart_paths': chart_paths,
                'email_sent': email_sent,
                'database_id': report_data.get('database_id')
            }
        except Exception as e:
            logger.error(f"Error generating complete report: {e}")
            return {
                'success': False,
                'error': str(e),
                'report_data': None,
                'pdf_path': None,
                'csv_path': None,
                'chart_paths': [],
                'email_sent': False
            }
        finally:
            if chart_paths:
                FileManager.cleanup_files(chart_paths)

    def _send_report_email(self, report_data: Dict[str, Any], pdf_path: str,
                          csv_path: str, recipient_email: str) -> bool:
        """Send report via email with enhanced formatting"""
        try:
            event_name = report_data.get('event_name', 'Unknown Event')
            currency_symbol = report_data.get('currency_symbol', '$')
            subject = f"Event Analytics Report - {event_name}"
            body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .header {{ background: linear-gradient(135deg, #2E86AB, #A23B72); color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 30px; background: #f9f9f9; }}
                    .summary-box {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .metric {{ display: inline-block; margin: 10px 20px; text-align: center; }}
                    .metric-value {{ font-size: 24px; font-weight: bold; color: #2E86AB; }}
                    .metric-label {{ font-size: 14px; color: #666; }}
                    .insights {{ background: #e8f4fd; padding: 15px; border-left: 4px solid #2E86AB; margin: 20px 0; }}
                    .footer {{ background: #333; color: white; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 8px 8px; }}
                    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                    th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
                    th {{ background-color: #2E86AB; color: white; }}
                    .attachment-note {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 4px; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📊 Event Report</h1>
                    <h2>{event_name}</h2>
                    <p>Report Period: {report_data.get('filter_start_date', 'N/A')} to {report_data.get('filter_end_date', 'N/A')}</p>
                </div>
                <div class="content">
                    <div class="summary-box">
                        <h3>📈 Executive Summary</h3>
                        <div class="metric">
                            <div class="metric-value">{report_data.get('total_tickets_sold', 0)}</div>
                            <div class="metric-label">Tickets Sold</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{currency_symbol}{report_data.get('total_revenue', 0):,.2f}</div>
                            <div class="metric-label">Total Revenue</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{report_data.get('number_of_attendees', 0)}</div>
                            <div class="metric-label">Attendees</div>
                        </div>
            """
            if report_data.get('total_tickets_sold', 0) > 0:
                attendance_rate = (report_data.get('number_of_attendees', 0) /
                                 report_data.get('total_tickets_sold', 1) * 100)
                body += f"""
                        <div class="metric">
                            <div class="metric-value">{attendance_rate:.1f}%</div>
                            <div class="metric-label">Attendance Rate</div>
                        </div>
                """
            body += """
                    </div>
            """
            if report_data.get('tickets_sold_by_type'):
                body += """
                    <div class="summary-box">
                        <h3>🎫 Ticket Sales Breakdown</h3>
                        <table>
                            <tr><th>Ticket Type</th><th>Quantity</th><th>Revenue</th></tr>
                """
                for ticket_type in report_data['tickets_sold_by_type'].keys():
                    quantity = report_data['tickets_sold_by_type'].get(ticket_type, 0)
                    revenue = report_data.get('revenue_by_ticket_type', {}).get(ticket_type, 0)
                    body += f"<tr><td>{ticket_type}</td><td>{quantity}</td><td>{currency_symbol}{revenue:,.2f}</td></tr>"
                body += """
                        </table>
                    </div>
                """
            body += f"""
                    <div class="insights">
                        <h3>💡 Key Insights</h3>
                        <ul>
            """
            if report_data.get('total_tickets_sold', 0) > 0:
                attendance_rate = (report_data.get('number_of_attendees', 0) /
                                 report_data.get('total_tickets_sold', 1) * 100)
                if attendance_rate > 90:
                    body += "<li>Excellent attendance rate! Most ticket holders attended the event.</li>"
                elif attendance_rate > 70:
                    body += "<li>Good attendance rate with room for improvement in no-show reduction.</li>"
                else:
                    body += "<li>Low attendance rate suggests potential areas for improvement.</li>"
            if report_data.get('revenue_by_ticket_type'):
                max_revenue_type = max(report_data['revenue_by_ticket_type'].items(), key=lambda x: x[1])[0]
                body += f"<li>{max_revenue_type} tickets generated the highest revenue for this event.</li>"
            body += """
                        </ul>
                    </div>
                    <div class="attachment-note">
                        <h3>📎 Attachments</h3>
                        <p><strong>Detailed PDF Report:</strong> Complete analytics with charts and visualizations</p>
                        <p><strong>CSV Data Export:</strong> Raw data for further analysis and processing</p>
                    </div>
                </div>
                <div class="footer">
                    <p>This report was automatically generated by the Event Management System</p>
                    <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            </body>
            </html>
            """
            attachments = []
            if pdf_path and os.path.exists(pdf_path):
                attachments.append({
                    'filename': f'event_report_{event_name.replace(" ", "_")}.pdf',
                    'content': open(pdf_path, 'rb').read(),
                    'content_type': 'application/pdf'
                })
            if csv_path and os.path.exists(csv_path):
                attachments.append({
                    'filename': f'event_data_{event_name.replace(" ", "_")}.csv',
                    'content': open(csv_path, 'rb').read(),
                    'content_type': 'text/csv'
                })
            success = send_email_with_attachment(
                recipient=recipient_email,
                subject=subject,
                body=body,
                attachments=attachments,
                is_html=True
            )
            return success
        except Exception as e:
            logger.error(f"Error sending report email: {e}")
            return False

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

class GenerateReportResource(Resource, AuthorizationMixin):
    """API endpoint for generating comprehensive reports"""
    @jwt_required()
    def post(self):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                return {'error': 'User not found'}, 404

            data = request.get_json()
            event_id = data.get('event_id')
            start_date_str = data.get('start_date')
            end_date_str = data.get('end_date')
            ticket_type_id = data.get('ticket_type_id')
            target_currency_id = data.get('target_currency_id')
            send_email = data.get('send_email', False)
            recipient_email = data.get('recipient_email', current_user.email)

            if not event_id:
                return {'error': 'Event ID is required'}, 400

            event = Event.query.get(event_id)
            if not event:
                return {'error': 'Event not found'}, 404

            # Check if the user is authorized to generate the report for this event
            organizer = Organizer.query.filter_by(user_id=current_user_id).first()
            if not organizer or organizer.id != event.organizer_id:
                if not current_user.role == UserRole.ADMIN:
                    return {'error': 'Unauthorized to generate report for this event'}, 403

            start_date = DateUtils.parse_date_param(start_date_str, 'start_date') if start_date_str else None
            end_date = DateUtils.parse_date_param(end_date_str, 'end_date') if end_date_str else None

            if not start_date:
                start_date = event.timestamp if hasattr(event, 'timestamp') else datetime.now() - timedelta(days=30)
            if not end_date:
                end_date = datetime.now()

            end_date = DateUtils.adjust_end_date(end_date)

            # 1. Get the target currency from the DB
            target_currency = Currency.query.get(target_currency_id) if target_currency_id else None
            if not target_currency:
                return {'error': 'Target currency not found or invalid'}, 400
            target_currency_code = target_currency.code.value  # e.g. 'KES'

            config = ReportConfig(
                include_charts=True,
                include_email=send_email,
                chart_dpi=300,
                chart_style='seaborn-v0_8'
            )

            report_service = ReportService(config)
            result = report_service.generate_complete_report(
                event_id=event_id,
                organizer_id=current_user_id,
                start_date=start_date,
                end_date=end_date,
                ticket_type_id=ticket_type_id,
                send_email=send_email,
                recipient_email=recipient_email
            )

            if result['success']:
                response_data = {
                    'message': 'Report generated successfully',
                    'report_id': result.get('database_id'),
                    'report_data': result['report_data'],
                    'email_sent': result['email_sent']
                }

                # 2. After generating the report, get the total_revenue and base_currency
                total_revenue = result['report_data'].get('total_revenue')
                base_currency = result['report_data'].get('currency', 'USD')  # Example: 'USD'

                # 3. Call convert_currency() with the total revenue
                from currency_routes import convert_currency  # if it's not already imported
                converted_value, conversion_rate = convert_currency(
                    amount=total_revenue,
                    from_currency=base_currency,
                    to_currency=target_currency_code
                )

                # 4. Include conversion in your response
                response_data['currency_conversion'] = {
                    'original_amount': float(total_revenue),
                    'original_currency': base_currency,
                    'converted_amount': float(converted_value),
                    'converted_currency': target_currency_code,
                    'conversion_rate': float(conversion_rate)
                }

                if result.get('pdf_path'):
                    response_data['pdf_available'] = True
                if result.get('csv_path'):
                    response_data['csv_available'] = True

                return response_data, 200
            else:
                return {'error': result.get('error', 'Failed to generate report')}, 500

        except Exception as e:
            logger.error(f"Error in GenerateReportResource: {e}")
            return {'error': 'Internal server error'}, 500

class GetReportsResource(Resource, AuthorizationMixin):
    """API endpoint for retrieving saved reports"""
    @jwt_required()
    def get(self):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                return {'error': 'User not found'}, 404
            event_id = request.args.get('event_id', type=int)
            scope = request.args.get('scope')
            limit = request.args.get('limit', 10, type=int)
            offset = request.args.get('offset', 0, type=int)
            target_currency_id = request.args.get('target_currency_id', type=int)
            query = Report.query.filter_by(organizer_id=current_user_id)
            if event_id:
                query = query.filter_by(event_id=event_id)
            if scope:
                query = query.filter_by(report_scope=scope)
            query = query.order_by(Report.timestamp.desc())
            total_count = query.count()
            reports = query.offset(offset).limit(limit).all()
            reports_data = []
            for report in reports:
                report_dict = report.as_dict(target_currency_id=target_currency_id)
                reports_data.append(report_dict)
            return {
                'reports': reports_data,
                'total_count': total_count,
                'limit': limit,
                'offset': offset
            }, 200
        except Exception as e:
            logger.error(f"Error in GetReportsResource: {e}")
            return {'error': 'Internal server error'}, 500

class GetReportResource(Resource, AuthorizationMixin):
    """API endpoint for retrieving a specific report"""
    @jwt_required()
    def get(self, report_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                return {'error': 'User not found'}, 404
            report = Report.query.get(report_id)
            if not report:
                return {'error': 'Report not found'}, 404
            if not (report.organizer_id == current_user_id or current_user.role == UserRole.ADMIN):
                return {'error': 'Unauthorized to access this report'}, 403
            target_currency_id = request.args.get('target_currency_id', type=int)
            return {
                'report': report.as_dict(target_currency_id=target_currency_id)
            }, 200
        except Exception as e:
            logger.error(f"Error in GetReportResource: {e}")
            return {'error': 'Internal server error'}, 500

class ExportReportResource(Resource):
    """API endpoint for exporting reports as PDF or CSV"""
    @jwt_required()
    def get(self, report_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"User {current_user_id} not found")
                return {'error': 'User not found'}, 404
            report = Report.query.get(report_id)
            if not report:
                logger.warning(f"Report {report_id} not found")
                return {'error': 'Report not found'}, 404
            # Debug logging to check the relationship
            logger.info(f"Report organizer_id: {report.organizer_id}, Current user_id: {current_user_id}")
            logger.info(f"User role: {current_user.role.value if current_user.role else 'No role'}")
            # Check if user is the organizer of the report OR is an admin
            # Also check if user is an organizer through the Organizer table
            is_authorized = False
            # Direct check: user is the organizer
            if report.organizer_id == current_user_id:
                is_authorized = True
                logger.info(f"User {current_user_id} is the direct organizer of report {report_id}")
            # Check if user is admin
            elif hasattr(current_user, 'role') and current_user.role and current_user.role.value.upper() == 'ADMIN':
                is_authorized = True
                logger.info(f"User {current_user_id} is admin, allowing access to report {report_id}")
            # Check if user is an organizer and owns the event associated with the report
            elif hasattr(current_user, 'organizer_profile') and current_user.organizer_profile:
                # If the report is associated with an event, check if the user's organizer profile owns that event
                if hasattr(report, 'event') and report.event:
                    if report.event.organizer_id == current_user.organizer_profile.id:
                        is_authorized = True
                        logger.info(f"User {current_user_id} owns the event associated with report {report_id}")
            if not is_authorized:
                logger.warning(f"User {current_user_id} not authorized to access report {report_id}")
                return {'error': 'Unauthorized to export this report'}, 403
            # Get format and target currency from query parameters
            format_type = request.args.get('format', 'pdf').lower()
            target_currency_id = request.args.get('target_currency_id', type=int)
            # Generate the file path based on the format
            if format_type == 'pdf':
                file_path = self._generate_pdf_report(report, target_currency_id)
                mime_type = 'application/pdf'
                filename = f"report_{report.id}.pdf"
            elif format_type == 'csv':
                file_path = self._generate_csv_report(report, target_currency_id)
                mime_type = 'text/csv'
                filename = f"report_{report.id}.csv"
            else:
                return {'error': 'Unsupported format. Use "pdf" or "csv".'}, 400
            if not file_path or not os.path.exists(file_path):
                logger.error(f"Failed to generate or find report file: {file_path}")
                return {'error': 'Failed to generate report file'}, 500
            logger.info(f"Successfully generated report file: {file_path}")
            return send_file(
                file_path,
                mimetype=mime_type,
                as_attachment=True,
                download_name=filename
            )
        except Exception as e:
            logger.error(f"Error in ExportReportResource: {str(e)}", exc_info=True)
            return {'error': 'Internal server error'}, 500

    def _generate_pdf_report(self, report, target_currency_id):
        """Generate a PDF report file and return the file path"""
        try:
            # Create a temporary file for the PDF
            temp_dir = tempfile.gettempdir()
            pdf_path = os.path.join(temp_dir, f"report_{report.id}.pdf")
            # TODO: Implement your PDF generation logic here
            # For now, create a simple placeholder file
            with open(pdf_path, 'w') as f:
                f.write("PDF Report Content - Replace with actual PDF generation")
            logger.info(f"PDF report generated at: {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"Error generating PDF report: {str(e)}", exc_info=True)
            return None

    def _generate_csv_report(self, report, target_currency_id):
        """Generate a CSV report file and return the file path"""
        try:
            # Create a temporary file for the CSV
            temp_dir = tempfile.gettempdir()
            csv_path = os.path.join(temp_dir, f"report_{report.id}.csv")
            # TODO: Implement your CSV generation logic here
            # For now, create a simple placeholder file
            with open(csv_path, 'w') as f:
                f.write("CSV Report Content - Replace with actual CSV generation")
            logger.info(f"CSV report generated at: {csv_path}")
            return csv_path
        except Exception as e:
            logger.error(f"Error generating CSV report: {str(e)}", exc_info=True)
            return None

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

class EventReportsResource(Resource):
    """API endpoint for retrieving reports for a specific event"""
    @jwt_required()
    def get(self, event_id):
        try:
            current_user_id = get_jwt_identity()
            current_user = User.query.get(current_user_id)
            if not current_user:
                logger.warning(f"User {current_user_id} not found")
                return {'error': 'User not found'}, 404
            # Get and validate date params
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            start_date, end_date, error = DateValidator.validate_date_range(start_date_str, end_date_str)
            if error:
                logger.warning(f"Invalid date range: {error}")
                return error, error.get('status', 400)
            # Ensure event exists
            event = Event.query.get(event_id)
            if not event:
                logger.warning(f"Event {event_id} not found")
                return {'error': 'Event not found'}, 404
            # Verify access rights
            if not AuthorizationMixin.check_event_ownership(event, current_user):
                logger.warning(f"User {current_user_id} not authorized for event {event_id}")
                return {'error': 'Unauthorized to access reports for this event'}, 403
            # Fetch reports for event and date range
            query = Report.query.filter_by(event_id=event_id)
            if start_date and end_date:
                query = query.filter(Report.report_date.between(start_date, end_date))
            reports = query.all()
            logger.info(f"Found {len(reports)} reports for event {event_id} from {start_date} to {end_date}")
            # Return empty list instead of error if no reports
            reports_data = [
                {
                    'report_id': r.id,
                    'event_id': r.event_id,
                    'total_tickets_sold': r.total_tickets_sold,
                    'total_revenue': float(r.total_revenue),
                    'number_of_attendees': r.number_of_attendees,
                    'report_date': r.report_date.isoformat()
                }
                for r in reports
            ]
            return {
                'event_id': event_id,
                'reports': reports_data
            }, 200
        except Exception as e:
            logger.exception(f"Error fetching event reports for event {event_id}: {e}")
            return {'error': 'Internal server error'}, 500

class ReportResourceRegistry:
    """Registry for report-related API resources"""
    @staticmethod
    def register_organizer_report_resources(api):
        """Register all report resources with the API"""
        api.add_resource(GenerateReportResource, '/reports/generate')
        api.add_resource(GetReportsResource, '/reports')
        api.add_resource(GetReportResource, '/reports/<int:report_id>')
        api.add_resource(ExportReportResource, '/reports/<int:report_id>/export')
        api.add_resource(OrganizerSummaryReportResource, '/reports/organizer/summary')
        api.add_resource(EventReportsResource, '/reports/events/<int:event_id>')
