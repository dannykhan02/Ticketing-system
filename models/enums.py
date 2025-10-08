# """
# Enumerations for the ticketing system
# All enum types used across models
# """
# import enum

# class UserRole(enum.Enum):
#     ADMIN = "ADMIN"
#     ORGANIZER = "ORGANIZER"
#     ATTENDEE = "ATTENDEE"
#     SECURITY = "SECURITY"
    
#     def __str__(self):
#         return self.value

# class TicketTypeEnum(enum.Enum):
#     REGULAR = "REGULAR"
#     VIP = "VIP"
#     STUDENT = "STUDENT"
#     GROUP_OF_5 = "GROUP_OF_5"
#     COUPLES = "COUPLES"
#     EARLY_BIRD = "EARLY_BIRD"
#     VVIP = "VVIP"
#     GIVEAWAY = "GIVEAWAY"

# class PaymentStatus(enum.Enum):
#     PENDING = 'pending'
#     COMPLETED = 'completed'
#     PAID = 'paid'
#     FAILED = 'failed'
#     REFUNDED = 'refunded'
#     CANCELED = 'canceled'
#     CHARGEBACK = 'chargeback'
#     ON_HOLD = 'on_hold'

# class PaymentMethod(enum.Enum):
#     MPESA = 'Mpesa'
#     PAYSTACK = 'Paystack'

# class CurrencyCode(enum.Enum):
#     USD = "USD"
#     EUR = "EUR"
#     GBP = "GBP"
#     KES = "KES"
#     UGX = "UGX"
#     TZS = "TZS"
#     NGN = "NGN"
#     GHS = "GHS"
#     ZAR = "ZAR"
#     JPY = "JPY"
#     CAD = "CAD"
#     AUD = "AUD"

# class CollaborationType(enum.Enum):
#     PARTNER = "Partner"
#     OFFICIAL_PARTNER = "Official Partner"
#     COLLABORATOR = "Collaborator"
#     SUPPORTER = "Supporter"
#     MEDIA_PARTNER = "Media Partner"
    
#     def __str__(self):
#         return self.value

# class AIIntentType(enum.Enum):
#     """Types of user intents the AI can recognize"""
#     CREATE_EVENT = "create_event"
#     UPDATE_EVENT = "update_event"
#     DELETE_EVENT = "delete_event"
#     SEARCH_EVENTS = "search_events"
#     CREATE_TICKETS = "create_tickets"
#     UPDATE_TICKETS = "update_tickets"
#     ANALYZE_SALES = "analyze_sales"
#     GENERATE_REPORT = "generate_report"
#     MANAGE_PARTNERS = "manage_partners"
#     PRICING_RECOMMENDATION = "pricing_recommendation"
#     INVENTORY_CHECK = "inventory_check"
#     REVENUE_ANALYSIS = "revenue_analysis"
#     BULK_OPERATION = "bulk_operation"
#     GENERAL_QUERY = "general_query"

# class AIActionStatus(enum.Enum):
#     """Status of AI-executed actions"""
#     PENDING = "pending"
#     IN_PROGRESS = "in_progress"
#     COMPLETED = "completed"
#     FAILED = "failed"
#     REQUIRES_CONFIRMATION = "requires_confirmation"
#     CANCELLED = "cancelled"

# class AICachePriority(enum.Enum):
#     """Priority levels for cached analytics"""
#     LOW = "low"
#     MEDIUM = "medium"
#     HIGH = "high"
#     CRITICAL = "critical"