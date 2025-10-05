"""
Centralized LLM Client for AI Features
Handles all Groq API interactions with proper error handling, retries, and caching
"""

from openai import OpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError, AuthenticationError
import logging
import time
from typing import List, Dict, Optional
from config import Config
from ai.utils.cache_manager import get_cache_manager

logger = logging.getLogger(__name__)


class LLMClient:
    """Centralized client for LLM interactions (supports Groq and OpenAI)"""
    
    def __init__(self):
        """Initialize LLM client with config settings"""
        self.provider = Config.AI_PROVIDER
        self.model = Config.AI_MODEL
        self.temperature = Config.AI_TEMPERATURE
        self.max_tokens = Config.AI_MAX_TOKENS
        self.timeout = Config.AI_TIMEOUT
        self.max_retries = Config.AI_MAX_RETRIES
        self.rate_limit_wait = Config.AI_RATE_LIMIT_WAIT
        
        # Get API key based on provider
        if self.provider.lower() == "groq":
            self.api_key = Config.GROQ_API_KEY
            self.base_url = "https://api.groq.com/openai/v1"
        else:  # Default to OpenAI
            self.api_key = Config.OPENAI_API_KEY
            self.base_url = None  # Use OpenAI's default
        
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
        
        # Configure client with retries DISABLED
        if self.enabled:
            client_kwargs = {
                "api_key": self.api_key,
                "timeout": self.timeout,
                "max_retries": 0  # CRITICAL: Disable internal retries
            }
            
            # Add base_url for Groq
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            
            self.client = OpenAI(**client_kwargs)
            logger.info(f"LLM Client initialized - Provider: {self.provider}, Model: {self.model}")
        else:
            self.client = None
            logger.warning(f"LLM Client initialized but disabled - API key not configured for {self.provider}")
    
    def is_enabled(self) -> bool:
        """Check if LLM is enabled and configured"""
        return self.enabled
    
    def _calculate_retry_delay(self, attempt: int, error_type: str = "default") -> int:
        """
        Calculate retry delay with exponential backoff
        
        Args:
            attempt: Current retry attempt (0-indexed)
            error_type: Type of error for specialized backoff
        
        Returns:
            int: Wait time in seconds
        """
        if error_type == "rate_limit":
            # For rate limits, use longer progressive waits
            # 60s, 120s, 180s, 240s
            base_wait = self.rate_limit_wait
            return base_wait * (attempt + 1)
        else:
            # For other errors, use exponential backoff with jitter
            # 2s, 4s, 8s, 16s
            return min(2 ** (attempt + 1), 30)  # Cap at 30 seconds
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        use_cache: bool = True,
        **kwargs
    ) -> Optional[str]:
        """
        Get chat completion from LLM with caching and improved retry logic
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Override default temperature
            max_tokens: Override default max tokens
            use_cache: Whether to use cache (default True)
            **kwargs: Additional API parameters
        
        Returns:
            str: AI response content or None if failed
        """
        if not self.enabled or not self.client:
            logger.warning(f"LLM chat completion requested but LLM is not enabled (Provider: {self.provider})")
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
        
        # Make API call with retry logic
        last_error = None
        for attempt in range(self.max_retries + 1):  # +1 because first attempt is not a retry
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
                
                response_content = response.choices[0].message.content
                logger.info(f"{self.provider} chat completion successful on attempt {attempt + 1}")
                
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
                
            except RateLimitError as e:
                last_error = e
                if attempt < self.max_retries:
                    wait_time = self._calculate_retry_delay(attempt, "rate_limit")
                    logger.warning(
                        f"{self.provider} rate limit hit (attempt {attempt + 1}/{self.max_retries + 1}). "
                        f"Waiting {wait_time}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(
                        f"Rate limit exceeded after {self.max_retries + 1} attempts. "
                        f"Consider upgrading your {self.provider} plan or reducing request frequency."
                    )
                    return None
                
            except APITimeoutError as e:
                last_error = e
                if attempt < self.max_retries:
                    wait_time = self._calculate_retry_delay(attempt)
                    logger.warning(
                        f"{self.provider} timeout (attempt {attempt + 1}/{self.max_retries + 1}). "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Request timed out after {self.max_retries + 1} attempts")
                    return None
                
            except APIConnectionError as e:
                last_error = e
                if attempt < self.max_retries:
                    wait_time = self._calculate_retry_delay(attempt)
                    logger.warning(
                        f"{self.provider} connection error (attempt {attempt + 1}/{self.max_retries + 1}). "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Connection failed after {self.max_retries + 1} attempts: {e}")
                    return None
                
            except APIError as e:
                last_error = e
                # Check if it's a server error (5xx) - these are retryable
                if hasattr(e, 'status_code') and 500 <= e.status_code < 600:
                    if attempt < self.max_retries:
                        wait_time = self._calculate_retry_delay(attempt)
                        logger.warning(
                            f"{self.provider} server error {e.status_code} "
                            f"(attempt {attempt + 1}/{self.max_retries + 1}). "
                            f"Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                        continue
                # Client errors (4xx) should not be retried
                logger.error(f"{self.provider} API error: {e}")
                return None
                
            except AuthenticationError as e:
                logger.error(f"{self.provider} authentication failed - check your API key")
                return None
            
            except Exception as e:
                logger.error(f"Unexpected error in LLM chat completion: {type(e).__name__}: {e}")
                return None
        
        # If we exhausted all retries
        if last_error:
            logger.error(f"All retry attempts exhausted. Last error: {last_error}")
        return None
    
    def generate_embedding(self, text: str, model: str = "text-embedding-ada-002") -> Optional[List[float]]:
        """
        Generate embedding for text
        Note: Groq doesn't support embeddings, will fall back to OpenAI if needed
        
        Args:
            text: Text to embed
            model: Embedding model to use
        
        Returns:
            List[float]: Embedding vector or None if failed
        """
        if not self.enabled or not self.client:
            logger.warning("Embedding generation requested but LLM is not enabled")
            return None
        
        if self.provider.lower() == "groq":
            logger.warning("Groq doesn't support embeddings. Please configure OpenAI for embedding generation.")
            return None
        
        try:
            response = self.client.embeddings.create(
                model=model,
                input=text
            )
            return response.data[0].embedding
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ):
        """
        Stream chat completion from LLM (for real-time responses)
        Note: Streaming responses are not cached
        
        Args:
            messages: List of message dicts
            temperature: Override default temperature
            max_tokens: Override default max tokens
            **kwargs: Additional API parameters
        
        Yields:
            str: Chunks of AI response
        """
        if not self.enabled or not self.client:
            logger.warning(f"LLM streaming requested but LLM is not enabled (Provider: {self.provider})")
            return
        
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"Error in streaming chat completion: {e}")
            yield None
    
    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for text (rough estimate)
        
        Args:
            text: Text to count tokens for
        
        Returns:
            int: Estimated token count
        """
        # Rough estimation: ~4 characters per token
        return len(text) // 4
    
    def build_system_message(self, context: str = None) -> Dict[str, str]:
        """
        Build system message for AI assistant
        
        Args:
            context: Additional context to include
        
        Returns:
            dict: System message
        """
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
    
    def get_config_info(self) -> Dict[str, any]:
        """Get current LLM configuration info"""
        config = {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "rate_limit_wait": self.rate_limit_wait,
            "cache_enabled": self.cache_enabled,
            "base_url": self.base_url if self.provider.lower() == "groq" else "default"
        }
        
        if self.cache_enabled:
            config["cache_stats"] = self.get_cache_stats()
        
        return config


# Singleton instance
llm_client = LLMClient()