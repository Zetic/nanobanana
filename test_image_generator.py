#!/usr/bin/env python3
"""
Test the ImageGenerator text-only functionality without making actual API calls.
"""
import os
from unittest.mock import Mock, patch

# Set up environment for testing
os.environ['DISCORD_TOKEN'] = 'test_token'  
os.environ['GOOGLE_API_KEY'] = 'test_key'

from genai_client import ImageGenerator

def test_image_generator_init():
    """Test that ImageGenerator initializes with both models."""
    
    with patch('genai_client.genai.Client') as mock_client:
        generator = ImageGenerator()
        
        # Verify both models are set
        assert generator.model == "gemini-2.5-flash-image-preview"
        assert generator.text_only_model == "gemini-2.5-flash"
        
        print("✅ ImageGenerator initializes with correct models")


def test_text_only_response_method_exists():
    """Test that the text-only response method exists and has correct signature."""
    
    with patch('genai_client.genai.Client') as mock_client:
        generator = ImageGenerator()
        
        # Verify the method exists
        assert hasattr(generator, 'generate_text_only_response')
        
        # Check method signature (should accept prompt and optional images)
        import inspect
        sig = inspect.signature(generator.generate_text_only_response)
        params = list(sig.parameters.keys())
        
        assert 'prompt' in params
        assert 'input_images' in params
        
        print("✅ generate_text_only_response method exists with correct signature")


if __name__ == "__main__":
    print("Running ImageGenerator tests...")
    test_image_generator_init()
    test_text_only_response_method_exists()
    print("\n🎉 All ImageGenerator tests passed!")