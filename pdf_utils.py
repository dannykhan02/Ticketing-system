import csv
import logging
from typing import Dict, Any, Optional, List
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

def validate_and_process_report_data(report: Dict) -> Dict:
    """
    Validate and process report data, adding debugging information.
    
    Parameters
    ----------
    report : dict
        The raw report data
        
    Returns
    -------
    dict
        Processed and validated report data
    """
    logger.info("=== REPORT DATA VALIDATION ===")
    logger.info(f"Report keys: {list(report.keys())}")
    
    # Log all data for debugging
    for key, value in report.items():
        logger.info(f"{key}: {value} (type: {type(value)})")
    
    # Check if revenue_by_ticket_type exists and has valid data
    revenue_data = report.get("revenue_by_ticket_type", {})
    logger.info(f"Revenue data type: {type(revenue_data)}")
    logger.info(f"Revenue data content: {revenue_data}")
    
    # If revenue_by_ticket_type is empty, try to construct it from other data
    if not revenue_data or not isinstance(revenue_data, dict):
        logger.warning("Empty or invalid revenue_by_ticket_type, attempting to reconstruct...")
        
        # Try to find ticket sales data to construct revenue data
        ticket_sales = report.get("ticket_sales_by_type", {})
        ticket_prices = report.get("ticket_prices", {})
        
        if ticket_sales and ticket_prices:
            constructed_revenue = {}
            for ticket_type, quantity in ticket_sales.items():
                price = ticket_prices.get(ticket_type, 0)
                if quantity > 0 and price > 0:
                    constructed_revenue[ticket_type] = quantity * price
            
            if constructed_revenue:
                logger.info(f"Reconstructed revenue data: {constructed_revenue}")
                report["revenue_by_ticket_type"] = constructed_revenue
            else:
                logger.warning("Could not reconstruct revenue data from ticket sales and prices")
        
        # If still no data, check for individual ticket records
        if not report.get("revenue_by_ticket_type"):
            tickets = report.get("tickets", [])
            if tickets:
                revenue_by_type = {}
                for ticket in tickets:
                    ticket_type = ticket.get("type", "UNKNOWN_TYPE").upper()
                    price = ticket.get("price", 0)
                    if price > 0:
                        revenue_by_type[ticket_type] = revenue_by_type.get(ticket_type, 0) + price
                
                if revenue_by_type:
                    logger.info(f"Constructed revenue from individual tickets: {revenue_by_type}")
                    report["revenue_by_ticket_type"] = revenue_by_type
    
    # Final validation
    final_revenue = report.get("revenue_by_ticket_type", {})
    if final_revenue:
        logger.info(f"Final revenue data: {final_revenue}")
        # Validate data types
        valid_revenue = {}
        for ticket_type, amount in final_revenue.items():
            if isinstance(amount, (int, float)) and amount > 0:
                valid_revenue[ticket_type.upper()] = amount
            else:
                logger.warning(f"Invalid revenue amount for {ticket_type}: {amount}")
        
        report["revenue_by_ticket_type"] = valid_revenue
    else:
        logger.warning("No valid revenue data found after all attempts")
    
    return report

def generate_sample_data_for_testing(event_id: int = 1) -> Dict:
    """
    Generate sample data for testing purposes.
    
    Parameters
    ----------
    event_id : int
        Event ID for the sample data
        
    Returns
    -------
    dict
        Sample report data
    """
    return {
        "event_id": event_id,
        "event_name": "Sample Music Festival",
        "event_date": "2024-07-15",
        "event_location": "Central Park, New York",
        "event_description": "A fantastic music festival featuring top artists from around the world.",
        "total_tickets_sold": 1500,
        "total_revenue": 75000.00,
        "number_of_attendees": 1450,
        "revenue_by_ticket_type": {
            "REGULAR": 30000.00,
            "VIP": 25000.00,
            "STUDENT": 12000.00,
            "COUPLES": 8000.00
        },
        "ticket_sales_by_type": {
            "REGULAR": 1000,
            "VIP": 250,
            "STUDENT": 200,
            "COUPLES": 50
        },
        "filter_start_date": "2024-07-01",
        "filter_end_date": "2024-07-31"
    }

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
        # Validate and process the report data first
        processed_report = validate_and_process_report_data(report)
        
        # Retrieve and log the revenue data for debugging
        revenue_data = processed_report.get("revenue_by_ticket_type", {})
        logger.info(f"Processed revenue_by_ticket_type: {revenue_data} ({type(revenue_data)})")

        # Validate the revenue data format
        if not isinstance(revenue_data, dict):
            logger.warning("Expected 'revenue_by_ticket_type' to be a dictionary")
            raise ValueError("Invalid revenue data format")

        # Filter out zero or negative values and prepare data
        filtered_data = {k: v for k, v in revenue_data.items() if isinstance(v, (int, float)) and v > 0}

        if not filtered_data:
            logger.warning("No positive revenue data found for chart generation")
            # Instead of raising an error, create a "No Data" chart
            return create_no_data_chart(processed_report, path)

        # Extract labels (ticket types) and values (revenue amounts)
        labels = [label.upper() for label in filtered_data.keys()]
        values = list(filtered_data.values())

        # Map colors based on ticket type labels
        chart_colors = [COLORS_BY_TICKET_MATPLOTLIB.get(label, FALLBACK_COLOR_MATPLOTLIB) for label in labels]

        # Create the Donut Chart with improved styling
        fig, ax = plt.subplots(figsize=(8, 8), facecolor='#1e1e1e')
        ax.set_facecolor('#1e1e1e')

        # Fixed autopct function - create a closure to capture values
        def make_autopct(values):
            def autopct_func(pct):
                absolute = int(pct/100.*sum(values))
                return f'{pct:.1f}%\n(${absolute:.0f})' if pct > 5 else ''
            return autopct_func

        # Create the pie chart with enhanced styling
        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=chart_colors,
            autopct=make_autopct(values),
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
        ax.text(0, 0, f'Total Revenue\n${total_revenue:,.2f}', ha='center', va='center',
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
        return create_error_chart(path, str(e))

    finally:
        plt.close('all')  # Ensure all figures are closed to prevent memory leaks

    return path if os.path.exists(path) and os.path.getsize(path) > 0 else ""

def create_no_data_chart(report: Dict, path: str) -> str:
    """
    Create a chart indicating no data is available.
    """
    try:
        fig, ax = plt.subplots(figsize=(8, 8), facecolor='#1e1e1e')
        ax.set_facecolor('#1e1e1e')
        
        # Create a simple circle to represent "no data"
        circle = plt.Circle((0, 0), 0.8, fc='#404040', linewidth=3, edgecolor='#606060')
        ax.add_patch(circle)
        
        # Add text indicating no data
        ax.text(0, 0.1, "No Revenue Data", ha='center', va='center', 
                color='#ffffff', fontsize=16, weight='bold')
        ax.text(0, -0.1, "Available", ha='center', va='center', 
                color='#cccccc', fontsize=12)
        
        # Check if there's any other data to display
        total_tickets = report.get('total_tickets_sold', 0)
        if total_tickets > 0:
            ax.text(0, -0.3, f"Tickets Sold: {total_tickets}", ha='center', va='center',
                    color='#99ccff', fontsize=10)
        
        ax.set_xlim(-1.2, 1.2)
        ax.set_ylim(-1.2, 1.2)
        ax.axis('equal')
        ax.axis('off')
        
        plt.title('Revenue by Ticket Type', color='#ffffff', fontsize=18, weight='bold', pad=20)
        plt.tight_layout()
        
        plt.savefig(path, transparent=False, dpi=300, bbox_inches='tight',
                    facecolor=fig.get_facecolor(), edgecolor='none')
        logger.info(f"No data chart saved to {path}")
        
        return path
        
    except Exception as e:
        logger.error(f"Error creating no data chart: {e}")
        return create_error_chart(path, "No data available")
    finally:
        plt.close('all')

def create_error_chart(path: str, error_message: str = "Error generating chart") -> str:
    """
    Create a fallback error chart.
    """
    try:
        fig, ax = plt.subplots(figsize=(8, 8), facecolor='#1e1e1e')
        ax.set_facecolor('#1e1e1e')
        
        # Create error visualization
        ax.text(0, 0.1, "Chart Generation Error", ha='center', va='center', 
                color='#ff6b6b', fontsize=14, weight='bold')
        ax.text(0, -0.1, "Please check data format", ha='center', va='center',
                color='#ff9999', fontsize=10)
        
        # Add a simple error icon (triangle with exclamation)
        triangle = plt.Polygon([[-0.1, -0.4], [0.1, -0.4], [0, -0.6]], 
                              closed=True, fill=True, color='#ff6b6b')
        ax.add_patch(triangle)
        ax.text(0, -0.5, '!', ha='center', va='center', 
                color='#1e1e1e', fontsize=12, weight='bold')
        
        ax.set_xlim(-1, 1)
        ax.set_ylim(-1, 1)
        ax.axis('equal')
        ax.axis('off')
        
        plt.title('Revenue by Ticket Type', color='#ffffff', fontsize=18, weight='bold', pad=20)
        plt.tight_layout()
        
        plt.savefig(path, transparent=False, dpi=300, bbox_inches='tight',
                    facecolor=fig.get_facecolor())
        logger.info(f"Error chart saved to {path}")
        
        return path
        
    except Exception as fallback_error:
        logger.error(f"Error creating fallback chart: {fallback_error}")
        return ""
    finally:
        plt.close('all')

def generate_pdf_with_graph(report: Dict, event_id: int, pdf_path: str = "ticket_report.pdf",
                            graph_path: str = "report_graph.png") -> str:
    """
    Build a comprehensive one-page PDF report with embedded sales graph and event details.
    """
    # Validate input parameters
    if not isinstance(report, dict):
        logger.error("Report parameter must be a dictionary")
        return ""
    
    # Validate and process the report data
    processed_report = validate_and_process_report_data(report)
    
    # Log the processed report data for debugging
    logger.info(f"Generating PDF for processed report with keys: {list(processed_report.keys())}")
    
    # Ensure graph image exists or generate it
    if not os.path.exists(graph_path) or os.path.getsize(graph_path) == 0:
        logger.info(f"Graph image not found at {graph_path}, generating new one")
        try:
            generated_graph_path = generate_graph_image(processed_report, graph_path)
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
        
        styles.add(ParagraphStyle(
            name='WarningText',
            parent=styles['CustomBodyText'],
            fontSize=11,
            textColor=colors.HexColor('#f39c12'),
            fontName='Helvetica-Bold'
        ))
        
        elements = []
        
        # Enhanced title with event information
        event_name = processed_report.get('event_name', f'Event ID {event_id}')
        title = f"Event Analytics Report"
        subtitle = f"{event_name}"
        elements.append(Paragraph(title, styles['ReportTitle']))
        elements.append(Paragraph(subtitle, styles['SubHeading']))
        elements.append(Spacer(1, 12))
        
        # Filter information with better formatting
        filter_start_date = processed_report.get('filter_start_date', 'N/A')
        filter_end_date = processed_report.get('filter_end_date', 'N/A')
        if filter_start_date != "N/A" or filter_end_date != "N/A":
            filter_text = f"Report Period: {filter_start_date} to {filter_end_date}"
            elements.append(Paragraph(filter_text, styles['FilterText']))
            elements.append(Spacer(1, 16))
        
        # Check if we have revenue data
        revenue_data = processed_report.get("revenue_by_ticket_type", {})
        has_revenue_data = bool(revenue_data and any(isinstance(v, (int, float)) and v > 0 for v in revenue_data.values()))
        
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
                
                # Add note if no revenue data
                if not has_revenue_data:
                    elements.append(Paragraph("⚠️ No revenue data available for this event", styles['WarningText']))
                    elements.append(Spacer(1, 12))
                    
            except Exception as e:
                logger.error(f"Failed to embed graph from {graph_path}: {e}")
                elements.append(Paragraph("📊 Chart visualization unavailable", styles['CustomBodyText']))
                elements.append(Spacer(1, 12))
        else:
            elements.append(Paragraph("📊 Chart visualization not available", styles['CustomBodyText']))
            elements.append(Spacer(1, 12))
        
        # Key metrics section with improved formatting
        elements.append(Paragraph("📈 Key Performance Metrics", styles['SubHeading']))
        total_tickets = processed_report.get('total_tickets_sold', 0)
        total_revenue = processed_report.get('total_revenue', 0)
        attendees = processed_report.get('number_of_attendees', 0)
        
        elements.append(Paragraph(f"<b>Total Tickets Sold:</b> {total_tickets:,}", styles['CustomBodyText']))
        elements.append(Paragraph(f"<b>Total Revenue Generated:</b> ${total_revenue:,.2f}", styles['HighlightText']))
        elements.append(Paragraph(f"<b>Number of Attendees:</b> {attendees:,}", styles['CustomBodyText']))
        
        # Calculate average ticket price if possible
        if total_tickets > 0:
            avg_price = total_revenue / total_tickets
            elements.append(Paragraph(f"<b>Average Ticket Price:</b> ${avg_price:.2f}", styles['CustomBodyText']))
        
        # Add data status information
        if not has_revenue_data and total_tickets == 0:
            elements.append(Spacer(1, 8))
            elements.append(Paragraph("⚠️ <b>Note:</b> This event appears to have no ticket sales or revenue data. This could indicate:", styles['WarningText']))
            elements.append(Paragraph("• Event has not started selling tickets yet", styles['CustomBodyText']))
            elements.append(Paragraph("• All tickets were complimentary/free", styles['CustomBodyText']))
            elements.append(Paragraph("• Data sync issues with the ticketing system", styles['CustomBodyText']))
        
        elements.append(Spacer(1, 16))
        
        # Event details section
        elements.append(Paragraph("📅 Event Information", styles['SubHeading']))
        event_date = processed_report.get('event_date', 'Not specified')
        event_location = processed_report.get('event_location', 'Not specified')
        elements.append(Paragraph(f"<b>Event Date:</b> {event_date}", styles['CustomBodyText']))
        elements.append(Paragraph(f"<b>Event Location:</b> {event_location}", styles['CustomBodyText']))
        
        # Event description with text wrapping
        description = processed_report.get('event_description', '').strip()
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

# Testing function
def test_with_sample_data():
    """Test the PDF generation with sample data."""
    sample_data = generate_sample_data_for_testing()
    result = PDFReportGenerator.generate_pdf_report(sample_data)
    print(f"Test PDF generated: {result}")
    return result

def test_with_empty_data():
    """Test the PDF generation with empty data."""
    empty_data = {
        "event_id": 999,
        "event_name": "Empty Event",
        "revenue_by_ticket_type": {},
        "total_tickets_sold": 0,
        "total_revenue": 0.0
    }
    result = PDFReportGenerator.generate_pdf_report(empty_data)
    print(f"Empty data test PDF generated: {result}")
    return result

if __name__ == "__main__":
    print("Testing PDF generation...")
    test_with_sample_data()
    test_with_empty_data()