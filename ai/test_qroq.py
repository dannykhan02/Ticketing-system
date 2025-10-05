"""
Test script for Groq API connection
Tests the configuration and API call structure
"""

import os
import sys
from dotenv import load_dotenv
from openai import OpenAI

# ✅ Load the .env file before importing Config
load_dotenv()

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config


def test_config():
    """Test configuration loading"""
    print("=" * 60)
    print("CONFIGURATION TEST")
    print("=" * 60)

    # Add GROQ_API_KEY to Config if not defined
    if not hasattr(Config, "GROQ_API_KEY"):
        Config.GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    print(f"AI Provider: {Config.AI_PROVIDER}")
    print(f"AI Model: {Config.AI_MODEL}")
    print(f"AI Enabled: {Config.ENABLE_AI_FEATURES}")
    print(f"AI Temperature: {Config.AI_TEMPERATURE}")
    print(f"AI Max Tokens: {Config.AI_MAX_TOKENS}")
    print(f"AI Timeout: {getattr(Config, 'AI_TIMEOUT', 30)}")
    print(f"AI Max Retries: {Config.AI_MAX_RETRIES}")
    print(f"Cache Enabled: {Config.AI_CACHE_ENABLED}")
    print(f"Cache TTL: {Config.AI_CACHE_TTL}")
    print(f"Cache Max Size: {Config.AI_CACHE_MAX_SIZE}")
    print()

    # Check API key
    if Config.GROQ_API_KEY:
        key_prefix = (
            Config.GROQ_API_KEY[:10]
            if len(Config.GROQ_API_KEY) > 10
            else Config.GROQ_API_KEY
        )
        print(f"✓ Groq API Key Found: {key_prefix}...")

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
            timeout=getattr(Config, "AI_TIMEOUT", 30),
        )

        print(f"✓ Client initialized successfully")
        print(f"Base URL: https://api.groq.com/openai/v1")
        print(f"Timeout: {getattr(Config, 'AI_TIMEOUT', 30)}s")
        print()

        print("Testing chat completion...")
        print(f"Model: {Config.AI_MODEL}")
        print(f"Temperature: {Config.AI_TEMPERATURE}")
        print(f"Max Tokens: {Config.AI_MAX_TOKENS}")
        print()

        response = client.chat.completions.create(
            model=Config.AI_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant."},
                {
                    "role": "user",
                    "content": "Say 'Hello! I am working correctly.' in one sentence.",
                },
            ],
            temperature=Config.AI_TEMPERATURE,
            max_tokens=100,
        )

        message = response.choices[0].message.content

        print("=" * 60)
        print("✓ API CALL SUCCESSFUL!")
        print("=" * 60)
        print(f"Response: {message}")
        print(f"Model: {response.model}")
        print(f"Finish reason: {response.choices[0].finish_reason}")

        if hasattr(response, "usage"):
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

        if "authentication" in str(e).lower() or "401" in str(e):
            print("\nPossible causes:")
            print("- Invalid or missing GROQ_API_KEY")
            print("- Key not properly loaded from .env")
        elif "timeout" in str(e).lower():
            print("\nPossible causes:")
            print("- Network connection issues")
            print("- API timeout too short")
        elif "rate" in str(e).lower():
            print("\nPossible causes:")
            print("- Rate limit exceeded")
        else:
            print("\nCheck:")
            print("- Internet connection")
            print("- API key validity")
            print("- Groq API status: https://status.groq.com")

        return False


def test_available_models():
    """Show supported Groq models"""
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

    config_ok = test_config()
    if not config_ok:
        print("\n✗ Configuration test failed. Cannot proceed with API test.")
        print("\nMake sure GROQ_API_KEY is set in your .env file")
        sys.exit(1)

    api_ok = test_api_connection()
    test_available_models()

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
        print("\n⚠️ Some tests failed. Please check the logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
