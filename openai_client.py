import io
import logging
from PIL import Image
import openai
from typing import Optional, Dict, Any, Tuple
import config

logger = logging.getLogger(__name__)

def extract_openai_error_message(e: Exception) -> str:
    """Extract informative error message from OpenAI API exceptions."""
    if hasattr(e, 'response') and hasattr(e.response, 'json'):
        # Try to extract error from OpenAI API response
        try:
            error_info = e.response.json()
            if 'error' in error_info and 'message' in error_info['error']:
                return error_info['error']['message']
        except:
            pass
    
    # Fallback to string representation
    return str(e)

class OpenAIImageGenerator:
    """Handles OpenAI image generation for memes."""
    
    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
    
    async def generate_meme(self) -> Tuple[Optional[Image.Image], Optional[str]]:
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
            error_message = extract_openai_error_message(e)
            logger.error(f"Error generating meme with OpenAI: {error_message}")
            return None, error_message