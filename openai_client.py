import io
import logging
from PIL import Image
import openai
from typing import Optional, Dict, Any
import config

logger = logging.getLogger(__name__)

class OpenAIImageGenerator:
    """Handles OpenAI image generation for memes."""
    
    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    
    def _extract_error_message(self, exception: Exception) -> Optional[str]:
        """Extract user-friendly error message from OpenAI API exception."""
        error_str = str(exception)
        
        # Check for common OpenAI API error patterns
        if hasattr(exception, 'message'):
            return exception.message
        elif 'quota exceeded' in error_str.lower() or 'insufficient_quota' in error_str.lower():
            return "OpenAI API quota exceeded. Please try again later."
        elif 'invalid request' in error_str.lower():
            return "Invalid request format. Please check your input."
        elif 'authentication' in error_str.lower() or 'unauthorized' in error_str.lower():
            return "OpenAI authentication failed. Please check API credentials."
        elif 'rate limit' in error_str.lower():
            return "OpenAI rate limit exceeded. Please wait before trying again."
        elif 'timeout' in error_str.lower():
            return "OpenAI request timed out. Please try again."
        elif 'content policy' in error_str.lower() or 'safety' in error_str.lower():
            return "Content blocked by OpenAI safety policies. Please try a different prompt."
        elif 'billing' in error_str.lower():
            return "OpenAI billing issue. Please check your account status."
        
        # If no specific pattern matches, check if the error message looks user-friendly
        # Filter out obviously technical messages while allowing reasonable error messages
        if (len(error_str) < 200 and 
            error_str and  # Not empty
            not (len(error_str.split()) == 1 and any(char.isdigit() for char in error_str)) and  # Not single word with numbers
            not any(term in error_str.lower() for term in ['stacktrace', 'traceback', 'at line', 'exception in thread'])):  # Not stack trace
            return error_str
        
        # If it's just technical details, return None (bot should be silent)
        return None
    
    async def generate_meme(self) -> tuple[Optional[Image.Image], Optional[str]]:
        """Generate a meme using the hardcoded prompt. Returns (image, error_message)."""
        try:
            # Fixed prompt as specified in the issue
            prompt = "generate a single image meme that makes no sense. it can be borderline offsve"
            
            response = self.client.images.generate(
                model="dall-e-3",  # Note: Issue mentions "gpt-image-1" but using DALL-E 3 as the available OpenAI image model
                prompt=prompt,
                size="1024x1024", 
                quality="standard",
                n=1,
            )
            
            # Get the image URL from the response
            image_url = response.data[0].url
            
            # Download and convert to PIL Image
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        return Image.open(io.BytesIO(image_data)), None
            
            return None, "Failed to download generated image"
            
        except Exception as e:
            logger.error(f"Error generating meme with OpenAI: {e}")
            error_message = self._extract_error_message(e)
            return None, error_message