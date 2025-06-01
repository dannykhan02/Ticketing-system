# import matplotlib.pyplot as plt
# from reportlab.lib.pagesizes import A4
# from reportlab.pdfgen import canvas
# from reportlab.lib.utils import ImageReader
# from reportlab.lib import colors
# from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
# from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
# from reportlab.lib.enums import TA_CENTER, TA_LEFT
# import os
# import logging

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# # Define specific colors for each ticket type, matching frontend (use uppercase keys)
# COLORS_BY_TICKET_PYTHON = {
#     'REGULAR': '#FF8042',        # Orange
#     'VIP': '#FFBB28',            # Yellow
#     'STUDENT': '#0088FE',        # Blue
#     'GROUP_OF_5': '#00C49F',     # Green
#     'COUPLES': '#FF6699',        # Pinkish
#     'EARLY_BIRD': '#AA336A',     # Purple
#     'VVIP': '#00FF00',           # Bright Green for VVIP
#     'GIVEAWAY': '#CCCCCC',       # Grey
#     'UNKNOWN_TYPE': '#A9A9A9',   # Darker Grey for unknown types
# }

# # Fallback color if a ticket type is not in COLORS_BY_TICKET_PYTHON
# FALLBACK_COLOR_PYTHON = COLORS_BY_TICKET_PYTHON.get('UNKNOWN_TYPE', '#808080')

# # ---------- GRAPH (Donut Chart) ---------- #
# def generate_graph_image(report: dict, path: str = "report_graph.png") -> str:
#     """
#     Generate a donut chart image for Revenue by Ticket Type.

#     Parameters
#     ----------
#     report  dict    – The event report dictionary containing revenue data.
#     path    str     – The path to save the generated image.

#     Returns
#     -------
#     str     – The path to the saved image file.
#     """
#     revenue_data = report.get("revenue_by_ticket_type", {})

#     # Extract labels (ticket types) and values (revenue amounts)
#     # Ensure labels are uppercase for consistent color mapping
#     labels = [label.upper() for label in revenue_data.keys()]
#     values = list(revenue_data.values())

#     # Map colors based on ticket type labels
#     chart_colors = [COLORS_BY_TICKET_PYTHON.get(label, FALLBACK_COLOR_PYTHON) for label in labels]

#     # --- Create the Donut Chart ---
#     fig, ax = plt.subplots(figsize=(7, 7), facecolor='#1e1e1e') # Set figure background to dark color
#     ax.set_facecolor('#1e1e1e') # Set axes background to dark color

#     # Ensure there are values to plot, otherwise pie() might raise an error
#     if not values or sum(values) == 0:
#         logger.info("No revenue data > 0 to plot in donut chart. Generating placeholder.")
#         ax.text(0, 0, "No Revenue Data Available", ha='center', va='center', color='#cccccc', fontsize=14)
#         chart_colors = [FALLBACK_COLOR_PYTHON] # Use fallback color for empty circle
#         values = [1] # Plot a single slice to show an empty state circle
#         labels = ['No Data']
#         autopct = '' # No percentage for no data
#     else:
#         autopct='%1.1f%%' # Percentage format


#     wedges, texts, autotexts = ax.pie(
#         values,
#         labels=labels, # Use ticket type names as labels
#         colors=chart_colors, # Use the mapped colors
#         autopct=autopct, # Display percentages if data exists
#         startangle=140, # Starting angle for the first slice
#         pctdistance=0.85, # Distance of the percentage label from the center
#         textprops={'color': '#cccccc'} # Set text color for labels/percentages
#     )

#     # Draw a circle in the center (to make it a donut)
#     # Use a dark color for the center circle background
#     centre_circle = plt.Circle((0, 0), 0.70, fc='#2a2a2a')
#     fig.gca().add_artist(centre_circle)

#     # --- Styling ---
#     ax.axis('equal')  # Equal aspect ratio ensures the pie is a circle
#     plt.title('Revenue by Ticket Type', color='#cccccc', fontsize=16) # Set title and color
#     plt.tight_layout() # Adjust layout to prevent labels overlapping

#     # --- Save the image ---
#     try:
#         plt.savefig(path, transparent=False, dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor()) # Save with dark background
#         logger.info(f"Graph image saved to {path}")
#     except Exception as e:
#         logger.error(f"Error saving graph image to {path}: {e}")
#         # Handle potential errors during saving
#         if os.path.exists(path):
#             os.remove(path) # Clean up potentially corrupted file
#         path = "" # Indicate failure

#     plt.close(fig) # Close the figure to free memory
#     return path

# # ---------- PDF Generation ---------- #
# def generate_pdf_with_graph(
#     report: dict,
#     event_id: int,
#     pdf_path: str = "ticket_report.pdf",
#     graph_path: str = "report_graph.png",
# ) -> str:
#     """
#     Build a one-page PDF with an embedded sales graph and details.

#     Parameters
#     ----------
#     report      dict    – output of get_event_report(); MUST contain 'event_name', 'total_tickets_sold', 'total_revenue', etc.
#     event_id    int     – Used in the report title if event_name is missing.
#     pdf_path    str     – where to write the PDF.
#     graph_path  str     – where the PNG graph is stored/should be saved by generate_graph_image.

#     Returns
#     -------
#     str     – The path to the generated PDF file.
#     """
#     # Ensure graph image exists or try to generate it
#     if not os.path.exists(graph_path) or os.path.getsize(graph_path) == 0:
#         logger.info(f"Graph image not found or is empty at {graph_path}, attempting to generate.")
#         try:
#             generated_graph_path = generate_graph_image(report, graph_path)
#             if not generated_graph_path or not os.path.exists(generated_graph_path) or os.path.getsize(generated_graph_path) == 0:
#                 logger.error("Failed to generate graph image for PDF.")
#                 graph_path = None
#             else:
#                 graph_path = generated_graph_path
#         except Exception as e:
#             logger.error(f"Error during graph image generation for PDF: {e}")
#             graph_path = None

#     doc = SimpleDocTemplate(pdf_path, pagesize=A4)
#     styles = getSampleStyleSheet()

#     # Custom style for title and subheadings
#     styles.add(ParagraphStyle(name='ReportTitle',
#                               parent=styles['h1'],
#                               fontSize=20,
#                               spaceAfter=14,
#                               alignment=TA_CENTER,
#                               textColor=colors.HexColor('#333333'))) # Dark grey title

#     styles.add(ParagraphStyle(name='SubHeading',
#                               parent=styles['h2'],
#                               fontSize=14,
#                               spaceBefore=10,
#                               spaceAfter=6,
#                               textColor=colors.HexColor('#444444'))) # Slightly lighter grey subheadings

#     # Renamed the custom BodyText style to CustomBodyText to avoid collision
#     styles.add(ParagraphStyle(name='CustomBodyText',
#                               parent=styles['Normal'],
#                               fontSize=10,
#                               leading=14,
#                               spaceBefore=4,
#                               textColor=colors.HexColor('#555555'),
#                               alignment=TA_LEFT)) # Regular text color

#     styles.add(ParagraphStyle(name='SmallText',
#                               parent=styles['Normal'],
#                               fontSize=9,
#                               leading=11,
#                               spaceBefore=2,
#                               textColor=colors.HexColor('#777777'),
#                               alignment=TA_LEFT)) # Smaller, lighter text for filters

#     # Updated parent to 'CustomBodyText' for DescriptionStyle
#     styles.add(ParagraphStyle(name='DescriptionStyle',
#                               parent=styles['CustomBodyText'],
#                               fontSize=10,
#                               leading=12,
#                               textColor=colors.HexColor('#666666'),
#                               alignment=TA_LEFT, # Changed to left align for descriptions
#                               spaceAfter=10))


#     elements = []

#     # Title
#     title = f"Event Report: {report.get('event_name', f'ID {event_id}')}"
#     elements.append(Paragraph(title, styles['ReportTitle']))
#     elements.append(Spacer(1, 0.2 * 0.5 * A4[1])) # Space below title

#     # Filtered Date Range (if applicable)
#     filter_start_date = report.get('filter_start_date')
#     filter_end_date = report.get('filter_end_date')

#     if filter_start_date != "N/A" or filter_end_date != "N/A":
#         elements.append(Paragraph("<b>Report Filter:</b>", styles['SmallText']))
#         elements.append(Paragraph(f"Start Date: {filter_start_date} | End Date: {filter_end_date}", styles['SmallText']))
#         elements.append(Spacer(1, 10))

#     # Graph
#     if graph_path and os.path.exists(graph_path) and os.path.getsize(graph_path) > 0:
#         try:
#             img = Image(graph_path)
#             img.drawWidth = 400  # Set a fixed width
#             img.drawHeight = 400 # Set a fixed height
#             img.hAlign = 'CENTER'
#             elements.append(img)
#             elements.append(Spacer(1, 20)) # Space after graph
#         except Exception as e:
#             logger.error(f"[PDF] could not embed graph from {graph_path}: {e}")
#             elements.append(Paragraph("Error embedding graph image or Graph image not available.", styles['CustomBodyText']))
#             elements.append(Spacer(1, 10))
#     else:
#         elements.append(Paragraph("Graph image not available.", styles['CustomBodyText']))
#         elements.append(Spacer(1, 10))


#     # Details Section
#     elements.append(Paragraph("<b>Summary Details:</b>", styles['SubHeading']))
#     elements.append(Paragraph(f"<b>Total Tickets Sold:</b> {report.get('total_tickets_sold', 'N/A')}", styles['CustomBodyText']))
#     total_revenue = report.get('total_revenue', 0)
#     elements.append(Paragraph(f"<b>Total Revenue:</b> ${total_revenue:.2f}", styles['CustomBodyText']))
#     elements.append(Paragraph(f"<b>Number of Attendees:</b> {report.get('number_of_attendees', 'N/A')}", styles['CustomBodyText']))
#     elements.append(Spacer(1, 10))

#     # Event Details
#     elements.append(Paragraph("<b>Event Information:</b>", styles['SubHeading']))
#     elements.append(Paragraph(f"<b>Event Date:</b> {report.get('event_date', 'N/A')}", styles['CustomBodyText']))
#     elements.append(Paragraph(f"<b>Event Location:</b> {report.get('event_location', 'N/A')}", styles['CustomBodyText']))

#     # Description (handle long text)
#     description = report.get('event_description')
#     if description:
#         elements.append(Paragraph(f"<b>Event Description:</b>", styles['CustomBodyText']))
#         elements.append(Paragraph(description, styles['DescriptionStyle']))
#     elements.append(Spacer(1, 20))

#     # Generate the PDF
#     try:
#         doc.build(elements)
#         logger.info(f"PDF report saved to {pdf_path}")
#     except Exception as e:
#         logger.error(f"Error saving PDF report to {pdf_path}: {e}")
#         if os.path.exists(pdf_path):
#             os.remove(pdf_path)
#         pdf_path = ""
#     return pdf_path

import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define specific colors for each ticket type - using string hex values for matplotlib
COLORS_BY_TICKET_MATPLOTLIB = {
    'REGULAR': '#FF8042',        # Orange
    'VIP': '#FFBB28',            # Yellow
    'STUDENT': '#0088FE',        # Blue
    'GROUP_OF_5': '#00C49F',     # Green
    'COUPLES': '#FF6699',        # Pinkish
    'EARLY_BIRD': '#AA336A',     # Purple
    'VVIP': '#00FF00',           # Bright Green for VVIP
    'GIVEAWAY': '#CCCCCC',       # Grey
    'UNKNOWN_TYPE': '#A9A9A9',   # Darker Grey for unknown types
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

def generate_graph_image(report: dict, path: str = "report_graph.png") -> str:
    """
    Generate a donut chart image for Revenue by Ticket Type.

    Parameters
    ----------
    report: dict
        The event report dictionary containing revenue data.
    path: str
        The path to save the generated image.

    Returns
    -------
    str
        The path to the saved image file.
    """
    try:
        revenue_data = report.get("revenue_by_ticket_type", {})

        # Extract labels (ticket types) and values (revenue amounts)
        labels = [label.upper() for label in revenue_data.keys()]
        values = list(revenue_data.values())

        # Map colors based on ticket type labels - use matplotlib color format
        chart_colors = [COLORS_BY_TICKET_MATPLOTLIB.get(label, FALLBACK_COLOR_MATPLOTLIB) for label in labels]

        # Create the Donut Chart
        fig, ax = plt.subplots(figsize=(7, 7), facecolor='#1e1e1e')
        ax.set_facecolor('#1e1e1e')

        # Ensure there are values to plot, otherwise pie() might raise an error
        if not values or sum(values) == 0:
            logger.info("No revenue data > 0 to plot in donut chart. Generating placeholder.")
            ax.text(0, 0, "No Revenue Data Available", ha='center', va='center', color='#cccccc', fontsize=14)
            chart_colors = [FALLBACK_COLOR_MATPLOTLIB]  # Use fallback color for empty circle
            values = [1]  # Plot a single slice to show an empty state circle
            labels = ['No Data']
            autopct = ''  # No percentage for no data
        else:
            autopct = '%1.1f%%'  # Percentage format

        # Create the pie chart with proper error handling
        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=chart_colors,
            autopct=autopct,
            startangle=140,
            pctdistance=0.85,
            textprops={'color': '#cccccc'}
        )

        # Draw a circle in the center (to make it a donut)
        centre_circle = plt.Circle((0, 0), 0.70, fc='#2a2a2a')
        fig.gca().add_artist(centre_circle)

        # Styling
        ax.axis('equal')  # Equal aspect ratio ensures the pie is a circle
        plt.title('Revenue by Ticket Type', color='#cccccc', fontsize=16)
        plt.tight_layout()

        # Save the image
        plt.savefig(path, transparent=False, dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
        logger.info(f"Graph image saved to {path}")

    except Exception as e:
        logger.error(f"Error generating graph image: {e}")
        # Create a simple fallback image
        try:
            fig, ax = plt.subplots(figsize=(7, 7), facecolor='#1e1e1e')
            ax.set_facecolor('#1e1e1e')
            ax.text(0, 0, "Error generating chart", ha='center', va='center', color='#cccccc', fontsize=14)
            ax.axis('equal')
            plt.title('Revenue by Ticket Type', color='#cccccc', fontsize=16)
            plt.savefig(path, transparent=False, dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
            logger.info(f"Fallback graph image saved to {path}")
        except Exception as fallback_error:
            logger.error(f"Error creating fallback graph: {fallback_error}")
            if os.path.exists(path):
                os.remove(path)  # Clean up potentially corrupted file
            path = ""  # Indicate failure
    finally:
        plt.close('all')  # Close all figures to free memory

    return path

def generate_pdf_with_graph(report: dict, event_id: int, pdf_path: str = "ticket_report.pdf", graph_path: str = "report_graph.png") -> str:
    """
    Build a one-page PDF with an embedded sales graph and details.

    Parameters
    ----------
    report: dict
        Output of get_event_report(); MUST contain 'event_name', 'total_tickets_sold', 'total_revenue', etc.
    event_id: int
        Used in the report title if event_name is missing.
    pdf_path: str
        Where to write the PDF.
    graph_path: str
        Where the PNG graph is stored/should be saved by generate_graph_image.

    Returns
    -------
    str
        The path to the generated PDF file.
    """
    # Ensure graph image exists or try to generate it
    if not os.path.exists(graph_path) or os.path.getsize(graph_path) == 0:
        logger.info(f"Graph image not found or is empty at {graph_path}, attempting to generate.")
        try:
            generated_graph_path = generate_graph_image(report, graph_path)
            if not generated_graph_path or not os.path.exists(generated_graph_path) or os.path.getsize(generated_graph_path) == 0:
                logger.error("Failed to generate graph image for PDF.")
                graph_path = None
            else:
                graph_path = generated_graph_path
        except Exception as e:
            logger.error(f"Error during graph image generation for PDF: {e}")
            graph_path = None

    try:
        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        styles = getSampleStyleSheet()

        # Custom style for title and subheadings
        styles.add(ParagraphStyle(name='ReportTitle',
                                   parent=styles['h1'],
                                   fontSize=20,
                                   spaceAfter=14,
                                   alignment=TA_CENTER,
                                   textColor=colors.HexColor('#333333')))  # Dark grey title

        styles.add(ParagraphStyle(name='SubHeading',
                                   parent=styles['h2'],
                                   fontSize=14,
                                   spaceBefore=10,
                                   spaceAfter=6,
                                   textColor=colors.HexColor('#4a154b')))  # Purple subheadings

        styles.add(ParagraphStyle(name='CustomBodyText',
                                   parent=styles['Normal'],
                                   fontSize=10,
                                   leading=14,
                                   spaceBefore=4,
                                   textColor=colors.HexColor('#555555'),
                                   alignment=TA_LEFT))  # Regular text color

        styles.add(ParagraphStyle(name='SmallText',
                                   parent=styles['Normal'],
                                   fontSize=9,
                                   leading=11,
                                   spaceBefore=2,
                                   textColor=colors.HexColor('#777777'),
                                   alignment=TA_LEFT))  # Smaller, lighter text for filters

        styles.add(ParagraphStyle(name='DescriptionStyle',
                                   parent=styles['CustomBodyText'],
                                   fontSize=10,
                                   leading=12,
                                   textColor=colors.HexColor('#666666'),
                                   alignment=TA_LEFT,
                                   spaceAfter=10))

        elements = []

        # Title
        title = f"Event Report: {report.get('event_name', f'ID {event_id}')}"
        elements.append(Paragraph(title, styles['ReportTitle']))
        elements.append(Spacer(1, 0.2 * 0.5 * A4[1]))  # Space below title

        # Filtered Date Range (if applicable)
        filter_start_date = report.get('filter_start_date')
        filter_end_date = report.get('filter_end_date')

        if filter_start_date != "N/A" or filter_end_date != "N/A":
            elements.append(Paragraph("<b>Report Filter:</b>", styles['SmallText']))
            elements.append(Paragraph(f"Start Date: {filter_start_date} | End Date: {filter_end_date}", styles['SmallText']))
            elements.append(Spacer(1, 10))

        # Graph
        if graph_path and os.path.exists(graph_path) and os.path.getsize(graph_path) > 0:
            try:
                img = Image(graph_path)
                img.drawWidth = 400  # Set a fixed width
                img.drawHeight = 400  # Set a fixed height
                img.hAlign = 'CENTER'
                elements.append(img)
                elements.append(Spacer(1, 20))  # Space after graph
            except Exception as e:
                logger.error(f"[PDF] could not embed graph from {graph_path}: {e}")
                elements.append(Paragraph("Error embedding graph image or Graph image not available.", styles['CustomBodyText']))
                elements.append(Spacer(1, 10))
        else:
            elements.append(Paragraph("Graph image not available.", styles['CustomBodyText']))
            elements.append(Spacer(1, 10))

        # Details Section
        elements.append(Paragraph("<b>Summary Details:</b>", styles['SubHeading']))
        elements.append(Paragraph(f"<b>Total Tickets Sold:</b> {report.get('total_tickets_sold', 'N/A')}", styles['CustomBodyText']))
        total_revenue = report.get('total_revenue', 0)
        elements.append(Paragraph(f"<b>Total Revenue:</b> ${total_revenue:.2f}", styles['CustomBodyText']))
        elements.append(Paragraph(f"<b>Number of Attendees:</b> {report.get('number_of_attendees', 'N/A')}", styles['CustomBodyText']))
        elements.append(Spacer(1, 10))

        # Event Details
        elements.append(Paragraph("<b>Event Information:</b>", styles['SubHeading']))
        elements.append(Paragraph(f"<b>Event Date:</b> {report.get('event_date', 'N/A')}", styles['CustomBodyText']))
        elements.append(Paragraph(f"<b>Event Location:</b> {report.get('event_location', 'N/A')}", styles['CustomBodyText']))

        # Description (handle long text)
        description = report.get('event_description')
        if description:
            elements.append(Paragraph(f"<b>Event Description:</b>", styles['CustomBodyText']))
            elements.append(Paragraph(description, styles['DescriptionStyle']))
        elements.append(Spacer(1, 20))

        # Generate the PDF
        doc.build(elements)
        logger.info(f"PDF report saved to {pdf_path}")

    except Exception as e:
        logger.error(f"Error saving PDF report to {pdf_path}: {e}")
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        pdf_path = ""

    return pdf_path