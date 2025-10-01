"""
AI Assistant Module for Ticketing System
Provides intelligent assistance for event management, sales analysis, and operations
"""

import logging
from typing import Optional
from config import Config

logger = logging.getLogger(__name__)

# Package version
__version__ = '1.0.0'

# Import core assistant + submodules
from ai.ai_assistant import AIAssistant
from ai.intent_classifier import IntentClassifier
from ai.action_executor import ActionExecutor
from ai.context_manager import ContextManager
from ai.analytics_engine import AnalyticsEngine
from ai.pricing_optimizer import PricingOptimizer
from ai.response_formatter import ResponseFormatter


class AIAssistantFactory:
    """Factory for creating AI Assistant instances with proper dependency injection"""

    _instance: Optional[AIAssistant] = None
    _initialized: bool = False

    @classmethod
    def get_instance(cls) -> AIAssistant:
        if cls._instance is None:
            cls._instance = cls._create_assistant()
            cls._initialized = True
            logger.info("AI Assistant singleton created")
        return cls._instance

    @classmethod
    def _create_assistant(cls) -> AIAssistant:
        return AIAssistant()

    @classmethod
    def reset(cls):
        cls._instance = None
        cls._initialized = False
        logger.info("AI Assistant singleton reset")

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._initialized


def get_ai_assistant() -> AIAssistant:
    """Get the AI Assistant instance"""
    return AIAssistantFactory.get_instance()


def is_ai_enabled() -> bool:
    """Check if AI features are enabled"""
    return Config.ENABLE_AI_FEATURES and bool(Config.OPENAI_API_KEY)


def get_ai_config() -> dict:
    """Get current AI configuration"""
    return {
        'enabled': is_ai_enabled(),
        'provider': Config.AI_PROVIDER,
        'model': Config.AI_MODEL,
        'temperature': Config.AI_TEMPERATURE,
        'max_tokens': Config.AI_MAX_TOKENS,
        'timeout': Config.AI_TIMEOUT,
        'version': __version__
    }


# Create singleton instance
ai_assistant = AIAssistantFactory.get_instance()

# Log initialization status
if is_ai_enabled():
    logger.info(f"AI Module initialized - Version: {__version__}, Provider: {Config.AI_PROVIDER}, Model: {Config.AI_MODEL}")
else:
    logger.warning(f"AI Module initialized but disabled - Version: {__version__}, AI features require OpenAI API key")


__all__ = [
    'ai_assistant',
    'AIAssistant',
    'IntentClassifier',
    'ActionExecutor',
    'ContextManager',
    'AnalyticsEngine',
    'PricingOptimizer',
    'ResponseFormatter',
    'get_ai_assistant'
]
