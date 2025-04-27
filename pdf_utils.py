import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors # Import colors for ReportLab
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Define specific colors for each ticket type, matching frontend (use uppercase keys)
COLORS_BY_TICKET_PYTHON = {
  'REGULAR': '#FF8042',     # Orange
  'VIP': '#FFBB28',         # Yellow
  'STUDENT': '#0088FE',     # Blue
  'GROUP_OF_5': '#00C49F',  # Green
  'COUPLES': '#FF6699',     # Pinkish
  'EARLY_BIRD': '#AA336A',  # Purple
  'VVIP': '#00FF00',        # Bright Green for VVIP
  'GIVEAWAY': '#CCCCCC',    # Grey
  'UNKNOWN_TYPE': '#A9A9A9', # Darker Grey for unknown types
  # Ensure all possible ticket types from your backend are mapped here
}

# Fallback color if a ticket type is not in COLORS_BY_TICKET_PYTHON
FALLBACK_COLOR_PYTHON = COLORS_BY_TICKET_PYTHON.get('UNKNOWN_TYPE', '#808080') # Use get with a default


# ----------  GRAPH (Donut Chart)  ---------- #
def generate_graph_image(report: dict, path: str = "report_graph.png") -> str:
    """
    Generate a donut chart image for Revenue by Ticket Type.

    Parameters
    ----------
    report    dict   – The event report dictionary containing revenue data.
    path      str    – The path to save the generated image.

    Returns
    -------
    str   – The path to the saved image file.
    """
    # --- Prepare data for the chart ---
    # Use revenue_by_ticket_type data for the donut chart
    revenue_data = report.get("revenue_by_ticket_type", {})

    if not revenue_data:
        logger.warning(f"No revenue data by ticket type found for graph generation. Report: {report.get('event_name', 'Unknown Event')}")
        # Optionally, generate a placeholder image or return a specific path indicating no data
        # For now, let's proceed, which might result in an empty chart

    # Extract labels (ticket types) and values (revenue amounts)
    # Ensure labels are uppercase for consistent color mapping
    labels = [label.upper() for label in revenue_data.keys()]
    values = list(revenue_data.values())

    # Map colors based on ticket type labels
    chart_colors = [COLORS_BY_TICKET_PYTHON.get(label, FALLBACK_COLOR_PYTHON) for label in labels]

    # --- Create the Donut Chart ---
    fig, ax = plt.subplots(figsize=(7, 7), facecolor='#1e1e1e') # Set figure background to dark color
    ax.set_facecolor('#1e1e1e') # Set axes background to dark color

    # Ensure there are values to plot, otherwise pie() might raise an error
    if not values or sum(values) == 0:
         logger.info("No revenue data > 0 to plot in donut chart.")
         ax.text(0, 0, "No Revenue Data", ha='center', va='center', color='#cccccc', fontsize=14)
         chart_colors = [FALLBACK_COLOR_PYTHON] # Use fallback color for empty circle
         values = [1] # Plot a single slice to show an empty state circle
         labels = ['No Data']
         autopct = '' # No percentage for no data
    else:
         autopct='%1.1f%%' # Percentage format


    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels, # Use ticket type names as labels
        colors=chart_colors, # Use the mapped colors
        autopct=autopct, # Display percentages if data exists
        startangle=140, # Starting angle for the first slice
        pctdistance=0.85, # Distance of the percentage label from the center
         textprops={'color': '#cccccc'} # Set text color for labels/percentages
    )

    # Draw a circle in the center (to make it a donut)
    # Use a dark color for the center circle background
    centre_circle = plt.Circle((0, 0), 0.70, fc='#2a2a2a')
    fig.gca().add_artist(centre_circle)

    # --- Styling ---
    ax.axis('equal')  # Equal aspect ratio ensures the pie is a circle
    plt.title('Revenue by Ticket Type', color='#cccccc', fontsize=16) # Set title and color
    plt.tight_layout() # Adjust layout to prevent labels overlapping

    # --- Save the image ---
    try:
         plt.savefig(path, transparent=False, dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor()) # Save with dark background
         logger.info(f"Graph image saved to {path}")
    except Exception as e:
         logger.error(f"Error saving graph image to {path}: {e}")
         # Handle potential errors during saving
         if os.path.exists(path):
             os.remove(path) # Clean up potentially corrupted file
         path = "" # Indicate failure

    plt.close(fig) # Close the figure to free memory
    return path

# ----------  PDF  ---------- #
def generate_pdf_with_graph(
    report: dict,
    event_id: int, # event_id is provided but not used in this function based on current code
    pdf_path: str = "ticket_report.pdf",
    graph_path: str = "report_graph.png",
) -> str:
    """
    Build a one-page PDF with an embedded sales graph and details.

    Parameters
    ----------
    report      dict   – output of get_event_report(); MUST contain 'event_name', 'total_tickets_sold', 'total_revenue', etc.
    event_id    int    – Used in the report title if event_name is missing.
    pdf_path    str    – where to write the PDF.
    graph_path  str    – where the PNG graph is stored/should be saved by generate_graph_image.

    Returns
    -------
    str   – The path to the generated PDF file.
    """
    # Ensure graph image exists or try to generate it
    if not os.path.exists(graph_path) or os.path.getsize(graph_path) == 0:
        logger.info(f"Graph image not found or is empty at {graph_path}, attempting to generate.")
        try:
             generated_graph_path = generate_graph_image(report, graph_path)
             if not generated_graph_path or not os.path.exists(generated_graph_path) or os.path.getsize(generated_graph_path) == 0:
                 logger.error("Failed to generate graph image.")
                 graph_path = None # Indicate graph is not available
             else:
                 graph_path = generated_graph_path # Use the path if successful
        except Exception as e:
             logger.error(f"Error during graph image generation: {e}")
             graph_path = None # Indicate graph is not available

    # --- Create PDF Canvas ---
    c = canvas.Canvas(pdf_path, pagesize=A4)

    # Set default text color to a dark grey for better contrast on white PDF background
    c.setFillColor(colors.black) # Using black for simplicity, could use a dark grey like colors.darkgrey

    # ---------- Header ----------
    c.setFont("Helvetica-Bold", 16)
    # Use event_name if available, otherwise use event_id in the title
    title = f"Event Report: {report.get('event_name', f'ID {event_id}')}"
    # Center the title (approximately)
    text_width = c.stringWidth(title, "Helvetica-Bold", 16)
    page_width, page_height = A4
    x_position = (page_width - text_width) / 2
    c.drawString(x_position, 800, title)


    # ---------- Graph ----------
    # Position the graph roughly centered below the title
    graph_width = 400
    graph_height = 400 # Donut charts are typically square or taller than bar charts
    graph_x = (page_width - graph_width) / 2
    graph_y = 800 - 50 - graph_height # Position below title with padding

    if graph_path and os.path.exists(graph_path) and os.path.getsize(graph_path) > 0:
        try:
            c.drawImage(ImageReader(graph_path), graph_x, graph_y, width=graph_width, height=graph_height, preserveAspectRatio=True)
            logger.info(f"Graph image embedded into PDF from {graph_path}")
        except Exception as e:
            logger.error(f"[PDF] could not embed graph from {graph_path}: {e}")
            # Optionally draw a placeholder text indicating graph failure
            c.setFont("Helvetica-Oblique", 10)
            c.setFillColor(colors.red)
            c.drawString(graph_x, graph_y + graph_height / 2, "Error embedding graph image")
            c.setFillColor(colors.black) # Reset color
    else:
         # Draw placeholder text if graph generation failed or file was invalid
        c.setFont("Helvetica-Oblique", 10)
        c.setFillColor(colors.red)
        c.drawString(graph_x, graph_y + graph_height / 2, "Graph image not available")
        c.setFillColor(colors.black) # Reset color


    # ---------- Details ----------
    # Position details below the graph
    details_y_start = graph_y - 30 # Start 30 points below the graph
    current_y = details_y_start
    x_margin = 100 # Left margin for text details

    c.setFont("Helvetica", 12)

    # Add static detail text
    c.drawString(x_margin, current_y, "Report Details:")
    current_y -= 20 # Move down for next line

    # Ensure expected keys exist in the report dictionary before accessing
    c.drawString(x_margin, current_y, f"Total Tickets Sold: {report.get('total_tickets_sold', 'N/A')}")
    current_y -= 20

    # Format total revenue as currency
    total_revenue = report.get('total_revenue', 0)
    c.drawString(x_margin, current_y, f"Total Revenue: ${total_revenue:.2f}")
    current_y -= 20

    # Add optional keys only if present in the report
    details_keys = [
        ("event_date", "Date"),
        ("event_location", "Location"),
        ("event_description", "Description"), # Added description
        # Add other keys from your report dictionary if needed
    ]

    for key, label in details_keys:
        if key in report and report[key] is not None: # Check if key exists and value is not None
             # Basic handling for potentially long description
             if key == "event_description":
                  description = report[key]
                  c.drawString(x_margin, current_y, f"{label}:")
                  current_y -= 15 # Move down for description text
                  # Use a TextObject for wrapping long text
                  description_text_object = c.beginText(x_margin + 10, current_y) # Indent description slightly
                  description_text_object.setFont("Helvetica", 10) # Smaller font for description
                  description_text_object.setFillColor(colors.darkgrey) # Different color for description
                  description_width = page_width - 2 * x_margin - 10 # Calculate available width
                  # Wrap the text
                  lines = []
                  words = description.split()
                  current_line = ""
                  for word in words:
                      if c.stringWidth(current_line + word, "Helvetica", 10) < description_width:
                           current_line += word + " "
                      else:
                           lines.append(current_line.strip())
                           current_line = word + " "
                  lines.append(current_line.strip())

                  for line in lines:
                      description_text_object.textLine(line)
                      current_y -= 12 # Adjust y position based on smaller font and line spacing

                  c.drawText(description_text_object)
                  current_y -= 10 # Add space after description block
                  c.setFillColor(colors.black) # Reset color
                  c.setFont("Helvetica", 12) # Reset font
             else:
                c.drawString(x_margin, current_y, f"{label}: {report[key]}")
                current_y -= 20 # Move down for next line
        # Add more space if needed between detail lines

    # Add a footer or page number if desired

    # --- Save PDF ---
    try:
        c.save()
        logger.info(f"PDF report saved to {pdf_path}")
    except Exception as e:
         logger.error(f"Error saving PDF report to {pdf_path}: {e}")
         # Handle potential errors during saving
         if os.path.exists(pdf_path):
             os.remove(pdf_path) # Clean up potentially corrupted file
         pdf_path = "" # Indicate failure

    return pdf_path