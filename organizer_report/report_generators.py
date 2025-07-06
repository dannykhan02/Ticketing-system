import matplotlib
matplotlib.use('Agg')
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
from datetime import datetime
import csv
from decimal import Decimal
from io import StringIO, BytesIO
import tempfile
from typing import Dict, List, Optional, Tuple, Any, Union
from contextlib import contextmanager
from .config import ReportConfig
import logging

logger = logging.getLogger(__name__)

class ChartGenerator:
    def __init__(self, config: ReportConfig):
        self.config = config
        self._setup_matplotlib()

    def _setup_matplotlib(self):
        plt.style.use(self.config.chart_style)
        sns.set_palette("husl")

    @contextmanager
    def _chart_context(self, figsize: Tuple[int, int] = (10, 8)):
        fig, ax = plt.subplots(figsize=figsize)
        try:
            yield fig, ax
        finally:
            plt.close(fig)

    def create_pie_chart(self, data: Dict[str, int], title: str) -> Optional[str]:
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

    def _create_summary_table(self, report_data: Dict[str, Any]) -> Table:
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

class CSVReportGenerator:
    @staticmethod
    def generate_csv(report_data: Dict[str, Any], output_path: str) -> Optional[str]:
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
