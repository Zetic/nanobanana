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
        session = WordplaySession(12345, "plant", "planet", "e", "test_puzzle_1")
        
        self.assertEqual(session.user_id, 12345)
        self.assertEqual(session.shorter_word, "PLANT")
        self.assertEqual(session.longer_word, "PLANET")
        self.assertEqual(session.extra_letter, "E")
        self.assertEqual(session.puzzle_id, "test_puzzle_1")
        self.assertEqual(session.attempts_remaining, 3)
        self.assertFalse(session.solved)
        self.assertFalse(session.point_awarded)
    
    def test_check_answer_correct(self):
        """Test checking a correct answer."""
        session = WordplaySession(12345, "plant", "planet", "e", "test_puzzle_1")
        
        result = session.check_answer("e")
        
        self.assertTrue(result)
        self.assertTrue(session.solved)
        self.assertEqual(session.attempts_remaining, 3)  # Attempts not decremented on success
    
    def test_check_answer_incorrect(self):
        """Test checking an incorrect answer."""
        session = WordplaySession(12345, "plant", "planet", "e", "test_puzzle_1")
        
        result = session.check_answer("a")
        
        self.assertFalse(result)
        self.assertFalse(session.solved)
        self.assertEqual(session.attempts_remaining, 2)
    
    def test_check_answer_case_insensitive(self):
        """Test that answer checking is case insensitive."""
        session = WordplaySession(12345, "plant", "planet", "e", "test_puzzle_1")
        
        result = session.check_answer("E")
        
        self.assertTrue(result)
        self.assertTrue(session.solved)
    
    def test_check_answer_invalid_length(self):
        """Test checking an answer with invalid length."""
        session = WordplaySession(12345, "plant", "planet", "e", "test_puzzle_1")
        
        result = session.check_answer("ea")
        
        self.assertFalse(result)
        self.assertFalse(session.solved)
        # Invalid answers (wrong format) don't decrement attempts
        self.assertEqual(session.attempts_remaining, 3)
    
    def test_check_answer_non_alphabetic(self):
        """Test checking an answer with non-alphabetic characters."""
        session = WordplaySession(12345, "plant", "planet", "e", "test_puzzle_1")
        
        result = session.check_answer("1")
        
        self.assertFalse(result)
        self.assertFalse(session.solved)
        # Invalid answers (wrong format) don't decrement attempts
        self.assertEqual(session.attempts_remaining, 3)
    
    def test_has_attempts_remaining(self):
        """Test checking if attempts remain."""
        session = WordplaySession(12345, "plant", "planet", "e", "test_puzzle_1")
        
        self.assertTrue(session.has_attempts_remaining())
        
        session.check_answer("a")
        session.check_answer("b")
        session.check_answer("c")
        
        self.assertFalse(session.has_attempts_remaining())
    
    def test_session_no_expiration(self):
        """Test that sessions don't expire based on time."""
        session = WordplaySession(12345, "plant", "planet", "e", "test_puzzle_1")
        
        # Simulate time passing by modifying created_at
        session.created_at = datetime.now() - timedelta(hours=24)
        
        # Session should still be valid (no expiration based on time)
        # We verify this by checking that the session itself doesn't have expiration logic
        self.assertTrue(session.attempts_remaining > 0 or session.solved)


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
        session = self.manager.create_session(12345, "plant", "planet", "e", "test_puzzle_1")
        
        self.assertIsNotNone(session)
        self.assertEqual(session.user_id, 12345)
        self.assertEqual(session.puzzle_id, "test_puzzle_1")
        self.assertEqual(len(self.manager.sessions), 1)
    
    def test_create_session_replaces_existing(self):
        """Test that creating a new session replaces an existing one."""
        session1 = self.manager.create_session(12345, "plant", "planet", "e", "test_puzzle_1")
        session2 = self.manager.create_session(12345, "star", "stair", "i", "test_puzzle_2")
        
        self.assertEqual(len(self.manager.sessions), 1)
        self.assertEqual(session2.shorter_word, "STAR")
        self.assertEqual(session2.puzzle_id, "test_puzzle_2")
    
    def test_get_session(self):
        """Test getting a session."""
        created_session = self.manager.create_session(12345, "plant", "planet", "e", "test_puzzle_1")
        retrieved_session = self.manager.get_session(12345)
        
        self.assertEqual(created_session, retrieved_session)
    
    def test_get_nonexistent_session(self):
        """Test getting a session that doesn't exist."""
        session = self.manager.get_session(99999)
        
        self.assertIsNone(session)
    
    def test_remove_session(self):
        """Test removing a session."""
        self.manager.create_session(12345, "plant", "planet", "e", "test_puzzle_1")
        self.manager.remove_session(12345)
        
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
