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

# Session configuration
# Sessions persist until solved or failed (no time-based expiration)
SESSION_CLEANUP_INTERVAL = 300  # Cleanup runs every 5 minutes (in seconds)


class WordplaySession:
    """Represents a single wordplay game session for a message."""
    
    def __init__(self, message_id: int, creator_user_id: int, shorter_word: str, longer_word: str, extra_letters: str, puzzle_id: str):
        self.message_id = message_id
        self.creator_user_id = creator_user_id  # User who created the puzzle
        self.shorter_word = shorter_word.upper()
        self.longer_word = longer_word.upper()
        self.extra_letters = extra_letters.upper()
        self.puzzle_id = puzzle_id  # Unique identifier for this puzzle
        self.created_at = datetime.now()
        self.user_attempts: Dict[int, int] = {}  # user_id -> attempts_remaining
        self.solved_by_users: set = set()  # Set of user_ids who solved it
        self.point_awarded_users: set = set()  # Set of user_ids who got points
    
    def check_answer(self, user_id: int, answer: str) -> bool:
        """Check if the provided answer is correct for a specific user."""
        if not answer:
            return False
        
        # Clean the answer - remove spaces, commas, and convert to uppercase
        cleaned_answer = ''.join(answer.upper().split()).replace(',', '')
        
        # Validate that all characters are alphabetic
        if not cleaned_answer.isalpha():
            return False
        
        # Check if the length matches expected extra_letters length
        if len(cleaned_answer) != len(self.extra_letters):
            return False
        
        # Initialize attempts for this user if they haven't tried yet
        if user_id not in self.user_attempts:
            self.user_attempts[user_id] = 3
        
        is_correct = cleaned_answer == self.extra_letters
        if is_correct:
            self.solved_by_users.add(user_id)
        else:
            self.user_attempts[user_id] -= 1
        
        return is_correct
    
    def has_attempts_remaining(self, user_id: int) -> bool:
        """Check if a specific user has attempts remaining."""
        if user_id not in self.user_attempts:
            return True  # User hasn't tried yet, so they have all attempts
        return self.user_attempts[user_id] > 0
    
    def get_attempts_remaining(self, user_id: int) -> int:
        """Get the number of attempts remaining for a specific user."""
        return self.user_attempts.get(user_id, 3)


class WordplaySessionManager:
    """Manages active wordplay sessions for messages."""
    
    def __init__(self):
        self.sessions: Dict[int, WordplaySession] = {}  # message_id -> session
        self._cleanup_task = None
    
    def create_session(self, message_id: int, creator_user_id: int, shorter_word: str, longer_word: str, extra_letters: str, puzzle_id: str) -> WordplaySession:
        """Create a new session for a message."""
        # Clean up any existing session for this message
        if message_id in self.sessions:
            del self.sessions[message_id]
        
        session = WordplaySession(message_id, creator_user_id, shorter_word, longer_word, extra_letters, puzzle_id)
        self.sessions[message_id] = session
        logger.info(f"Created wordplay session for message {message_id} by user {creator_user_id}: {shorter_word} -> {longer_word} (puzzle_id: {puzzle_id})")
        return session
    
    def get_session(self, message_id: int) -> Optional[WordplaySession]:
        """Get the active session for a message."""
        return self.sessions.get(message_id)
    
    def remove_session(self, message_id: int):
        """Remove a session for a message."""
        if message_id in self.sessions:
            del self.sessions[message_id]
            logger.info(f"Removed wordplay session for message {message_id}")
    
    async def cleanup_expired_sessions(self):
        """
        Periodically clean up old sessions.
        
        Since sessions are now multi-user and don't expire based on solve status,
        this cleanup only removes very old sessions (e.g., over 24 hours old).
        """
        while True:
            try:
                await asyncio.sleep(SESSION_CLEANUP_INTERVAL)
                
                # Clean up sessions older than 24 hours
                old_sessions = [
                    message_id for message_id, session in self.sessions.items()
                    if (datetime.now() - session.created_at).total_seconds() > 86400  # 24 hours
                ]
                
                for message_id in old_sessions:
                    del self.sessions[message_id]
                
                if old_sessions:
                    logger.info(f"Cleaned up {len(old_sessions)} old wordplay sessions (>24h)")
            except Exception as e:
                logger.error(f"Error cleaning up wordplay sessions: {e}")


# Global session manager
session_manager = WordplaySessionManager()


async def generate_word_pair_with_gemini(generator, min_word_length: int = 4, letter_difference: int = 1) -> Optional[Tuple[str, str, str]]:
    """
    Generate a valid word pair using Gemini AI.
    
    Args:
        generator: The model generator to use
        min_word_length: Minimum length for the shorter word (default: 4)
        letter_difference: Number of letters to add (default: 1)
    
    Returns:
        Tuple of (shorter_word, longer_word, extra_letters) or None if generation fails
    """
    # Determine the letter difference rules
    if letter_difference == 1:
        letter_rule = "3. One word is formed by inserting ONE additional letter into the other word"
        extra_format = "EXTRA: [letter]"
        examples = """EXAMPLES OF VALID PAIRS:
- PLANT → PLANET (extra letter: E)
- STAR → STAIR (extra letter: I)
- PLAN → PLAIN (extra letter: I)
- MATE → MATTE (extra letter: T)
- SCAR → SCARE (extra letter: E)"""
    else:
        letter_rule = f"3. One word is formed by inserting EXACTLY {letter_difference} additional letters into the other word"
        extra_format = f"EXTRA: [comma-separated list of {letter_difference} letters in insertion order]"
        examples = f"""EXAMPLES OF VALID PAIRS (for {letter_difference} letters):
- For 2 letters: PLAN → PLANET (extra letters: E, T)
- For 2 letters: STAR → STAIRS (extra letters: I, S)"""
    
    prompt = f"""Generate a word pair that follows these EXACT rules:

RULES (ALL MUST BE SATISFIED):
1. Two English words only
2. Both words must be common nouns and/or verbs (no proper nouns, slang, or abbreviations)
{letter_rule}
4. The letter order must stay the same (the shorter word is a subsequence of the longer word)
5. NOT simple pluralization (no adding just 's' or 'es')
6. The extra letter(s) can be inserted anywhere in the word
7. Both words must be visually representable in an image
8. The shorter word must be at least {min_word_length} letters long
9. Both words should be distinctly different in meaning to make the puzzle challenging

{examples}

RESPOND WITH ONLY THREE LINES IN THIS EXACT FORMAT:
SHORTER: [word]
LONGER: [word]
{extra_format}

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
        extra_letters = None
        
        for line in lines:
            if line.startswith('SHORTER:'):
                shorter_word = line.split(':', 1)[1].strip().upper()
            elif line.startswith('LONGER:'):
                longer_word = line.split(':', 1)[1].strip().upper()
            elif line.startswith('EXTRA:'):
                extra_letters_raw = line.split(':', 1)[1].strip().upper()
                # Parse the extra letters (could be single letter or comma-separated list)
                if ',' in extra_letters_raw:
                    # Multiple letters case
                    extra_letters = ''.join([l.strip() for l in extra_letters_raw.split(',')])
                else:
                    # Single letter case
                    extra_letters = extra_letters_raw.strip()
                
                # Validate that we have the expected number of letters
                if len(extra_letters) != letter_difference:
                    logger.error(f"Extra letters must be {letter_difference} character(s), got: {extra_letters}")
                    return None
        
        if not all([shorter_word, longer_word, extra_letters]):
            logger.error(f"Failed to parse word pair from response: {text_response}")
            return None
        
        # Validate the word pair
        if not validate_word_pair(shorter_word, longer_word, extra_letters):
            logger.error(f"Invalid word pair generated: {shorter_word} -> {longer_word} (extra: {extra_letters})")
            return None
        
        logger.info(f"Generated valid word pair: {shorter_word} -> {longer_word} (extra: {extra_letters})")
        return shorter_word, longer_word, extra_letters
        
    except Exception as e:
        logger.error(f"Error generating word pair: {e}")
        return None


def validate_word_pair(shorter_word: str, longer_word: str, extra_letters: str) -> bool:
    """
    Validate that a word pair follows the Extra-Letter rule.
    
    Args:
        shorter_word: The shorter word
        longer_word: The longer word
        extra_letters: The extra letter(s) as a string
    
    Returns:
        True if valid, False otherwise
    """
    # Basic validation
    if not all([shorter_word, longer_word, extra_letters]):
        return False
    
    # Longer word should be exactly N characters longer
    letter_diff = len(extra_letters)
    if len(longer_word) != len(shorter_word) + letter_diff:
        return False
    
    # Check if removing occurrences of the extra letters from longer_word gives shorter_word
    # We need to ensure that we can remove exactly the letters in extra_letters to get shorter_word
    
    # Convert to list for easier manipulation
    longer_list = list(longer_word)
    extra_list = list(extra_letters)
    
    # Try to find a valid sequence of positions to remove
    def can_remove_letters(positions_removed, current_idx=0, remove_count=0):
        """Recursively check if we can remove the specified letters to get the shorter word."""
        if remove_count == len(extra_list):
            # We've removed all required letters, check if result matches shorter_word
            result = ''.join([c for i, c in enumerate(longer_list) if i not in positions_removed])
            return result == shorter_word
        
        if current_idx >= len(longer_list):
            return False
        
        letter_to_remove = extra_list[remove_count]
        
        # Try removing at each valid position
        for i in range(current_idx, len(longer_list)):
            if longer_list[i] == letter_to_remove and i not in positions_removed:
                new_positions = positions_removed | {i}
                if can_remove_letters(new_positions, i + 1, remove_count + 1):
                    return True
        
        return False
    
    return can_remove_letters(set())


async def generate_word_image(generator, word: str, style: Optional[str] = None) -> Optional[Image.Image]:
    """
    Generate an image representing a word using Gemini.
    
    Args:
        generator: The model generator to use
        word: The word to visualize
        style: Optional style theme for the image (e.g., "anime", "watercolor", etc.)
    
    Returns:
        PIL Image or None if generation fails
    """
    if style:
        # Generate a style-based prompt using AI
        style_prompt = f"""Generate an image generation prompt for the word "{word}" in the style of "{style}".

The prompt should:
- Describe how to visually represent the word "{word}" in the {style} style
- Be suitable for a word guessing puzzle
- Not include any text or letters in the image
- Focus on clear, recognizable representation despite the artistic style

Create a detailed prompt that captures the essence of the {style} style while making the word "{word}" recognizable."""
        
        try:
            # Get style-based prompt from AI
            _, generated_prompt, _ = await generator.generate_text_only_response(style_prompt)
            if generated_prompt:
                prompt = generated_prompt.strip()
                logger.info(f"Generated style-based prompt for {word} in {style} style")
            else:
                # Fallback to default if generation fails
                logger.warning(f"Failed to generate style-based prompt, using default")
                prompt = f"""Create a {style} style image that represents the word "{word}".

The image should:
- Be in the {style} artistic style
- Be a clear visual representation of the word
- Not include any text or letters
- Be suitable for a word guessing puzzle"""
        except Exception as e:
            logger.error(f"Error generating style-based prompt: {e}")
            prompt = f"""Create a {style} style image that represents the word "{word}".

The image should:
- Be in the {style} artistic style
- Be a clear visual representation of the word
- Not include any text or letters
- Be suitable for a word guessing puzzle"""
    else:
        # Use the default monochrome graphite pencil style
        prompt = f"""Create a monochrome graphite pencil illustration that represents the word "{word}".

The image should:
- Be hand-drawn in appearance, like a traditional sketch
- Use fine linework with light cross-hatching for shading
- Be black and gray only (no color)
- Have a soft, slightly rough paper texture
- Focus on clear silhouette and readable shapes
- Avoid heavy fills or solid blacks
- Look like classical concept art or an academic drawing study
- Not include any text or letters
- Be suitable for a word guessing puzzle

"""

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
