import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import os

# ----------  GRAPH  ---------- #
def generate_graph_image(report, path: str = "report_graph.png") -> str:
    """Generate a bar‑chart image and return its path."""
    labels = list(report["tickets_sold_by_type"].keys())
    values = list(report["tickets_sold_by_type"].values())

    plt.figure(figsize=(8, 6))
    plt.bar(labels, values)
    plt.title("Tickets Sold by Type")
    plt.xlabel("Ticket Type")
    plt.ylabel("Count")
    plt.tight_layout()
    plt.savefig(path)
    plt.close()
    return path


# ----------  PDF  ---------- #
def generate_pdf_with_graph(
    report: dict,
    event_id: int,
    pdf_path: str = "ticket_report.pdf",
    graph_path: str = "report_graph.png",
) -> str:
    """
    Build a one‑page PDF with an embedded sales graph.

    Parameters
    ----------
    report      dict   – output of get_event_report(); may or may not contain 'event_id'
    event_id    int    – passed down by the caller so we never KeyError
    pdf_path    str    – where to write the PDF
    graph_path  str    – where the PNG graph is stored/should be saved
    """
    # if the caller hasn’t created the graph yet, do it here
    if not os.path.exists(graph_path):
        graph_path = generate_graph_image(report, graph_path)

    c = canvas.Canvas(pdf_path, pagesize=A4)

    # ---------- Header ----------
    c.setFont("Helvetica-Bold", 16)
    title = f"Event Report – ID {event_id}"
    if "event_name" in report:
        title = f"Event Report: {report['event_name']}"
    c.drawString(200, 800, title)

    # ---------- Graph ----------
    try:
        c.drawImage(ImageReader(graph_path), 100, 500, width=400, height=250)
    except Exception as e:
        print(f"[PDF] could not embed graph: {e}")

    # ---------- Details ----------
    c.setFont("Helvetica", 12)
    c.drawString(100, 470, "Graph shows ticket sales by category.")
    c.drawString(100, 450, f"Total Tickets Sold: {report['total_tickets_sold']}")
    c.drawString(100, 430, f"Total Revenue: ${report['total_revenue']:.2f}")

    # optional keys – print only if present
    y = 410
    for key, label in (
        ("event_date", "Date"),
        ("event_location", "Location"),
    ):
        if key in report:
            c.drawString(100, y, f"{label}: {report[key]}")
            y -= 20

    c.save()
    return pdf_path
