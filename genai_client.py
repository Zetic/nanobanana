import io
import logging
import asyncio
import time
from PIL import Image
from google import genai
from google.genai import types
from typing import Optional, Tuple
import config

logger = logging.getLogger(__name__)

class APIQuotaExhaustedException(Exception):
    """Exception raised when API quota is exhausted."""
    def __init__(self, message: str, retry_delay: int = 60):
        super().__init__(message)
        self.retry_delay = retry_delay

class APIAuthenticationException(Exception):
    """Exception raised when API authentication fails."""
    pass

class ImageGenerator:
    """Handles Google GenAI image generation."""
    
    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
        self.model = "gemini-2.5-flash-image-preview"
        self.max_retries = 3
        self.base_delay = 1  # Base delay in seconds for exponential backoff
    
    def _parse_api_error(self, error) -> Tuple[str, bool, int]:
        """Parse API error and return (message, is_quota_error, retry_delay)."""
        error_str = str(error)
        
        # Check for quota exhaustion (429 errors)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            if "quota" in error_str.lower() or "rate" in error_str.lower():
                # Extract retry delay if available
                retry_delay = 60  # Default retry delay
                if "retryDelay" in error_str:
                    try:
                        # Try to extract retry delay from error message
                        import re
                        delay_match = re.search(r"retryDelay.*?(\d+)s", error_str)
                        if delay_match:
                            retry_delay = int(delay_match.group(1))
                    except:
                        pass
                
                raise APIQuotaExhaustedException(
                    "API quota limit exceeded. This usually happens with the free tier of Google GenAI. Please wait a few minutes before trying again, or consider upgrading your API plan.",
                    retry_delay
                )
        
        # Check for authentication errors
        if "401" in error_str or "UNAUTHENTICATED" in error_str:
            raise APIAuthenticationException("Invalid API key. Please check your Google GenAI API key configuration.")
        
        # Check for permission errors
        if "403" in error_str or "PERMISSION_DENIED" in error_str:
            raise APIAuthenticationException("Permission denied. Please check your Google GenAI API permissions.")
        
        # Re-raise original error for other cases
        raise error
    
    async def _make_api_call_with_retry(self, call_func, *args, **kwargs):
        """Make API call with exponential backoff retry for rate limiting."""
        for attempt in range(self.max_retries):
            try:
                return await call_func(*args, **kwargs)
            except APIQuotaExhaustedException as e:
                if attempt == self.max_retries - 1:
                    # Last attempt, re-raise the quota exception
                    raise
                
                # Calculate delay: use API suggested delay or exponential backoff
                delay = min(e.retry_delay if e.retry_delay > 0 else self.base_delay * (2 ** attempt), 300)  # Cap at 5 minutes
                
                logger.warning(f"Rate limited, retrying in {delay} seconds (attempt {attempt + 1}/{self.max_retries})")
                await asyncio.sleep(delay)
            except (APIAuthenticationException, Exception) as e:
                # Don't retry authentication errors or other exceptions
                raise
    
    async def generate_image_from_text(self, prompt: str) -> Optional[Image.Image]:
        """Generate an image from text prompt only."""
        try:
            async def api_call():
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[prompt],
                )
                return self._extract_image_from_response(response)
            
            return await self._make_api_call_with_retry(api_call)
            
        except Exception as e:
            self._parse_api_error(e)  # This will raise appropriate exceptions
            logger.error(f"Error generating image from text: {e}")
            return None
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Optional[Image.Image]:
        """Generate an image from both text prompt and input image."""
        try:
            async def api_call():
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[prompt, input_image],
                )
                return self._extract_image_from_response(response)
            
            return await self._make_api_call_with_retry(api_call)
            
        except Exception as e:
            self._parse_api_error(e)  # This will raise appropriate exceptions
            logger.error(f"Error generating image from text and image: {e}")
            return None
    
    def _extract_image_from_response(self, response) -> Optional[Image.Image]:
        """Extract image from GenAI response."""
        try:
            for part in response.candidates[0].content.parts:
                if part.text is not None:
                    logger.info(f"GenAI response text: {part.text}")
                elif part.inline_data is not None:
                    image = Image.open(io.BytesIO(part.inline_data.data))
                    return image
            
            logger.warning("No image found in GenAI response")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting image from response: {e}")
            return None