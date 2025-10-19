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
    async def generate_image_from_text(self, prompt: str, streaming_callback=None, aspect_ratio: Optional[str] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt. Returns (image, text_response, usage_metadata)."""
        pass
    
    @abstractmethod  
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from both text prompt and input image(s). Returns (image, text_response, usage_metadata)."""
        pass
    
    @abstractmethod
    async def generate_image_from_image_only(self, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from input image(s) only. Returns (image, text_response, usage_metadata)."""
        pass
        
    @abstractmethod
    async def generate_text_only_response(self, prompt: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
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
    
    async def generate_image_from_text(self, prompt: str, streaming_callback=None, aspect_ratio: Optional[str] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt only."""
        try:
            # Build config for generate_content
            config_params = {
                "response_modalities": ["IMAGE"]
            }
            
            # Add aspect ratio to image config if specified
            if aspect_ratio:
                config_params["image_config"] = types.ImageConfig(
                    aspect_ratio=aspect_ratio
                )
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt],
                config=types.GenerateContentConfig(**config_params)
            )
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text: {e}")
            return None, None, None
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from both text prompt and input image(s)."""
        try:
            # Convert PIL Image to bytes for API
            img_buffer = io.BytesIO()
            input_image.save(img_buffer, format='PNG')
            img_bytes = img_buffer.getvalue()
            
            # Create Part from bytes for primary image
            image_part = types.Part.from_bytes(
                data=img_bytes,
                mime_type='image/png'
            )
            
            # Prepare contents list with prompt and primary image
            contents = [prompt, image_part]
            
            # Add additional images if provided
            if additional_images:
                for add_image in additional_images:
                    add_img_buffer = io.BytesIO()
                    add_image.save(add_img_buffer, format='PNG')
                    add_img_bytes = add_img_buffer.getvalue()
                    
                    add_image_part = types.Part.from_bytes(
                        data=add_img_bytes,
                        mime_type='image/png'
                    )
                    contents.append(add_image_part)
            
            # Build config for generate_content
            config_params = {
                "response_modalities": ["IMAGE"]
            }
            
            # Add aspect ratio to image config if specified
            if aspect_ratio:
                config_params["image_config"] = types.ImageConfig(
                    aspect_ratio=aspect_ratio
                )
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config_params)
            )
            
            image = self._extract_image_from_response(response)
            text = self._extract_text_from_response(response)
            usage = self._extract_usage_from_response(response)
            
            return image, text, usage
            
        except Exception as e:
            logger.error(f"Error generating image from text and image: {e}")
            return None, None, None
    
    async def generate_image_from_image_only(self, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from input image(s) only with generic transformation prompt."""
        try:
            generic_prompt = "Transform this image in an interesting and creative way"
            return await self.generate_image_from_text_and_image(generic_prompt, input_image, streaming_callback, aspect_ratio, additional_images)
        except Exception as e:
            logger.error(f"Error generating image from image only: {e}")
            return None, None, None
    
    async def generate_text_only_response(self, prompt: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
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
    """Handles OpenAI image generation using the gpt-image-1 model."""
    
    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.model = "gpt-image-1"
    
    async def _generate_image_only(self, prompt: str, streaming_callback=None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate image from text prompt using OpenAI Image API with streaming."""
        try:
            # Use streaming generation with partial images
            stream = self.client.images.generate(
                model=self.model,
                prompt=prompt,
                quality="medium",
                stream=True,
                partial_images=3,
                response_format="b64_json"  # Ensure we get base64 encoded responses
            )
            
            generated_image = None
            partial_count = 0
            
            for event in stream:
                if event.type == "image_generation.partial_image":
                    partial_count += 1
                    # Log partial image received (could save them if needed)
                    logger.info(f"Received partial image {event.partial_image_index + 1}/3")
                    
                    # Update Discord message with partial image if callback provided
                    if streaming_callback:
                        try:
                            # Convert partial image to PIL Image and send to callback
                            if hasattr(event, 'b64_json') and event.b64_json:
                                image_bytes = base64.b64decode(event.b64_json)
                                partial_image = Image.open(io.BytesIO(image_bytes))
                                # Call callback with partial image instead of just text
                                await streaming_callback(f"Generating image... ({partial_count}/3)", partial_image)
                            else:
                                # Fallback to text if no image data
                                await streaming_callback(f"Generating image... ({partial_count}/3)")
                        except Exception as callback_error:
                            logger.warning(f"Streaming callback failed: {callback_error}")
                    
                    # Could save partial images for debugging:
                    # image_base64 = event.b64_json
                    # image_bytes = base64.b64decode(image_base64)
                    # with open(f"partial_{event.partial_image_index}.png", "wb") as f:
                    #     f.write(image_bytes)
                elif event.type == "image_generation.done":
                    # Final image
                    image_base64 = event.b64_json
                    image_bytes = base64.b64decode(image_base64)
                    generated_image = Image.open(io.BytesIO(image_bytes))
            
            # If streaming didn't work, fall back to non-streaming
            if generated_image is None:
                logger.info("Streaming failed, falling back to non-streaming generation")
                response = self.client.images.generate(
                    model=self.model,
                    prompt=prompt,
                    quality="medium",
                    response_format="b64_json"
                )
                if response.data and len(response.data) > 0:
                    image_base64 = response.data[0].b64_json
                    image_bytes = base64.b64decode(image_base64)
                    generated_image = Image.open(io.BytesIO(image_bytes))
            
            # Return just the prompt as text response (as requested in issue)
            text_response = prompt
            
            # Create usage metadata
            usage_metadata = {
                "prompt_token_count": len(prompt.split()) * 1.3,  # Rough estimate for image prompts
                "candidates_token_count": 0,  # No text generation
                "total_token_count": len(prompt.split()) * 1.3,
            }
            
            return generated_image, text_response, usage_metadata
            
        except Exception as e:
            logger.error(f"Error generating image with gpt-image-1: {e}")
            return None, None, None
    
    async def _generate_image_with_input_images(self, prompt: str, input_images: List[Image.Image], streaming_callback=None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate image using input images for editing/reference with streaming."""
        temp_filename = None
        try:
            # For image editing, we'll use the first image as primary
            # OpenAI image edit API takes a single image, not a list
            primary_image = input_images[0]
            
            # Convert PIL image to binary format for the API
            # Some versions of OpenAI API work better with actual file handles
            import tempfile
            import os
            
            # Save to temporary file first (some APIs prefer this)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                primary_image.save(temp_file.name, format='PNG')
                temp_filename = temp_file.name
            
            generated_image = None
            
            # Try streaming first - images.edit API also supports streaming  
            try:
                with open(temp_filename, 'rb') as img_file:
                    stream = self.client.images.edit(
                        model=self.model,
                        image=img_file,  # Use file handle directly
                        prompt=prompt,
                        quality="medium",
                        stream=True,
                        partial_images=3,
                        response_format="b64_json"  # Ensure we get base64 encoded responses
                    )
                
                partial_count = 0
                
                for event in stream:
                    if event.type == "image_generation.partial_image":
                        partial_count += 1
                        # Log partial image received for image editing
                        logger.info(f"Received partial edited image {event.partial_image_index + 1}/3")
                        
                        # Update Discord message with partial image if callback provided
                        if streaming_callback:
                            try:
                                # Convert partial image to PIL Image and send to callback
                                if hasattr(event, 'b64_json') and event.b64_json:
                                    image_bytes = base64.b64decode(event.b64_json)
                                    partial_image = Image.open(io.BytesIO(image_bytes))
                                    # Call callback with partial image instead of just text
                                    await streaming_callback(f"Editing image... ({partial_count}/3)", partial_image)
                                else:
                                    # Fallback to text if no image data
                                    await streaming_callback(f"Editing image... ({partial_count}/3)")
                            except Exception as callback_error:
                                logger.warning(f"Streaming callback failed: {callback_error}")
                        
                    elif event.type == "image_generation.done":
                        # Final edited image
                        image_base64 = event.b64_json
                        image_bytes = base64.b64decode(image_base64)
                        generated_image = Image.open(io.BytesIO(image_bytes))
                
                # If streaming worked, return the result
                if generated_image is not None:
                    text_response = prompt
                    usage_metadata = {
                        "prompt_token_count": len(prompt.split()) * 1.3 + len(input_images) * 50,
                        "candidates_token_count": 0,
                        "total_token_count": len(prompt.split()) * 1.3 + len(input_images) * 50,
                    }
                    return generated_image, text_response, usage_metadata
                
            except Exception as streaming_error:
                logger.info(f"Streaming failed for image editing, falling back to non-streaming: {streaming_error}")
            
            # Fallback to non-streaming if streaming failed
            with open(temp_filename, 'rb') as img_file:
                response = self.client.images.edit(
                    model=self.model,
                    image=img_file,  # Use file handle directly
                    prompt=prompt,
                    quality="medium",
                    response_format="b64_json"  # Ensure we get base64 encoded responses
                )
            
            if response.data and len(response.data) > 0:
                image_base64 = response.data[0].b64_json
                image_bytes = base64.b64decode(image_base64)
                generated_image = Image.open(io.BytesIO(image_bytes))
            
            # Return just the prompt as text response (matching issue requirements)
            text_response = prompt
            
            # Create usage metadata
            usage_metadata = {
                "prompt_token_count": len(prompt.split()) * 1.3 + len(input_images) * 50,  # Account for image processing
                "candidates_token_count": 0,
                "total_token_count": len(prompt.split()) * 1.3 + len(input_images) * 50,
            }
            
            return generated_image, text_response, usage_metadata
            
        except Exception as e:
            logger.error(f"Error generating image with input images: {e}")
            return None, None, None
        finally:
            # Clean up temporary file if it exists
            try:
                if temp_filename and os.path.exists(temp_filename):
                    os.unlink(temp_filename)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temporary file: {cleanup_error}")
    
    async def generate_image_from_text(self, prompt: str, streaming_callback=None, aspect_ratio: Optional[str] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from text prompt only."""
        return await self._generate_image_only(prompt, streaming_callback)
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from both text prompt and input image(s)."""
        # Combine all images into a list
        all_images = [input_image]
        if additional_images:
            all_images.extend(additional_images)
        return await self._generate_image_with_input_images(prompt, all_images, streaming_callback)
    
    async def generate_image_from_image_only(self, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate an image from input image(s) only."""
        # Use a generic creative prompt for image-only generation
        generic_prompt = "Transform this image in a creative and interesting way"
        # Combine all images into a list
        all_images = [input_image]
        if additional_images:
            all_images.extend(additional_images)
        return await self._generate_image_with_input_images(generic_prompt, all_images, streaming_callback)
    
    async def generate_text_only_response(self, prompt: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
        """Generate text-only response. GPT Image API doesn't support text-only, so return a simple response."""
        try:
            # Since this is the image model, we can't generate text-only responses
            # Return a simple acknowledgment
            response_text = f"I understand you want: {prompt}"
            if input_images:
                response_text += f" [Note: {len(input_images)} image(s) were provided but I can only generate images, not analyze them in text-only mode.]"
            
            usage_metadata = {
                "prompt_token_count": len(prompt.split()),
                "candidates_token_count": len(response_text.split()),
                "total_token_count": len(prompt.split()) + len(response_text.split()),
            }
            
            return None, response_text, usage_metadata
            
        except Exception as e:
            logger.error(f"Error generating text-only response: {e}")
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
    
    async def _generate_text_response(self, prompt: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
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
    
    async def generate_image_from_text(self, prompt: str, streaming_callback=None, aspect_ratio: Optional[str] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images, only text responses."""
        return await self._generate_text_response(prompt)
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images, only text responses."""
        # Combine all images into a list
        all_images = [input_image]
        if additional_images:
            all_images.extend(additional_images)
        return await self._generate_text_response(prompt, all_images)
    
    async def generate_image_from_image_only(self, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images, only text responses."""
        generic_prompt = "Please provide a text description or analysis of the provided content."
        # Combine all images into a list
        all_images = [input_image]
        if additional_images:
            all_images.extend(additional_images)
        return await self._generate_text_response(generic_prompt, all_images)
    
    async def generate_text_only_response(self, prompt: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
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