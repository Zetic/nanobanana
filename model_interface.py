"""
Modular interface for different AI models.
This provides a unified interface for different AI model providers.
"""

import io
import json
import logging
import base64
import asyncio
import random
from abc import ABC, abstractmethod
from PIL import Image
from google import genai
from google.genai import types
from openai import OpenAI
from typing import Optional, List, Tuple, Dict, Any, Union
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
    async def generate_text_only_response(self, prompt: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate a response. Returns (image_or_none, text_response, usage_metadata). The image is non-None only when the implementation supports tool-based image generation."""
        pass


class GeminiModelGenerator(BaseModelGenerator):
    """Handles Google Gemini AI generation."""
    
    def __init__(self):
        if not config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
        
        self.client = genai.Client(api_key=config.GOOGLE_API_KEY)
        self.model = "gemini-2.5-flash-image"
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
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt],
                config=types.GenerateContentConfig(seed=random.randint(0, 2**31 - 1)),
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
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(seed=random.randint(0, 2**31 - 1)),
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
    """Handles OpenAI image generation using the gpt-image-2 model."""
    
    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.model = "gpt-image-2"
    
    async def _generate_image_only(self, prompt: str, streaming_callback=None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate image from text prompt using OpenAI Image API."""
        try:
            if streaming_callback:
                await streaming_callback("Generating image...")
            
            response = await asyncio.to_thread(
                self.client.images.generate,
                model=self.model,
                prompt=prompt,
                quality="medium",
            )
            
            generated_image = None
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
            logger.error(f"Error generating image with gpt-image-2: {e}")
            error_reason = str(e).strip() or "Unknown error"
            return None, f"❌ Failed to generate image.\nAttempted prompt: {prompt}\nReason: {error_reason}", None
    
    async def _generate_image_with_input_images(self, prompt: str, input_images: List[Image.Image], streaming_callback=None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate image using input images for editing/reference."""
        try:
            generated_image = None

            if streaming_callback:
                await streaming_callback("Editing image...")

            content_parts = [{"type": "input_text", "text": prompt}]
            for input_image in input_images:
                img_buffer = io.BytesIO()
                input_image.save(img_buffer, format='PNG')
                image_base64 = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
                content_parts.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{image_base64}",
                    }
                )

            def _responses_image_request():
                return self.client.responses.create(
                    model="gpt-5.4",
                    tools=[{"type": "image_generation", "model": self.model}],
                    input=[{"role": "user", "content": content_parts}],
                )

            response = await asyncio.to_thread(
                _responses_image_request
            )

            output_items = getattr(response, "output", None) or []
            image_base64 = None
            for output_item in output_items:
                if getattr(output_item, "type", None) == "image_generation_call":
                    image_base64 = getattr(output_item, "result", None)
                    if image_base64:
                        break

            if image_base64:
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
            error_reason = str(e).strip() or "Unknown error"
            return None, f"❌ Failed to generate image.\nAttempted prompt: {prompt}\nReason: {error_reason}", None
    
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


# Tool definition for image generation, used by ChatModelGenerator
IMAGE_GENERATION_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate an image based on a text description. "
            "Use this when the user requests image creation or generation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed text description of the image to generate.",
                },
                "model": {
                    "type": "string",
                    "enum": ["gemini", "gpt"],
                    "description": (
                        "The AI model to use for image generation. "
                        "Use 'gemini' for creative or artistic images; "
                        "use 'gpt' for photorealistic or detailed images."
                    ),
                },
            },
            "required": ["prompt", "model"],
        },
    },
}


class ChatModelGenerator(BaseModelGenerator):
    """Handles text chat responses using OpenAI GPT-5.4 mini, with image generation tool support."""
    
    def __init__(self):
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.text_only_model = "gpt-5.4-mini"
    
    def _extract_text_from_response(self, response) -> Optional[str]:
        """Extract text from OpenAI chat response."""
        try:
            if not response or not getattr(response, "choices", None):
                return None
            message = response.choices[0].message
            if message and message.content:
                return message.content.strip()
            return None
        except Exception as e:
            logger.error(f"Error extracting text from response: {e}")
            return None
    
    def _extract_usage_from_response(self, response) -> Optional[Dict[str, Any]]:
        """Extract usage metadata from OpenAI chat response."""
        try:
            if hasattr(response, 'usage') and response.usage:
                usage_metadata = response.usage
                return {
                    "prompt_token_count": getattr(usage_metadata, 'prompt_tokens', 0) or 0,
                    "candidates_token_count": getattr(usage_metadata, 'completion_tokens', 0) or 0,
                    "total_token_count": getattr(usage_metadata, 'total_tokens', 0) or 0,
                }
            else:
                return {
                    "prompt_token_count": 0,
                    "candidates_token_count": 0,
                    "total_token_count": 0,
                }
        except Exception as e:
            logger.error(f"Error extracting usage metadata: {e}")
            return {
                "prompt_token_count": 0,
                "candidates_token_count": 0,
                "total_token_count": 0,
            }

    async def _execute_image_generation_tool(self, prompt: str, model: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Execute the image generation tool using the specified model ('gemini' or 'gpt').

        When *input_images* are provided they are forwarded to the image generator so the
        model can edit/transform the supplied images rather than creating from scratch.
        """
        try:
            generator = get_model_generator(model)
            if input_images:
                if len(input_images) == 1:
                    return await generator.generate_image_from_text_and_image(prompt, input_images[0])
                return await generator.generate_image_from_text_and_image(prompt, input_images[0], additional_images=input_images[1:])
            return await generator.generate_image_from_text(prompt)
        except Exception as e:
            logger.error(f"Error executing image generation tool (model={model}): {e}")
            return None, None, None

    async def _generate_text_response(self, prompt: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate a response using OpenAI GPT-5.4 mini with image generation tool support."""
        try:
            if input_images:
                content: Union[str, List[Dict[str, Any]]] = [{"type": "text", "text": prompt}]
                for image in input_images:
                    img_buffer = io.BytesIO()
                    image.save(img_buffer, format='PNG')
                    image_base64 = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    })
            else:
                content = prompt

            response = self.client.chat.completions.create(
                model=self.text_only_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful Discord assistant. Reply in plain text only. "
                            "Use the generate_image tool when the user requests image creation, generation, or editing."
                        ),
                    },
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                tools=[IMAGE_GENERATION_TOOL],
                tool_choice="auto",
            )

            usage = self._extract_usage_from_response(response)

            # Check whether the model decided to call the image generation tool
            message = response.choices[0].message if response.choices else None
            if message and getattr(message, "tool_calls", None):
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "generate_image":
                        args = json.loads(tool_call.function.arguments)

                        image_prompt = args.get("prompt")
                        if not image_prompt:
                            logger.warning("generate_image tool call missing 'prompt'; falling back to user prompt")
                            image_prompt = prompt

                        image_model = args.get("model")
                        if not image_model:
                            logger.warning("generate_image tool call missing 'model'; defaulting to 'gemini'")
                            image_model = "gemini"

                        generated_image, image_text, image_usage = await self._execute_image_generation_tool(
                            image_prompt, image_model, input_images
                        )

                        # Merge usage from both the chat call and the image generation call
                        if image_usage and usage:
                            combined_usage = {
                                "prompt_token_count": usage.get("prompt_token_count", 0) + image_usage.get("prompt_token_count", 0),
                                "candidates_token_count": usage.get("candidates_token_count", 0) + image_usage.get("candidates_token_count", 0),
                                "total_token_count": usage.get("total_token_count", 0) + image_usage.get("total_token_count", 0),
                            }
                        else:
                            combined_usage = usage or image_usage or {}

                        combined_usage["image_model_used"] = image_model

                        # Only the first generate_image tool call is executed
                        return generated_image, image_text, combined_usage

            text = self._extract_text_from_response(response)
            return None, text, usage
            
        except Exception as e:
            logger.error(f"Error generating text response: {e}")
            return None, None, None
    
    async def generate_image_from_text(self, prompt: str, streaming_callback=None, aspect_ratio: Optional[str] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images directly; returns a text response."""
        return await self._generate_text_response(prompt)
    
    async def generate_image_from_text_and_image(self, prompt: str, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images directly; returns a text response."""
        # Combine all images into a list
        all_images = [input_image]
        if additional_images:
            all_images.extend(additional_images)
        return await self._generate_text_response(prompt, all_images)
    
    async def generate_image_from_image_only(self, input_image: Image.Image, streaming_callback=None, aspect_ratio: Optional[str] = None, additional_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Chat model doesn't generate images directly; returns a text response."""
        generic_prompt = "Please provide a text description or analysis of the provided content."
        # Combine all images into a list
        all_images = [input_image]
        if additional_images:
            all_images.extend(additional_images)
        return await self._generate_text_response(generic_prompt, all_images)
    
    async def generate_text_only_response(self, prompt: str, input_images: Optional[List[Image.Image]] = None) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate a response, potentially including an image if the model calls the image generation tool."""
        return await self._generate_text_response(prompt, input_images)


# Factory function to get the appropriate generator
def get_model_generator(model_type: str) -> BaseModelGenerator:
    """Get the appropriate model generator based on model type."""
    if model_type in ("nanobanana", "gemini"):
        return GeminiModelGenerator()
    elif model_type == "gpt":
        return GPTModelGenerator()
    elif model_type == "chat":
        return ChatModelGenerator()
    else:
        logger.warning(f"Unknown model type '{model_type}', defaulting to 'nanobanana'")
        return GeminiModelGenerator()
