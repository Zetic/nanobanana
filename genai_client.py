import io
import logging
from PIL import Image
from google import genai
from google.genai import types
from typing import Optional, List
import config

logger = logging.getLogger(__name__)

class ImageGenerator:
    """Handles Google GenAI image generation."""
    
    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
        # Use proper image generation model
        self.image_model = "imagen-3.0-generate-001"  # Dedicated image generation model
        self.text_model = "gemini-2.5-flash-image-preview"  # For text+image processing
    
    async def generate_image_from_text(self, prompt: str) -> Optional[Image.Image]:
        """Generate an image from text prompt only."""
        try:
            # First try the dedicated image generation API
            response = self.client.models.generate_images(
                model=self.image_model,
                prompt=prompt,
            )
            
            return self._extract_image_from_generate_images_response(response)
            
        except Exception as e:
            logger.warning(f"Image generation API failed: {e}. Falling back to content generation.")
            # Fallback to content generation with explicit image request
            try:
                enhanced_prompt = f"Generate an image of: {prompt}"
                response = self.client.models.generate_content(
                    model=self.text_model,
                    contents=[enhanced_prompt],
                )
                
                return self._extract_image_from_response(response)
                
            except Exception as fallback_error:
                logger.error(f"Error generating image from text (fallback also failed): {fallback_error}")
                return None
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Optional[Image.Image]:
        """Generate an image from both text prompt and input image."""
        try:
            response = self.client.models.generate_content(
                model=self.text_model,
                contents=[prompt, input_image],
            )
            
            return self._extract_image_from_response(response)
            
        except Exception as e:
            logger.error(f"Error generating image from text and image: {e}")
            return None
    
    async def generate_image_from_image_only(self, input_image: Image.Image) -> Optional[Image.Image]:
        """Generate an image from input image only with generic transformation prompt."""
        try:
            # Use a generic prompt that lets the AI decide how to transform the image
            generic_prompt = "Transform and enhance this image creatively while maintaining its core subject and essence."
            
            response = self.client.models.generate_content(
                model=self.text_model,
                contents=[generic_prompt, input_image],
            )
            
            return self._extract_image_from_response(response)
            
        except Exception as e:
            logger.error(f"Error generating image from image only: {e}")
            return None
    
    async def generate_image_from_images_only(self, input_images: List[Image.Image]) -> Optional[Image.Image]:
        """Generate an image from multiple input images only with generic transformation prompt."""
        try:
            # Use a generic prompt for multiple images
            generic_prompt = "Creatively combine and transform these images while maintaining their core subjects and essence."
            
            # Create contents list starting with the prompt
            contents = [generic_prompt]
            
            # Add each image to contents
            for i, image in enumerate(input_images):
                # Convert PIL Image to bytes for API
                img_buffer = io.BytesIO()
                image.save(img_buffer, format='PNG')
                img_bytes = img_buffer.getvalue()
                
                # Create Part from bytes
                image_part = types.Part.from_bytes(
                    data=img_bytes,
                    mime_type='image/png'
                )
                contents.append(image_part)
            
            response = self.client.models.generate_content(
                model=self.text_model,
                contents=contents,
            )
            
            return self._extract_image_from_response(response)
            
        except Exception as e:
            logger.error(f"Error generating image from images only: {e}")
            return None

    async def generate_image_from_text_and_images(self, prompt: str, input_images: List[Image.Image]) -> Optional[Image.Image]:
        """Generate an image from text prompt and multiple input images."""
        try:
            # Create contents list starting with the prompt
            contents = [prompt]
            
            # Add each image to contents
            for i, image in enumerate(input_images):
                # Convert PIL Image to bytes for API
                img_buffer = io.BytesIO()
                image.save(img_buffer, format='PNG')
                img_bytes = img_buffer.getvalue()
                
                # Create Part from bytes
                image_part = types.Part.from_bytes(
                    data=img_bytes,
                    mime_type='image/png'
                )
                contents.append(image_part)
            
            response = self.client.models.generate_content(
                model=self.text_model,
                contents=contents,
            )
            
            return self._extract_image_from_response(response)
            
        except Exception as e:
            logger.error(f"Error generating image from text and multiple images: {e}")
            return None
    
    def _extract_image_from_response(self, response) -> Optional[Image.Image]:
        """Extract image from GenAI content generation response (for text+image processing)."""
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
    
    def _extract_image_from_generate_images_response(self, response) -> Optional[Image.Image]:
        """Extract image from GenAI image generation response."""
        try:
            if hasattr(response, 'generated_images') and response.generated_images:
                # Get the first generated image
                first_generated_image = response.generated_images[0]
                if hasattr(first_generated_image, 'image') and first_generated_image.image:
                    image_obj = first_generated_image.image
                    if hasattr(image_obj, 'image_bytes') and image_obj.image_bytes:
                        # Convert bytes to PIL Image
                        return Image.open(io.BytesIO(image_obj.image_bytes))
                    else:
                        logger.error(f"Image object has no image_bytes: {dir(image_obj)}")
                        return None
                else:
                    logger.error(f"GeneratedImage has no image: {dir(first_generated_image)}")
                    return None
            elif hasattr(response, 'images') and response.images:
                # Alternative: direct images list
                first_image = response.images[0]
                if hasattr(first_image, 'image_bytes'):
                    return Image.open(io.BytesIO(first_image.image_bytes))
                else:
                    logger.error(f"Unknown image format in images list: {dir(first_image)}")
                    return None
            else:
                logger.warning("No generated_images or images found in GenerateImagesResponse")
                return None
            
        except Exception as e:
            logger.error(f"Error extracting image from GenerateImagesResponse: {e}")
            return None