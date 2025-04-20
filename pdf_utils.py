import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import os

def generate_graph_image(report, path="report_graph.png"):
    """Generate a bar chart image for the report."""
    labels = list(report['tickets_sold_by_type'].keys())
    values = list(report['tickets_sold_by_type'].values())

    plt.figure(figsize=(8, 6))
    plt.bar(labels, values, color='skyblue')
    plt.title("Tickets Sold by Type")
    plt.xlabel("Ticket Type")
    plt.ylabel("Count")
    plt.tight_layout()
    plt.savefig(path)
    plt.close()

def generate_pdf_with_graph(report, pdf_path="ticket_report.pdf", graph_path="report_graph.png"):
    """Generate a PDF report with an embedded graph image."""
    c = canvas.Canvas(pdf_path, pagesize=A4)

    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawString(200, 800, f"Event Report: {report['event_name']}")

    # Insert the graph image
    try:
        image = ImageReader(graph_path)
        c.drawImage(image, 100, 500, width=400, height=250)
    except Exception as e:
        print(f"Error adding image to PDF: {e}")

    # Additional text
    c.setFont("Helvetica", 12)
    c.drawString(100, 470, "This graph represents ticket sales by category.")
    c.drawString(100, 450, f"Total Tickets Sold: {report['total_tickets_sold']}")
    c.drawString(100, 430, f"Total Revenue: ${report['total_revenue']:.2f}")
    c.drawString(100, 410, f"Date: {report['event_date']}")
    c.drawString(100, 390, f"Location: {report['event_location']}")

    c.save()
