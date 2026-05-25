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
from typing import Optional, List, Tuple, Dict, Any, Union, Callable, Awaitable
import config
from image_utils import download_image

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
    async def generate_text_only_response(
        self,
        prompt: str,
        input_images: Optional[List[Image.Image]] = None,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        allow_image_generation: bool = True,
    ) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
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
            seed = random.randint(0, 2**31 - 1)
            response = await asyncio.to_thread(
                lambda: self.client.models.generate_content(
                    model=self.model,
                    contents=[prompt],
                    config=types.GenerateContentConfig(seed=seed),
                )
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
            
            seed = random.randint(0, 2**31 - 1)
            response = await asyncio.to_thread(
                lambda: self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(seed=seed),
                )
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
    
    async def generate_text_only_response(
        self,
        prompt: str,
        input_images: Optional[List[Image.Image]] = None,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        allow_image_generation: bool = True,
    ) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
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
            
            response = await asyncio.to_thread(
                lambda: self.client.models.generate_content(
                    model=self.text_only_model,
                    contents=contents,
                )
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
    
    async def generate_text_only_response(
        self,
        prompt: str,
        input_images: Optional[List[Image.Image]] = None,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        allow_image_generation: bool = True,
    ) -> Tuple[None, Optional[str], Optional[Dict[str, Any]]]:
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
                        "Always default to 'gemini' unless the user explicitly requests GPT or OpenAI."
                    ),
                },
            },
            "required": ["prompt", "model"],
        },
    },
}

DISCORD_GET_USER_AVATAR_TOOL = {
    "type": "function",
    "function": {
        "name": "get_discord_user_avatar",
        "description": (
            "Get a Discord user's avatar URL from a provided snowflake ID or mention. "
            "Use this instead of guessing what a user's avatar looks like."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Discord user snowflake ID or mention such as <@1234567890>.",
                },
            },
            "required": ["user_id"],
        },
    },
}

DISCORD_SEARCH_USERS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_discord_users",
        "description": (
            "Search users in the current Discord server by username, display name, global name, "
            "nickname, or user ID."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to match against users in the current server.",
                },
            },
            "required": ["query"],
        },
    },
}

DISCORD_LIST_USERS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_discord_users",
        "description": "List all users in the current Discord server.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

DISCORD_GET_USER_INFO_TOOL = {
    "type": "function",
    "function": {
        "name": "get_discord_user_info",
        "description": (
            "Get structured information about a Discord user from a provided snowflake ID or mention. "
            "Use this instead of guessing personal details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Discord user snowflake ID or mention such as <@1234567890>.",
                },
            },
            "required": ["user_id"],
        },
    },
}

DISCORD_TOOLS = [
    DISCORD_GET_USER_AVATAR_TOOL,
    DISCORD_SEARCH_USERS_TOOL,
    DISCORD_LIST_USERS_TOOL,
    DISCORD_GET_USER_INFO_TOOL,
]

DISCORD_TOOL_NAMES = {tool["function"]["name"] for tool in DISCORD_TOOLS}
MAX_CHAT_TOOL_CALL_ROUNDS = 4


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

    def _accumulate_usage_metadata(self, *usage_items: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge usage metadata objects by summing standard token counters.

        Known token counters are summed across calls. Any extra metadata keys are copied
        through, with later values overwriting earlier ones.
        """
        merged = {
            "prompt_token_count": 0,
            "candidates_token_count": 0,
            "total_token_count": 0,
        }
        for usage in usage_items:
            if not usage:
                continue
            for key in ("prompt_token_count", "candidates_token_count", "total_token_count"):
                merged[key] += usage.get(key, 0) or 0
            for key, value in usage.items():
                if key not in merged:
                    merged[key] = value
        return merged

    def _build_available_tools(
        self,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        allow_image_generation: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return the tools that should be exposed to the chat model."""
        tools = []
        if allow_image_generation:
            tools.append(IMAGE_GENERATION_TOOL)
        if tool_executor:
            tools.extend(DISCORD_TOOLS)
        return tools

    def _build_system_prompt(self, discord_tools_available: bool = False) -> str:
        """Build the system prompt for conversational responses."""
        prompt = (
            "You are a helpful Discord assistant. Reply in plain text only. "
            "Use the generate_image tool when the user requests image creation, generation, or editing."
        )
        if discord_tools_available:
            prompt += (
                " When the user asks about Discord users or server membership, use the available Discord tools "
                "to look up the real data instead of guessing or hallucinating."
            )
            prompt += (
                " If the user wants you to edit or transform a mentioned user's avatar, first call "
                "get_discord_user_avatar and then use generate_image so the fetched avatar can be used as an input image."
            )
        return prompt

    def _serialize_tool_call(self, tool_call: Any, fallback_index: int) -> Dict[str, Any]:
        """Convert an SDK tool_call object into a chat-completions message payload."""
        tool_call_id = getattr(tool_call, "id", None) or f"tool_call_{fallback_index}"
        return {
            "id": tool_call_id,
            "type": "function",
            "function": {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            },
        }

    async def _execute_non_image_tool_calls(
        self,
        tool_calls: List[Any],
        tool_executor: Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """Execute supported non-image tool calls and return assistant/tool follow-up messages plus image URLs."""
        serialized_calls: List[Dict[str, Any]] = []
        tool_messages: List[Dict[str, Any]] = []
        discovered_image_urls: List[str] = []

        for index, tool_call in enumerate(tool_calls):
            tool_name = getattr(tool_call.function, "name", "")
            if tool_name not in DISCORD_TOOL_NAMES:
                continue

            serialized_call = self._serialize_tool_call(tool_call, index)
            serialized_calls.append(serialized_call)

            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            result = await tool_executor(tool_name, args)
            avatar_url = result.get("avatar_url") or ((result.get("user") or {}).get("avatar_url"))
            if avatar_url:
                discovered_image_urls.append(avatar_url)
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": serialized_call["id"],
                    "content": json.dumps(result),
                }
            )

        return serialized_calls, tool_messages, discovered_image_urls

    async def _download_tool_result_images(self, image_urls: List[str]) -> List[Image.Image]:
        """Download unique tool-result image URLs for reuse in image-generation tool calls."""
        images: List[Image.Image] = []
        seen_urls = set()
        for image_url in image_urls:
            if not image_url or image_url in seen_urls:
                continue
            seen_urls.add(image_url)
            image = await download_image(image_url)
            if image:
                images.append(image)
        return images

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

    async def _generate_image_followup_text(self, original_prompt: str) -> Optional[str]:
        """Generate a brief conversational response after an image has been generated.

        Rather than surfacing the internal image-model prompt, this makes a second
        lightweight chat-completion call so the user receives a natural reply.
        """
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful Discord assistant. Reply in plain text only. "
                        "An image was just generated for the user based on their request. "
                        "Acknowledge the image creation and briefly describe what was created "
                        "based on the user's request, in 1-2 friendly sentences."
                    ),
                },
                {"role": "user", "content": original_prompt},
            ]
            response = await asyncio.to_thread(
                lambda: self.client.chat.completions.create(
                    model=self.text_only_model,
                    messages=messages,
                )
            )
            return self._extract_text_from_response(response)
        except Exception as e:
            logger.error(f"Error generating follow-up text after image generation: {e}")
            return None

    async def _generate_text_response(
        self,
        prompt: str,
        input_images: Optional[List[Image.Image]] = None,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        allow_image_generation: bool = True,
    ) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
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

            messages = [
                {
                    "role": "system",
                    "content": self._build_system_prompt(discord_tools_available=tool_executor is not None),
                },
                {
                    "role": "user",
                    "content": content
                }
            ]
            combined_usage: Dict[str, Any] = {
                "prompt_token_count": 0,
                "candidates_token_count": 0,
                "total_token_count": 0,
            }
            tools = self._build_available_tools(tool_executor, allow_image_generation=allow_image_generation)
            tool_result_image_urls: List[str] = []

            for round_number in range(1, MAX_CHAT_TOOL_CALL_ROUNDS + 1):
                response = await asyncio.to_thread(
                    lambda: self.client.chat.completions.create(
                        model=self.text_only_model,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                    )
                )

                combined_usage = self._accumulate_usage_metadata(combined_usage, self._extract_usage_from_response(response))

                message = response.choices[0].message if response.choices else None
                tool_calls = list(getattr(message, "tool_calls", None) or [])
                if not tool_calls:
                    text = self._extract_text_from_response(response)
                    return None, text, combined_usage

                for tool_call in tool_calls:
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

                        tool_images = await self._download_tool_result_images(tool_result_image_urls)
                        generation_input_images = list(input_images or [])
                        generation_input_images.extend(tool_images)
                        generation_input_images = generation_input_images or None

                        generated_image, image_text, image_usage = await self._execute_image_generation_tool(
                            image_prompt, image_model, generation_input_images
                        )

                        combined_usage = self._accumulate_usage_metadata(combined_usage, image_usage)
                        combined_usage["image_model_used"] = image_model

                        conversational_text = await self._generate_image_followup_text(prompt)
                        return generated_image, conversational_text, combined_usage

                if not tool_executor:
                    text = self._extract_text_from_response(response)
                    return None, text, combined_usage

                serialized_calls, tool_messages, discovered_image_urls = await self._execute_non_image_tool_calls(tool_calls, tool_executor)
                if not serialized_calls:
                    text = self._extract_text_from_response(response)
                    return None, text, combined_usage
                tool_result_image_urls.extend(discovered_image_urls)

                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": serialized_calls,
                    }
                )
                messages.extend(tool_messages)

            logger.warning(
                "Chat tool-calling exhausted after %s rounds for prompt %r with %s messages accumulated",
                round_number,
                prompt,
                len(messages),
            )
            return None, (
                f"Unable to complete that request after {MAX_CHAT_TOOL_CALL_ROUNDS} tool call rounds. "
                "Please simplify your request or try again."
            ), combined_usage
            
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
    
    async def generate_text_only_response(
        self,
        prompt: str,
        input_images: Optional[List[Image.Image]] = None,
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        allow_image_generation: bool = True,
    ) -> Tuple[Optional[Image.Image], Optional[str], Optional[Dict[str, Any]]]:
        """Generate a response, potentially including an image if the model calls the image generation tool."""
        return await self._generate_text_response(prompt, input_images, tool_executor, allow_image_generation=allow_image_generation)


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
