# """
# Models package initialization
# Imports all models and managers for easy access
# """
# from .base import db

# # Core models
# from .user import User
# from .organizer import Organizer
# from .event import Event, Category, AICategoryInsight
# from .ticket import Ticket, TicketType, TransactionTicket
# from .transaction import Transaction
# from .scan import Scan
# from .report import Report
# from .currency import Currency, ExchangeRate
# from .partner import Partner
# from .collaboration import EventCollaboration

# # Enums
# from .enums import (
#     UserRole, TicketTypeEnum, PaymentStatus, PaymentMethod,
#     CurrencyCode, CollaborationType, AIIntentType, 
#     AIActionStatus, AICachePriority
# )

# # AI models
# from .ai.conversation import AIConversation, AIMessage
# from .ai.action import AIActionLog
# from .ai.preferences import AIUserPreference
# from .ai.analytics import (
#     AIAnalyticsCache, AIUsageMetrics, AIQueryTemplate
# )
# from .ai.insight import (
#     AIInsight, AIPricingRecommendation, AIEventSuggestion,
#     AIFeedback, AIRevenueAnalysis, AITicketAnalysis
# )
# from .ai.partner_insight import AIPartnerInsight
# from .ai.partner_match_recommendation import AIPartnerMatchRecommendation

# # Managers
# from managers.ai_manager import AIManager
# from managers.collaboration_manager import CollaborationManager
# from managers.currency_converter import CurrencyConverter

# __all__ = [
#     # Database
#     'db',
    
#     # Enums
#     'UserRole', 'TicketTypeEnum', 'PaymentStatus', 'PaymentMethod',
#     'CurrencyCode', 'CollaborationType', 'AIIntentType',
#     'AIActionStatus', 'AICachePriority',
    
#     # Core Models
#     'User', 'Organizer', 'Event', 'Category', 'Ticket', 
#     'TicketType', 'Transaction', 'TransactionTicket', 'Scan',
#     'Report', 'Currency', 'ExchangeRate', 'Partner', 
#     'EventCollaboration',
    
#     # AI Models
#     'AIConversation', 'AIMessage', 'AIActionLog', 
#     'AIUserPreference', 'AIAnalyticsCache', 'AIInsight',
#     'AIPricingRecommendation', 'AIEventSuggestion',
#     'AICategoryInsight', 'AIQueryTemplate', 'AIUsageMetrics',
#     'AIFeedback', 'AIRevenueAnalysis', 'AITicketAnalysis',
#     'AIPartnerInsight', 'AIPartnerMatchRecommendation',
    
#     # Managers
#     'AIManager', 'CollaborationManager', 'CurrencyConverter'
# ]