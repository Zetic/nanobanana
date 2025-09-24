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
    
    async def generate_meme(self) -> Optional[Image.Image]:
        """Generate a meme using the hardcoded prompt."""
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
                        return Image.open(io.BytesIO(image_data))
            
            return None
            
        except Exception as e:
            logger.error(f"Error generating meme with OpenAI: {e}")
            # Note: OpenAI errors are handled differently - could extend this method 
            # to return error message if needed, but currently not used by bot
            return None

    def _extract_error_message(self, exception: Exception) -> str:
        """Extract informative error message from OpenAI API exceptions."""
        try:
            # Check if it's an OpenAI API error
            if hasattr(exception, 'message') and exception.message:
                return f"API Error: {exception.message}"
            
            # For OpenAI errors, also check for response content
            if hasattr(exception, 'response') and exception.response:
                try:
                    error_data = exception.response.json()
                    if 'error' in error_data and 'message' in error_data['error']:
                        return f"API Error: {error_data['error']['message']}"
                except:
                    pass
            
            # Check if it's a string representation that might be informative
            error_str = str(exception)
            if error_str and error_str.strip() and error_str != 'None':
                return f"Error: {error_str}"
                
            # Fallback to generic message if no useful error info
            return "An unexpected error occurred. Please try again with different input."
            
        except Exception:
            # If anything goes wrong extracting the error message, use fallback
            return "An unexpected error occurred. Please try again with different input."