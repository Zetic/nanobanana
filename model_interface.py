"""
Modular interface for different AI models.
This provides a unified interface for different AI model providers.
"""

import io
import logging
import base64
from abc import ABC, abstractmethod
from PIL import Image
from google import genai
from google.genai import types
from openai import OpenAI
from typing import Optional, List, Tuple, Dict, Any
import config

logger = logging.getLogger(__name__)


class BaseModelGenerator(ABC):
    """Abstract base class for AI model generators."""
    
    @abstractmethod
    async def generate_image_from_text(self, prompt: str) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt. Returns (image, text_response, usage_metadata)."""
        pass
    
    @abstractmethod  
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from both text prompt and input image. Returns (image, text_response, usage_metadata)."""
        pass
    
    @abstractmethod
    async def generate_image_from_image_only(self, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from input image only. Returns (image, text_response, usage_metadata)."""
        pass
        
    @abstractmethod
    async def generate_text_only_response(self, prompt: str, input_images: List[Image.Image] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
        """Generate text-only response. Returns (None, text_response, usage_metadata)."""
        pass


class GeminiModelGenerator(BaseModelGenerator):
    """Handles Google Gemini AI generation."""
    
    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
        self.model = "gemini-2.5-flash-image-preview"
        self.text_only_model = "gemini-2.5-flash"
    
    def _extract_image_from_response(self, response) -> Optional[Image.Image]:
        """Extract image from GenAI response."""
        try:
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content:
                        for part in candidate.content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                if part.inline_data.mime_type.startswith('image/'):
                                    # Try to use the data directly first (it should be bytes)
                                    try:
                                        return Image.open(io.BytesIO(part.inline_data.data))
                                    except Exception:
                                        # Fallback: try base64 decoding if direct bytes don't work
                                        try:
                                            image_data = base64.b64decode(part.inline_data.data)
                                            return Image.open(io.BytesIO(image_data))
                                        except Exception as e:
                                            logger.error(f"Failed to decode image data: {e}")
                                            continue
            return None
        except Exception as e:
            logger.error(f"Error extracting image from response: {e}")
            return None
    
    def _extract_text_from_response(self, response) -> Optional[str]:
        """Extract text from GenAI response."""
        try:
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content:
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                return part.text.strip()
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
    
    async def generate_image_from_text(self, prompt: str) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt only."""
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
            return None, None, None
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from both text prompt and input image."""
        try:
            # Convert PIL Image to bytes for API
            img_buffer = io.BytesIO()
            input_image.save(img_buffer, format='PNG')
            img_bytes = img_buffer.getvalue()
            
            # Create Part from bytes
            image_part = types.Part.from_bytes(
                data=img_bytes,
                mime_type='image/png'
            )
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, image_part],
            )
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text and image: {e}")
            return None, None, None
    
    async def generate_image_from_image_only(self, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from input image only with generic transformation prompt."""
        try:
            generic_prompt = "Transform this image in an interesting and creative way"
            return await self.generate_image_from_text_and_image(generic_prompt, input_image)
        except Exception as e:
            logger.error(f"Error generating image from image only: {e}")
            return None, None, None
    
    async def generate_text_only_response(self, prompt: str, input_images: List[Image.Image] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
        """Generate text-only response for rate-limited users."""
        try:
            # For text-only responses with images, include the images so the model can analyze them
            if input_images:
                contents = [prompt]
                for image in input_images:
                    img_buffer = io.BytesIO()
                    image.save(img_buffer, format='PNG')
                    img_bytes = img_buffer.getvalue()
                    
                    image_part = types.Part.from_bytes(
                        data=img_bytes,
                        mime_type='image/png'
                    )
                    contents.append(image_part)
            else:
                contents = [prompt]
            
            response = self.client.models.generate_content(
                model=self.text_only_model,
                contents=contents,
            )
            
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            return None, text, usage
            
        except Exception as e:
            logger.error(f"Error generating text-only response: {e}")
            return None, None, None


class GPTModelGenerator(BaseModelGenerator):
    """Handles OpenAI GPT-5 generation using the new API structure."""
    
    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.model = "gpt-5"
    
    async def _generate_with_gpt5(self, input_text: str) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate content using GPT-5 with image generation tools."""
        try:
            response = self.client.responses.create(
                model=self.model,
                input=input_text,
                tools=[{"type": "image_generation"}],
            )
            
            # Extract image data
            image_data = [
                output.result
                for output in response.output
                if output.type == "image_generation_call"
            ]
            
            generated_image = None
            if image_data:
                image_base64 = image_data[0]
                image_bytes = base64.b64decode(image_base64)
                generated_image = Image.open(io.BytesIO(image_bytes))
            
            # Generate simple text response
            text_response = f"Generated image using GPT-5 based on: {input_text}"
            
            # Create usage metadata (placeholder since GPT-5 API structure is not fully defined)
            usage_metadata = {
                "prompt_token_count": len(input_text.split()) * 2,  # Rough estimate
                "candidates_token_count": 10,  # Placeholder
                "total_token_count": len(input_text.split()) * 2 + 10,
            }
            
            return generated_image, text_response, usage_metadata
            
        except Exception as e:
            logger.error(f"Error generating with GPT-5: {e}")
            return None, None, None
    
    async def generate_image_from_text(self, prompt: str) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt only."""
        return await self._generate_with_gpt5(f"Generate an image: {prompt}")
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from both text prompt and input image."""
        # GPT-5 doesn't support image input in this API structure, so we'll use text only
        combined_prompt = f"Generate an image based on this description and the provided context: {prompt}"
        return await self._generate_with_gpt5(combined_prompt)
    
    async def generate_image_from_image_only(self, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from input image only."""
        # Since GPT-5 API doesn't accept image input in this structure, use a generic prompt
        generic_prompt = "Generate a creative and interesting image"
        return await self._generate_with_gpt5(generic_prompt)
    
    async def generate_text_only_response(self, prompt: str, input_images: List[Image.Image] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
        """Generate text-only response."""
        try:
            # For text-only, we'll simulate a response without image generation
            response_text = f"Text-only response: {prompt}"
            if input_images:
                response_text += " [Note: Image(s) were provided but cannot be processed in text-only mode.]"
            
            usage_metadata = {
                "prompt_token_count": len(prompt.split()) * 2,
                "candidates_token_count": len(response_text.split()),
                "total_token_count": len(prompt.split()) * 2 + len(response_text.split()),
            }
            
            return None, response_text, usage_metadata
            
        except Exception as e:
            logger.error(f"Error generating text-only response with GPT-5: {e}")
            return None, None, None


class ChatModelGenerator(BaseModelGenerator):
    """Handles text-only chat responses using Gemini."""
    
    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
        self.text_only_model = "gemini-2.5-flash"
    
    def _extract_text_from_response(self, response) -> Optional[str]:
        """Extract text from GenAI response."""
        try:
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content:
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                return part.text.strip()
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
                return {
                    "prompt_token_count": 0,
                    "candidates_token_count": 0,
                    "total_token_count": 0,
                    "cached_content_token_count": 0,
                }
        except Exception as e:
            logger.error(f"Error extracting usage metadata: {e}")
            return {
                "prompt_token_count": 0,
                "candidates_token_count": 0,
                "total_token_count": 0,
                "cached_content_token_count": 0,
            }
    
    async def _generate_text_response(self, prompt: str, input_images: List[Image.Image] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
        """Generate text response using Gemini."""
        try:
            # For text-only model, we need to process images differently
            if input_images:
                # Convert images to Parts for the text-only model to analyze
                contents = [prompt]
                for image in input_images:
                    img_buffer = io.BytesIO()
                    image.save(img_buffer, format='PNG')
                    img_bytes = img_buffer.getvalue()
                    
                    image_part = types.Part.from_bytes(
                        data=img_bytes,
                        mime_type='image/png'
                    )
                    contents.append(image_part)
            else:
                contents = [prompt]
            
            response = self.client.models.generate_content(
                model=self.text_only_model,
                contents=contents,
            )
            
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            return None, text, usage
            
        except Exception as e:
            logger.error(f"Error generating text response: {e}")
            return None, None, None
    
    async def generate_image_from_text(self, prompt: str) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images, only text responses."""
        return await self._generate_text_response(prompt)
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images, only text responses."""
        return await self._generate_text_response(prompt, [input_image])
    
    async def generate_image_from_image_only(self, input_image: Image.Image) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images, only text responses."""
        generic_prompt = "Please provide a text description or analysis of the provided content."
        return await self._generate_text_response(generic_prompt, [input_image])
    
    async def generate_text_only_response(self, prompt: str, input_images: List[Image.Image] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
        """Generate text-only response."""
        return await self._generate_text_response(prompt, input_images)


# Factory function to get the appropriate generator
def get_model_generator(model_type: str) -> BaseModelGenerator:
    """Get the appropriate model generator based on model type."""
    if model_type == "nanobanana":
        return GeminiModelGenerator()
    elif model_type == "gpt":
        return GPTModelGenerator()
    elif model_type == "chat":
        return ChatModelGenerator()
    else:
        logger.warning(f"Unknown model type '{model_type}', defaulting to 'nanobanana'")
        return GeminiModelGenerator()