"""
AI Assistant Module for Ticketing System
Provides intelligent assistance for event management, sales analysis, and operations
"""

from flask import Blueprint

# Package version
__version__ = '1.0.0'

# Import main components for easier access
from ai.ai_assistant import AIAssistant
from ai.intent_classifier import IntentClassifier
from ai.action_executor import ActionExecutor
from ai.context_manager import ContextManager
from ai.analytics_engine import AnalyticsEngine
from ai.pricing_optimizer import PricingOptimizer
from ai.response_formatter import ResponseFormatter

__all__ = [
    'AIAssistant',
    'IntentClassifier',
    'ActionExecutor',
    'ContextManager',
    'AnalyticsEngine',
    'PricingOptimizer',
    'ResponseFormatter'
]