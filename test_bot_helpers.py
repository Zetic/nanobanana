import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import bot


class TestGetGitCommitHash(unittest.TestCase):
    def test_returns_7_char_hash_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234\n"
        with patch("bot.subprocess.run", return_value=mock_result) as mock_run:
            result = bot.get_git_commit_hash()
        self.assertEqual(result, "abc1234")
        mock_run.assert_called_once_with(
            ['git', 'rev-parse', '--short=7', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_returns_none_on_nonzero_returncode(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch("bot.subprocess.run", return_value=mock_result):
            result = bot.get_git_commit_hash()
        self.assertIsNone(result)

    def test_returns_none_on_exception(self):
        with patch("bot.subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = bot.get_git_commit_hash()
        self.assertIsNone(result)


class TestFormatElapsedTime(unittest.TestCase):
    def test_sub_second_returns_milliseconds(self):
        self.assertEqual(bot.format_elapsed_time(0.25), "250ms")

    def test_zero_returns_zero_milliseconds(self):
        self.assertEqual(bot.format_elapsed_time(0.0), "0ms")

    def test_just_under_one_second_returns_milliseconds(self):
        self.assertEqual(bot.format_elapsed_time(0.999), "999ms")

    def test_exactly_one_second_returns_seconds(self):
        self.assertEqual(bot.format_elapsed_time(1.0), "1s")

    def test_whole_seconds_returned(self):
        self.assertEqual(bot.format_elapsed_time(97.0), "97s")

    def test_fractional_seconds_rounded(self):
        self.assertEqual(bot.format_elapsed_time(97.6), "98s")


class TestBuildEmbedFooter(unittest.TestCase):
    def test_with_commit_hash(self):
        with patch.object(bot, "_git_commit_hash", "b97f08e"):
            result = bot.build_embed_footer(97.0)
        self.assertEqual(result, "ZPT b97f08e | Thought for 97s")

    def test_with_commit_hash_milliseconds(self):
        with patch.object(bot, "_git_commit_hash", "b97f08e"):
            result = bot.build_embed_footer(0.5)
        self.assertEqual(result, "ZPT b97f08e | Thought for 500ms")

    def test_without_commit_hash(self):
        with patch.object(bot, "_git_commit_hash", None):
            result = bot.build_embed_footer(5.0)
        self.assertEqual(result, "ZPT | Thought for 5s")


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


def _make_message(content="hello", attachments=None, reference=None, embeds=None):
    """Create a minimal mock Discord message."""
    msg = MagicMock()
    msg.content = content
    msg.attachments = attachments or []
    msg.embeds = embeds or []
    msg.reference = reference
    msg.reply = AsyncMock()
    msg.channel.send = AsyncMock()
    msg.channel.fetch_message = AsyncMock(return_value=None)
    return msg


def _make_embed(description=None, fields=None, image_url=None, thumbnail_url=None):
    """Create a minimal mock Discord embed."""
    embed = MagicMock()
    embed.description = description
    embed.fields = []
    for name, value in (fields or []):
        field = MagicMock()
        field.name = name
        field.value = value
        embed.fields.append(field)
    embed.image = MagicMock(url=image_url) if image_url else None
    embed.thumbnail = MagicMock(url=thumbnail_url) if thumbnail_url else None
    return embed


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

    async def test_embed_image_downloaded(self):
        """Images inside an embed's image field are downloaded."""
        embed = _make_embed(image_url="http://example.com/embed.png")
        msg = _make_message(attachments=[], embeds=[embed])

        fake_img = object()
        with patch("bot.download_image", AsyncMock(return_value=fake_img)):
            images = await bot.collect_message_images(msg)

        self.assertEqual(images, [fake_img])

    async def test_embed_thumbnail_downloaded(self):
        """Images inside an embed's thumbnail field are downloaded."""
        embed = _make_embed(thumbnail_url="http://example.com/thumb.png")
        msg = _make_message(attachments=[], embeds=[embed])

        fake_img = object()
        with patch("bot.download_image", AsyncMock(return_value=fake_img)):
            images = await bot.collect_message_images(msg)

        self.assertEqual(images, [fake_img])

    async def test_embed_image_not_duplicated_when_also_attachment(self):
        """If the same URL appears as both an attachment and an embed image, it is only downloaded once."""
        shared_url = "http://example.com/shared.png"
        attachment = _make_attachment(url=shared_url)
        embed = _make_embed(image_url=shared_url)
        msg = _make_message(attachments=[attachment], embeds=[embed])

        fake_img = object()
        mock_dl = AsyncMock(return_value=fake_img)
        with patch("bot.download_image", mock_dl):
            images = await bot.collect_message_images(msg)

        mock_dl.assert_called_once_with(shared_url)
        self.assertEqual(images, [fake_img])


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

    async def test_embed_text_from_replied_message_included(self):
        """Embed description and fields from the replied-to message are included in context."""
        embed = _make_embed(
            description="A generated story",
            fields=[("Prompt", "write a story"), ("Model", "Gemini")],
        )
        ref_author = MagicMock()
        ref_author.display_name = "BotUser"
        ref_msg = _make_message(content="", attachments=[], embeds=[embed])
        ref_msg.author = ref_author

        reference = MagicMock()
        reference.message_id = 7
        reference.cached_message = ref_msg

        user_msg = _make_message(content="continue this", attachments=[], reference=reference)

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(None, "Continuation...", {}))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="continue this")), \
             patch("bot.download_image", AsyncMock(return_value=None)):
            await bot.handle_conversation_request(user_msg)

        call_args = mock_generator.generate_text_only_response.call_args
        prompt_sent = call_args[0][0]
        self.assertIn("A generated story", prompt_sent)
        self.assertIn("Prompt", prompt_sent)
        self.assertIn("write a story", prompt_sent)
        self.assertIn("continue this", prompt_sent)

    async def test_embed_image_from_replied_message_passed(self):
        """Images inside an embed of the replied-to message are forwarded to the model."""
        embed = _make_embed(image_url="http://cdn.example.com/generated.png")
        ref_author = MagicMock()
        ref_author.display_name = "BotUser"
        ref_msg = _make_message(content="", attachments=[], embeds=[embed])
        ref_msg.author = ref_author

        reference = MagicMock()
        reference.message_id = 8
        reference.cached_message = ref_msg

        user_msg = _make_message(content="write a story for this image", attachments=[], reference=reference)

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        fake_img = object()
        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(None, "Once upon a time...", {}))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="write a story for this image")), \
             patch("bot.download_image", AsyncMock(return_value=fake_img)):
            await bot.handle_conversation_request(user_msg)

        call_args = mock_generator.generate_text_only_response.call_args
        images_sent = call_args[0][1]
        self.assertIsNotNone(images_sent)
        self.assertIn(fake_img, images_sent)

    async def test_usage_tracked_when_image_generated(self):
        """record_usage is called with images_generated=1 when the tool returns an image."""
        from PIL import Image as PILImage
        import io

        fake_img = PILImage.new("RGB", (1, 1))
        usage_meta = {
            "prompt_token_count": 5,
            "candidates_token_count": 2,
            "total_token_count": 7,
            "image_model_used": "gpt",
        }

        author = MagicMock()
        author.id = 123
        author.bot = False
        author.display_name = "TestUser"
        author.name = "testuser"
        user_msg = _make_message(content="draw a cat", attachments=[])
        user_msg.reference = None
        user_msg.author = author

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(fake_img, "Here you go!", usage_meta))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="draw a cat")), \
             patch("bot.download_image", AsyncMock(return_value=None)), \
             patch("bot.usage_tracker") as mock_tracker:
            await bot.handle_conversation_request(user_msg)

        mock_tracker.record_usage.assert_called_once()
        call_kwargs = mock_tracker.record_usage.call_args.kwargs
        self.assertEqual(call_kwargs["user_id"], 123)
        self.assertEqual(call_kwargs["images_generated"], 1)
        self.assertEqual(call_kwargs["prompt_tokens"], 5)
        self.assertEqual(call_kwargs["total_tokens"], 7)

    async def test_usage_tracked_for_text_only_response(self):
        """record_usage is called with images_generated=0 for a plain text response."""
        usage_meta = {
            "prompt_token_count": 3,
            "candidates_token_count": 1,
            "total_token_count": 4,
        }

        author = MagicMock()
        author.id = 456
        author.bot = False
        author.display_name = "AnotherUser"
        author.name = "anotheruser"
        user_msg = _make_message(content="hello", attachments=[])
        user_msg.reference = None
        user_msg.author = author

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(None, "Hello there!", usage_meta))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="hello")), \
             patch("bot.download_image", AsyncMock(return_value=None)), \
             patch("bot.usage_tracker") as mock_tracker:
            await bot.handle_conversation_request(user_msg)

        mock_tracker.record_usage.assert_called_once()
        call_kwargs = mock_tracker.record_usage.call_args.kwargs
        self.assertEqual(call_kwargs["images_generated"], 0)

    async def test_model_footer_appended_for_gpt_image(self):
        """When gpt image tool fires, response includes '-# *Used GPT Image 2 in Xs*'."""
        from PIL import Image as PILImage

        fake_img = PILImage.new("RGB", (1, 1))
        usage_meta = {
            "prompt_token_count": 1,
            "candidates_token_count": 0,
            "total_token_count": 1,
            "image_model_used": "gpt",
        }

        author = MagicMock()
        author.id = 789
        author.bot = False
        author.display_name = "User"
        author.name = "user"
        user_msg = _make_message(content="make a dog", attachments=[])
        user_msg.reference = None
        user_msg.author = author

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(fake_img, "Here is your dog!", usage_meta))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="make a dog")), \
             patch("bot.download_image", AsyncMock(return_value=None)), \
             patch("bot.usage_tracker"):
            await bot.handle_conversation_request(user_msg)

        response_msg.edit.assert_awaited_once()
        content_sent = response_msg.edit.call_args.kwargs.get("content", "")
        self.assertIn("Here is your dog!", content_sent)
        self.assertIn("GPT Image 2", content_sent)
        self.assertIn("-# *Used GPT Image 2 in", content_sent)

    async def test_model_footer_appended_for_gemini_image(self):
        """When gemini image tool fires, response includes '-# *Used Gemini in Xs*'."""
        from PIL import Image as PILImage

        fake_img = PILImage.new("RGB", (1, 1))
        usage_meta = {
            "prompt_token_count": 1,
            "candidates_token_count": 0,
            "total_token_count": 1,
            "image_model_used": "gemini",
        }

        author = MagicMock()
        author.id = 111
        author.bot = False
        author.display_name = "User2"
        author.name = "user2"
        user_msg = _make_message(content="paint a sky", attachments=[])
        user_msg.reference = None
        user_msg.author = author

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(fake_img, "Sky painted!", usage_meta))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="paint a sky")), \
             patch("bot.download_image", AsyncMock(return_value=None)), \
             patch("bot.usage_tracker"):
            await bot.handle_conversation_request(user_msg)

        content_sent = response_msg.edit.call_args.kwargs.get("content", "")
        self.assertIn("Gemini", content_sent)
        self.assertIn("-# *Used Gemini in", content_sent)

    async def test_no_footer_when_no_model_recorded(self):
        """When image_model_used is absent from usage, no footer is appended."""
        from PIL import Image as PILImage

        fake_img = PILImage.new("RGB", (1, 1))
        usage_meta = {
            "prompt_token_count": 1,
            "candidates_token_count": 0,
            "total_token_count": 1,
        }

        author = MagicMock()
        author.id = 222
        author.bot = False
        author.display_name = "User3"
        author.name = "user3"
        user_msg = _make_message(content="show me something", attachments=[])
        user_msg.reference = None
        user_msg.author = author

        response_msg = AsyncMock()
        user_msg.reply = AsyncMock(return_value=response_msg)

        mock_generator = MagicMock()
        mock_generator.generate_text_only_response = AsyncMock(return_value=(fake_img, "Here!", usage_meta))

        with patch("bot.get_model_generator", return_value=mock_generator), \
             patch("bot.extract_text_from_message", AsyncMock(return_value="show me something")), \
             patch("bot.download_image", AsyncMock(return_value=None)), \
             patch("bot.usage_tracker"):
            await bot.handle_conversation_request(user_msg)

        content_sent = response_msg.edit.call_args.kwargs.get("content", "")
        self.assertNotIn("-# *Used", content_sent)


if __name__ == "__main__":
    unittest.main()
