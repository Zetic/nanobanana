#!/usr/bin/env python3
"""
Simple test to validate that rate limiting allows text responses when image generation is blocked.
"""

import os
import tempfile
import json
from datetime import date
from unittest.mock import Mock, patch, AsyncMock
import asyncio

# Set up environment for testing
os.environ['DISCORD_TOKEN'] = 'test_token'
os.environ['GOOGLE_API_KEY'] = 'test_key'

import config
import usage_tracker
from genai_client import ImageGenerator
from bot import process_generation_request


async def test_text_fallback_when_rate_limited():
    """Test that users can still get text responses when image rate limited."""
    
    # Create a temporary directory for test usage tracking
    with tempfile.TemporaryDirectory() as temp_dir:
        # Override the generated images directory for testing
        original_dir = config.GENERATED_IMAGES_DIR
        config.GENERATED_IMAGES_DIR = temp_dir
        
        # Create a new usage tracker instance
        test_tracker = usage_tracker.UsageTracker()
        
        # Mock a user who has reached the image limit
        user_id = 12345
        username = "test_user"
        
        # Simulate user having reached the daily limit
        today = date.today().isoformat()
        usage_data = {
            "users": {
                str(user_id): {
                    "username": username,
                    "total_prompt_tokens": 100,
                    "total_output_tokens": 200,
                    "total_tokens": 300,
                    "images_generated": 5,
                    "requests_count": 5,
                    "first_use": "2024-01-01T00:00:00",
                    "last_use": "2024-01-01T12:00:00",
                    "daily_images": {today: 5}  # User has reached daily limit of 5
                }
            },
            "last_updated": "2024-01-01T12:00:00"
        }
        
        # Write test data to the usage file
        with open(test_tracker.usage_file, 'w') as f:
            json.dump(usage_data, f)
        
        # Verify the user is rate limited
        assert not test_tracker.can_generate_image(user_id), "User should be rate limited"
        assert test_tracker.get_daily_image_count(user_id) == 5, "User should have 5 images today"
        
        # Mock objects for testing
        mock_response_message = Mock()
        mock_response_message.edit = AsyncMock()
        
        mock_user = Mock()
        mock_user.id = user_id
        mock_user.bot = False
        
        # Mock the image generator to avoid actual API calls
        with patch('bot.get_image_generator') as mock_get_generator:
            mock_generator = Mock()
            mock_generator.generate_text_only_response = AsyncMock(
                return_value=(None, "This is a text-only response for a rate-limited user.", {"prompt_token_count": 10, "candidates_token_count": 20, "total_token_count": 30})
            )
            mock_get_generator.return_value = mock_generator
            
            # Patch the usage tracker
            with patch('bot.usage_tracker', test_tracker):
                # Test text-only request from rate-limited user
                await process_generation_request(
                    mock_response_message, 
                    "Hello, can you help me?", 
                    [], 
                    mock_user
                )
                
                # Verify that a text response was provided
                mock_response_message.edit.assert_called()
                call_args = mock_response_message.edit.call_args
                
                # Check that content contains rate limit warning and response
                content = call_args[1]['content'] if 'content' in call_args[1] else call_args[0][0]
                assert "Image generation limit reached" in content, f"Should contain rate limit warning. Got: {content}"
                assert "text-only response" in content, f"Should contain text response. Got: {content}"
                
                # Verify the text-only generator was called
                mock_generator.generate_text_only_response.assert_called_once()
                
        # Reset the config
        config.GENERATED_IMAGES_DIR = original_dir
        
        print("✅ Test passed: Rate-limited users can still receive text responses")


async def test_normal_user_not_affected():
    """Test that normal users (not rate limited) still get full functionality."""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Override the generated images directory for testing
        original_dir = config.GENERATED_IMAGES_DIR
        config.GENERATED_IMAGES_DIR = temp_dir
        
        # Create a new usage tracker instance
        test_tracker = usage_tracker.UsageTracker()
        
        # Mock a user who has NOT reached the image limit
        user_id = 67890
        username = "normal_user"
        
        # User has only generated 2 images today (under the limit of 5)
        today = date.today().isoformat()
        usage_data = {
            "users": {
                str(user_id): {
                    "username": username,
                    "total_prompt_tokens": 50,
                    "total_output_tokens": 100,
                    "total_tokens": 150,
                    "images_generated": 2,
                    "requests_count": 2,
                    "first_use": "2024-01-01T00:00:00",
                    "last_use": "2024-01-01T12:00:00",
                    "daily_images": {today: 2}  # User has only 2 images today
                }
            },
            "last_updated": "2024-01-01T12:00:00"
        }
        
        # Write test data to the usage file
        with open(test_tracker.usage_file, 'w') as f:
            json.dump(usage_data, f)
        
        # Verify the user is NOT rate limited
        assert test_tracker.can_generate_image(user_id), "User should not be rate limited"
        assert test_tracker.get_daily_image_count(user_id) == 2, "User should have 2 images today"
        
        # Mock objects for testing
        mock_response_message = Mock()
        mock_response_message.edit = AsyncMock()
        
        mock_user = Mock()
        mock_user.id = user_id
        mock_user.bot = False
        
        # Mock the image generator to avoid actual API calls
        with patch('bot.get_image_generator') as mock_get_generator:
            mock_generator = Mock()
            mock_generator.generate_image_from_text = AsyncMock(
                return_value=(Mock(), "This is a normal response with image generation.", {"prompt_token_count": 15, "candidates_token_count": 25, "total_token_count": 40})
            )
            mock_get_generator.return_value = mock_generator
            
            # Patch the usage tracker
            with patch('bot.usage_tracker', test_tracker):
                # Test text request from normal user
                await process_generation_request(
                    mock_response_message, 
                    "Create an image of a cat", 
                    [], 
                    mock_user
                )
                
                # Verify that normal image generation was called
                mock_generator.generate_image_from_text.assert_called_once()
                
                # Verify text-only fallback was NOT used
                assert not hasattr(mock_generator, 'generate_text_only_response') or not mock_generator.generate_text_only_response.called
        
        # Reset the config
        config.GENERATED_IMAGES_DIR = original_dir
        
        print("✅ Test passed: Normal users still get full image generation functionality")


async def main():
    """Run all tests."""
    print("Running rate limiting tests...")
    
    try:
        await test_text_fallback_when_rate_limited()
        await test_normal_user_not_affected()
        print("\n🎉 All tests passed! Rate limiting fix is working correctly.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())