import base64
import io
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
        self.assertNotIn("stream", kwargs)
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("partial_images", kwargs)

    async def test_edit_stream_call_omits_unsupported_params(self):
        mock_images = Mock()
        mock_images.edit.return_value = SimpleNamespace(
            data=[SimpleNamespace(b64_json=_png_b64())]
        )
        mock_client = SimpleNamespace(images=mock_images)
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

        kwargs = mock_images.edit.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-image-2")
        self.assertEqual(kwargs["prompt"], "edit banana")
        self.assertNotIn("quality", kwargs)
        self.assertNotIn("stream", kwargs)
        self.assertIsInstance(kwargs["image"], bytes)
        self.assertGreater(len(kwargs["image"]), 0)
        self.assertTrue(kwargs["image"].startswith(b"\x89PNG"))
        sent_image = Image.open(io.BytesIO(kwargs["image"]))
        self.assertEqual(sent_image.size, (2, 2))
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("partial_images", kwargs)

    async def test_edit_failure_returns_prompt_and_reason(self):
        mock_images = Mock()
        mock_images.edit.side_effect = RuntimeError("Rate limit exceeded")
        mock_client = SimpleNamespace(images=mock_images)
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


if __name__ == "__main__":
    unittest.main()
