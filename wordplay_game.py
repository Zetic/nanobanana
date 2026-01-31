"""
Wordplay puzzle game module for Discord bot.
Generates word pairs following the Extra-Letter rule and manages game sessions.
"""

import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, Any
from PIL import Image

logger = logging.getLogger(__name__)


class WordplaySession:
    """Represents a single wordplay game session for a user."""
    
    def __init__(self, user_id: int, shorter_word: str, longer_word: str, extra_letter: str):
        self.user_id = user_id
        self.shorter_word = shorter_word.upper()
        self.longer_word = longer_word.upper()
        self.extra_letter = extra_letter.upper()
        self.created_at = datetime.now()
        self.attempts_remaining = 3
        self.solved = False
    
    def is_expired(self) -> bool:
        """Check if the session has expired (10 minutes)."""
        return datetime.now() - self.created_at > timedelta(minutes=10)
    
    def check_answer(self, answer: str) -> bool:
        """Check if the provided answer is correct."""
        if not answer or len(answer) != 1:
            return False
        
        is_correct = answer.upper() == self.extra_letter
        if is_correct:
            self.solved = True
        else:
            self.attempts_remaining -= 1
        
        return is_correct
    
    def has_attempts_remaining(self) -> bool:
        """Check if the user has attempts remaining."""
        return self.attempts_remaining > 0


class WordplaySessionManager:
    """Manages active wordplay sessions for users."""
    
    def __init__(self):
        self.sessions: Dict[int, WordplaySession] = {}
        self._cleanup_task = None
    
    def create_session(self, user_id: int, shorter_word: str, longer_word: str, extra_letter: str) -> WordplaySession:
        """Create a new session for a user."""
        # Clean up any existing session for this user
        if user_id in self.sessions:
            del self.sessions[user_id]
        
        session = WordplaySession(user_id, shorter_word, longer_word, extra_letter)
        self.sessions[user_id] = session
        logger.info(f"Created wordplay session for user {user_id}: {shorter_word} -> {longer_word}")
        return session
    
    def get_session(self, user_id: int) -> Optional[WordplaySession]:
        """Get the active session for a user."""
        session = self.sessions.get(user_id)
        
        # Clean up expired sessions
        if session and session.is_expired():
            logger.info(f"Session for user {user_id} has expired")
            del self.sessions[user_id]
            return None
        
        return session
    
    def remove_session(self, user_id: int):
        """Remove a session for a user."""
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"Removed wordplay session for user {user_id}")
    
    async def cleanup_expired_sessions(self):
        """Periodically clean up expired sessions."""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                expired_users = [
                    user_id for user_id, session in self.sessions.items()
                    if session.is_expired()
                ]
                
                for user_id in expired_users:
                    del self.sessions[user_id]
                
                if expired_users:
                    logger.info(f"Cleaned up {len(expired_users)} expired wordplay sessions")
            except Exception as e:
                logger.error(f"Error cleaning up wordplay sessions: {e}")


# Global session manager
session_manager = WordplaySessionManager()


async def generate_word_pair_with_gemini(generator) -> Optional[Tuple[str, str, str]]:
    """
    Generate a valid word pair using Gemini AI.
    
    Returns:
        Tuple of (shorter_word, longer_word, extra_letter) or None if generation fails
    """
    prompt = """Generate a word pair that follows these EXACT rules:

RULES (ALL MUST BE SATISFIED):
1. Two English words only
2. Both words must be common nouns and/or verbs (no proper nouns, slang, or abbreviations)
3. One word is formed by inserting ONE additional letter into the other word
4. The letter order must stay the same (the shorter word is a subsequence of the longer word)
5. NOT simple pluralization (no adding just 's' or 'es')
6. The extra letter can be inserted anywhere in the word
7. Both words must be visually representable in an image

EXAMPLES OF VALID PAIRS:
- PLANT → PLANET (extra letter: E)
- STAR → STAIR (extra letter: I)
- PLAN → PLAIN (extra letter: I)
- MATE → MATTE (extra letter: T)
- SCAR → SCARE (extra letter: E)

RESPOND WITH ONLY THREE LINES IN THIS EXACT FORMAT:
SHORTER: [word]
LONGER: [word]
EXTRA: [letter]

Do not include any other text, explanations, or formatting."""

    try:
        # Use text-only response to get the word pair
        _, text_response, _ = await generator.generate_text_only_response(prompt)
        
        if not text_response:
            logger.error("No response from Gemini for word pair generation")
            return None
        
        # Parse the response
        lines = [line.strip() for line in text_response.strip().split('\n') if line.strip()]
        
        shorter_word = None
        longer_word = None
        extra_letter = None
        
        for line in lines:
            if line.startswith('SHORTER:'):
                shorter_word = line.split(':', 1)[1].strip().upper()
            elif line.startswith('LONGER:'):
                longer_word = line.split(':', 1)[1].strip().upper()
            elif line.startswith('EXTRA:'):
                extra_letter = line.split(':', 1)[1].strip().upper()
        
        if not all([shorter_word, longer_word, extra_letter]):
            logger.error(f"Failed to parse word pair from response: {text_response}")
            return None
        
        # Validate the word pair
        if not validate_word_pair(shorter_word, longer_word, extra_letter):
            logger.error(f"Invalid word pair generated: {shorter_word} -> {longer_word} (extra: {extra_letter})")
            return None
        
        logger.info(f"Generated valid word pair: {shorter_word} -> {longer_word} (extra: {extra_letter})")
        return shorter_word, longer_word, extra_letter
        
    except Exception as e:
        logger.error(f"Error generating word pair: {e}")
        return None


def validate_word_pair(shorter_word: str, longer_word: str, extra_letter: str) -> bool:
    """
    Validate that a word pair follows the Extra-Letter rule.
    
    Args:
        shorter_word: The shorter word
        longer_word: The longer word
        extra_letter: The extra letter
    
    Returns:
        True if valid, False otherwise
    """
    # Basic validation
    if not all([shorter_word, longer_word, extra_letter]):
        return False
    
    if len(extra_letter) != 1:
        return False
    
    # Longer word should be exactly 1 character longer
    if len(longer_word) != len(shorter_word) + 1:
        return False
    
    # Check if removing one occurrence of the extra letter from longer_word gives shorter_word
    # Try removing the extra letter at each position
    for i in range(len(longer_word)):
        if longer_word[i] == extra_letter:
            # Create a word with this letter removed
            test_word = longer_word[:i] + longer_word[i+1:]
            if test_word == shorter_word:
                return True
    
    return False


async def generate_word_image(generator, word: str) -> Optional[Image.Image]:
    """
    Generate an image representing a word using Gemini.
    
    Args:
        generator: The model generator to use
        word: The word to visualize
    
    Returns:
        PIL Image or None if generation fails
    """
    prompt = f"""Create a clear, simple image that represents the word "{word}".

The image should:
- Be a straightforward visual representation of the word
- Be easily recognizable
- Have good contrast and clear details
- Be suitable for a word guessing puzzle
- Not include any text or letters

Create the image in a simple, clean style."""

    try:
        image, _, _ = await generator.generate_image_from_text(prompt, aspect_ratio="1:1")
        
        if image:
            logger.info(f"Successfully generated image for word: {word}")
            return image
        else:
            logger.error(f"Failed to generate image for word: {word}")
            return None
            
    except Exception as e:
        logger.error(f"Error generating image for word {word}: {e}")
        return None
