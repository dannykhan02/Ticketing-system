import matplotlib
matplotlib.use('Agg')

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import os
from datetime import datetime
import csv
from decimal import Decimal
from io import StringIO, BytesIO
import tempfile
from typing import Dict, List, Optional, Tuple, Any, Union
from contextlib import contextmanager
from .config import ReportConfig # Assuming .config refers to a local config file
import logging

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
        This is typically used when preparing data that might have Enum objects as keys
        from a data source, making it JSON-serializable.
        """
        if not isinstance(data, dict):
            return data
            
        converted = {}
        for key, value in data.items():
            # Convert Enum keys to their string values
            if hasattr(key, 'value'):
                string_key = key.value
            else:
                string_key = str(key)
            
            # Recursively convert nested dictionaries or lists of dictionaries
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
        appropriate numeric types (float or int). This is crucial for mathematical
        operations in chart and PDF generation, especially if data comes from JSON.
        """
        if not isinstance(data, dict):
            return data # Only process dictionaries

        processed_data = data.copy()

        # Core numeric summary fields
        numeric_fields = [
            'total_tickets_sold',
            'number_of_attendees',
            'total_revenue',
            'converted_revenue', # If you store this directly
            # Add any other top-level numeric fields here
        ]
        for field in numeric_fields:
            if field in processed_data and processed_data[field] is not None:
                try:
                    # Attempt float first for general numbers, then int for counts
                    if field in ['total_revenue', 'converted_revenue']:
                        processed_data[field] = float(processed_data[field])
                    else:
                        processed_data[field] = int(processed_data[field])
                except (ValueError, TypeError) as e:
                    logger.warning(f"Could not convert field '{field}' to numeric type. Value: '{processed_data[field]}', Error: {e}")
                    # Keep original value or set to default if conversion fails for safety
                    if field in ['total_revenue', 'converted_revenue']:
                        processed_data[field] = 0.0
                    else:
                        processed_data[field] = 0

        # Nested dictionaries with numeric values (e.g., breakdown by type)
        nested_numeric_fields = [
            'tickets_sold_by_type',
            'revenue_by_ticket_type',
            'attendees_by_ticket_type',
            'payment_method_usage',
            'daily_revenue' # Add if you have this in report_data
        ]

        for field in nested_numeric_fields:
            if field in processed_data and isinstance(processed_data[field], dict):
                converted_nested_data = {}
                for key, value in processed_data[field].items():
                    try:
                        # Attempt to convert all values in these nested dicts to float
                        converted_nested_data[key] = float(value) if isinstance(value, (int, float, str, Decimal)) else value
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Could not convert nested field '{field}' key '{key}' to numeric. Value: '{value}', Error: {e}")
                        converted_nested_data[key] = 0.0 # Default to 0.0 on failure

                processed_data[field] = converted_nested_data
            elif field in processed_data and isinstance(processed_data[field], list):
                # If these fields can be lists of dicts (e.g., daily breakdown list)
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
        # First, ensure Enum keys are strings recursively
        processed_data = ReportDataProcessor.convert_enum_keys_to_strings(report_data)
        
        # Then, ensure numeric types are correct
        processed_data = ReportDataProcessor._ensure_numeric_types(processed_data)
        
        return processed_data

class ChartGenerator:
    """
    Generates various types of charts (pie, bar, comparison) using Matplotlib and Seaborn,
    saving them as temporary image files.
    """
    def __init__(self, config: ReportConfig):
        self.config = config
        self._setup_matplotlib()

    def _setup_matplotlib(self):
        """
        Sets up Matplotlib style and Seaborn palette based on configuration.
        """
        try:
            # Change for performance if needed based on the warning
            plt.style.use(self.config.chart_style or 'default') 
            if self.config.chart_style and self.config.chart_style.startswith("seaborn"):
                logger.warning("Seaborn style may use more memory. Consider using 'default' instead.")
            if not getattr(self.config, "limit_charts", False):
                sns.set_palette("husl") 
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

    def create_pie_chart(self, data: Dict[str, Union[int, float]], title: str) -> Optional[str]:
        """
        Creates a pie chart from the given data and saves it to a temporary file.

        Args:
            data (Dict[str, Union[int, float]]): A dictionary where keys are categories and values are counts.
            title (str): The title of the pie chart.

        Returns:
            Optional[str]: The path to the saved image file, or None if an error occurred or data is empty.
        """
        if not data:
            logger.info(f"No data provided for pie chart '{title}'. Skipping chart generation.")
            return None

        try:
            # Data should already be processed by ReportDataProcessor.process_report_data before reaching here
            labels = list(data.keys())
            sizes = [float(v) for v in data.values()] # Ensure values are float for plotting
            
            # Filter out zero values to prevent issues with pie chart or misleading slices
            filtered_labels_sizes = [(lbl, sz) for lbl, sz in zip(labels, sizes) if sz > 0]
            if not filtered_labels_sizes:
                logger.info(f"All data values are zero for pie chart '{title}'. Skipping chart generation.")
                return None

            labels, sizes = zip(*filtered_labels_sizes) # Unzip filtered data
            
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

                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    plt.savefig(tmp.name, dpi=self.config.chart_dpi, bbox_inches='tight')
                    return tmp.name

        except Exception as e:
            logger.error(f"Error creating pie chart '{title}': {e}", exc_info=True)
            return None

    def create_bar_chart(self, data: Dict[str, Union[float, int]], title: str, xlabel: str, ylabel: str, currency_symbol: str = '$') -> Optional[str]:
        """
        Creates a bar chart from the given data and saves it to a temporary file.

        Args:
            data (Dict[str, Union[float, int]]): A dictionary where keys are categories and values are numerical.
            title (str): The title of the bar chart.
            xlabel (str): The label for the x-axis.
            ylabel (str): The label for the y-axis.
            currency_symbol (str): The currency symbol to use for y-axis labels if 'Revenue' is in ylabel.

        Returns:
            Optional[str]: The path to the saved image file, or None if an error occurred or data is empty.
        """
        if not data:
            logger.info(f"No data provided for bar chart '{title}'. Skipping chart generation.")
            return None

        try:
            # Data should already be processed by ReportDataProcessor.process_report_data before reaching here
            categories = list(data.keys())
            values = [float(v) for v in data.values()] # Ensure values are float for plotting

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

                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    plt.savefig(tmp.name, dpi=self.config.chart_dpi, bbox_inches='tight')
                    return tmp.name

        except Exception as e:
            logger.error(f"Error creating bar chart '{title}': {e}", exc_info=True)
            return None

    def create_comparison_chart(self, sold_data: Dict[str, int], attended_data: Dict[str, int], title: str) -> Optional[str]:
        """
        Creates a comparison bar chart showing tickets sold vs. actual attendance and saves it to a temporary file.

        Args:
            sold_data (Dict[str, int]): Dictionary of tickets sold by type.
            attended_data (Dict[str, int]): Dictionary of attendees by ticket type.
            title (str): The title of the comparison chart.

        Returns:
            Optional[str]: The path to the saved image file, or None if an error occurred or data is empty.
        """
        if not sold_data and not attended_data:
            logger.info(f"No data provided for comparison chart '{title}'. Skipping chart generation.")
            return None

        try:
            # Data should already be processed by ReportDataProcessor.process_report_data before reaching here
            
            # Combine all unique ticket types from both datasets
            all_ticket_types = sorted(list(set(sold_data.keys()) | set(attended_data.keys())))
            
            # Ensure categories are ordered consistently and get counts
            categories = all_ticket_types
            sold_counts = [int(sold_data.get(t, 0)) for t in categories] # Ensure int
            attended_counts = [int(attended_data.get(t, 0)) for t in categories] # Ensure int

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
                        if height > 0: # Only add label if height > 0
                            ax.text(bar.get_x() + bar.get_width()/2., height,
                                    f'{int(height)}', ha='center', va='bottom', fontweight='bold')

                ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
                ax.set_xlabel('Ticket Type', fontsize=12, fontweight='bold')
                ax.set_ylabel('Count', fontsize=12, fontweight='bold')
                ax.set_xticks(x)
                ax.set_xticklabels(categories, rotation=45, ha='right')
                ax.legend()
                plt.tight_layout()

                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    plt.savefig(tmp.name, dpi=self.config.chart_dpi, bbox_inches='tight')
                    return tmp.name

        except Exception as e:
            logger.error(f"Error creating comparison chart '{title}': {e}", exc_info=True)
            return None

    def create_all_charts(self, report_data: Dict[str, Any]) -> List[str]:
        """
        Generates all configured charts based on the provided report data.
        Applies data preprocessing to handle Enum keys and ensure numeric types.

        Args:
            report_data (Dict[str, Any]): The raw report data.

        Returns:
            List[str]: A list of paths to the generated chart image files.
        """
        if getattr(self.config, "limit_charts", False):
            logger.warning("Chart generation skipped due to memory constraints (limit_charts=True).")
            return []

        if PSUTIL_AVAILABLE:
            logger.info(f"Memory usage before chart generation: {psutil.Process().memory_info().rss / (1024 ** 2):.2f} MB")

        # Process data once to ensure all keys are strings and numeric types are correct
        processed_data = ReportDataProcessor.process_report_data(report_data)
        
        chart_paths = []
        currency_symbol = processed_data.get('currency_symbol', '$')

        chart_configs = [
            {'type': 'pie', 'data_key': 'tickets_sold_by_type', 'title': 'Ticket Sales Distribution by Type'},
            {'type': 'bar', 'data_key': 'revenue_by_ticket_type', 'title': 'Revenue by Ticket Type', 'xlabel': 'Ticket Type', 'ylabel': f'Revenue ({currency_symbol})', 'currency_symbol': currency_symbol},
            {'type': 'comparison', 'data_key_sold': 'tickets_sold_by_type', 'data_key_attended': 'attendees_by_ticket_type', 'title': 'Tickets Sold vs Actual Attendance'},
            {'type': 'bar', 'data_key': 'payment_method_usage', 'title': 'Payment Method Usage', 'xlabel': 'Payment Method', 'ylabel': 'Number of Transactions'}
        ]

        for chart_conf in chart_configs:
            chart_path = None
            if chart_conf['type'] == 'pie' and processed_data.get(chart_conf['data_key']):
                chart_path = self.create_pie_chart(
                    processed_data[chart_conf['data_key']],
                    chart_conf['title']
                )
            elif chart_conf['type'] == 'bar' and processed_data.get(chart_conf['data_key']):
                chart_path = self.create_bar_chart(
                    processed_data[chart_conf['data_key']],
                    chart_conf['title'],
                    chart_conf['xlabel'],
                    chart_conf['ylabel'],
                    chart_conf.get('currency_symbol', '$')
                )
            elif chart_conf['type'] == 'comparison' and processed_data.get(chart_conf['data_key_sold']) and processed_data.get(chart_conf['data_key_attended']):
                chart_path = self.create_comparison_chart(
                    processed_data[chart_conf['data_key_sold']],
                    processed_data[chart_conf['data_key_attended']],
                    chart_conf['title']
                )
            
            if chart_path:
                chart_paths.append(chart_path)
        
        if PSUTIL_AVAILABLE:
            logger.info(f"Memory usage after chart generation: {psutil.Process().memory_info().rss / (1024 ** 2):.2f} MB")

        return chart_paths

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

    def _create_summary_table(self, report_data: Dict[str, Any]) -> Table:
        """
        Creates a summary table for the PDF report.

        Args:
            report_data (Dict[str, Any]): The processed report data.

        Returns:
            Table: A ReportLab Table object containing the summary.
        """
        total_tickets_sold = report_data.get('total_tickets_sold', 0)
        number_of_attendees = report_data.get('number_of_attendees', 0)
        total_revenue = report_data.get('total_revenue', 0.0) # Ensure float
        
        attendance_rate = 0.0
        if total_tickets_sold > 0:
            attendance_rate = (float(number_of_attendees) / total_tickets_sold) * 100 # Ensure division is float

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

        Args:
            report_data (Dict[str, Any]): The processed report data.

        Returns:
            List[str]: A list of insight strings.
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
            # Data should already be processed by ReportDataProcessor.process_report_data
            # so keys are strings and values are numbers
            if tickets_sold_by_type:
                max_sold_type = max(tickets_sold_by_type.items(), key=lambda x: x[1])[0]
                insights.append(f"• The **{max_sold_type}** ticket type was the most popular by volume, indicating strong demand for this option.")

        if revenue_by_ticket_type:
            # Data should already be processed by ReportDataProcessor.process_report_data
            if revenue_by_ticket_type:
                max_revenue_type = max(revenue_by_ticket_type.items(), key=lambda x: x[1])[0] # Values are already float
                insights.append(f"• **{max_revenue_type}** tickets generated the highest revenue, highlighting its significant contribution to overall earnings.")
                
                # Check if most popular by volume is different from highest revenue
                if tickets_sold_by_type and (max_sold_type != max_revenue_type):
                    insights.append(f"• While **{max_sold_type}** sold the most tickets, **{max_revenue_type}** was the top revenue generator, suggesting different pricing or value propositions.")

        payment_methods = report_data.get('payment_method_usage', {})
        if payment_methods:
            # Data should already be processed by ReportDataProcessor.process_report_data
            if payment_methods:
                preferred_method = max(payment_methods.items(), key=lambda x: x[1])[0]
                insights.append(f"• **{preferred_method}** was the most frequently used payment method for this event, suggesting its convenience for attendees.")

        if not insights:
            insights.append("• No specific insights could be generated due to insufficient or incomplete data. Ensure all relevant data points are provided.")
            
        return insights

    def _create_breakdown_tables(self, report_data: Dict[str, Any]) -> List[Tuple[str, Table]]:
        """
        Creates detailed breakdown tables for the PDF report.

        Args:
            report_data (Dict[str, Any]): The processed report data.

        Returns:
            List[Tuple[str, Table]]: A list of tuples, each containing a table title and a ReportLab Table object.
        """
        tables = []
        currency_symbol = report_data.get('currency_symbol', '$')

        # Ticket Sales Breakdown
        if report_data.get('tickets_sold_by_type'):
            # Data is already processed by ReportDataProcessor.process_report_data
            tickets_sold_by_type = report_data['tickets_sold_by_type']
            
            data = [['Ticket Type', 'Tickets Sold', 'Percentage']]
            total_tickets = sum(tickets_sold_by_type.values())

            for ticket_type, count in tickets_sold_by_type.items():
                percentage = (float(count) / total_tickets * 100) if total_tickets > 0 else 0.0 # Ensure float division
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

        # Revenue Breakdown
        if report_data.get('revenue_by_ticket_type'):
            # Data is already processed by ReportDataProcessor.process_report_data
            revenue_by_ticket_type = report_data['revenue_by_ticket_type']

            data = [['Ticket Type', 'Revenue', 'Percentage']]
            total_revenue = sum(revenue_by_ticket_type.values()) # Sum of floats

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
            
        # Payment Method Usage Breakdown
        if report_data.get('payment_method_usage'):
            # Data is already processed by ReportDataProcessor.process_report_data
            payment_method_usage = report_data['payment_method_usage']
            data = [['Payment Method', 'Transactions', 'Percentage']]
            total_transactions = sum(payment_method_usage.values())

            for method, count in payment_method_usage.items():
                percentage = (float(count) / total_transactions * 100) if total_transactions > 0 else 0.0 # Ensure float division
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

    def generate_pdf(self, report_data: Dict[str, Any], chart_paths: List[str], output_path: str) -> Optional[str]:
        """
        Generates the complete PDF report.

        Args:
            report_data (Dict[str, Any]): The raw report data.
            chart_paths (List[str]): A list of paths to temporary chart image files.
            output_path (str): The desired path for the output PDF file.

        Returns:
            Optional[str]: The path to the generated PDF file, or None if an error occurred.
        """
        try:
            # Process data *before* using it in PDF generation
            # This ensures all numeric fields are correctly typed
            processed_data = ReportDataProcessor.process_report_data(report_data)
            
            doc = SimpleDocTemplate(
                output_path, pagesize=self.config.pdf_pagesize,
                rightMargin=72, leftMargin=72,
                topMargin=72, bottomMargin=18
            )

            story = []

            # Title
            story.append(Paragraph("EVENT ANALYTICS REPORT", self.title_style))
            story.append(Spacer(1, 20))

            # Event Information
            # Ensure safe retrieval with .get() and default values
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

            # Executive Summary
            story.append(Paragraph("EXECUTIVE SUMMARY", self.subtitle_style))
            story.append(self._create_summary_table(processed_data))
            story.append(Spacer(1, 30))

            # Insights
            insights = self._generate_insights(processed_data)
            if insights:
                story.append(Paragraph("KEY INSIGHTS", self.header_style))
                for insight in insights:
                    story.append(Paragraph(insight, self.normal_style))
                story.append(Spacer(1, 20))

            # Page Break before charts/detailed breakdown if content is substantial
            if len(story) > 5: # Arbitrary threshold to decide if a page break is needed
                story.append(PageBreak())

            # Charts
            if chart_paths and self.config.include_charts:
                story.append(Paragraph("VISUAL ANALYTICS", self.subtitle_style))
                for i, chart_path in enumerate(chart_paths):
                    if os.path.exists(chart_path):
                        try:
                            # Adjust image width/height if needed based on PDF page size or desired layout
                            img = Image(chart_path, width=6*inch, height=4.5*inch) 
                            story.append(img)
                            story.append(Spacer(1, 20))
                            # Add a page break after every two charts to keep layout clean
                            if (i + 1) % 2 == 0 and i < len(chart_paths) - 1:
                                story.append(PageBreak())
                        except Exception as img_e:
                            logger.error(f"Error adding image {chart_path} to PDF: {img_e}", exc_info=True)
                        finally:
                            # Ensure the temporary chart file is deleted after being used in the PDF
                            os.remove(chart_path) 
            
            # Detailed Breakdown
            story.append(PageBreak()) # Start detailed breakdown on a new page
            story.append(Paragraph("DETAILED BREAKDOWN", self.subtitle_style))
            tables = self._create_breakdown_tables(processed_data)
            for table_title, table in tables:
                story.append(Paragraph(table_title, self.header_style))
                story.append(table)
                story.append(Spacer(1, 20))

            # Footer
            footer_text = """
            <para alignment="center" fontSize=10 textColor="grey">
            This report was automatically generated by the Event Management System<br/>
            For questions or support, please contact your system administrator
            </para>
            """
            story.append(Spacer(1, 50))
            story.append(Paragraph(footer_text, self.normal_style))

            doc.build(story)
            return output_path

        except Exception as e:
            logger.error(f"Error generating PDF report: {e}", exc_info=True)
            # Ensure any remaining temporary chart files are cleaned up if an error occurs
            for chart_path in chart_paths:
                if os.path.exists(chart_path):
                    os.remove(chart_path)
            return None

class CSVReportGenerator:
    """
    Generates a CSV report from event data.
    """
    @staticmethod
    def generate_csv(report_data: Dict[str, Any], output_path: str) -> Optional[str]:
        """
        Generates a CSV report from the provided report data.

        Args:
            report_data (Dict[str, Any]): The raw report data.
            output_path (str): The desired path for the output CSV file.

        Returns:
            Optional[str]: The path to the generated CSV file, or None if an error occurred.
        """
        try:
            # Process data to ensure consistent types for CSV output
            processed_data = ReportDataProcessor.process_report_data(report_data)

            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)

                # Summary Section
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
                writer.writerow([]) # Blank row for separation

                # Ticket Sales Breakdown
                if processed_data.get('tickets_sold_by_type'):
                    writer.writerow(['Ticket Sales Breakdown'])
                    writer.writerow(['Ticket Type', 'Tickets Sold', 'Percentage'])
                    tickets_sold_by_type = processed_data['tickets_sold_by_type']
                    total_tickets_breakdown = sum(tickets_sold_by_type.values())
                    for ticket_type, count in tickets_sold_by_type.items():
                        percentage = (float(count) / total_tickets_breakdown * 100) if total_tickets_breakdown > 0 else 0.0
                        writer.writerow([ticket_type, count, f"{percentage:.1f}%"])
                    writer.writerow([])

                # Revenue Breakdown
                if processed_data.get('revenue_by_ticket_type'):
                    writer.writerow(['Revenue Breakdown'])
                    writer.writerow(['Ticket Type', 'Revenue', 'Percentage'])
                    revenue_by_ticket_type = processed_data['revenue_by_ticket_type']
                    total_revenue_breakdown = sum(revenue_by_ticket_type.values())
                    for ticket_type, revenue in revenue_by_ticket_type.items():
                        percentage = (revenue / total_revenue_breakdown * 100) if total_revenue_breakdown > 0 else 0.0
                        writer.writerow([ticket_type, f"{processed_data.get('currency_symbol', '$')}{revenue:.2f}", f"{percentage:.1f}%"])
                    writer.writerow([])

                # Payment Method Usage
                if processed_data.get('payment_method_usage'):
                    writer.writerow(['Payment Method Usage'])
                    writer.writerow(['Payment Method', 'Transactions', 'Percentage'])
                    payment_method_usage = processed_data['payment_method_usage']
                    total_transactions_usage = sum(payment_method_usage.values())
                    for method, count in payment_method_usage.items():
                        percentage = (float(count) / total_transactions_usage * 100) if total_transactions_usage > 0 else 0.0
                        writer.writerow([method, count, f"{percentage:.1f}%"])
                    writer.writerow([])

                # Daily Sales/Revenue (if available)
                if processed_data.get('daily_revenue'):
                    writer.writerow(['Daily Revenue'])
                    writer.writerow(['Date', 'Revenue', 'Tickets Sold'])
                    # Assuming daily_revenue is a dict of date strings to dicts like {'revenue': X, 'tickets_sold': Y}
                    for date_str, daily_data in processed_data['daily_revenue'].items():
                        daily_revenue = float(daily_data.get('revenue', 0.0))
                        daily_tickets = int(daily_data.get('tickets_sold', 0))
                        writer.writerow([date_str, f"{processed_data.get('currency_symbol', '$')}{daily_revenue:.2f}", daily_tickets])
                    writer.writerow([])

            return output_path

        except Exception as e:
            logger.error(f"Error generating CSV report: {e}", exc_info=True)
            return None