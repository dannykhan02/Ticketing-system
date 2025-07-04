import csv
import logging
from typing import Dict, Any
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define specific colors for each ticket type - using string hex values for matplotlib
COLORS_BY_TICKET_MATPLOTLIB = {
    'REGULAR': '#FF8042',    # Orange
    'VIP': '#FFBB28',        # Yellow
    'STUDENT': '#0088FE',    # Blue
    'GROUP_OF_5': '#00C49F', # Green
    'COUPLES': '#FF6699',    # Pink
    'EARLY_BIRD': '#AA336A', # Purple
    'VVIP': '#00FF00',       # Bright Green for VVIP
    'GIVEAWAY': '#CCCCCC',   # Grey
    'UNKNOWN_TYPE': '#A9A9A9', # Darker Grey for unknown types
}

# Separate color definitions for ReportLab (using HexColor objects)
COLORS_BY_TICKET_REPORTLAB = {
    'REGULAR': colors.HexColor('#FF8042'),
    'VIP': colors.HexColor('#FFBB28'),
    'STUDENT': colors.HexColor('#0088FE'),
    'GROUP_OF_5': colors.HexColor('#00C49F'),
    'COUPLES': colors.HexColor('#FF6699'),
    'EARLY_BIRD': colors.HexColor('#AA336A'),
    'VVIP': colors.HexColor('#00FF00'),
    'GIVEAWAY': colors.HexColor('#CCCCCC'),
    'UNKNOWN_TYPE': colors.HexColor('#A9A9A9'),
}

# Fallback colors
FALLBACK_COLOR_MATPLOTLIB = '#808080'
FALLBACK_COLOR_REPORTLAB = colors.HexColor('#808080')

def generate_graph_image(report: Dict, path: str = "report_graph.png") -> str:
    """
    Generate a donut chart image for Revenue by Ticket Type.
    Parameters
    ----------
    report : dict
        The event report dictionary containing revenue data.
    path : str, optional
        The path to save the generated image (default: "report_graph.png").
    Returns
    -------
    str
        The path to the saved image file, or empty string if generation failed.
    """
    try:
        # Retrieve and log the revenue data for debugging
        revenue_data = report.get("revenue_by_ticket_type", {})
        logger.info(f"Raw revenue_by_ticket_type: {revenue_data} ({type(revenue_data)})")

        # Validate the revenue data format
        if not isinstance(revenue_data, dict):
            logger.warning("Expected 'revenue_by_ticket_type' to be a dictionary")
            raise ValueError("Invalid revenue data format")

        # Filter out zero or negative values and prepare data
        filtered_data = {k: v for k, v in revenue_data.items() if isinstance(v, (int, float)) and v > 0}

        if not filtered_data:
            logger.warning("No positive revenue data found for chart generation")
            raise ValueError("No valid revenue data to plot")

        # Extract labels (ticket types) and values (revenue amounts)
        labels = [label.upper() for label in filtered_data.keys()]
        values = list(filtered_data.values())

        # Map colors based on ticket type labels
        chart_colors = [COLORS_BY_TICKET_MATPLOTLIB.get(label, FALLBACK_COLOR_MATPLOTLIB) for label in labels]

        # Create the Donut Chart with improved styling
        fig, ax = plt.subplots(figsize=(8, 8), facecolor='#1e1e1e')
        ax.set_facecolor('#1e1e1e')

        # Create the pie chart with enhanced styling
        autopct = lambda pct: f'{pct:.1f}%\n(${values[int(pct/100*len(values))]:.0f})' if pct > 5 else ''
        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=chart_colors,
            autopct=autopct,
            startangle=90,
            pctdistance=0.85,
            textprops={'color': '#cccccc', 'fontsize': 10, 'weight': 'bold'},
            wedgeprops={'linewidth': 2, 'edgecolor': '#2a2a2a'}
        )

        # Create donut hole with better styling
        centre_circle = plt.Circle((0, 0), 0.65, fc='#2a2a2a', linewidth=2, edgecolor='#1e1e1e')
        fig.gca().add_artist(centre_circle)

        # Add total revenue in center if data exists
        total_revenue = sum(values)
        ax.text(0, 0, f'Total Revenue\n${total_revenue:.2f}', ha='center', va='center',
                color='#ffffff', fontsize=12, weight='bold')

        # Enhanced styling
        ax.axis('equal')
        plt.title('Revenue by Ticket Type', color='#ffffff', fontsize=18, weight='bold', pad=20)
        plt.tight_layout()

        # Save with higher quality
        plt.savefig(path, transparent=False, dpi=300, bbox_inches='tight',
                    facecolor=fig.get_facecolor(), edgecolor='none')
        logger.info(f"Graph image successfully saved to {path}")

    except Exception as e:
        logger.error(f"Error generating graph image: {e}")
        # Create a fallback image with error message
        try:
            fig, ax = plt.subplots(figsize=(8, 8), facecolor='#1e1e1e')
            ax.set_facecolor('#1e1e1e')
            ax.text(0, 0, "Error Generating Chart\nPlease check data format",
                    ha='center', va='center', color='#ff6b6b', fontsize=14, weight='bold')
            ax.axis('equal')
            plt.title('Revenue by Ticket Type', color='#ffffff', fontsize=18, weight='bold', pad=20)
            plt.savefig(path, transparent=False, dpi=300, bbox_inches='tight',
                        facecolor=fig.get_facecolor())
            logger.info(f"Fallback error chart saved to {path}")
        except Exception as fallback_error:
            logger.error(f"Error creating fallback graph: {fallback_error}")
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return ""

    finally:
        plt.close('all')  # Ensure all figures are closed to prevent memory leaks

    return path if os.path.exists(path) and os.path.getsize(path) > 0 else ""

def generate_pdf_with_graph(report: Dict, event_id: int, pdf_path: str = "ticket_report.pdf",
                            graph_path: str = "report_graph.png") -> str:
    """
    Build a comprehensive one-page PDF report with embedded sales graph and event details.
    Parameters
    ----------
    report : dict
        Output of get_event_report(); MUST contain 'event_name', 'total_tickets_sold',
        'total_revenue', etc.
    event_id : int
        Used in the report title if event_name is missing.
    pdf_path : str, optional
        Where to write the PDF (default: "ticket_report.pdf").
    graph_path : str, optional
        Where the PNG graph is stored/should be saved (default: "report_graph.png").
    Returns
    -------
    str
        The path to the generated PDF file, or empty string if generation failed.
    """
    # Validate input parameters
    if not isinstance(report, dict):
        logger.error("Report parameter must be a dictionary")
        return ""
    # Ensure graph image exists or generate it
    if not os.path.exists(graph_path) or os.path.getsize(graph_path) == 0:
        logger.info(f"Graph image not found at {graph_path}, generating new one")
        try:
            generated_graph_path = generate_graph_image(report, graph_path)
            graph_path = generated_graph_path if generated_graph_path else None
        except Exception as e:
            logger.error(f"Failed to generate graph image for PDF: {e}")
            graph_path = None
    try:
        # Initialize PDF document with metadata
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )
        styles = getSampleStyleSheet()
        # Enhanced custom styles
        styles.add(ParagraphStyle(
            name='ReportTitle',
            parent=styles['Heading1'],
            fontSize=22,
            spaceAfter=16,
            spaceBefore=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#2c3e50'),
            fontName='Helvetica-Bold'
        ))
        styles.add(ParagraphStyle(
            name='SubHeading',
            parent=styles['Heading2'],
            fontSize=16,
            spaceBefore=12,
            spaceAfter=8,
            textColor=colors.HexColor('#34495e'),
            fontName='Helvetica-Bold'
        ))
        styles.add(ParagraphStyle(
            name='CustomBodyText',
            parent=styles['Normal'],
            fontSize=11,
            leading=16,
            spaceBefore=4,
            spaceAfter=4,
            textColor=colors.HexColor('#2c3e50'),
            fontName='Helvetica'
        ))
        styles.add(ParagraphStyle(
            name='FilterText',
            parent=styles['Normal'],
            fontSize=10,
            leading=12,
            spaceBefore=2,
            spaceAfter=6,
            textColor=colors.HexColor('#7f8c8d'),
            fontName='Helvetica-Oblique',
            alignment=TA_CENTER
        ))
        styles.add(ParagraphStyle(
            name='HighlightText',
            parent=styles['CustomBodyText'],
            fontSize=12,
            textColor=colors.HexColor('#e74c3c'),
            fontName='Helvetica-Bold'
        ))
        elements = []
        # Enhanced title with event information
        event_name = report.get('event_name', f'Event ID {event_id}')
        title = f"Event Analytics Report"
        subtitle = f"{event_name}"
        elements.append(Paragraph(title, styles['ReportTitle']))
        elements.append(Paragraph(subtitle, styles['SubHeading']))
        elements.append(Spacer(1, 12))
        # Filter information with better formatting
        filter_start_date = report.get('filter_start_date', 'N/A')
        filter_end_date = report.get('filter_end_date', 'N/A')
        if filter_start_date != "N/A" or filter_end_date != "N/A":
            filter_text = f"Report Period: {filter_start_date} to {filter_end_date}"
            elements.append(Paragraph(filter_text, styles['FilterText']))
            elements.append(Spacer(1, 16))
        # Revenue graph with improved error handling
        if graph_path and os.path.exists(graph_path) and os.path.getsize(graph_path) > 0:
            try:
                img = Image(graph_path)
                # Maintain aspect ratio while fitting within page
                img.drawWidth = min(400, A4[0] - 144)  # Account for margins
                img.drawHeight = min(400, A4[0] - 144)
                img.hAlign = 'CENTER'
                elements.append(img)
                elements.append(Spacer(1, 20))
            except Exception as e:
                logger.error(f"Failed to embed graph from {graph_path}: {e}")
                elements.append(Paragraph("📊 Chart visualization unavailable", styles['CustomBodyText']))
                elements.append(Spacer(1, 12))
        else:
            elements.append(Paragraph("📊 Chart visualization not available", styles['CustomBodyText']))
            elements.append(Spacer(1, 12))
        # Key metrics section with improved formatting
        elements.append(Paragraph("📈 Key Performance Metrics", styles['SubHeading']))
        total_tickets = report.get('total_tickets_sold', 0)
        total_revenue = report.get('total_revenue', 0)
        attendees = report.get('number_of_attendees', 0)
        elements.append(Paragraph(f"<b>Total Tickets Sold:</b> {total_tickets:,}", styles['CustomBodyText']))
        elements.append(Paragraph(f"<b>Total Revenue Generated:</b> ${total_revenue:,.2f}", styles['HighlightText']))
        elements.append(Paragraph(f"<b>Number of Attendees:</b> {attendees:,}", styles['CustomBodyText']))
        # Calculate average ticket price if possible
        if total_tickets > 0:
            avg_price = total_revenue / total_tickets
            elements.append(Paragraph(f"<b>Average Ticket Price:</b> ${avg_price:.2f}", styles['CustomBodyText']))
        elements.append(Spacer(1, 16))
        # Event details section
        elements.append(Paragraph("📅 Event Information", styles['SubHeading']))
        event_date = report.get('event_date', 'Not specified')
        event_location = report.get('event_location', 'Not specified')
        elements.append(Paragraph(f"<b>Event Date:</b> {event_date}", styles['CustomBodyText']))
        elements.append(Paragraph(f"<b>Event Location:</b> {event_location}", styles['CustomBodyText']))
        # Event description with text wrapping
        description = report.get('event_description', '').strip()
        if description:
            elements.append(Spacer(1, 8))
            elements.append(Paragraph("<b>Event Description:</b>", styles['CustomBodyText']))
            # Limit description length for PDF formatting
            if len(description) > 500:
                description = description[:497] + "..."
            elements.append(Paragraph(description, styles['CustomBodyText']))
        # Add footer spacer
        elements.append(Spacer(1, 20))
        # Generate PDF with error handling
        doc.build(elements)
        logger.info(f"PDF report successfully generated and saved to {pdf_path}")
    except Exception as e:
        logger.error(f"Error generating PDF report: {e}")
        # Clean up potentially corrupted file
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except OSError:
                pass
        return ""
    return pdf_path if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0 else ""

class PDFReportGenerator:
    @staticmethod
    def generate_pdf_report(report_data: Dict, config=None) -> str:
        event_id = report_data.get("event_id", 0)
        pdf_path = f"report_{event_id}.pdf"
        graph_path = f"report_graph_{event_id}.png"
        return generate_pdf_with_graph(report_data, event_id, pdf_path, graph_path)

class CSVExporter:
    @staticmethod
    def generate_csv_report(data: Dict) -> str:
        if not data:
            return ""
        # Example: Convert report data to CSV format
        output = "Field1,Field2\n"
        output += f"{data.get('field1', '')},{data.get('field2', '')}\n"
        return output
