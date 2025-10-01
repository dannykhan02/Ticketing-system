"""
Centralized LLM Client for AI Features
Handles all OpenAI API interactions with proper error handling and retries
"""

import openai
import logging
import time
from typing import List, Dict, Optional
from config import Config

logger = logging.getLogger(__name__)


class LLMClient:
    """Centralized client for LLM interactions"""
    
    def __init__(self):
        """Initialize LLM client with config settings"""
        self.api_key = Config.OPENAI_API_KEY
        self.provider = Config.AI_PROVIDER
        self.model = Config.AI_MODEL
        self.temperature = Config.AI_TEMPERATURE
        self.max_tokens = Config.AI_MAX_TOKENS
        self.timeout = Config.AI_TIMEOUT
        self.max_retries = Config.AI_MAX_RETRIES
        self.enabled = Config.ENABLE_AI_FEATURES and bool(self.api_key)
        
        # Configure OpenAI
        if self.enabled:
            openai.api_key = self.api_key
            logger.info(f"LLM Client initialized - Provider: {self.provider}, Model: {self.model}")
        else:
            logger.warning("LLM Client initialized but disabled - API key not configured")
    
    def is_enabled(self) -> bool:
        """Check if LLM is enabled and configured"""
        return self.enabled
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Optional[str]:
        """
        Get chat completion from OpenAI
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Override default temperature
            max_tokens: Override default max tokens
            **kwargs: Additional OpenAI API parameters
        
        Returns:
            str: AI response content or None if failed
        """
        if not self.enabled:
            logger.warning("LLM chat completion requested but LLM is not enabled")
            return None
        
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        
        for attempt in range(self.max_retries):
            try:
                response = openai.ChatCompletion.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.timeout,
                    **kwargs
                )
                
                content = response.choices[0].message.content
                logger.info(f"LLM chat completion successful (attempt {attempt + 1})")
                return content
                
            except openai.error.Timeout:
                logger.warning(f"OpenAI timeout (attempt {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                return None
                
            except openai.error.RateLimitError:
                logger.warning(f"OpenAI rate limit hit (attempt {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    time.sleep(5 * (attempt + 1))  # Progressive backoff
                    continue
                return None
                
            except openai.error.APIError as e:
                logger.error(f"OpenAI API error: {e} (attempt {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
                
            except openai.error.AuthenticationError:
                logger.error("OpenAI authentication failed - invalid API key")
                return None
                
            except Exception as e:
                logger.error(f"Unexpected error in LLM chat completion: {e}")
                return None
        
        return None
    
    def generate_embedding(self, text: str, model: str = "text-embedding-ada-002") -> Optional[List[float]]:
        """
        Generate embedding for text
        
        Args:
            text: Text to embed
            model: Embedding model to use
        
        Returns:
            List[float]: Embedding vector or None if failed
        """
        if not self.enabled:
            logger.warning("Embedding generation requested but LLM is not enabled")
            return None
        
        try:
            response = openai.Embedding.create(
                model=model,
                input=text,
                timeout=self.timeout
            )
            return response['data'][0]['embedding']
            
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
        Stream chat completion from OpenAI (for real-time responses)
        
        Args:
            messages: List of message dicts
            temperature: Override default temperature
            max_tokens: Override default max tokens
            **kwargs: Additional OpenAI API parameters
        
        Yields:
            str: Chunks of AI response
        """
        if not self.enabled:
            logger.warning("LLM streaming requested but LLM is not enabled")
            return
        
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        
        try:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                timeout=self.timeout,
                **kwargs
            )
            
            for chunk in response:
                if chunk.choices[0].delta.get("content"):
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
    
    def get_config_info(self) -> Dict[str, any]:
        """Get current LLM configuration info"""
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_retries": self.max_retries
        }


# Singleton instance
llm_client = LLMClient()