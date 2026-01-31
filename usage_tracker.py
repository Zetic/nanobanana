import json
import os
import logging
import threading
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, date, time, timedelta
import config

logger = logging.getLogger(__name__)

# Tier definitions with their corresponding charge limits
TIER_LIMITS = {
    'standard': 3,
    'limited': 2,
    'strict': 1,
    'extra': 5,
    'unlimited': float('inf')
}

class UsageTracker:
    """Tracks token usage per Discord user with thread-safe JSON operations."""
    
    def __init__(self):
        self.usage_file = os.path.join(config.GENERATED_IMAGES_DIR, 'usage_stats.json')
        self._lock = threading.Lock()
        self._ensure_usage_file_exists()
        self.rate_limit_hours = 8  # Each usage charge expires after 8 hours
    
    def _ensure_usage_file_exists(self):
        """Ensure the usage stats file exists with proper structure."""
        if not os.path.exists(self.usage_file):
            with self._lock:
                # Double-check in case another thread created it
                if not os.path.exists(self.usage_file):
                    initial_data = {
                        "users": {},
                        "last_updated": datetime.now().isoformat()
                    }
                    with open(self.usage_file, 'w') as f:
                        json.dump(initial_data, f, indent=2)
    
    def _get_user_tier_unlocked(self, user_id: int, data: Dict[str, Any]) -> str:
        """
        Internal method to get user tier without acquiring lock.
        Must be called from within a locked context with data already loaded.
        
        Args:
            user_id: Discord user ID
            data: Already loaded usage data
        
        Returns:
            Tier name (default: 'standard')
        """
        user_id_str = str(user_id)
        if user_id_str not in data["users"]:
            return 'standard'
        return data["users"][user_id_str].get("tier", 'standard')
    
    def _get_available_usage_slots(self, user_id: int) -> int:
        """
        Get the number of available usage slots for a user.
        Each slot expires 8 hours after it was used.
        
        Returns:
            Number of available slots based on user's tier
        """
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            # Get user's tier limit (using unlocked version since we're already in a lock)
            user_tier = self._get_user_tier_unlocked(user_id, data)
            tier_limit = TIER_LIMITS.get(user_tier, config.DAILY_IMAGE_LIMIT)
            
            if user_id_str not in data["users"]:
                return tier_limit  # All slots available for new users
            
            user_data = data["users"][user_id_str]
            usage_timestamps = user_data.get("usage_timestamps", [])
            
            # Filter out timestamps older than 8 hours
            now = datetime.now()
            cutoff_time = now - timedelta(hours=self.rate_limit_hours)
            
            active_usages = [
                ts for ts in usage_timestamps
                if datetime.fromisoformat(ts) > cutoff_time
            ]
            
            # Return number of available slots
            return tier_limit - len(active_usages)
    
    def _get_next_available_time(self, user_id: int) -> Optional[datetime]:
        """
        Get the timestamp when the next usage slot will become available.
        
        Returns:
            datetime when next slot available, or None if slots are available now
        """
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            if user_id_str not in data["users"]:
                return None  # All slots available
            
            user_data = data["users"][user_id_str]
            usage_timestamps = user_data.get("usage_timestamps", [])
            
            if not usage_timestamps:
                return None  # All slots available
            
            # Filter out timestamps older than 8 hours
            now = datetime.now()
            cutoff_time = now - timedelta(hours=self.rate_limit_hours)
            
            active_usages = [
                datetime.fromisoformat(ts) for ts in usage_timestamps
                if datetime.fromisoformat(ts) > cutoff_time
            ]
            
            # Get user's tier limit (using unlocked version since we're already in a lock)
            user_tier = self._get_user_tier_unlocked(user_id, data)
            tier_limit = TIER_LIMITS.get(user_tier, config.DAILY_IMAGE_LIMIT)
            
            if len(active_usages) < tier_limit:
                return None  # At least one slot is available
            
            # Find the oldest active usage and calculate when it expires
            oldest_usage = min(active_usages)
            next_available = oldest_usage + timedelta(hours=self.rate_limit_hours)
            
            return next_available
    
    def _load_usage_data(self) -> Dict[str, Any]:
        """Load usage data from JSON file."""
        try:
            with open(self.usage_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Error loading usage data: {e}. Creating new file.")
            return {
                "users": {},
                "last_updated": datetime.now().isoformat()
            }
    
    def _save_usage_data(self, data: Dict[str, Any]):
        """Save usage data to JSON file."""
        data["last_updated"] = datetime.now().isoformat()
        with open(self.usage_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def record_usage(self, user_id: int, username: str, prompt_tokens: int, 
                    output_tokens: int, total_tokens: int, images_generated: int = 0):
        """
        Record token usage for a user.
        
        Args:
            user_id: Discord user ID
            username: Discord username (for display purposes)
            prompt_tokens: Number of input tokens used
            output_tokens: Number of output tokens generated
            total_tokens: Total tokens used
            images_generated: Number of images generated (default 0)
        """
        with self._lock:
            data = self._load_usage_data()
            
            user_id_str = str(user_id)
            if user_id_str not in data["users"]:
                data["users"][user_id_str] = {
                    "username": username,
                    "total_prompt_tokens": 0,
                    "total_output_tokens": 0,
                    "total_tokens": 0,
                    "images_generated": 0,
                    "requests_count": 0,
                    "first_use": datetime.now().isoformat(),
                    "last_use": datetime.now().isoformat(),
                    "usage_timestamps": [],  # List of timestamps for each image generation
                    "wordplay_score": 0  # Score for wordplay puzzles
                }
            
            user_data = data["users"][user_id_str]
            user_data["username"] = username  # Update username in case it changed
            user_data["total_prompt_tokens"] += prompt_tokens
            user_data["total_output_tokens"] += output_tokens
            user_data["total_tokens"] += total_tokens
            user_data["images_generated"] += images_generated
            user_data["requests_count"] += 1
            user_data["last_use"] = datetime.now().isoformat()
            
            # Track image generation timestamp if any were generated
            if images_generated > 0:
                if "usage_timestamps" not in user_data:
                    user_data["usage_timestamps"] = []
                
                # Add timestamp for this usage
                user_data["usage_timestamps"].append(datetime.now().isoformat())
                
                # Clean up old timestamps (older than 8 hours)
                cutoff_time = datetime.now() - timedelta(hours=self.rate_limit_hours)
                user_data["usage_timestamps"] = [
                    ts for ts in user_data["usage_timestamps"]
                    if datetime.fromisoformat(ts) > cutoff_time
                ]
            
            self._save_usage_data(data)
            
            logger.info(f"Recorded usage for user {username} ({user_id}): "
                       f"prompt={prompt_tokens}, output={output_tokens}, "
                       f"total={total_tokens}, images={images_generated}")
    
    def get_usage_stats(self) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Get usage statistics for all users, sorted by output token usage.
        
        Returns:
            List of tuples (user_id, user_data) sorted by total_output_tokens descending
        """
        with self._lock:
            data = self._load_usage_data()
            
            # Convert to list of tuples and sort by output tokens
            users_list = []
            for user_id, user_data in data["users"].items():
                users_list.append((user_id, user_data))
            
            # Sort by total_output_tokens in descending order
            users_list.sort(key=lambda x: x[1]["total_output_tokens"], reverse=True)
            
            return users_list
    
    def get_user_usage(self, user_id: int) -> Dict[str, Any]:
        """Get usage statistics for a specific user."""
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            return data["users"].get(user_id_str, {})
    
    def get_total_stats(self) -> Dict[str, Any]:
        """Get overall usage statistics across all users."""
        with self._lock:
            data = self._load_usage_data()
            
            total_stats = {
                "total_users": len(data["users"]),
                "total_prompt_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "total_images_generated": 0,
                "total_requests": 0
            }
            
            for user_data in data["users"].values():
                total_stats["total_prompt_tokens"] += user_data.get("total_prompt_tokens", 0)
                total_stats["total_output_tokens"] += user_data.get("total_output_tokens", 0)
                total_stats["total_tokens"] += user_data.get("total_tokens", 0)
                total_stats["total_images_generated"] += user_data.get("images_generated", 0)
                total_stats["total_requests"] += user_data.get("requests_count", 0)
            
            return total_stats

    def get_daily_image_count(self, user_id: int) -> int:
        """Get the number of active usage charges for a user (within 8-hour window)."""
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            if user_id_str not in data["users"]:
                return 0
            
            user_data = data["users"][user_id_str]
            usage_timestamps = user_data.get("usage_timestamps", [])
            
            # Count timestamps within the 8-hour window
            now = datetime.now()
            cutoff_time = now - timedelta(hours=self.rate_limit_hours)
            
            active_count = sum(
                1 for ts in usage_timestamps
                if datetime.fromisoformat(ts) > cutoff_time
            )
            
            return active_count
    
    def has_reached_usage_limit(self, user_id: int) -> Tuple[bool, Optional[datetime]]:
        """
        Check if a user has reached their usage limit (all slots are full).
        
        Returns:
            Tuple of (has_reached_limit, next_available_time)
        """
        # Elevated users never reach usage limit
        if user_id in config.ELEVATED_USERS:
            return False, None
        
        # Unlimited tier users never reach usage limit
        user_tier = self.get_user_tier(user_id)
        if user_tier == 'unlimited':
            return False, None
        
        available_slots = self._get_available_usage_slots(user_id)
        
        if available_slots > 0:
            return False, None
        else:
            next_available = self._get_next_available_time(user_id)
            return True, next_available
    
    def can_generate_image(self, user_id: int) -> bool:
        """Check if a user can generate an image (has at least one available slot)."""
        # Check if user is elevated (not bound by limitations)
        if user_id in config.ELEVATED_USERS:
            return True
        
        # Unlimited tier users can always generate
        user_tier = self.get_user_tier(user_id)
        if user_tier == 'unlimited':
            return True
        
        available_slots = self._get_available_usage_slots(user_id)
        return available_slots > 0
    
    def get_remaining_images_today(self, user_id: int) -> int:
        """Get the number of available usage slots for a user."""
        # Elevated users have unlimited images
        if user_id in config.ELEVATED_USERS:
            return float('inf')
        
        # Unlimited tier users have unlimited images
        user_tier = self.get_user_tier(user_id)
        if user_tier == 'unlimited':
            return float('inf')
        
        return self._get_available_usage_slots(user_id)
    
    def reset_daily_usage(self, user_id: int) -> bool:
        """
        Reset usage timestamps for a specific user.
        Returns True if successful, False if user not found.
        """
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            if user_id_str not in data["users"]:
                return False
            
            user_data = data["users"][user_id_str]
            
            # Reset usage timestamps
            user_data["usage_timestamps"] = []
            
            self._save_usage_data(data)
            logger.info(f"Reset usage timestamps for user {user_id}")
            return True
    
    def get_user_tier(self, user_id: int) -> str:
        """
        Get the tier for a user.
        Returns 'standard' if not set.
        """
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            if user_id_str not in data["users"]:
                return 'standard'
            
            return data["users"][user_id_str].get("tier", 'standard')
    
    def set_user_tier(self, user_id: int, tier: str, username: str = None) -> bool:
        """
        Set the tier for a user.
        
        Args:
            user_id: Discord user ID
            tier: Tier name (standard, limited, strict, extra, unlimited)
            username: Optional username to store
        
        Returns:
            True if successful, False if tier is invalid
        """
        if tier not in TIER_LIMITS:
            return False
        
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            # Create user entry if it doesn't exist
            if user_id_str not in data["users"]:
                data["users"][user_id_str] = {
                    "username": username or "Unknown User",
                    "total_prompt_tokens": 0,
                    "total_output_tokens": 0,
                    "total_tokens": 0,
                    "images_generated": 0,
                    "requests_count": 0,
                    "first_use": datetime.now().isoformat(),
                    "last_use": datetime.now().isoformat(),
                    "usage_timestamps": [],
                    "tier": tier
                }
            else:
                # Update existing user's tier
                data["users"][user_id_str]["tier"] = tier
                if username:
                    data["users"][user_id_str]["username"] = username
            
            self._save_usage_data(data)
            logger.info(f"Set tier '{tier}' for user {user_id}")
            return True
    
    def is_elevated_user(self, user_id: int) -> bool:
        """Check if a user has elevated status."""
        return user_id in config.ELEVATED_USERS
    
    def get_wordplay_score(self, user_id: int) -> int:
        """
        Get the wordplay score for a user.
        Returns 0 if user has no score.
        """
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            if user_id_str not in data["users"]:
                return 0
            
            return data["users"][user_id_str].get("wordplay_score", 0)
    
    def increment_wordplay_score(self, user_id: int, username: str) -> int:
        """
        Increment the wordplay score for a user.
        
        Args:
            user_id: Discord user ID
            username: Discord username (for display purposes)
        
        Returns:
            New wordplay score
        """
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            # Create user entry if it doesn't exist
            if user_id_str not in data["users"]:
                data["users"][user_id_str] = {
                    "username": username,
                    "total_prompt_tokens": 0,
                    "total_output_tokens": 0,
                    "total_tokens": 0,
                    "images_generated": 0,
                    "requests_count": 0,
                    "first_use": datetime.now().isoformat(),
                    "last_use": datetime.now().isoformat(),
                    "usage_timestamps": [],
                    "wordplay_score": 0
                }
            
            # Ensure wordplay_score field exists (for existing users)
            if "wordplay_score" not in data["users"][user_id_str]:
                data["users"][user_id_str]["wordplay_score"] = 0
            
            # Increment score
            data["users"][user_id_str]["wordplay_score"] += 1
            new_score = data["users"][user_id_str]["wordplay_score"]
            
            self._save_usage_data(data)
            logger.info(f"Incremented wordplay score for user {username} ({user_id}): {new_score}")
            return new_score

# Global instance
usage_tracker = UsageTracker()