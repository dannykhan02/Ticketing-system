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
from contextlib import contextmanager
from .config import ReportConfig
import logging
import time

# Optional: Import psutil for memory logging
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not found. Memory usage logging will be skipped.")

logger = logging.getLogger(__name__)

class ReportDataProcessor:
    """
    Utility class to handle Enum key conversion and type casting in report data.
    """
    @staticmethod
    def convert_enum_keys_to_strings(data: Dict[Any, Any]) -> Dict[str, Any]:
        """
        Convert Enum keys to their string values for JSON serialization.
        """
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
        """
        Ensures that specific numeric fields within the report_data are cast to
        appropriate numeric types (float or int).
        """
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
    def process_report_data(report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process report data to ensure all Enum keys are converted to strings
        and numeric fields are correctly typed.
        """
        processed_data = ReportDataProcessor.convert_enum_keys_to_strings(report_data)
        processed_data = ReportDataProcessor._ensure_numeric_types(processed_data)
        return processed_data

class ChartGenerator:
    """
    Generates various types of charts (pie, bar, comparison) using Matplotlib,
    saving them as temporary image files.
    """
    def __init__(self, config: ReportConfig):
        self.config = config
        self._setup_matplotlib()

    def _setup_matplotlib(self):
        """
        Sets up Matplotlib style based on configuration.
        """
        try:
            plt.style.use(self.config.chart_style if self.config.chart_style else 'default')
        except Exception as e:
            logger.warning(f"Failed to apply matplotlib style: {e}")

    @contextmanager
    def _chart_context(self, figsize: Tuple[int, int] = (10, 8)):
        """
        Provides a context manager for creating Matplotlib figures and axes,
        ensuring proper cleanup.
        """
        fig, ax = plt.subplots(figsize=figsize)
        try:
            yield fig, ax
        finally:
            plt.close(fig)

    def _save_chart_safely(self, fig, title: str) -> Optional[str]:
        """
        Safely saves a matplotlib figure to a temporary file with proper error handling.
        """
        try:
            # Create temporary file with a more descriptive name
            tmp_file = tempfile.NamedTemporaryFile(
                suffix='.png',
                prefix=f'chart_{title.replace(" ", "_")}_',
                delete=False
            )
            tmp_filename = tmp_file.name
            tmp_file.close()  # Close the file handle but keep the file

            # Save the figure
            fig.savefig(tmp_filename, dpi=self.config.chart_dpi, bbox_inches='tight')

            # Force matplotlib to finish writing
            plt.close(fig)

            # Verify the file was created and has content
            if os.path.exists(tmp_filename) and os.path.getsize(tmp_filename) > 0:
                logger.info(f"Successfully created chart: {tmp_filename}")
                return tmp_filename
            else:
                logger.error(f"Failed to create chart file: {tmp_filename}")
                # Clean up failed file
                try:
                    os.remove(tmp_filename)
                except:
                    pass
                return None

        except Exception as e:
            logger.error(f"Error saving chart '{title}': {e}", exc_info=True)
            return None

    def create_pie_chart(self, data: Dict[str, Union[int, float]], title: str) -> Optional[str]:
        """
        Creates a pie chart from the given data and saves it to a temporary file.
        """
        if not data:
            logger.info(f"No data provided for pie chart '{title}'. Skipping chart generation.")
            return None

        try:
            labels = list(data.keys())
            sizes = [float(v) for v in data.values()]
            filtered_labels_sizes = [(lbl, sz) for lbl, sz in zip(labels, sizes) if sz > 0]

            if not filtered_labels_sizes:
                logger.info(f"All data values are zero for pie chart '{title}'. Skipping chart generation.")
                return None

            labels, sizes = zip(*filtered_labels_sizes)

            with self._chart_context() as (fig, ax):
                colors_list = plt.cm.Set3(range(len(labels)))
                wedges, texts, autotexts = ax.pie(
                    sizes, labels=labels, autopct='%1.1f%%',
                    colors=colors_list, startangle=90,
                    explode=[0.05] * len(labels) if labels else None
                )

                for autotext in autotexts:
                    autotext.set_color('white')
                    autotext.set_fontweight('bold')

                ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
                plt.tight_layout()

                return self._save_chart_safely(fig, title)

        except Exception as e:
            logger.error(f"Error creating pie chart '{title}': {e}", exc_info=True)
            return None

    def create_bar_chart(self, data: Dict[str, Union[float, int]], title: str, xlabel: str, ylabel: str, currency_symbol: str = '$') -> Optional[str]:
        """
        Creates a bar chart from the given data and saves it to a temporary file.
        """
        if not data:
            logger.info(f"No data provided for bar chart '{title}'. Skipping chart generation.")
            return None

        try:
            categories = list(data.keys())
            values = [float(v) for v in data.values()]

            with self._chart_context((12, 8)) as (fig, ax):
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

                return self._save_chart_safely(fig, title)

        except Exception as e:
            logger.error(f"Error creating bar chart '{title}': {e}", exc_info=True)
            return None

    def create_comparison_chart(self, sold_data: Dict[str, int], attended_data: Dict[str, int], title: str) -> Optional[str]:
        """
        Creates a comparison bar chart showing tickets sold vs. actual attendance and saves it to a temporary file.
        """
        if not sold_data and not attended_data:
            logger.info(f"No data provided for comparison chart '{title}'. Skipping chart generation.")
            return None

        try:
            all_ticket_types = sorted(list(set(sold_data.keys()) | set(attended_data.keys())))
            categories = all_ticket_types
            sold_counts = [int(sold_data.get(t, 0)) for t in categories]
            attended_counts = [int(attended_data.get(t, 0)) for t in categories]

            if not categories or (sum(sold_counts) == 0 and sum(attended_counts) == 0):
                logger.info(f"No valid data to plot for comparison chart '{title}'. Skipping.")
                return None

            with self._chart_context((12, 8)) as (fig, ax):
                x = range(len(categories))
                width = 0.35

                bars1 = ax.bar([i - width/2 for i in x], sold_counts, width,
                             label='Tickets Sold', color='skyblue', alpha=0.8)
                bars2 = ax.bar([i + width/2 for i in x], attended_counts, width,
                             label='Attendees', color='lightcoral', alpha=0.8)

                for bars in [bars1, bars2]:
                    for bar in bars:
                        height = bar.get_height()
                        if height > 0:
                            ax.text(bar.get_x() + bar.get_width()/2., height,
                                    f'{int(height)}', ha='center', va='bottom', fontweight='bold')

                ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
                ax.set_xlabel('Ticket Type', fontsize=12, fontweight='bold')
                ax.set_ylabel('Count', fontsize=12, fontweight='bold')
                ax.set_xticks(x)
                ax.set_xticklabels(categories, rotation=45, ha='right')
                ax.legend()
                plt.tight_layout()

                return self._save_chart_safely(fig, title)

        except Exception as e:
            logger.error(f"Error creating comparison chart '{title}': {e}", exc_info=True)
            return None

class PDFReportGenerator:
    """
    Generates a PDF report from event data, including summaries, insights,
    tables, and charts.
    """
    def __init__(self, config: ReportConfig):
        self.config = config
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """
        Configures custom paragraph styles for the PDF report.
        """
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
        """
        Converts the pagesize configuration to a proper tuple format.
        Returns:
            Tuple[float, float]: A tuple of (width, height) in points.
        """
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
        """
        Creates a summary table for the PDF report.
        """
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
        """
        Generates key insights based on the report data.
        """
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
        tickets_sold_by_type = report_data.get('tickets_sold_by_type', {})
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
        """
        Creates detailed breakdown tables for the PDF report.
        """
        tables = []
        currency_symbol = report_data.get('currency_symbol', '$')
        if report_data.get('tickets_sold_by_type'):
            tickets_sold_by_type = report_data['tickets_sold_by_type']
            data = [['Ticket Type', 'Tickets Sold', 'Percentage']]
            total_tickets = sum(tickets_sold_by_type.values())
            for ticket_type, count in tickets_sold_by_type.items():
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
        """
        Safely adds charts to the PDF story with proper error handling.
        """
        if not chart_paths or not self.config.include_charts:
            return

        story.append(Paragraph("VISUAL ANALYTICS", self.subtitle_style))

        for i, chart_path in enumerate(chart_paths):
            if not chart_path:
                continue

            # Wait a bit to ensure file is fully written
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries:
                if os.path.exists(chart_path) and os.path.getsize(chart_path) > 0:
                    try:
                        # Try to open and verify the file
                        with open(chart_path, 'rb') as f:
                            # Read first few bytes to verify it's a valid image
                            header = f.read(8)
                            if header.startswith(b'\x89PNG\r\n\x1a\n'):
                                # Valid PNG file
                                break
                    except Exception as e:
                        logger.warning(f"File verification failed for {chart_path}: {e}")

                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(0.1)  # Wait 100ms before retry

            if retry_count >= max_retries:
                logger.error(f"Could not verify chart file after {max_retries} attempts: {chart_path}")
                continue

            try:
                # Create the image with explicit error handling
                img = Image(chart_path, width=6*inch, height=4.5*inch)
                story.append(img)
                story.append(Spacer(1, 20))

                # Add page break after every 2 charts
                if (i + 1) % 2 == 0 and i < len(chart_paths) - 1:
                    story.append(PageBreak())

                logger.info(f"Successfully added chart to PDF: {chart_path}")

            except Exception as img_e:
                logger.error(f"Error adding image {chart_path} to PDF: {img_e}", exc_info=True)

    def _cleanup_chart_files(self, chart_paths):
        """
        Safely cleanup chart files after PDF generation.
        """
        for chart_path in chart_paths:
            if chart_path and os.path.exists(chart_path):
                try:
                    os.remove(chart_path)
                    logger.debug(f"Cleaned up chart file: {chart_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup chart file {chart_path}: {cleanup_error}")

    def generate_pdf(self, report_data: Dict[str, Any], chart_paths: List[str], output_path: str) -> Optional[str]:
        """
        Generates the complete PDF report with improved error handling.
        """
        try:
            processed_data = ReportDataProcessor.process_report_data(report_data)
            pagesize = self._get_pagesize()
            doc = SimpleDocTemplate(output_path, pagesize=pagesize, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
            story = []
            story.append(Paragraph("EVENT ANALYTICS REPORT", self.title_style))
            story.append(Spacer(1, 20))

            event_name = processed_data.get('event_name', 'N/A')
            event_date = processed_data.get('event_date', 'N/A')
            event_location = processed_data.get('event_location', 'N/A')
            filter_start_date = processed_data.get('filter_start_date', 'N/A')
            filter_end_date = processed_data.get('filter_end_date', 'N/A')
            currency = processed_data.get('currency', 'USD')
            currency_symbol = processed_data.get('currency_symbol', '$')

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
            story.append(self._create_summary_table(processed_data))
            story.append(Spacer(1, 30))

            insights = self._generate_insights(processed_data)
            if insights:
                story.append(Paragraph("KEY INSIGHTS", self.header_style))
                for insight in insights:
                    story.append(Paragraph(insight, self.normal_style))
                story.append(Spacer(1, 20))

            if len(story) > 5:
                story.append(PageBreak())

            # Add charts with improved error handling
            if chart_paths:
                self._add_charts_to_story(story, chart_paths)

            story.append(PageBreak())
            story.append(Paragraph("DETAILED BREAKDOWN", self.subtitle_style))

            tables = self._create_breakdown_tables(processed_data)
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

            # Cleanup chart files after successful PDF generation
            self._cleanup_chart_files(chart_paths)

            return output_path

        except Exception as e:
            logger.error(f"Error generating PDF report: {e}", exc_info=True)

            # Cleanup chart files on error
            self._cleanup_chart_files(chart_paths)

            return None

class CSVReportGenerator:
    """
    Generates a CSV report from event data.
    """
    @staticmethod
    def generate_csv(report_data: Dict[str, Any], output_path: str) -> Optional[str]:
        """
        Generates a CSV report from the provided report data.
        """
        try:
            processed_data = ReportDataProcessor.process_report_data(report_data)
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Report Summary'])
                writer.writerow(['Metric', 'Value'])
                writer.writerow(['Event Name', processed_data.get('event_name', 'N/A')])
                writer.writerow(['Report Period Start', processed_data.get('filter_start_date', 'N/A')])
                writer.writerow(['Report Period End', processed_data.get('filter_end_date', 'N/A')])
                writer.writerow(['Total Tickets Sold', processed_data.get('total_tickets_sold', 0)])
                writer.writerow(['Total Revenue', f"{processed_data.get('currency_symbol', '$')}{processed_data.get('total_revenue', 0.0):.2f}"])
                writer.writerow(['Total Attendees', processed_data.get('number_of_attendees', 0)])
                total_tickets_sold = processed_data.get('total_tickets_sold', 0)
                number_of_attendees = processed_data.get('number_of_attendees', 0)
                attendance_rate = (float(number_of_attendees) / total_tickets_sold * 100) if total_tickets_sold > 0 else 0.0
                writer.writerow(['Attendance Rate', f"{attendance_rate:.1f}%"])
                writer.writerow(['Currency', f"{processed_data.get('currency', 'USD')} ({processed_data.get('currency_symbol', '$')})"])
                writer.writerow([])
                if processed_data.get('tickets_sold_by_type'):
                    writer.writerow(['Ticket Sales Breakdown'])
                    writer.writerow(['Ticket Type', 'Tickets Sold', 'Percentage'])
                    tickets_sold_by_type = processed_data['tickets_sold_by_type']
                    total_tickets_breakdown = sum(tickets_sold_by_type.values())
                    for ticket_type, count in tickets_sold_by_type.items():
                        percentage = (float(count) / total_tickets_breakdown * 100) if total_tickets_breakdown > 0 else 0.0
                        writer.writerow([ticket_type, count, f"{percentage:.1f}%"])
                    writer.writerow([])
                if processed_data.get('revenue_by_ticket_type'):
                    writer.writerow(['Revenue Breakdown'])
                    writer.writerow(['Ticket Type', 'Revenue', 'Percentage'])
                    revenue_by_ticket_type = processed_data['revenue_by_ticket_type']
                    total_revenue_breakdown = sum(revenue_by_ticket_type.values())
                    for ticket_type, revenue in revenue_by_ticket_type.items():
                        percentage = (revenue / total_revenue_breakdown * 100) if total_revenue_breakdown > 0 else 0.0
                        writer.writerow([ticket_type, f"{processed_data.get('currency_symbol', '$')}{revenue:.2f}", f"{percentage:.1f}%"])
                    writer.writerow([])
                if processed_data.get('payment_method_usage'):
                    writer.writerow(['Payment Method Usage'])
                    writer.writerow(['Payment Method', 'Transactions', 'Percentage'])
                    payment_method_usage = processed_data['payment_method_usage']
                    total_transactions_usage = sum(payment_method_usage.values())
                    for method, count in payment_method_usage.items():
                        percentage = (float(count) / total_transactions_usage * 100) if total_transactions_usage > 0 else 0.0
                        writer.writerow([method, count, f"{percentage:.1f}%"])
                    writer.writerow([])
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
