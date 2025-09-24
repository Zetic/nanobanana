import io
import logging
from PIL import Image
from google import genai
from google.genai import types
from typing import Optional, List, Tuple, Dict, Any
import config

logger = logging.getLogger(__name__)

class ImageGenerator:
    """Handles Google GenAI image generation."""
    
    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
        self.model = "gemini-2.5-flash-image-preview"
        self.text_only_model = "gemini-2.5-flash"
    
    async def generate_image_from_text(self, prompt: str) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt only. Returns (image, text_response, usage_metadata)."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt],
            )
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text: {e}")
            error_message = self._extract_error_message(e)
            return None, error_message, None
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from both text prompt and input image. Returns (image, text_response, usage_metadata)."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, input_image],
            )
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text and image: {e}")
            error_message = self._extract_error_message(e)
            return None, error_message, None
    
    async def generate_image_from_image_only(self, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from input image only with generic transformation prompt. Returns (image, text_response, usage_metadata)."""
        try:
            # Use a generic prompt that lets the AI decide how to transform the image
            generic_prompt = "Transform and enhance this image creatively while maintaining its core subject and essence."
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=[generic_prompt, input_image],
            )
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from image only: {e}")
            error_message = self._extract_error_message(e)
            return None, error_message, None
    
    async def generate_image_from_images_only(self, input_images: List[Image.Image]) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from multiple input images only with generic transformation prompt. Returns (image, text_response, usage_metadata)."""
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
                model=self.model,
                contents=contents,
            )
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from images only: {e}")
            error_message = self._extract_error_message(e)
            return None, error_message, None

    async def generate_image_from_text_and_images(self, prompt: str, input_images: List[Image.Image]) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt and multiple input images. Returns (image, text_response, usage_metadata)."""
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
                model=self.model,
                contents=contents,
            )
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text and multiple images: {e}")
            error_message = self._extract_error_message(e)
            return None, error_message, None

    async def generate_text_only_response(self, prompt: str, input_images: List[Image.Image] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
        """Generate text-only response for rate-limited users. Returns (None, text_response, usage_metadata)."""
        try:
            # Create appropriate prompt based on input
            if input_images:
                # If images are provided, describe them in the prompt since text-only model can't see them
                full_prompt = f"{prompt}\n\n[Note: Image(s) were provided but cannot be processed due to daily image generation limit. Responding with text only.]"
            else:
                full_prompt = prompt
            
            response = self.client.models.generate_content(
                model=self.text_only_model,
                contents=[full_prompt],
            )
            
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            # Always return None for image since this is text-only
            return None, text, usage
            
        except Exception as e:
            logger.error(f"Error generating text-only response: {e}")
            error_message = self._extract_error_message(e)
            return None, error_message, None
    
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

    def _extract_text_from_response(self, response) -> Optional[str]:
        """Extract text from GenAI response."""
        try:
            for part in response.candidates[0].content.parts:
                if part.text is not None:
                    return part.text.strip()
            
            logger.warning("No text found in GenAI response")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting text from response: {e}")
            return None

    def _extract_usage_from_response(self, response) -> Optional[Dict[str, Any]]:
        """Extract usage metadata from GenAI response."""
        try:
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage_metadata = response.usage_metadata
                return {
                    "prompt_token_count": getattr(usage_metadata, 'prompt_token_count', 0) or 0,
                    "candidates_token_count": getattr(usage_metadata, 'candidates_token_count', 0) or 0,
                    "total_token_count": getattr(usage_metadata, 'total_token_count', 0) or 0,
                    "cached_content_token_count": getattr(usage_metadata, 'cached_content_token_count', 0) or 0,
                }
            else:
                logger.warning("No usage metadata found in GenAI response")
                return {
                    "prompt_token_count": 0,
                    "candidates_token_count": 0,
                    "total_token_count": 0,
                    "cached_content_token_count": 0,
                }
            
        except Exception as e:
            logger.error(f"Error extracting usage metadata from response: {e}")
            return {
                "prompt_token_count": 0,
                "candidates_token_count": 0,
                "total_token_count": 0,
                "cached_content_token_count": 0,
            }

    def _extract_error_message(self, exception: Exception) -> str:
        """Extract informative error message from API exceptions."""
        try:
            # Check if it's a Google GenAI API error with a message attribute
            if hasattr(exception, 'message') and exception.message:
                return f"API Error: {exception.message}"
            
            # Check if it's a string representation that might be informative
            error_str = str(exception)
            if error_str and error_str.strip() and error_str != 'None':
                return f"Error: {error_str}"
                
            # Fallback to generic message if no useful error info
            return "An unexpected error occurred. Please try again with different input."
            
        except Exception:
            # If anything goes wrong extracting the error message, use fallback
            return "An unexpected error occurred. Please try again with different input."