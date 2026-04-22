import base64
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

import model_interface


def _png_b64() -> str:
    image = Image.new("RGB", (1, 1), color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class TestGPTModelGenerator(unittest.IsolatedAsyncioTestCase):
    async def test_generate_stream_call_omits_unsupported_params(self):
        mock_images = Mock()
        mock_images.generate.return_value = [
            SimpleNamespace(type="image_generation.done", b64_json=_png_b64())
        ]
        mock_client = SimpleNamespace(images=mock_images)

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), patch.object(
            model_interface, "OpenAI", return_value=mock_client
        ):
            generator = model_interface.GPTModelGenerator()
            image, text, usage = await generator._generate_image_only("banana")

        self.assertIsNotNone(image)
        self.assertEqual(text, "banana")
        self.assertIsNotNone(usage)

        kwargs = mock_images.generate.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-image-2")
        self.assertEqual(kwargs["prompt"], "banana")
        self.assertEqual(kwargs["quality"], "medium")
        self.assertTrue(kwargs["stream"])
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("partial_images", kwargs)

    async def test_edit_stream_call_omits_unsupported_params(self):
        mock_images = Mock()
        mock_images.edit.return_value = [
            SimpleNamespace(type="image_generation.done", b64_json=_png_b64())
        ]
        mock_client = SimpleNamespace(images=mock_images)
        input_image = Image.new("RGB", (2, 2), color="blue")

        with patch.object(model_interface.config, "OPENAI_API_KEY", "test-key"), patch.object(
            model_interface, "OpenAI", return_value=mock_client
        ):
            generator = model_interface.GPTModelGenerator()
            image, text, usage = await generator._generate_image_with_input_images(
                "edit banana", [input_image]
            )

        self.assertIsNotNone(image)
        self.assertEqual(text, "edit banana")
        self.assertIsNotNone(usage)

        kwargs = mock_images.edit.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-image-2")
        self.assertEqual(kwargs["prompt"], "edit banana")
        self.assertEqual(kwargs["quality"], "medium")
        self.assertTrue(kwargs["stream"])
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("partial_images", kwargs)


if __name__ == "__main__":
    unittest.main()
