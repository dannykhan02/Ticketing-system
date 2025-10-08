# """
# AI models package - Import all AI-related models
# """

# # Existing AI models
# from .conversation import AIConversation, AIMessage
# from .action import AIActionLog
# from .preferences import AIUserPreference
# from .analytics import AIAnalyticsCache, AIUsageMetrics, AIQueryTemplate
# from .insight import (
#     AIInsight, 
#     AIPricingRecommendation, 
#     AIEventSuggestion,
#     AIFeedback, 
#     AIRevenueAnalysis, 
#     AITicketAnalysis
# )

# # Partner AI models (new)
# from .partner_insight import AIPartnerInsight
# from .partner_match_recommendation import AIPartnerMatchRecommendation

# __all__ = [
#     # Conversation
#     'AIConversation',
#     'AIMessage',
    
#     # Actions
#     'AIActionLog',
    
#     # Preferences
#     'AIUserPreference',
    
#     # Analytics
#     'AIAnalyticsCache',
#     'AIUsageMetrics',
#     'AIQueryTemplate',
    
#     # Insights
#     'AIInsight',
#     'AIPricingRecommendation',
#     'AIEventSuggestion',
#     'AIFeedback',
#     'AIRevenueAnalysis',
#     'AITicketAnalysis',
    
#     # Partner AI
#     'AIPartnerInsight',
#     'AIPartnerMatchRecommendation',
# ]