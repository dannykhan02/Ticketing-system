"""
AI Assistant Module for Ticketing System
Provides intelligent assistance for event management, sales analysis, and operations
"""
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ai.ai_assistant import AIAssistant

logger = logging.getLogger(__name__)

# Package version
__version__ = '1.0.0'

# Import core assistant + submodules (but don't instantiate yet)
from ai.intent_classifier import IntentClassifier
from ai.action_executor import ActionExecutor
from ai.context_manager import ContextManager
from ai.analytics_engine import AnalyticsEngine
from ai.pricing_optimizer import PricingOptimizer
from ai.response_formatter import ResponseFormatter


class AIAssistantFactory:
    """Factory for creating AI Assistant instances with proper dependency injection"""
    
    _instance: Optional['AIAssistant'] = None
    _initialized: bool = False
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            # Lazy import to avoid circular dependency
            from ai.ai_assistant import AIAssistant
            cls._instance = AIAssistant()
            cls._initialized = True
            logger.info("AI Assistant singleton created")
        return cls._instance
    
    @classmethod
    def reset(cls):
        cls._instance = None
        cls._initialized = False
        logger.info("AI Assistant singleton reset")
    
    @classmethod
    def is_initialized(cls) -> bool:
        return cls._initialized


def get_ai_assistant():
    """Get the AI Assistant instance (lazy-loaded)"""
    return AIAssistantFactory.get_instance()


def is_ai_enabled() -> bool:
    """Check if AI features are enabled"""
    try:
        from config import Config
        return Config.ENABLE_AI_FEATURES and bool(Config.OPENAI_API_KEY)
    except ImportError:
        return False


def get_ai_config() -> dict:
    """Get current AI configuration"""
    try:
        from config import Config
        return {
            'enabled': is_ai_enabled(),
            'provider': Config.AI_PROVIDER,
            'model': Config.AI_MODEL,
            'temperature': Config.AI_TEMPERATURE,
            'max_tokens': Config.AI_MAX_TOKENS,
            'timeout': Config.AI_TIMEOUT,
            'version': __version__
        }
    except ImportError:
        return {
            'enabled': False,
            'version': __version__
        }


# DO NOT create singleton instance at module level - this causes circular imports
# Instead, use get_ai_assistant() when you need the instance

# Log initialization status only if config is available
try:
    from config import Config
    if is_ai_enabled():
        logger.info(f"AI Module initialized - Version: {__version__}, Provider: {Config.AI_PROVIDER}, Model: {Config.AI_MODEL}")
    else:
        logger.info(f"AI Module initialized - Version: {__version__}, AI features disabled")
except ImportError:
    logger.info(f"AI Module initialized - Version: {__version__}, Config not yet available")


__all__ = [
    'AIAssistantFactory',
    'IntentClassifier',
    'ActionExecutor',
    'ContextManager',
    'AnalyticsEngine',
    'PricingOptimizer',
    'ResponseFormatter',
    'get_ai_assistant',
    'is_ai_enabled',
    'get_ai_config'
]