import tempfile
import os
import unittest
from unittest.mock import patch

from usage_tracker import UsageTracker


class TestUsageReservations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_patcher = patch.multiple(
            "config",
            GENERATED_IMAGES_DIR=self.temp_dir.name,
            LOGS_DIR=self.temp_dir.name,
            ELEVATED_USERS=[]
        )
        self.config_patcher.start()
        self.tracker = UsageTracker()
        self.user_id = 12345

    def tearDown(self):
        self.config_patcher.stop()
        self.temp_dir.cleanup()

    def test_reservation_blocks_over_queueing(self):
        self.assertEqual(self.tracker.get_remaining_images_today(self.user_id), 3)

        ok1, _ = self.tracker.reserve_usage_slots(self.user_id, slots=1)
        ok2, _ = self.tracker.reserve_usage_slots(self.user_id, slots=1)
        ok3, _ = self.tracker.reserve_usage_slots(self.user_id, slots=1)
        blocked, _ = self.tracker.reserve_usage_slots(self.user_id, slots=1)

        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertTrue(ok3)
        self.assertFalse(blocked)
        self.assertEqual(self.tracker.get_remaining_images_today(self.user_id), 0)

    def test_release_reserved_slot_restores_capacity(self):
        ok, _ = self.tracker.reserve_usage_slots(self.user_id, slots=1)
        self.assertTrue(ok)
        self.assertEqual(self.tracker.get_remaining_images_today(self.user_id), 2)

        self.tracker.release_reserved_usage_slots(self.user_id, slots=1)

        self.assertEqual(self.tracker.get_remaining_images_today(self.user_id), 3)

    def test_record_usage_consumes_reserved_slots(self):
        ok, _ = self.tracker.reserve_usage_slots(self.user_id, slots=1)
        self.assertTrue(ok)

        self.tracker.record_usage(
            user_id=self.user_id,
            username="test-user",
            prompt_tokens=0,
            output_tokens=0,
            total_tokens=0,
            images_generated=1,
            consume_reserved_slots=1,
        )

        self.assertEqual(self.tracker.get_daily_image_count(self.user_id), 1)
        self.assertEqual(self.tracker.get_remaining_images_today(self.user_id), 2)

    def test_wordplay_style_two_slot_reservation(self):
        ok, _ = self.tracker.reserve_usage_slots(self.user_id, slots=2)
        self.assertTrue(ok)

        blocked, _ = self.tracker.reserve_usage_slots(self.user_id, slots=2)
        self.assertFalse(blocked)

    def test_usage_log_written_when_image_generated(self):
        """record_usage writes a line to usage.log when images_generated > 0."""
        self.tracker.record_usage(
            user_id=self.user_id,
            username="test-user",
            prompt_tokens=0,
            output_tokens=0,
            total_tokens=0,
            images_generated=1,
            channel_id=999,
            channel_name="general",
        )

        log_path = self.tracker.usage_log_file
        self.assertTrue(os.path.exists(log_path), "usage.log should be created")
        with open(log_path, encoding='utf-8') as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        entry = lines[0]
        self.assertIn("test-user", entry)
        self.assertIn(str(self.user_id), entry)
        self.assertIn("#general", entry)
        self.assertIn("999", entry)
        # usage format: remaining/total  (e.g. "2/3")
        self.assertIn("/3", entry)

    def test_usage_log_not_written_for_text_only(self):
        """record_usage does NOT write to usage.log when images_generated == 0."""
        self.tracker.record_usage(
            user_id=self.user_id,
            username="test-user",
            prompt_tokens=10,
            output_tokens=5,
            total_tokens=15,
            images_generated=0,
            channel_id=999,
            channel_name="general",
        )

        log_path = self.tracker.usage_log_file
        self.assertFalse(os.path.exists(log_path), "usage.log should not be created for text-only calls")

    def test_usage_log_accumulates_across_calls(self):
        """Multiple image-generating calls each produce a separate log line."""
        for i in range(3):
            self.tracker.record_usage(
                user_id=self.user_id,
                username="test-user",
                prompt_tokens=0,
                output_tokens=0,
                total_tokens=0,
                images_generated=1,
                channel_id=111,
                channel_name="art",
            )

        with open(self.tracker.usage_log_file, encoding='utf-8') as f:
            lines = [l for l in f.readlines() if l.strip()]
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
