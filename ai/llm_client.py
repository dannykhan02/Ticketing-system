"""
Enhanced LLM Client with Circuit Breaker Pattern
Prevents cascade failures and provides better error handling
"""

from openai import OpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError, AuthenticationError
import logging
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from config import Config
from ai.utils.cache_manager import get_cache_manager

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker to prevent repeated failed API calls"""
    
    def __init__(self, failure_threshold=5, timeout=300):
        self.failure_threshold = failure_threshold
        self.timeout = timeout  # seconds before attempting reset
        self.failures = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def call_failed(self):
        """Record a failed call"""
        self.failures += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                f"Circuit breaker OPENED after {self.failures} failures. "
                f"Will retry after {self.timeout}s"
            )
    
    def call_succeeded(self):
        """Record a successful call"""
        self.failures = 0
        self.state = "CLOSED"
        logger.info("Circuit breaker CLOSED - service recovered")
    
    def can_attempt(self):
        """Check if we should attempt a call"""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            # Check if timeout has passed
            if self.last_failure_time:
                elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if elapsed >= self.timeout:
                    self.state = "HALF_OPEN"
                    logger.info("Circuit breaker entering HALF_OPEN state")
                    return True
            return False
        
        # HALF_OPEN state - allow one attempt
        return True
    
    def get_state(self):
        """Get current circuit breaker state"""
        return {
            "state": self.state,
            "failures": self.failures,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None
        }


class LLMClient:
    """Enhanced LLM client with circuit breaker and better error handling"""
    
    def __init__(self):
        """Initialize LLM client with config settings"""
        self.provider = Config.AI_PROVIDER
        self.model = Config.AI_MODEL
        self.temperature = Config.AI_TEMPERATURE
        self.max_tokens = Config.AI_MAX_TOKENS
        self.timeout = Config.AI_TIMEOUT
        self.max_retries = Config.AI_MAX_RETRIES
        self.rate_limit_wait = Config.AI_RATE_LIMIT_WAIT
        
        # Initialize circuit breaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            timeout=300  # 5 minutes
        )
        
        # Get API key based on provider
        if self.provider.lower() == "groq":
            self.api_key = Config.GROQ_API_KEY
            self.base_url = "https://api.groq.com/openai/v1"
        else:
            self.api_key = Config.OPENAI_API_KEY
            self.base_url = None
        
        # Validate API key format
        if self.api_key:
            if self.provider.lower() == "groq" and not self.api_key.startswith("gsk_"):
                logger.error("Invalid Groq API key format - should start with 'gsk_'")
                self.api_key = None
        
        logger.info(f"AI Provider: {self.provider}")
        logger.info(f"AI Features Enabled: {Config.ENABLE_AI_FEATURES}")
        logger.info(f"API Key Present: {bool(self.api_key)}")
        
        self.enabled = Config.ENABLE_AI_FEATURES and bool(self.api_key)
        
        # Initialize cache
        self.cache_enabled = Config.AI_CACHE_ENABLED
        if self.cache_enabled:
            self.cache = get_cache_manager(
                max_size=Config.AI_CACHE_MAX_SIZE,
                ttl=Config.AI_CACHE_TTL
            )
            logger.info(f"Cache enabled - Max size: {Config.AI_CACHE_MAX_SIZE}, TTL: {Config.AI_CACHE_TTL}s")
        else:
            self.cache = None
            logger.info("Cache disabled")
        
        # Configure client
        if self.enabled:
            try:
                client_kwargs = {
                    "api_key": self.api_key,
                    "timeout": self.timeout,
                    "max_retries": 0  # Handle retries manually
                }
                
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                
                self.client = OpenAI(**client_kwargs)
                logger.info(f"LLM Client initialized - Provider: {self.provider}, Model: {self.model}")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self.client = None
                self.enabled = False
        else:
            self.client = None
            logger.warning(f"LLM Client disabled - API key not configured for {self.provider}")
    
    def is_enabled(self) -> bool:
        """Check if LLM is enabled and available"""
        return self.enabled and self.circuit_breaker.can_attempt()
    
    def _calculate_retry_delay(self, attempt: int, error_type: str = "default") -> int:
        """Calculate retry delay with exponential backoff"""
        if error_type == "rate_limit":
            base_wait = self.rate_limit_wait
            return base_wait * (attempt + 1)
        else:
            return min(2 ** (attempt + 1), 30)
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        use_cache: bool = True,
        quick_mode: bool = False,
        **kwargs
    ) -> Optional[str]:
        """
        Get chat completion with enhanced error handling
        
        Args:
            messages: List of message dicts
            temperature: Override default temperature
            max_tokens: Override default max tokens
            use_cache: Whether to use cache
            quick_mode: If True, don't retry on failure (for real-time responses)
            **kwargs: Additional API parameters
        
        Returns:
            str: AI response or None if failed
        """
        if not self.enabled or not self.client:
            logger.warning(f"LLM not enabled (Provider: {self.provider})")
            return None
        
        # Check circuit breaker
        if not self.circuit_breaker.can_attempt():
            logger.warning(
                f"Circuit breaker {self.circuit_breaker.state} - skipping API call. "
                f"Failures: {self.circuit_breaker.failures}"
            )
            return None
        
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        
        # Check cache first
        if use_cache and self.cache_enabled and self.cache:
            cached_response = self.cache.get(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=self.model,
                **kwargs
            )
            if cached_response:
                logger.info("Returning cached response")
                return cached_response
        
        # Determine retry count based on mode
        max_attempts = 1 if quick_mode else (self.max_retries + 1)
        
        # Make API call with retry logic
        last_error = None
        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
                
                response_content = response.choices[0].message.content
                logger.info(f"LLM call successful (attempt {attempt + 1}/{max_attempts})")
                
                # Mark success in circuit breaker
                self.circuit_breaker.call_succeeded()
                
                # Cache the response
                if use_cache and self.cache_enabled and self.cache and response_content:
                    self.cache.set(
                        messages,
                        response_content,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model=self.model,
                        **kwargs
                    )
                
                return response_content
                
            except AuthenticationError as e:
                logger.error(f"{self.provider} authentication failed - check your API key")
                self.circuit_breaker.call_failed()
                return None
                
            except RateLimitError as e:
                last_error = e
                if not quick_mode and attempt < max_attempts - 1:
                    wait_time = self._calculate_retry_delay(attempt, "rate_limit")
                    logger.warning(
                        f"Rate limit (attempt {attempt + 1}/{max_attempts}). "
                        f"Waiting {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Rate limit exceeded after {attempt + 1} attempts")
                    self.circuit_breaker.call_failed()
                    return None
                
            except APITimeoutError as e:
                last_error = e
                if not quick_mode and attempt < max_attempts - 1:
                    wait_time = self._calculate_retry_delay(attempt)
                    logger.warning(
                        f"Timeout (attempt {attempt + 1}/{max_attempts}). "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Timeout after {attempt + 1} attempts")
                    self.circuit_breaker.call_failed()
                    return None
                
            except APIConnectionError as e:
                last_error = e
                if not quick_mode and attempt < max_attempts - 1:
                    wait_time = self._calculate_retry_delay(attempt)
                    logger.warning(
                        f"Connection error (attempt {attempt + 1}/{max_attempts}). "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Connection failed after {attempt + 1} attempts: {e}")
                    self.circuit_breaker.call_failed()
                    return None
                
            except APIError as e:
                last_error = e
                # Retry server errors (5xx)
                if hasattr(e, 'status_code') and 500 <= e.status_code < 600:
                    if not quick_mode and attempt < max_attempts - 1:
                        wait_time = self._calculate_retry_delay(attempt)
                        logger.warning(
                            f"Server error {e.status_code} "
                            f"(attempt {attempt + 1}/{max_attempts}). "
                            f"Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                        continue
                
                logger.error(f"API error: {e}")
                self.circuit_breaker.call_failed()
                return None
                
            except Exception as e:
                logger.error(f"Unexpected error: {type(e).__name__}: {e}")
                self.circuit_breaker.call_failed()
                return None
        
        # All retries exhausted
        if last_error:
            logger.error(f"All retries exhausted. Last error: {last_error}")
            self.circuit_breaker.call_failed()
        return None
    
    def get_health_status(self) -> Dict[str, any]:
        """Get health status of LLM client"""
        circuit_state = self.circuit_breaker.get_state()
        
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "circuit_breaker": circuit_state,
            "cache_enabled": self.cache_enabled,
            "cache_stats": self.get_cache_stats() if self.cache_enabled else None,
            "available": self.is_enabled()
        }
    
    def build_system_message(self, context: str = None) -> Dict[str, str]:
        """Build system message for AI assistant"""
        base_prompt = (
            "You are an AI assistant for a ticketing and event management system. "
            "Help users manage events, analyze sales data, check inventory, optimize pricing, "
            "and provide insights. Be concise, professional, and helpful. "
            "When providing data, format it clearly. "
            "If you need more information to help, ask specific questions."
        )
        
        if context:
            base_prompt += f"\n\nAdditional context: {context}"
        
        return {"role": "system", "content": base_prompt}
    
    def get_cache_stats(self) -> Optional[Dict[str, any]]:
        """Get cache statistics"""
        if self.cache_enabled and self.cache:
            return self.cache.get_stats()
        return None
    
    def clear_cache(self):
        """Clear all cached responses"""
        if self.cache_enabled and self.cache:
            self.cache.clear()
            logger.info("Cache cleared")
    
    def reset_circuit_breaker(self):
        """Manually reset circuit breaker (for admin use)"""
        self.circuit_breaker.failures = 0
        self.circuit_breaker.state = "CLOSED"
        logger.info("Circuit breaker manually reset")


# Singleton instance
llm_client = LLMClient()