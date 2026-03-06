"""
Quick sanity test for OpenAI API connectivity.
Tests both models used in the pipeline without running a full audit.

Run from the backend/ directory:
    python test_api.py
"""

import os
from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def test_generation():
    """Test gpt-4o with a trivial generation call."""
    print("Testing gpt-4o (generation)...")
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "user", "content": 'Return this exact JSON: {"status": "ok", "model": "gpt-4o"}'}
        ],
    )
    result = response.choices[0].message.content
    print(f"  Response: {result}")
    print("  PASS\n")


def test_search():
    """Test gpt-4o-search-preview with a minimal web search call."""
    print("Testing gpt-4o-search-preview (web search)...")
    response = client.chat.completions.create(
        model="gpt-4o-search-preview",
        messages=[
            {"role": "user", "content": "What is the current homepage title of example.com? Reply in one sentence."}
        ],
    )
    result = response.choices[0].message.content
    print(f"  Response: {result}")
    print("  PASS\n")


if __name__ == "__main__":
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY not set. Check your .env file.")
        exit(1)
    print(f"API key loaded: {key[:8]}...\n")

    test_generation()
    test_search()
    print("All tests passed. Ready to run the full pipeline.")
