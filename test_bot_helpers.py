import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import bot


class TestBotHelpers(unittest.IsolatedAsyncioTestCase):
    async def test_generate_image_for_model_text_only(self):
        mock_generator = SimpleNamespace(
            generate_image_from_text=AsyncMock(return_value=("img", "text", {"total_token_count": 1})),
            generate_image_from_text_and_image=AsyncMock(),
            generate_image_from_image_only=AsyncMock(),
        )

        with patch("bot.get_model_generator", return_value=mock_generator):
            image, text, usage = await bot.generate_image_for_model("nanobanana", "prompt", [], None)

        self.assertEqual(image, "img")
        self.assertEqual(text, "text")
        self.assertEqual(usage, {"total_token_count": 1})
        mock_generator.generate_image_from_text.assert_awaited_once_with("prompt", None, None)

    async def test_generate_image_for_model_without_prompt_or_images(self):
        mock_generator = SimpleNamespace(
            generate_image_from_text=AsyncMock(),
            generate_image_from_text_and_image=AsyncMock(),
            generate_image_from_image_only=AsyncMock(),
        )

        with patch("bot.get_model_generator", return_value=mock_generator):
            image, text, usage = await bot.generate_image_for_model("nanobanana", "   ", [], None)

        self.assertIsNone(image)
        self.assertIsNone(text)
        self.assertIsNone(usage)


def _make_attachment(filename="img.png", content_type="image/png", url="http://example.com/img.png"):
    """Create a minimal mock Discord attachment."""
    a = MagicMock()
    a.filename = filename
    a.content_type = content_type
    a.url = url
    return a


def _make_message(content="hello", attachments=None, reference=None):
    """Create a minimal mock Discord message."""
    msg = MagicMock()
    msg.content = content
    msg.attachments = attachments or []
    msg.reference = reference
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.channel.fetch_message = AsyncMock(return_value=None)
    return msg


class TestCollectMessageImages(unittest.IsolatedAsyncioTestCase):
    async def test_no_attachments(self):
        msg = _make_message(attachments=[])
        images = await bot.collect_message_images(msg)
        self.assertEqual(images, [])

    async def test_image_attachment_downloaded(self):
        attachment = _make_attachment()
        msg = _make_message(attachments=[attachment])

        fake_img = object()
        with patch("bot.download_image", AsyncMock(return_value=fake_img)):
            images = await bot.collect_message_images(msg)

        self.assertEqual(images, [fake_img])

    async def test_non_image_attachment_skipped(self):
        attachment = _make_attachment(filename="doc.pdf", content_type="application/pdf")
        msg = _make_message(attachments=[attachment])

        with patch("bot.download_image", AsyncMock()) as mock_dl:
            images = await bot.collect_message_images(msg)

        self.assertEqual(images, [])
        mock_dl.assert_not_called()

    async def test_failed_download_skipped(self):
        attachment = _make_attachment()
        msg = _make_message(attachments=[attachment])

        with patch("bot.download_image", AsyncMock(return_value=None)):
            images = await bot.collect_message_images(msg)

        self.assertEqual(images, [])


class TestHandleConversationRequest(unittest.IsolatedAsyncioTestCase):
    async def test_includes_replied_message_text(self):
        """Context from the replied-to message is prepended to the user's message."""
        ref_author = MagicMock()
        ref_author.display_name = "Alice"
        ref_msg = _make_message(content="The paragraph of text", attachments=[])
        ref_msg.author = ref_author

        reference = MagicMock()
        reference.message_id = 99
        reference.cached_message = ref_msg

        user_msg = _make_message(content="summarise this", reference=reference)

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(None, "Summary here", {}))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="summarise this")), \
             patch("bot.download_image", AsyncMock(return_value=None)):
            await bot.handle_conversation_request(user_msg)

        call_args = mock_generator.generate_text_only_response.call_args
        prompt_sent = call_args[0][0]
        self.assertIn("Alice", prompt_sent)
        self.assertIn("The paragraph of text", prompt_sent)
        self.assertIn("summarise this", prompt_sent)

    async def test_images_from_current_message_passed(self):
        """Image attachments on the user's own message are forwarded to the model."""
        attachment = _make_attachment()
        user_msg = _make_message(content="describe this", attachments=[attachment])
        user_msg.reference = None

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        fake_img = object()
        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(None, "Description", {}))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="describe this")), \
             patch("bot.download_image", AsyncMock(return_value=fake_img)):
            await bot.handle_conversation_request(user_msg)

        call_args = mock_generator.generate_text_only_response.call_args
        images_sent = call_args[0][1]
        self.assertIsNotNone(images_sent)
        self.assertIn(fake_img, images_sent)

    async def test_images_from_replied_message_passed(self):
        """Image attachments on the replied-to message are forwarded to the model."""
        ref_attachment = _make_attachment(url="http://example.com/ref.png")
        ref_author = MagicMock()
        ref_author.display_name = "Bob"
        ref_msg = _make_message(content="look at this", attachments=[ref_attachment])
        ref_msg.author = ref_author

        reference = MagicMock()
        reference.message_id = 42
        reference.cached_message = ref_msg

        user_msg = _make_message(content="what is this image?", attachments=[], reference=reference)

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        fake_img = object()
        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(None, "It is a cat", {}))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="what is this image?")), \
             patch("bot.download_image", AsyncMock(return_value=fake_img)):
            await bot.handle_conversation_request(user_msg)

        call_args = mock_generator.generate_text_only_response.call_args
        images_sent = call_args[0][1]
        self.assertIsNotNone(images_sent)
        self.assertIn(fake_img, images_sent)

    async def test_no_text_and_no_images_sends_error(self):
        """If the message has no text and no images, an error is returned."""
        user_msg = _make_message(content="", attachments=[])
        user_msg.reference = None

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock()

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="")):
            await bot.handle_conversation_request(user_msg)

        response_msg.edit.assert_awaited_once()
        edit_kwargs = response_msg.edit.call_args
        self.assertIn("image", edit_kwargs[1]["content"].lower())
        mock_generator.generate_text_only_response.assert_not_called()


if __name__ == "__main__":
    unittest.main()
