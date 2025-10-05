"""
Test script for Groq API connection
Tests the configuration and API call structure
"""

from openai import OpenAI
from config import Config
import sys

def test_config():
    """Test configuration loading"""
    print("=" * 60)
    print("CONFIGURATION TEST")
    print("=" * 60)
    
    print(f"AI Provider: {Config.AI_PROVIDER}")
    print(f"AI Model: {Config.AI_MODEL}")
    print(f"AI Enabled: {Config.ENABLE_AI_FEATURES}")
    print(f"AI Temperature: {Config.AI_TEMPERATURE}")
    print(f"AI Max Tokens: {Config.AI_MAX_TOKENS}")
    print(f"AI Timeout: {Config.AI_TIMEOUT}")
    print(f"AI Max Retries: {Config.AI_MAX_RETRIES}")
    print(f"Cache Enabled: {Config.AI_CACHE_ENABLED}")
    print(f"Cache TTL: {Config.AI_CACHE_TTL}")
    print(f"Cache Max Size: {Config.AI_CACHE_MAX_SIZE}")
    print()
    
    # Check API key
    if Config.GROQ_API_KEY:
        key_prefix = Config.GROQ_API_KEY[:10] if len(Config.GROQ_API_KEY) > 10 else Config.GROQ_API_KEY
        print(f"✓ Groq API Key Found: {key_prefix}...")
        
        # Validate key format
        if Config.GROQ_API_KEY.startswith("gsk_"):
            print("✓ API Key format is valid (starts with 'gsk_')")
        else:
            print("✗ WARNING: API Key doesn't start with 'gsk_' - may be invalid")
            return False
    else:
        print("✗ Groq API Key NOT found in environment")
        return False
    
    print()
    return True


def test_api_connection():
    """Test actual API connection"""
    print("=" * 60)
    print("API CONNECTION TEST")
    print("=" * 60)
    
    try:
        # Initialize client using config values
        client = OpenAI(
            api_key=Config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            timeout=Config.AI_TIMEOUT,
            max_retries=0  # Handle retries manually
        )
        
        print(f"✓ Client initialized successfully")
        print(f"Base URL: https://api.groq.com/openai/v1")
        print(f"Timeout: {Config.AI_TIMEOUT}s")
        print()
        
        # Test with a simple query
        print("Testing chat completion...")
        print(f"Model: {Config.AI_MODEL}")
        print(f"Temperature: {Config.AI_TEMPERATURE}")
        print(f"Max Tokens: {Config.AI_MAX_TOKENS}")
        print()
        
        response = client.chat.completions.create(
            model=Config.AI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful AI assistant for a ticketing system."
                },
                {
                    "role": "user",
                    "content": "Say 'Hello! I am working correctly.' in one sentence."
                }
            ],
            temperature=Config.AI_TEMPERATURE,
            max_tokens=100  # Use less tokens for test
        )
        
        # Extract response
        response_content = response.choices[0].message.content
        
        print("=" * 60)
        print("✓ API CALL SUCCESSFUL!")
        print("=" * 60)
        print(f"Response: {response_content}")
        print()
        print(f"Model used: {response.model}")
        print(f"Finish reason: {response.choices[0].finish_reason}")
        
        if hasattr(response, 'usage'):
            print(f"Tokens used: {response.usage.total_tokens}")
            print(f"  - Prompt: {response.usage.prompt_tokens}")
            print(f"  - Completion: {response.usage.completion_tokens}")
        
        return True
        
    except Exception as e:
        print("=" * 60)
        print("✗ API CALL FAILED")
        print("=" * 60)
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {str(e)}")
        
        # Provide helpful debugging info
        if "authentication" in str(e).lower() or "401" in str(e):
            print("\nPossible causes:")
            print("- Invalid API key")
            print("- API key not properly set in environment")
            print("- API key format incorrect (should start with 'gsk_')")
        elif "timeout" in str(e).lower():
            print("\nPossible causes:")
            print("- Network connectivity issues")
            print("- Groq API is slow or unavailable")
            print(f"- Timeout too short (current: {Config.AI_TIMEOUT}s)")
        elif "rate" in str(e).lower():
            print("\nPossible causes:")
            print("- Rate limit exceeded")
            print("- Too many requests in short time")
        else:
            print("\nCheck:")
            print("- Your internet connection")
            print("- Groq API status at https://status.groq.com")
            print("- API key is valid and active")
        
        return False


def test_available_models():
    """Test listing available models"""
    print("\n" + "=" * 60)
    print("AVAILABLE MODELS TEST")
    print("=" * 60)
    
    print("\nCommonly available Groq models:")
    models = [
        "llama3-8b-8192",
        "llama3-70b-8192",
        "mixtral-8x7b-32768",
        "gemma-7b-it",
    ]
    
    for model in models:
        if model == Config.AI_MODEL:
            print(f"→ {model} (currently configured)")
        else:
            print(f"  {model}")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("GROQ API TEST SUITE")
    print("=" * 60)
    print()
    
    # Test 1: Configuration
    config_ok = test_config()
    if not config_ok:
        print("\n✗ Configuration test failed. Cannot proceed with API test.")
        print("\nMake sure GROQ_API_KEY is set in your .env file")
        sys.exit(1)
    
    # Test 2: API Connection
    api_ok = test_api_connection()
    
    # Test 3: Show available models
    test_available_models()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Configuration: {'✓ PASSED' if config_ok else '✗ FAILED'}")
    print(f"API Connection: {'✓ PASSED' if api_ok else '✗ FAILED'}")
    print("=" * 60)
    
    if config_ok and api_ok:
        print("\n🎉 All tests passed! Your Groq integration is working correctly.")
        sys.exit(0)
    else:
        print("\n⚠️ Some tests failed. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()