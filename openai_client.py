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
            
            return None, "Failed to download generated meme image"
            
        except Exception as e:
            logger.error(f"Error generating meme with OpenAI: {e}")
            return None, self._extract_api_error_message(e)
    
    def _extract_api_error_message(self, exception) -> str:
        """Extract meaningful error message from OpenAI API exception."""
        error_msg = str(exception)
        
        # Handle OpenAI specific errors
        if hasattr(exception, 'response') and exception.response is not None:
            try:
                if hasattr(exception.response, 'json'):
                    error_data = exception.response.json()
                    if 'error' in error_data:
                        error_info = error_data['error']
                        if isinstance(error_info, dict) and 'message' in error_info:
                            return f"OpenAI API Error: {error_info['message']}"
                        elif isinstance(error_info, str):
                            return f"OpenAI API Error: {error_info}"
            except Exception:
                pass
        
        # Handle common OpenAI error patterns
        if 'insufficient_quota' in error_msg.lower():
            return "OpenAI API Error: Insufficient quota - billing issue"
        elif 'invalid_api_key' in error_msg.lower() or 'unauthorized' in error_msg.lower():
            return "OpenAI API Error: Invalid API key or unauthorized access"
        elif 'rate_limit' in error_msg.lower():
            return "OpenAI API Error: Rate limit exceeded - please try again later"
        elif 'content_policy' in error_msg.lower():
            return "OpenAI API Error: Content policy violation - prompt rejected"
        elif 'model_overloaded' in error_msg.lower():
            return "OpenAI API Error: Model overloaded - service temporarily unavailable"
        
        # Default fallback
        return f"OpenAI API Error: {error_msg}"