"""
Unit tests for wordplay game module.
"""

import unittest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta
from wordplay_game import (
    WordplaySession,
    WordplaySessionManager,
    validate_word_pair,
)


class TestWordplaySession(unittest.TestCase):
    """Test WordplaySession class."""
    
    def test_session_creation(self):
        """Test creating a wordplay session."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        
        self.assertEqual(session.message_id, 999888)
        self.assertEqual(session.creator_user_id, 12345)
        self.assertEqual(session.shorter_word, "PLANT")
        self.assertEqual(session.longer_word, "PLANET")
        self.assertEqual(session.extra_letter, "E")
        self.assertEqual(session.puzzle_id, "test_puzzle_1")
        self.assertEqual(len(session.user_attempts), 0)  # No attempts yet
        self.assertEqual(len(session.solved_by_users), 0)  # No solvers yet
        self.assertEqual(len(session.point_awarded_users), 0)  # No points awarded yet
    
    def test_check_answer_correct(self):
        """Test checking a correct answer."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user_id = 111
        
        result = session.check_answer(user_id, "e")
        
        self.assertTrue(result)
        self.assertIn(user_id, session.solved_by_users)
        self.assertEqual(session.get_attempts_remaining(user_id), 3)  # Attempts not decremented on success
    
    def test_check_answer_incorrect(self):
        """Test checking an incorrect answer."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user_id = 111
        
        result = session.check_answer(user_id, "a")
        
        self.assertFalse(result)
        self.assertNotIn(user_id, session.solved_by_users)
        self.assertEqual(session.get_attempts_remaining(user_id), 2)
    
    def test_check_answer_case_insensitive(self):
        """Test that answer checking is case insensitive."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user_id = 111
        
        result = session.check_answer(user_id, "E")
        
        self.assertTrue(result)
        self.assertIn(user_id, session.solved_by_users)
    
    def test_check_answer_invalid_length(self):
        """Test checking an answer with invalid length."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user_id = 111
        
        result = session.check_answer(user_id, "ea")
        
        self.assertFalse(result)
        self.assertNotIn(user_id, session.solved_by_users)
        # Invalid answers (wrong format) don't decrement attempts
        self.assertEqual(session.get_attempts_remaining(user_id), 3)
    
    def test_check_answer_non_alphabetic(self):
        """Test checking an answer with non-alphabetic characters."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user_id = 111
        
        result = session.check_answer(user_id, "1")
        
        self.assertFalse(result)
        self.assertNotIn(user_id, session.solved_by_users)
        # Invalid answers (wrong format) don't decrement attempts
        self.assertEqual(session.get_attempts_remaining(user_id), 3)
    
    def test_has_attempts_remaining(self):
        """Test checking if attempts remain."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user_id = 111
        
        self.assertTrue(session.has_attempts_remaining(user_id))
        
        session.check_answer(user_id, "a")
        session.check_answer(user_id, "b")
        session.check_answer(user_id, "c")
        
        self.assertFalse(session.has_attempts_remaining(user_id))
    
    def test_point_awarded_tracking(self):
        """Test that point_awarded flag is tracked correctly per user."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user_id = 111
        
        # Initially no point awarded
        self.assertNotIn(user_id, session.point_awarded_users)
        
        # After solving, point should be manually awarded in application logic
        session.check_answer(user_id, "e")
        self.assertIn(user_id, session.solved_by_users)
        
        # The application sets point_awarded flag
        session.point_awarded_users.add(user_id)
        self.assertIn(user_id, session.point_awarded_users)
    
    def test_multiple_users_can_solve(self):
        """Test that multiple users can solve the same puzzle."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user1 = 111
        user2 = 222
        user3 = 333
        
        # User 1 solves correctly
        result1 = session.check_answer(user1, "e")
        self.assertTrue(result1)
        self.assertIn(user1, session.solved_by_users)
        
        # User 2 can still solve
        result2 = session.check_answer(user2, "e")
        self.assertTrue(result2)
        self.assertIn(user2, session.solved_by_users)
        
        # User 3 gets it wrong but has attempts
        result3 = session.check_answer(user3, "a")
        self.assertFalse(result3)
        self.assertTrue(session.has_attempts_remaining(user3))
        self.assertEqual(session.get_attempts_remaining(user3), 2)
    
    def test_per_user_attempts_are_independent(self):
        """Test that each user has independent attempts."""
        session = WordplaySession(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        user1 = 111
        user2 = 222
        
        # User 1 uses all attempts
        session.check_answer(user1, "a")
        session.check_answer(user1, "b")
        session.check_answer(user1, "c")
        self.assertFalse(session.has_attempts_remaining(user1))
        
        # User 2 still has all attempts
        self.assertTrue(session.has_attempts_remaining(user2))
        self.assertEqual(session.get_attempts_remaining(user2), 3)


class TestWordplaySessionManager(unittest.TestCase):
    """Test WordplaySessionManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.manager = WordplaySessionManager()
    
    def tearDown(self):
        """Clean up after tests."""
        self.manager.sessions.clear()
    
    def test_create_session(self):
        """Test creating a session."""
        session = self.manager.create_session(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        
        self.assertIsNotNone(session)
        self.assertEqual(session.message_id, 999888)
        self.assertEqual(session.creator_user_id, 12345)
        self.assertEqual(session.puzzle_id, "test_puzzle_1")
        self.assertEqual(len(self.manager.sessions), 1)
    
    def test_create_session_replaces_existing(self):
        """Test that creating a new session replaces an existing one for the same message."""
        session1 = self.manager.create_session(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        session2 = self.manager.create_session(999888, 12345, "star", "stair", "i", "test_puzzle_2")
        
        self.assertEqual(len(self.manager.sessions), 1)
        self.assertEqual(session2.shorter_word, "STAR")
        self.assertEqual(session2.puzzle_id, "test_puzzle_2")
    
    def test_get_session(self):
        """Test getting a session."""
        created_session = self.manager.create_session(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        retrieved_session = self.manager.get_session(999888)
        
        self.assertEqual(created_session, retrieved_session)
    
    def test_get_nonexistent_session(self):
        """Test getting a session that doesn't exist."""
        session = self.manager.get_session(99999)
        
        self.assertIsNone(session)
    
    def test_remove_session(self):
        """Test removing a session."""
        self.manager.create_session(999888, 12345, "plant", "planet", "e", "test_puzzle_1")
        self.manager.remove_session(999888)
        
        self.assertEqual(len(self.manager.sessions), 0)
    
    def test_remove_nonexistent_session(self):
        """Test removing a session that doesn't exist (should not raise error)."""
        # This should not raise an exception
        self.manager.remove_session(99999)


class TestValidateWordPair(unittest.TestCase):
    """Test word pair validation."""
    
    def test_valid_pairs(self):
        """Test valid word pairs."""
        valid_pairs = [
            ("PLANT", "PLANET", "E"),
            ("STAR", "STAIR", "I"),
            ("PLAN", "PLAIN", "I"),
            ("MATE", "MATTE", "T"),
            ("SCAR", "SCARE", "E"),
        ]
        
        for shorter, longer, extra in valid_pairs:
            with self.subTest(pair=(shorter, longer, extra)):
                self.assertTrue(validate_word_pair(shorter, longer, extra))
    
    def test_invalid_length_difference(self):
        """Test that pairs with wrong length difference are invalid."""
        # Note: Simple pluralization like CAT -> CATS is technically valid by the rule,
        # though the AI should avoid generating such pairs
        self.assertFalse(validate_word_pair("CAT", "CATCH", "C"))  # Length diff is 2
    
    def test_invalid_extra_letter_not_in_word(self):
        """Test that pairs where the extra letter isn't used correctly are invalid."""
        self.assertFalse(validate_word_pair("PLANT", "PLANET", "X"))
    
    def test_empty_inputs(self):
        """Test that empty inputs are invalid."""
        self.assertFalse(validate_word_pair("", "PLANET", "E"))
        self.assertFalse(validate_word_pair("PLANT", "", "E"))
        self.assertFalse(validate_word_pair("PLANT", "PLANET", ""))
    
    def test_extra_letter_wrong_length(self):
        """Test that extra letter must be exactly one character."""
        self.assertFalse(validate_word_pair("PLANT", "PLANET", "EA"))
    
    def test_none_inputs(self):
        """Test that None inputs are invalid."""
        self.assertFalse(validate_word_pair(None, "PLANET", "E"))
        self.assertFalse(validate_word_pair("PLANT", None, "E"))
        self.assertFalse(validate_word_pair("PLANT", "PLANET", None))


if __name__ == '__main__':
    unittest.main()
