from dataclasses import dataclass
from reportlab.lib.pagesizes import A4

@dataclass
class ReportConfig:
    include_charts: bool = True
    include_email: bool = True
    chart_dpi: int = 300
    chart_style: str = 'seaborn-v0_8'
    pdf_pagesize: tuple = A4
    default_currency: str = 'USD'
