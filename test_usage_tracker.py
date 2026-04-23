import tempfile
import unittest
from unittest.mock import patch

from usage_tracker import UsageTracker


class TestUsageReservations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_patcher = patch.multiple(
            "config",
            GENERATED_IMAGES_DIR=self.temp_dir.name,
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


if __name__ == "__main__":
    unittest.main()
