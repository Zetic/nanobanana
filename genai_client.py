import io
import logging
from PIL import Image
from google import genai
from google.genai import types, errors
from typing import Optional, List, Tuple, Dict, Any
import config

logger = logging.getLogger(__name__)

# HTTP status code to description mapping for common errors
HTTP_ERROR_CODES = {
    400: {
        'INVALID_ARGUMENT': 'The request body is malformed. There is a typo, or a missing required field in your request.',
        'FAILED_PRECONDITION': 'Gemini API free tier is not available in your country. Please enable billing on your project in Google AI Studio.'
    },
    403: {'PERMISSION_DENIED': 'Your API key doesn\'t have the required permissions.'},
    404: {'NOT_FOUND': 'The requested resource wasn\'t found.'},
    429: {'RESOURCE_EXHAUSTED': 'You\'ve exceeded the rate limit.'},
    500: {'INTERNAL': 'An unexpected error occurred on Google\'s side.'},
    503: {'UNAVAILABLE': 'The service may be temporarily overloaded or down.'},
    504: {'DEADLINE_EXCEEDED': 'The service is unable to finish processing within the deadline.'}
}

# Safety block reason descriptions
SAFETY_BLOCK_REASONS = {
    'BLOCKED_REASON_UNSPECIFIED': 'The blocked reason is unspecified (default/fallback)',
    'SAFETY': 'The content was blocked for safety reasons (violation of configured safety filters)',
    'OTHER': 'The content was blocked for "other" reasons (not in standard categories)',
    'BLOCKLIST': 'The content was blocked because it matched a blocked term/terminology blocklist',
    'PROHIBITED_CONTENT': 'The content was blocked because it contains prohibited content (non-negotiable, e.g. CSAM)',
    'MODEL_ARMOR': 'The prompt was blocked by a defense layer called "Model Armor"',
    'IMAGE_SAFETY': 'The content was blocked because it\'s unsafe for image generation',
    'JAILBREAK': 'The content was blocked because it was considered a jailbreak attempt'
}

# Additional finish reason descriptions beyond safety
FINISH_REASON_DESCRIPTIONS = {
    'MAX_TOKENS': 'Response was truncated due to maximum token limit',
    'RECITATION': 'Content flagged for recitation concerns',
    'LANGUAGE': 'Content flagged for language reasons',
    'SPII': 'Content flagged for sensitive personally identifiable information',
    'MALFORMED_FUNCTION_CALL': 'Function call was malformed'
}

class ImageGenerator:
    """Handles Google GenAI image generation."""
    
    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
        self.model = "gemini-2.5-flash-image-preview"
        self.text_only_model = "gemini-2.5-flash"
    
    def _extract_error_message(self, error: Exception) -> Optional[str]:
        """Extract meaningful error message from API exception."""
        if isinstance(error, errors.APIError):
            try:
                # Get HTTP status code
                status_code = error.status if hasattr(error, 'status') else None
                
                # Try to extract structured error info
                if hasattr(error, 'message') and error.message:
                    return error.message
                
                # Fallback to string representation
                error_str = str(error)
                if error_str and error_str != str(type(error)):
                    return error_str
                    
            except Exception:
                pass
        
        # For non-API errors, return the string representation
        error_str = str(error)
        if error_str and error_str != str(type(error)):
            return error_str
            
        return None
    
    def _check_safety_blocking(self, response) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Check if response was blocked for safety reasons.
        Returns (block_reason, safety_message, suggested_fallback_prompt)
        """
        try:
            if not hasattr(response, 'candidates') or not response.candidates:
                return None, None, None
                
            candidate = response.candidates[0]
            
            # Check finish reason for safety blocks
            if hasattr(candidate, 'finish_reason') and candidate.finish_reason:
                finish_reason = str(candidate.finish_reason)
                
                # Handle safety-related finish reasons
                if finish_reason in ['SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'IMAGE_SAFETY']:
                    block_reason = SAFETY_BLOCK_REASONS.get(finish_reason, f"Content blocked: {finish_reason}")
                    
                    # Extract safety ratings for more detailed info
                    safety_details = []
                    if hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                        for rating in candidate.safety_ratings:
                            if hasattr(rating, 'category') and hasattr(rating, 'probability'):
                                safety_details.append(f"{rating.category}: {rating.probability}")
                    
                    safety_message = block_reason
                    if safety_details:
                        safety_message += f" (Safety ratings: {', '.join(safety_details)})"
                    
                    # Generate a suggested fallback prompt
                    fallback_prompt = ("Please provide a safe, appropriate response to the user's request. "
                                     "Avoid any content that might violate safety guidelines while still being helpful.")
                    
                    return finish_reason, safety_message, fallback_prompt
                    
                # Handle other finish reasons that might indicate issues
                elif finish_reason in FINISH_REASON_DESCRIPTIONS:
                    issue_msg = FINISH_REASON_DESCRIPTIONS[finish_reason]
                    return finish_reason, f"Generation stopped: {issue_msg}", None
                    
        except Exception as e:
            logger.warning(f"Error checking safety blocking: {e}")
            
        return None, None, None
    
    async def generate_image_from_text(self, prompt: str) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt only. Returns (image, text_response, usage_metadata)."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt],
            )
            
            # Check for safety blocking first
            block_reason, safety_message, fallback_prompt = self._check_safety_blocking(response)
            if block_reason:
                logger.info(f"Content blocked for safety: {block_reason}")
                
                # If we have a fallback prompt, try text-only generation
                if fallback_prompt:
                    try:
                        fallback_response = self.client.models.generate_content(
                            model=self.text_only_model,
                            contents=[f"{fallback_prompt}\n\nOriginal request: {prompt}"],
                        )
                        fallback_text = self._extract_text_from_response(fallback_response)
                        if fallback_text:
                            # Return both the safety message and fallback response
                            combined_message = f"{safety_message}\n\nAlternative response: {fallback_text}"
                            return None, combined_message, self._extract_usage_from_response(fallback_response)
                    except Exception as fallback_error:
                        logger.warning(f"Fallback generation failed: {fallback_error}")
                
                # Return just the safety message if fallback failed
                return None, safety_message, None
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text: {e}")
            error_message = self._extract_error_message(e)
            if error_message:
                return None, error_message, None
            return None, None, None
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from both text prompt and input image. Returns (image, text_response, usage_metadata)."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, input_image],
            )
            
            # Check for safety blocking first
            block_reason, safety_message, fallback_prompt = self._check_safety_blocking(response)
            if block_reason:
                logger.info(f"Content blocked for safety: {block_reason}")
                
                # If we have a fallback prompt, try text-only generation without the image
                if fallback_prompt:
                    try:
                        fallback_response = self.client.models.generate_content(
                            model=self.text_only_model,
                            contents=[f"{fallback_prompt}\n\nOriginal request: {prompt}\n\n[Note: An image was provided but cannot be processed due to safety restrictions.]"],
                        )
                        fallback_text = self._extract_text_from_response(fallback_response)
                        if fallback_text:
                            # Return both the safety message and fallback response
                            combined_message = f"{safety_message}\n\nAlternative response: {fallback_text}"
                            return None, combined_message, self._extract_usage_from_response(fallback_response)
                    except Exception as fallback_error:
                        logger.warning(f"Fallback generation failed: {fallback_error}")
                
                # Return just the safety message if fallback failed
                return None, safety_message, None
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text and image: {e}")
            error_message = self._extract_error_message(e)
            if error_message:
                return None, error_message, None
            return None, None, None
    
    async def generate_image_from_image_only(self, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from input image only with generic transformation prompt. Returns (image, text_response, usage_metadata)."""
        try:
            # Use a generic prompt that lets the AI decide how to transform the image
            generic_prompt = "Transform and enhance this image creatively while maintaining its core subject and essence."
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=[generic_prompt, input_image],
            )
            
            # Check for safety blocking first
            block_reason, safety_message, fallback_prompt = self._check_safety_blocking(response)
            if block_reason:
                logger.info(f"Content blocked for safety: {block_reason}")
                
                # If we have a fallback prompt, try text-only generation
                if fallback_prompt:
                    try:
                        fallback_response = self.client.models.generate_content(
                            model=self.text_only_model,
                            contents=[f"{fallback_prompt}\n\n[Note: An image was provided for transformation but cannot be processed due to safety restrictions.]"],
                        )
                        fallback_text = self._extract_text_from_response(fallback_response)
                        if fallback_text:
                            # Return both the safety message and fallback response
                            combined_message = f"{safety_message}\n\nAlternative response: {fallback_text}"
                            return None, combined_message, self._extract_usage_from_response(fallback_response)
                    except Exception as fallback_error:
                        logger.warning(f"Fallback generation failed: {fallback_error}")
                
                # Return just the safety message if fallback failed
                return None, safety_message, None
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from image only: {e}")
            error_message = self._extract_error_message(e)
            if error_message:
                return None, error_message, None
            return None, None, None
    
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
            
            # Check for safety blocking first
            block_reason, safety_message, fallback_prompt = self._check_safety_blocking(response)
            if block_reason:
                logger.info(f"Content blocked for safety: {block_reason}")
                
                # If we have a fallback prompt, try text-only generation
                if fallback_prompt:
                    try:
                        fallback_response = self.client.models.generate_content(
                            model=self.text_only_model,
                            contents=[f"{fallback_prompt}\n\n[Note: Multiple images were provided for combination but cannot be processed due to safety restrictions.]"],
                        )
                        fallback_text = self._extract_text_from_response(fallback_response)
                        if fallback_text:
                            # Return both the safety message and fallback response
                            combined_message = f"{safety_message}\n\nAlternative response: {fallback_text}"
                            return None, combined_message, self._extract_usage_from_response(fallback_response)
                    except Exception as fallback_error:
                        logger.warning(f"Fallback generation failed: {fallback_error}")
                
                # Return just the safety message if fallback failed
                return None, safety_message, None
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from images only: {e}")
            error_message = self._extract_error_message(e)
            if error_message:
                return None, error_message, None
            return None, None, None

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
            
            # Check for safety blocking first
            block_reason, safety_message, fallback_prompt = self._check_safety_blocking(response)
            if block_reason:
                logger.info(f"Content blocked for safety: {block_reason}")
                
                # If we have a fallback prompt, try text-only generation
                if fallback_prompt:
                    try:
                        fallback_response = self.client.models.generate_content(
                            model=self.text_only_model,
                            contents=[f"{fallback_prompt}\n\nOriginal request: {prompt}\n\n[Note: Multiple images were provided but cannot be processed due to safety restrictions.]"],
                        )
                        fallback_text = self._extract_text_from_response(fallback_response)
                        if fallback_text:
                            # Return both the safety message and fallback response
                            combined_message = f"{safety_message}\n\nAlternative response: {fallback_text}"
                            return None, combined_message, self._extract_usage_from_response(fallback_response)
                    except Exception as fallback_error:
                        logger.warning(f"Fallback generation failed: {fallback_error}")
                
                # Return just the safety message if fallback failed
                return None, safety_message, None
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text and multiple images: {e}")
            error_message = self._extract_error_message(e)
            if error_message:
                return None, error_message, None
            return None, None, None

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
            
            # Check for safety blocking (even text-only can be blocked)
            block_reason, safety_message, fallback_prompt = self._check_safety_blocking(response)
            if block_reason:
                logger.info(f"Text-only content blocked for safety: {block_reason}")
                return None, safety_message, None
            
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            # Always return None for image since this is text-only
            return None, text, usage
            
        except Exception as e:
            logger.error(f"Error generating text-only response: {e}")
            error_message = self._extract_error_message(e)
            if error_message:
                return None, error_message, None
            return None, None, None
    
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