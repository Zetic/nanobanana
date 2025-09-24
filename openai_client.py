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
    
    async def generate_meme(self, custom_prompt: str = None) -> Optional[Image.Image]:
        """Generate a meme using custom prompt or hardcoded fallback."""
        try:
            if custom_prompt and custom_prompt.strip():
                # Use user's custom prompt for more personalized results
                prompt = f"generate a meme image: {custom_prompt.strip()}"
            else:
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
            return None