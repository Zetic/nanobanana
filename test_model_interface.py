import base64
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

import model_interface


def _png_b64() -> str:
    image = Image.new("RGB", (1, 1), color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class TestGPTModelGenerator(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def _mock_to_thread_call(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def test_generate_stream_call_omits_unsupported_params(self):
        mock_images = Mock()
        mock_images.generate.return_value = SimpleNamespace(
            data=[SimpleNamespace(b64_json=_png_b64())]
        )
        mock_client = SimpleNamespace(images=mock_images)

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), patch.object(
            model_interface, "OpenAI", return_value=mock_client
        ), patch.object(model_interface.asyncio, "to_thread", new=AsyncMock(side_effect=self._mock_to_thread_call)) as mock_to_thread:
            generator = model_interface.GPTModelGenerator()
            image, text, usage = await generator._generate_image_only("banana")

        self.assertIsNotNone(image)
        self.assertEqual(text, "banana")
        self.assertIsNotNone(usage)
        mock_to_thread.assert_awaited_once()

        kwargs = mock_images.generate.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-image-2")
        self.assertEqual(kwargs["prompt"], "banana")
        self.assertEqual(kwargs["quality"], "medium")
        self.assertNotIn("seed", kwargs)
        self.assertNotIn("stream", kwargs)
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("partial_images", kwargs)

    async def test_edit_stream_call_omits_unsupported_params(self):
        mock_images = Mock()
        mock_responses = Mock()
        mock_responses.create.return_value = SimpleNamespace(
            output=[SimpleNamespace(type="image_generation_call", result=_png_b64())]
        )
        mock_client = SimpleNamespace(images=mock_images, responses=mock_responses)
        input_image = Image.new("RGB", (2, 2), color="blue")

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), patch.object(
            model_interface, "OpenAI", return_value=mock_client
        ), patch.object(model_interface.asyncio, "to_thread", new=AsyncMock(side_effect=self._mock_to_thread_call)) as mock_to_thread:
            generator = model_interface.GPTModelGenerator()
            image, text, usage = await generator._generate_image_with_input_images(
                "edit banana", [input_image]
            )

        self.assertIsNotNone(image)
        self.assertEqual(text, "edit banana")
        self.assertIsNotNone(usage)
        mock_to_thread.assert_awaited_once()

        kwargs = mock_responses.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.4")
        self.assertEqual(len(kwargs["tools"]), 1)
        tool = kwargs["tools"][0]
        self.assertEqual(tool["type"], "image_generation")
        self.assertEqual(tool["model"], "gpt-image-2")
        self.assertNotIn("seed", tool)
        self.assertEqual(kwargs["input"][0]["role"], "user")
        self.assertEqual(kwargs["input"][0]["content"][0], {"type": "input_text", "text": "edit banana"})
        input_image_payload = kwargs["input"][0]["content"][1]
        self.assertEqual(input_image_payload["type"], "input_image")
        self.assertTrue(input_image_payload["image_url"].startswith("data:image/png;base64,"))
        decoded_image_bytes = base64.b64decode(input_image_payload["image_url"].split(",", 1)[1])
        self.assertTrue(decoded_image_bytes.startswith(b"\x89PNG"))
        self.assertNotIn("quality", kwargs)
        self.assertNotIn("stream", kwargs)
        self.assertNotIn("prompt", kwargs)
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("partial_images", kwargs)
        mock_images.edit.assert_not_called()

    async def test_edit_failure_returns_prompt_and_reason(self):
        mock_images = Mock()
        mock_responses = Mock()
        mock_responses.create.side_effect = RuntimeError("Rate limit exceeded")
        mock_client = SimpleNamespace(images=mock_images, responses=mock_responses)
        input_image = Image.new("RGB", (2, 2), color="blue")

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), patch.object(
            model_interface, "OpenAI", return_value=mock_client
        ), patch.object(model_interface.asyncio, "to_thread", new=AsyncMock(side_effect=self._mock_to_thread_call)):
            generator = model_interface.GPTModelGenerator()
            image, text, usage = await generator._generate_image_with_input_images(
                "invert this", [input_image]
            )

        self.assertIsNone(image)
        self.assertIsNone(usage)
        self.assertEqual(
            text,
            "❌ Failed to generate image.\nAttempted prompt: invert this\nReason: Rate limit exceeded",
        )


class TestChatModelGeneratorToolCalling(unittest.IsolatedAsyncioTestCase):
    def _make_tool_call(self, prompt: str, model: str):
        """Build a minimal tool_call object matching the OpenAI SDK shape."""
        tool_call = SimpleNamespace(
            function=SimpleNamespace(
                name="generate_image",
                arguments=json.dumps({"prompt": prompt, "model": model}),
            )
        )
        return tool_call

    def _make_chat_response(self, tool_calls=None, content=None):
        """Build a minimal chat completion response."""
        message = SimpleNamespace(tool_calls=tool_calls, content=content)
        choice = SimpleNamespace(message=message)
        usage = SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7)
        return SimpleNamespace(choices=[choice], usage=usage)

    async def test_tool_call_uses_gemini_model(self):
        """When the model returns a generate_image tool call with model='gemini', GeminiModelGenerator is used."""
        tool_call = self._make_tool_call("a red apple", "gemini")
        chat_response = self._make_chat_response(tool_calls=[tool_call])

        mock_chat = Mock()
        mock_chat.completions.create.return_value = chat_response
        mock_client = SimpleNamespace(chat=mock_chat)

        fake_image = Image.new("RGB", (1, 1))

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=mock_client):
            generator = model_interface.ChatModelGenerator()
            with patch.object(
                generator, "_execute_image_generation_tool",
                new=AsyncMock(return_value=(fake_image, "a red apple", {"prompt_token_count": 3, "candidates_token_count": 0, "total_token_count": 3}))
            ) as mock_exec:
                image, text, usage = await generator._generate_text_response("draw a red apple")

        mock_exec.assert_awaited_once_with("a red apple", "gemini", None)
        self.assertIs(image, fake_image)
        self.assertEqual(text, "a red apple")
        self.assertIsNotNone(usage)

    async def test_tool_call_uses_gpt_model(self):
        """When the model returns a generate_image tool call with model='gpt', GPTModelGenerator is used."""
        tool_call = self._make_tool_call("a blue sky", "gpt")
        chat_response = self._make_chat_response(tool_calls=[tool_call])

        mock_chat = Mock()
        mock_chat.completions.create.return_value = chat_response
        mock_client = SimpleNamespace(chat=mock_chat)

        fake_image = Image.new("RGB", (1, 1))

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=mock_client):
            generator = model_interface.ChatModelGenerator()
            with patch.object(
                generator, "_execute_image_generation_tool",
                new=AsyncMock(return_value=(fake_image, "a blue sky", {"prompt_token_count": 2, "candidates_token_count": 0, "total_token_count": 2}))
            ) as mock_exec:
                image, text, usage = await generator._generate_text_response("draw a blue sky")

        mock_exec.assert_awaited_once_with("a blue sky", "gpt", None)
        self.assertIs(image, fake_image)

    async def test_no_tool_call_returns_text_only(self):
        """When the model returns plain text (no tool call), the image is None."""
        chat_response = self._make_chat_response(tool_calls=None, content="Hello, world!")

        mock_chat = Mock()
        mock_chat.completions.create.return_value = chat_response
        mock_client = SimpleNamespace(chat=mock_chat)

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=mock_client):
            generator = model_interface.ChatModelGenerator()
            image, text, usage = await generator._generate_text_response("tell me a joke")

        self.assertIsNone(image)
        self.assertEqual(text, "Hello, world!")
        self.assertIsNotNone(usage)

    async def test_chat_completions_call_includes_tool_definition(self):
        """The chat completions API call must include the IMAGE_GENERATION_TOOL and tool_choice='auto'."""
        chat_response = self._make_chat_response(tool_calls=None, content="hi")

        mock_chat = Mock()
        mock_chat.completions.create.return_value = chat_response
        mock_client = SimpleNamespace(chat=mock_chat)

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=mock_client):
            generator = model_interface.ChatModelGenerator()
            await generator._generate_text_response("hello")

        call_kwargs = mock_chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["tool_choice"], "auto")
        tools = call_kwargs["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["function"]["name"], "generate_image")
        params = tools[0]["function"]["parameters"]["properties"]
        self.assertIn("prompt", params)
        self.assertIn("model", params)
        self.assertIn("gemini", params["model"]["enum"])
        self.assertIn("gpt", params["model"]["enum"])

    async def test_execute_image_generation_tool_gemini(self):
        """_execute_image_generation_tool without images delegates to generate_image_from_text."""
        fake_image = Image.new("RGB", (2, 2))

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=SimpleNamespace(chat=Mock())):
            generator = model_interface.ChatModelGenerator()

        mock_gemini = SimpleNamespace(
            generate_image_from_text=AsyncMock(return_value=(fake_image, "cat", {"total_token_count": 5}))
        )
        with patch.object(model_interface, "get_model_generator", return_value=mock_gemini) as mock_factory:
            image, text, usage = await generator._execute_image_generation_tool("a cat", "gemini")

        mock_factory.assert_called_once_with("gemini")
        mock_gemini.generate_image_from_text.assert_awaited_once_with("a cat")
        self.assertIs(image, fake_image)
        self.assertEqual(text, "cat")

    async def test_execute_image_generation_tool_gpt(self):
        """_execute_image_generation_tool without images delegates to generate_image_from_text."""
        fake_image = Image.new("RGB", (2, 2))

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=SimpleNamespace(chat=Mock())):
            generator = model_interface.ChatModelGenerator()

        mock_gpt = SimpleNamespace(
            generate_image_from_text=AsyncMock(return_value=(fake_image, "dog", {"total_token_count": 4}))
        )
        with patch.object(model_interface, "get_model_generator", return_value=mock_gpt) as mock_factory:
            image, text, usage = await generator._execute_image_generation_tool("a dog", "gpt")

        mock_factory.assert_called_once_with("gpt")
        mock_gpt.generate_image_from_text.assert_awaited_once_with("a dog")
        self.assertIs(image, fake_image)

    async def test_execute_image_generation_tool_with_single_image(self):
        """_execute_image_generation_tool with one image calls generate_image_from_text_and_image."""
        fake_image = Image.new("RGB", (2, 2))
        input_image = Image.new("RGB", (3, 3), color="red")

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=SimpleNamespace(chat=Mock())):
            generator = model_interface.ChatModelGenerator()

        mock_gen = SimpleNamespace(
            generate_image_from_text_and_image=AsyncMock(return_value=(fake_image, "edited", {"total_token_count": 6}))
        )
        with patch.object(model_interface, "get_model_generator", return_value=mock_gen):
            image, text, usage = await generator._execute_image_generation_tool("make it green", "gemini", [input_image])

        mock_gen.generate_image_from_text_and_image.assert_awaited_once_with("make it green", input_image)
        self.assertIs(image, fake_image)

    async def test_execute_image_generation_tool_with_multiple_images(self):
        """_execute_image_generation_tool with multiple images passes extras as additional_images."""
        fake_image = Image.new("RGB", (2, 2))
        img1 = Image.new("RGB", (3, 3), color="red")
        img2 = Image.new("RGB", (3, 3), color="blue")

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=SimpleNamespace(chat=Mock())):
            generator = model_interface.ChatModelGenerator()

        mock_gen = SimpleNamespace(
            generate_image_from_text_and_image=AsyncMock(return_value=(fake_image, "merged", {"total_token_count": 8}))
        )
        with patch.object(model_interface, "get_model_generator", return_value=mock_gen):
            image, text, usage = await generator._execute_image_generation_tool("combine", "gpt", [img1, img2])

        mock_gen.generate_image_from_text_and_image.assert_awaited_once_with("combine", img1, additional_images=[img2])
        self.assertIs(image, fake_image)

    async def test_tool_call_passes_images_to_execute(self):
        """When input_images are present, _execute_image_generation_tool is called with them."""
        tool_call = self._make_tool_call("turn it green", "gemini")
        chat_response = self._make_chat_response(tool_calls=[tool_call])

        mock_chat = Mock()
        mock_chat.completions.create.return_value = chat_response
        mock_client = SimpleNamespace(chat=mock_chat)

        fake_image = Image.new("RGB", (1, 1))
        input_image = Image.new("RGB", (4, 4), color="red")

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=mock_client):
            generator = model_interface.ChatModelGenerator()
            with patch.object(
                generator, "_execute_image_generation_tool",
                new=AsyncMock(return_value=(fake_image, "done", {"prompt_token_count": 1, "candidates_token_count": 0, "total_token_count": 1}))
            ) as mock_exec:
                await generator._generate_text_response("turn it green", [input_image])

        mock_exec.assert_awaited_once_with("turn it green", "gemini", [input_image])

    async def test_image_model_used_recorded_in_usage(self):
        """When the image tool fires, usage metadata contains 'image_model_used'."""
        tool_call = self._make_tool_call("a fox", "gpt")
        chat_response = self._make_chat_response(tool_calls=[tool_call])

        mock_chat = Mock()
        mock_chat.completions.create.return_value = chat_response
        mock_client = SimpleNamespace(chat=mock_chat)

        fake_image = Image.new("RGB", (1, 1))
        image_usage = {"prompt_token_count": 2, "candidates_token_count": 0, "total_token_count": 2}

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=mock_client):
            generator = model_interface.ChatModelGenerator()
            with patch.object(
                generator, "_execute_image_generation_tool",
                new=AsyncMock(return_value=(fake_image, "fox", image_usage))
            ):
                _, _, usage = await generator._generate_text_response("draw a fox")

        self.assertEqual(usage.get("image_model_used"), "gpt")

    async def test_usage_is_combined_on_tool_call(self):
        """Usage metadata from both the chat call and the image generation are summed."""
        tool_call = self._make_tool_call("sunset", "gemini")
        chat_response = self._make_chat_response(tool_calls=[tool_call])
        # Patch usage: prompt=5, completion=2, total=7
        chat_response.usage = SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7)

        mock_chat = Mock()
        mock_chat.completions.create.return_value = chat_response
        mock_client = SimpleNamespace(chat=mock_chat)

        image_usage = {"prompt_token_count": 10, "candidates_token_count": 0, "total_token_count": 10}
        fake_image = Image.new("RGB", (1, 1))

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), \
             patch.object(model_interface, "OpenAI", return_value=mock_client):
            generator = model_interface.ChatModelGenerator()
            with patch.object(
                generator, "_execute_image_generation_tool",
                new=AsyncMock(return_value=(fake_image, "sunset", image_usage))
            ):
                _, _, usage = await generator._generate_text_response("paint a sunset")

        self.assertEqual(usage["prompt_token_count"], 5 + 10)
        self.assertEqual(usage["total_token_count"], 7 + 10)


if __name__ == "__main__":
    unittest.main()
