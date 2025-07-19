import matplotlib
matplotlib.use('Agg')
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
import matplotlib.pyplot as plt
import pandas as pd
import os
from datetime import datetime
import csv
from decimal import Decimal
from io import StringIO, BytesIO
import tempfile
from typing import Dict, List, Optional, Tuple, Any, Union
from model import Ticket, Transaction, Scan, PaymentStatus, Currency, CurrencyCode,Event
from contextlib import contextmanager
from .config import ReportConfig
import logging
import time
from sqlalchemy.orm import Session
from sqlalchemy import func

# Import currency conversion functions from the currency module
from currency_routes import convert_ksh_to_target_currency, get_exchange_rate

# Optional: Import psutil for memory logging
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not found. Memory usage logging will be skipped.")

logger = logging.getLogger(__name__)

class ReportDataProcessor:
    @staticmethod
    def convert_enum_keys_to_strings(data: Dict[Any, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return data
        converted = {}
        for key, value in data.items():
            if hasattr(key, 'value'):
                string_key = key.value
            else:
                string_key = str(key)
            if isinstance(value, dict):
                converted[string_key] = ReportDataProcessor.convert_enum_keys_to_strings(value)
            elif isinstance(value, list):
                converted[string_key] = [
                    ReportDataProcessor.convert_enum_keys_to_strings(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                converted[string_key] = value
        return converted

    @staticmethod
    def _ensure_numeric_types(data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return data
        processed_data = data.copy()
        numeric_fields = [
            'total_tickets_sold',
            'number_of_attendees',
            'total_revenue',
            'converted_revenue',
        ]
        for field in numeric_fields:
            if field in processed_data and processed_data[field] is not None:
                try:
                    if field in ['total_revenue', 'converted_revenue']:
                        processed_data[field] = float(processed_data[field])
                    else:
                        processed_data[field] = int(processed_data[field])
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not convert field '{field}' to numeric type. Value: '{processed_data[field]}', Error: {e}")
                    processed_data[field] = 0.0 if field in ['total_revenue', 'converted_revenue'] else 0
        nested_numeric_fields = [
            'tickets_sold_by_type',
            'revenue_by_ticket_type',
            'attendees_by_ticket_type',
            'payment_method_usage',
            'daily_revenue'
        ]
        for field in nested_numeric_fields:
            if field in processed_data and isinstance(processed_data[field], dict):
                converted_nested_data = {}
                for key, value in processed_data[field].items():
                    try:
                        converted_nested_data[key] = float(value) if isinstance(value, (int, float, str, Decimal)) else value
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Could not convert nested field '{field}' key '{key}' to numeric. Value: '{value}', Error: {e}")
                        converted_nested_data[key] = 0.0
                processed_data[field] = converted_nested_data
            elif field in processed_data and isinstance(processed_data[field], list):
                processed_list = []
                for item in processed_data[field]:
                    if isinstance(item, dict):
                        processed_list.append(ReportDataProcessor._ensure_numeric_types(item))
                    else:
                        processed_list.append(item)
                processed_data[field] = processed_list
        return processed_data

    @staticmethod
    def process_report_data(report_data: Dict[str, Any], session: Session, event_id: int, target_currency: str = "KES") -> Dict[str, Any]:
        """
        Enhanced process_report_data with currency conversion support
        """
        processed_data = ReportDataProcessor.convert_enum_keys_to_strings(report_data)
        processed_data = ReportDataProcessor._ensure_numeric_types(processed_data)

        # Calculate total_ticket_sold and attendees
        processed_data['total_tickets_sold'] = ReportDataProcessor.calculate_total_tickets_sold(session, event_id)
        processed_data['number_of_attendees'] = ReportDataProcessor.calculate_attendees(session, event_id)

        # Add currency conversion if needed
        if target_currency and target_currency != "KES":
            processed_data = ReportDataProcessor.convert_report_currency(processed_data, target_currency, session)
        else:
            # Ensure currency info is set for KES
            processed_data['original_currency'] = "KES"
            processed_data['currency'] = "KES"
            processed_data['currency_symbol'] = "KSh"

        return processed_data

    @staticmethod
    def convert_report_currency(report_data: Dict[str, Any], target_currency: str, session: Session) -> Dict[str, Any]:
        """
        Convert all monetary values in report from KES to target currency
        """
        try:
            # Get target currency info from database
            currency_obj = session.query(Currency).filter_by(
                code=CurrencyCode(target_currency), 
                is_active=True
            ).first()
            
            if not currency_obj:
                logger.warning(f"Target currency {target_currency} not found in database. Keeping original KES values.")
                return report_data
            
            # Store original currency info
            report_data['original_currency'] = "KES"
            report_data['currency'] = target_currency
            report_data['currency_symbol'] = currency_obj.symbol
            
            # Convert total revenue
            if 'total_revenue' in report_data and report_data['total_revenue']:
                try:
                    ksh_amount = Decimal(str(report_data['total_revenue']))
                    converted_amount, ksh_to_usd_rate, usd_to_target_rate = convert_ksh_to_target_currency(
                        ksh_amount, target_currency
                    )
                    report_data['converted_revenue'] = float(converted_amount)
                    report_data['total_revenue'] = float(converted_amount)  # Update main revenue field
                    
                    # Store conversion rates for transparency
                    report_data['conversion_rates'] = {
                        'ksh_to_usd': float(ksh_to_usd_rate),
                        'usd_to_target': float(usd_to_target_rate),
                        'overall_rate': float(ksh_to_usd_rate * usd_to_target_rate)
                    }
                    
                    logger.info(f"Converted total revenue from KES {ksh_amount} to {target_currency} {converted_amount}")
                    
                except Exception as e:
                    logger.error(f"Error converting total revenue to {target_currency}: {e}")
                    # Keep original values if conversion fails
                    report_data['conversion_error'] = str(e)
            
            # Convert revenue by ticket type
            if 'revenue_by_ticket_type' in report_data and report_data['revenue_by_ticket_type']:
                converted_revenue_by_type = {}
                for ticket_type, ksh_revenue in report_data['revenue_by_ticket_type'].items():
                    try:
                        ksh_amount = Decimal(str(ksh_revenue))
                        converted_amount, _, _ = convert_ksh_to_target_currency(ksh_amount, target_currency)
                        converted_revenue_by_type[ticket_type] = float(converted_amount)
                    except Exception as e:
                        logger.warning(f"Error converting revenue for ticket type {ticket_type}: {e}")
                        converted_revenue_by_type[ticket_type] = float(ksh_revenue)  # Keep original
                
                report_data['revenue_by_ticket_type'] = converted_revenue_by_type
            
            # Convert daily revenue if present
            if 'daily_revenue' in report_data and report_data['daily_revenue']:
                converted_daily_revenue = {}
                for date_str, daily_data in report_data['daily_revenue'].items():
                    if isinstance(daily_data, dict) and 'revenue' in daily_data:
                        try:
                            ksh_amount = Decimal(str(daily_data['revenue']))
                            converted_amount, _, _ = convert_ksh_to_target_currency(ksh_amount, target_currency)
                            converted_daily_revenue[date_str] = {
                                **daily_data,
                                'revenue': float(converted_amount)
                            }
                        except Exception as e:
                            logger.warning(f"Error converting daily revenue for {date_str}: {e}")
                            converted_daily_revenue[date_str] = daily_data  # Keep original
                    else:
                        converted_daily_revenue[date_str] = daily_data
                
                report_data['daily_revenue'] = converted_daily_revenue
            
            logger.info(f"Successfully converted report data to {target_currency}")
            
        except Exception as e:
            logger.error(f"Error in currency conversion process: {e}")
            # Add error info but don't fail the report
            report_data['conversion_error'] = str(e)
            report_data['currency'] = "KES"  # Fallback to original
            report_data['currency_symbol'] = "KSh"
        
        return report_data

    @staticmethod
    def calculate_total_tickets_sold(session: Session, event_id: int) -> int:
        total_tickets_sold = session.query(func.sum(Ticket.quantity)).join(Transaction).filter(
            Ticket.event_id == event_id,
            Transaction.payment_status == PaymentStatus.PAID
        ).scalar()
        return total_tickets_sold if total_tickets_sold is not None else 0

    @staticmethod
    def calculate_attendees(session: Session, event_id: int) -> int:
        attendees = session.query(Ticket).join(Scan).filter(
            Ticket.event_id == event_id,
            Ticket.scanned == True
        ).count()
        return attendees

class PDFReportGenerator:
    def __init__(self, config: ReportConfig):
        self.config = config
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
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
        self.normal_style = ParagraphStyle(
            'CustomNormal',
            parent=self.styles['Normal'],
            fontSize=10,
            leading=14,
            spaceAfter=6,
        )

    def _get_pagesize(self) -> Tuple[float, float]:
        try:
            if hasattr(self.config, 'pdf_pagesize'):
                pagesize = self.config.pdf_pagesize
                if isinstance(pagesize, tuple) and len(pagesize) == 2:
                    return pagesize
                elif isinstance(pagesize, str):
                    pagesize_lower = pagesize.lower()
                    if pagesize_lower in ['letter', 'us_letter']:
                        return letter
                    elif pagesize_lower in ['a4']:
                        return A4
                    else:
                        logger.warning(f"Unknown pagesize string '{pagesize}'. Using default letter size.")
                        return letter
                else:
                    logger.warning(f"Invalid pagesize type '{type(pagesize)}'. Using default letter size.")
                    return letter
            else:
                return letter
        except Exception as e:
            logger.warning(f"Error processing pagesize config: {e}. Using default letter size.")
            return letter

    def _create_summary_table(self, report_data: Dict[str, Any]) -> Table:
        total_tickets_sold = report_data.get('total_tickets_sold', 0)
        number_of_attendees = report_data.get('number_of_attendees', 0)
        total_revenue = report_data.get('total_revenue', 0.0)
        attendance_rate = 0.0
        if total_tickets_sold > 0:
            attendance_rate = (float(number_of_attendees) / total_tickets_sold) * 100
        currency_symbol = report_data.get('currency_symbol', '$')
        summary_data = [
            ['Metric', 'Value'],
            ['Total Tickets Sold', str(total_tickets_sold)],
            ['Total Revenue', f"{currency_symbol}{total_revenue:.2f}"],
            ['Total Attendees', str(number_of_attendees)],
            ['Attendance Rate', f"{attendance_rate:.1f}%"],
        ]
        if total_tickets_sold > 0:
            avg_revenue = (total_revenue / float(total_tickets_sold))
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
        insights = []
        total_tickets_sold = report_data.get('total_tickets_sold', 0)
        number_of_attendees = report_data.get('number_of_attendees', 0)
        if total_tickets_sold > 0:
            attendance_rate = (float(number_of_attendees) / total_tickets_sold) * 100
            if attendance_rate > 90:
                insights.append("• Excellent attendance rate! Most ticket holders attended the event, indicating high engagement.")
            elif attendance_rate > 70:
                insights.append("• Good attendance rate. Consider strategies to reduce no-shows and further boost attendance for future events.")
            else:
                insights.append("• A lower attendance rate suggests potential areas for improvement. Analyze attendee feedback for insights.")
        
        # Updated to use the new field name
        tickets_sold_by_type = report_data.get('tickets_by_type', {})
        revenue_by_ticket_type = report_data.get('revenue_by_ticket_type', {})
        
        if tickets_sold_by_type:
            max_sold_type = max(tickets_sold_by_type.items(), key=lambda x: x[1])[0]
            insights.append(f"• The **{max_sold_type}** ticket type was the most popular by volume, indicating strong demand for this option.")
        if revenue_by_ticket_type:
            max_revenue_type = max(revenue_by_ticket_type.items(), key=lambda x: x[1])[0]
            insights.append(f"• **{max_revenue_type}** tickets generated the highest revenue, highlighting its significant contribution to overall earnings.")
            if tickets_sold_by_type and (max_sold_type != max_revenue_type):
                insights.append(f"• While **{max_sold_type}** sold the most tickets, **{max_revenue_type}** was the top revenue generator, suggesting different pricing or value propositions.")
        payment_methods = report_data.get('payment_method_usage', {})
        if payment_methods:
            preferred_method = max(payment_methods.items(), key=lambda x: x[1])[0]
            insights.append(f"• **{preferred_method}** was the most frequently used payment method for this event, suggesting its convenience for attendees.")
        if not insights:
            insights.append("• No specific insights could be generated due to insufficient or incomplete data. Ensure all relevant data points are provided.")
        return insights

    def _create_breakdown_tables(self, report_data: Dict[str, Any]) -> List[Tuple[str, Table]]:
        tables = []
        currency_symbol = report_data.get('currency_symbol', '$')
        
        # Updated to use the new field name
        if report_data.get('tickets_by_type'):
            tickets_by_type = report_data['tickets_by_type']
            data = [['Ticket Type', 'Tickets Sold', 'Percentage']]
            total_tickets = sum(tickets_by_type.values())
            for ticket_type, count in tickets_by_type.items():
                percentage = (float(count) / total_tickets * 100) if total_tickets > 0 else 0.0
                data.append([str(ticket_type), str(count), f"{percentage:.1f}%"])
            table = Table(data, colWidths=[2*inch, 1.5*inch, 1*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F18F01')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (0, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
            ]))
            tables.append(("Ticket Sales Breakdown", table))
        if report_data.get('revenue_by_ticket_type'):
            revenue_by_ticket_type = report_data['revenue_by_ticket_type']
            data = [['Ticket Type', 'Revenue', 'Percentage']]
            total_revenue = sum(revenue_by_ticket_type.values())
            for ticket_type, revenue in revenue_by_ticket_type.items():
                percentage = (revenue / total_revenue * 100) if total_revenue > 0 else 0.0
                data.append([str(ticket_type), f"{currency_symbol}{revenue:.2f}", f"{percentage:.1f}%"])
            table = Table(data, colWidths=[2*inch, 1.5*inch, 1*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F18F01')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (0, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
            ]))
            tables.append(("Revenue Breakdown", table))
        if report_data.get('payment_method_usage'):
            payment_method_usage = report_data['payment_method_usage']
            data = [['Payment Method', 'Transactions', 'Percentage']]
            total_transactions = sum(payment_method_usage.values())
            for method, count in payment_method_usage.items():
                percentage = (float(count) / total_transactions * 100) if total_transactions > 0 else 0.0
                data.append([str(method), str(count), f"{percentage:.1f}%"])
            table = Table(data, colWidths=[2*inch, 1.5*inch, 1*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F18F01')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (0, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
            ]))
            tables.append(("Payment Method Usage", table))
        return tables

    def _add_charts_to_story(self, story, chart_paths):
        if not chart_paths or not self.config.include_charts:
            return
        story.append(Paragraph("VISUAL ANALYTICS", self.subtitle_style))
        for i, chart_path in enumerate(chart_paths):
            if not chart_path:
                continue
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                if os.path.exists(chart_path) and os.path.getsize(chart_path) > 0:
                    try:
                        with open(chart_path, 'rb') as f:
                            header = f.read(8)
                            if header.startswith(b'\x89PNG\r\n\x1a\n'):
                                break
                    except Exception as e:
                        logger.warning(f"File verification failed for {chart_path}: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(0.1)
            if retry_count >= max_retries:
                logger.error(f"Could not verify chart file after {max_retries} attempts: {chart_path}")
                continue
            try:
                img = Image(chart_path, width=6*inch, height=4.5*inch)
                story.append(img)
                story.append(Spacer(1, 20))
                if (i + 1) % 2 == 0 and i < len(chart_paths) - 1:
                    story.append(PageBreak())
                logger.info(f"Successfully added chart to PDF: {chart_path}")
            except Exception as img_e:
                logger.error(f"Error adding image {chart_path} to PDF: {img_e}", exc_info=True)

    def _cleanup_chart_files(self, chart_paths):
        for chart_path in chart_paths:
            if chart_path and os.path.exists(chart_path):
                try:
                    os.remove(chart_path)
                    logger.debug(f"Cleaned up chart file: {chart_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup chart file {chart_path}: {cleanup_error}")

    def generate_pdf(self, report_data: Dict[str, Any], chart_paths: List[str], output_path: str) -> Optional[str]:
        """
        Generate PDF report from already-processed report data.
        
        Args:
            report_data: Pre-processed report data dictionary
            chart_paths: List of chart file paths to include
            output_path: Output file path for the PDF
            
        Returns:
            Output path if successful, None if failed
        """
        try:
            # Data is already processed - no need to call ReportDataProcessor again
            pagesize = self._get_pagesize()
            doc = SimpleDocTemplate(output_path, pagesize=pagesize, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
            story = []
            
            story.append(Paragraph("EVENT ANALYTICS REPORT", self.title_style))
            story.append(Spacer(1, 20))
            
            event_name = report_data.get('event_name', 'N/A')
            event_date = report_data.get('event_date', 'N/A')
            event_location = report_data.get('event_location', 'N/A')
            filter_start_date = report_data.get('filter_start_date', 'N/A')
            filter_end_date = report_data.get('filter_end_date', 'N/A')
            currency = report_data.get('currency', 'USD')
            currency_symbol = report_data.get('currency_symbol', '$')
            
            event_info = f"""
            <para fontSize=14>
            <b>Event:</b> {event_name}<br/>
            <b>Date:</b> {event_date}<br/>
            <b>Location:</b> {event_location}<br/>
            <b>Report Period:</b> {filter_start_date} to {filter_end_date}<br/>
            <b>Currency:</b> {currency} ({currency_symbol})<br/>
            <b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </para>
            """
            story.append(Paragraph(event_info, self.normal_style))
            story.append(Spacer(1, 30))
            
            story.append(Paragraph("EXECUTIVE SUMMARY", self.subtitle_style))
            story.append(self._create_summary_table(report_data))
            story.append(Spacer(1, 30))
            
            insights = self._generate_insights(report_data)
            if insights:
                story.append(Paragraph("KEY INSIGHTS", self.header_style))
                for insight in insights:
                    story.append(Paragraph(insight, self.normal_style))
                story.append(Spacer(1, 20))
            
            if len(story) > 5:
                story.append(PageBreak())
            
            if chart_paths:
                self._add_charts_to_story(story, chart_paths)
            
            story.append(PageBreak())
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
            story.append(Paragraph(footer_text, self.normal_style))
            
            doc.build(story)
            self._cleanup_chart_files(chart_paths)
            return output_path
            
        except Exception as e:
            logger.error(f"Error generating PDF report: {e}", exc_info=True)
            self._cleanup_chart_files(chart_paths)
            return None

class CSVReportGenerator:
    @staticmethod
    def generate_csv(report_data: Dict[str, Any], output_path: str) -> Optional[str]:
        """Generate CSV report from already processed report data"""
        try:
            # Remove the ReportDataProcessor.process_report_data call since 
            # report_data should already be processed when passed in
            processed_data = report_data  # Use data as-is
            
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                # Write report summary
                writer.writerow(['Report Summary'])
                writer.writerow(['Metric', 'Value'])
                writer.writerow(['Event Name', processed_data.get('event_name', 'N/A')])
                writer.writerow(['Report Period Start', processed_data.get('filter_start_date', 'N/A')])
                writer.writerow(['Report Period End', processed_data.get('filter_end_date', 'N/A')])
                writer.writerow(['Total Tickets Sold', processed_data.get('total_tickets_sold', 0)])
                writer.writerow(['Total Revenue', f"{processed_data.get('currency_symbol', '$')}{processed_data.get('total_revenue', 0.0):.2f}"])
                writer.writerow(['Total Attendees', processed_data.get('number_of_attendees', 0)])
                
                # Calculate attendance rate
                total_tickets_sold = processed_data.get('total_tickets_sold', 0)
                number_of_attendees = processed_data.get('number_of_attendees', 0)
                attendance_rate = (float(number_of_attendees) / total_tickets_sold * 100) if total_tickets_sold > 0 else 0.0
                writer.writerow(['Attendance Rate', f"{attendance_rate:.1f}%"])
                writer.writerow(['Currency', f"{processed_data.get('currency', 'USD')} ({processed_data.get('currency_symbol', '$')})"])
                writer.writerow([])

                # Write ticket sales breakdown
                if processed_data.get('tickets_by_type'):  # Note: using 'tickets_by_type' from your new structure
                    writer.writerow(['Ticket Sales Breakdown'])
                    writer.writerow(['Ticket Type', 'Tickets Sold', 'Percentage'])
                    tickets_sold_by_type = processed_data['tickets_by_type']
                    total_tickets_breakdown = sum(tickets_sold_by_type.values())
                    for ticket_type, count in tickets_sold_by_type.items():
                        percentage = (float(count) / total_tickets_breakdown * 100) if total_tickets_breakdown > 0 else 0.0
                        writer.writerow([ticket_type, count, f"{percentage:.1f}%"])
                    writer.writerow([])

                # Write revenue breakdown
                if processed_data.get('revenue_by_type'):
                    writer.writerow(['Revenue Breakdown'])
                    writer.writerow(['Ticket Type', 'Revenue', 'Percentage'])
                    revenue_by_ticket_type = processed_data['revenue_by_type']
                    total_revenue_breakdown = sum(revenue_by_ticket_type.values())
                    for ticket_type, revenue in revenue_by_ticket_type.items():
                        percentage = (revenue / total_revenue_breakdown * 100) if total_revenue_breakdown > 0 else 0.0
                        writer.writerow([ticket_type, f"{processed_data.get('currency_symbol', '$')}{revenue:.2f}", f"{percentage:.1f}%"])
                    writer.writerow([])

                # Write payment method usage
                if processed_data.get('payment_method_usage'):
                    writer.writerow(['Payment Method Usage'])
                    writer.writerow(['Payment Method', 'Transactions', 'Percentage'])
                    payment_method_usage = processed_data['payment_method_usage']
                    total_transactions_usage = sum(payment_method_usage.values())
                    for method, count in payment_method_usage.items():
                        percentage = (float(count) / total_transactions_usage * 100) if total_transactions_usage > 0 else 0.0
                        writer.writerow([method, count, f"{percentage:.1f}%"])
                    writer.writerow([])

                # Write daily revenue if available
                if processed_data.get('daily_revenue'):
                    writer.writerow(['Daily Revenue'])
                    writer.writerow(['Date', 'Revenue', 'Tickets Sold'])
                    for date_str, daily_data in processed_data['daily_revenue'].items():
                        daily_revenue = float(daily_data.get('revenue', 0.0))
                        daily_tickets = int(daily_data.get('tickets_sold', 0))
                        writer.writerow([date_str, f"{processed_data.get('currency_symbol', '$')}{daily_revenue:.2f}", daily_tickets])
                    writer.writerow([])

            return output_path
            
        except Exception as e:
            logger.error(f"Error generating CSV report: {e}", exc_info=True)
            return None