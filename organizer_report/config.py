from dataclasses import dataclass
from reportlab.lib.pagesizes import A4

@dataclass
class ReportConfig:
    include_charts: bool = True
    include_email: bool = True
    chart_dpi: int = 72                  # ↓ Reduced DPI for smaller image size
    chart_style: str = 'default'        # ↓ Avoid seaborn (high memory)
    pdf_pagesize: tuple = A4
    default_currency: str = 'USD'
    limit_charts: bool = False          # Add this to disable chart generation when needed
