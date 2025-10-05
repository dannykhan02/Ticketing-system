"""
Simple test script for LLM client
Run this from inside the ai/ directory OR move it to project root
"""
import os
import sys
from dotenv import load_dotenv

# Add parent directory to path so we can import from ai module
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# Load environment variables
load_dotenv(os.path.join(parent_dir, '.env'))

# Test 1: Direct OpenAI Client Test
print("=" * 60)
print("TEST 1: Direct OpenAI Client Test")
print("=" * 60)

from openai import OpenAI

try:
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    )
    
    print("✓ Client initialized successfully")
    print(f"✓ API Key present: {bool(os.environ.get('GROQ_API_KEY'))}")
    print(f"✓ API Key format: {os.environ.get('GROQ_API_KEY', '')[:10]}...")
    
    # Make a simple test call
    print("\n🔄 Making test API call...")
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "user", "content": "Say 'Hello, I am working!' in 5 words or less."}
        ],
        max_tokens=50
    )
    
    result = response.choices[0].message.content
    print(f"✅ SUCCESS! Response: {result}")
    
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")

# Test 2: Your LLM Client Test
print("\n" + "=" * 60)
print("TEST 2: Your LLMClient Class Test")
print("=" * 60)

try:
    # Import your LLM client - adjusted for running from ai/ directory
    from llm_client import llm_client
    
    print(f"✓ LLM Client imported")
    print(f"✓ Provider: {llm_client.provider}")
    print(f"✓ Model: {llm_client.model}")
    print(f"✓ Enabled: {llm_client.enabled}")
    print(f"✓ Circuit Breaker State: {llm_client.circuit_breaker.state}")
    
    # Get health status
    health = llm_client.get_health_status()
    print(f"\n📊 Health Status:")
    for key, value in health.items():
        if key != 'cache_stats':  # Skip detailed cache stats for cleaner output
            print(f"   {key}: {value}")
    
    # Make a test call
    print("\n🔄 Making test API call through LLMClient...")
    messages = [
        llm_client.build_system_message(),
        {"role": "user", "content": "What is 2+2? Answer in one word."}
    ]
    
    response = llm_client.chat_completion(
        messages=messages,
        use_cache=False,
        fallback_response="AI unavailable"
    )
    
    if response:
        print(f"✅ SUCCESS! Response: {response}")
    else:
        print(f"❌ No response received")
    
    # Check circuit breaker after call
    print(f"\n⚡ Circuit Breaker State After Call: {llm_client.circuit_breaker.state}")
    print(f"⚡ Failures: {llm_client.circuit_breaker.failures}")
    
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Cache Test
print("\n" + "=" * 60)
print("TEST 3: Cache Test")
print("=" * 60)

try:
    from llm_client import llm_client
    
    # Clear cache first
    llm_client.clear_cache()
    print("✓ Cache cleared")
    
    # First call (should hit API)
    print("\n🔄 First call (should hit API)...")
    messages = [{"role": "user", "content": "Count to 3"}]
    
    import time
    start = time.time()
    response1 = llm_client.chat_completion(messages, use_cache=True)
    time1 = time.time() - start
    
    print(f"✅ Response: {response1}")
    print(f"⏱️  Time taken: {time1:.2f}s")
    
    # Second call (should hit cache)
    print("\n🔄 Second call (should hit cache)...")
    start = time.time()
    response2 = llm_client.chat_completion(messages, use_cache=True)
    time2 = time.time() - start
    
    print(f"✅ Response: {response2}")
    print(f"⏱️  Time taken: {time2:.2f}s")
    
    if time2 < time1:
        print(f"🚀 Cache speedup: {time1/time2:.1f}x faster")
    else:
        print(f"⚠️  No speedup detected - cache might not be working")
    
    # Check cache stats
    cache_stats = llm_client.get_cache_stats()
    if cache_stats:
        print(f"\n📊 Cache Stats:")
        for key, value in cache_stats.items():
            print(f"   {key}: {value}")
    
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Error Handling Test
print("\n" + "=" * 60)
print("TEST 4: Error Handling & Fallback Test")
print("=" * 60)

try:
    from llm_client import llm_client
    
    # Test with fallback response
    print("🔄 Testing fallback response...")
    messages = [{"role": "user", "content": "Test message"}]
    
    response = llm_client.chat_completion(
        messages=messages,
        fallback_response="This is a fallback response if AI fails",
        quick_mode=False
    )
    
    print(f"✅ Response: {response}")
    
    # Test quick mode (no retries)
    print("\n🔄 Testing quick mode (no retries)...")
    response_quick = llm_client.chat_completion(
        messages=messages,
        quick_mode=True,
        fallback_response="Quick mode fallback"
    )
    
    print(f"✅ Quick mode response: {response_quick}")
    
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print("TESTING COMPLETE")
print("=" * 60)
print("\n💡 Next Steps:")
print("   1. If all tests passed ✅ - Your LLM client works perfectly!")
print("   2. Deploy to Render and set environment variables")
print("   3. Check Render logs for network/firewall issues")
print("=" * 60)