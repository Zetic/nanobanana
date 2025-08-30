import io
import logging
from PIL import Image
from google import genai
from google.genai import types
from typing import Optional
import config

logger = logging.getLogger(__name__)

class ImageGenerator:
    """Handles Google GenAI image generation."""
    
    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
        self.model = "gemini-2.5-flash-image-preview"
    
    async def generate_image_from_text(self, prompt: str) -> Optional[Image.Image]:
        """Generate an image from text prompt only."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt],
            )
            
            return self._extract_image_from_response(response)
            
        except Exception as e:
            logger.error(f"Error generating image from text: {e}")
            return None
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Optional[Image.Image]:
        """Generate an image from both text prompt and input image."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, input_image],
            )
            
            return self._extract_image_from_response(response)
            
        except Exception as e:
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