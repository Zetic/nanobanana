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


if __name__ == "__main__":
    unittest.main()
