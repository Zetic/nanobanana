import json
import os
import logging
import threading
from typing import Dict, Any, List, Tuple
from datetime import datetime, date, time
import config

logger = logging.getLogger(__name__)

class UsageTracker:
    """Tracks token usage per Discord user with thread-safe JSON operations."""
    
    def __init__(self):
        self.usage_file = os.path.join(config.GENERATED_IMAGES_DIR, 'usage_stats.json')
        self._lock = threading.Lock()
        self._ensure_usage_file_exists()
    
    def _get_current_cycle_key(self) -> str:
        """
        Get the current cycle key based on time.
        Cycles reset at noon (12:00) and midnight (00:00).
        Returns format: "2024-01-15-morning" or "2024-01-15-afternoon"
        """
        now = datetime.now()
        today = now.date().isoformat()
        
        # Morning cycle: 00:00 - 11:59
        # Afternoon cycle: 12:00 - 23:59
        if now.time() < time(12, 0):
            return f"{today}-morning"
        else:
            return f"{today}-afternoon"
    
    def _get_next_reset_timestamp(self) -> int:
        """Get the timestamp for the next cycle reset (noon or midnight)."""
        now = datetime.now()
        today = now.date()
        
        if now.time() < time(12, 0):
            # Currently in morning cycle, next reset is at noon
            next_reset = datetime.combine(today, time(12, 0))
        else:
            # Currently in afternoon cycle, next reset is at midnight tomorrow
            from datetime import timedelta
            tomorrow = today + timedelta(days=1)
            next_reset = datetime.combine(tomorrow, time(0, 0))
        
        return int(next_reset.timestamp())
    
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
                    "daily_images": {}  # Track images per day: {"2024-01-15": 3, "2024-01-16": 1}
                }
            
            user_data = data["users"][user_id_str]
            user_data["username"] = username  # Update username in case it changed
            user_data["total_prompt_tokens"] += prompt_tokens
            user_data["total_output_tokens"] += output_tokens
            user_data["total_tokens"] += total_tokens
            user_data["images_generated"] += images_generated
            user_data["requests_count"] += 1
            user_data["last_use"] = datetime.now().isoformat()
            
            # Track images per cycle if any were generated
            if images_generated > 0:
                current_cycle = self._get_current_cycle_key()
                if "daily_images" not in user_data:
                    user_data["daily_images"] = {}
                user_data["daily_images"][current_cycle] = user_data["daily_images"].get(current_cycle, 0) + images_generated
            
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
        """Get the number of images generated by a user in the current cycle."""
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            if user_id_str not in data["users"]:
                return 0
            
            user_data = data["users"][user_id_str]
            daily_images = user_data.get("daily_images", {})
            current_cycle = self._get_current_cycle_key()
            
            return daily_images.get(current_cycle, 0)
    
    def can_generate_image(self, user_id: int) -> bool:
        """Check if a user can generate an image in the current cycle (within cycle limit or is elevated user)."""
        # Check if user is elevated (not bound by limitations)
        if user_id in config.ELEVATED_USERS:
            return True
        
        cycle_count = self.get_daily_image_count(user_id)
        return cycle_count < config.DAILY_IMAGE_LIMIT
    
    def get_remaining_images_today(self, user_id: int) -> int:
        """Get the number of images a user can still generate in the current cycle."""
        # Elevated users have unlimited images
        if user_id in config.ELEVATED_USERS:
            return float('inf')
        
        cycle_count = self.get_daily_image_count(user_id)
        return max(0, config.DAILY_IMAGE_LIMIT - cycle_count)
    
    def reset_daily_usage(self, user_id: int) -> bool:
        """
        Reset current cycle image usage for a specific user.
        Returns True if successful, False if user not found.
        """
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            
            if user_id_str not in data["users"]:
                return False
            
            user_data = data["users"][user_id_str]
            current_cycle = self._get_current_cycle_key()
            
            # Reset current cycle's image count
            if "daily_images" not in user_data:
                user_data["daily_images"] = {}
            
            user_data["daily_images"][current_cycle] = 0
            
            self._save_usage_data(data)
            logger.info(f"Reset cycle usage for user {user_id} (cycle: {current_cycle})")
            return True
    
    def is_elevated_user(self, user_id: int) -> bool:
        """Check if a user has elevated status."""
        return user_id in config.ELEVATED_USERS

# Global instance
usage_tracker = UsageTracker()