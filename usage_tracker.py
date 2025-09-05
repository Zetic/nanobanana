import json
import os
import logging
import threading
from typing import Dict, Any, List, Tuple
from datetime import datetime, date
import config

logger = logging.getLogger(__name__)

class UsageTracker:
    """Tracks token usage per Discord user with thread-safe JSON operations."""
    
    # Rate limit configuration
    DAILY_IMAGE_LIMIT = 5
    
    def __init__(self):
        self.usage_file = os.path.join(config.GENERATED_IMAGES_DIR, 'usage_stats.json')
        self._lock = threading.Lock()
        self._ensure_usage_file_exists()
    
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
        
        # Periodically clean up old daily data (every time we save)
        # This is a lightweight operation since we only keep current month
        try:
            self._cleanup_old_daily_data_internal(data)
        except Exception as e:
            logger.warning(f"Could not clean up old daily data: {e}")
        
        with open(self.usage_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _cleanup_old_daily_data_internal(self, data: Dict[str, Any]):
        """Internal method to clean up old daily data from provided data dict."""
        cutoff_date = date.today().replace(day=1)  # Keep current month
        cutoff_str = cutoff_date.isoformat()
        
        for user_data in data["users"].values():
            if "daily_images" in user_data:
                # Keep only recent daily data
                daily_images = user_data["daily_images"]
                user_data["daily_images"] = {
                    date_str: count for date_str, count in daily_images.items()
                    if date_str >= cutoff_str
                }
    
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
            today_str = date.today().isoformat()
            
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
                    "daily_images": {}  # Track daily image generation
                }
            
            user_data = data["users"][user_id_str]
            user_data["username"] = username  # Update username in case it changed
            user_data["total_prompt_tokens"] += prompt_tokens
            user_data["total_output_tokens"] += output_tokens
            user_data["total_tokens"] += total_tokens
            user_data["images_generated"] += images_generated
            user_data["requests_count"] += 1
            user_data["last_use"] = datetime.now().isoformat()
            
            # Track daily images
            if "daily_images" not in user_data:
                user_data["daily_images"] = {}
            
            if today_str not in user_data["daily_images"]:
                user_data["daily_images"][today_str] = 0
            user_data["daily_images"][today_str] += images_generated
            
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
    
    def get_daily_images_count(self, user_id: int) -> int:
        """Get the number of images generated by user today."""
        with self._lock:
            data = self._load_usage_data()
            user_id_str = str(user_id)
            today_str = date.today().isoformat()
            
            if user_id_str not in data["users"]:
                return 0
            
            user_data = data["users"][user_id_str]
            daily_images = user_data.get("daily_images", {})
            return daily_images.get(today_str, 0)
    
    def can_generate_image(self, user_id: int) -> tuple[bool, int, int]:
        """
        Check if user can generate another image today.
        
        Returns:
            tuple: (can_generate, images_used_today, remaining_images)
        """
        images_today = self.get_daily_images_count(user_id)
        remaining = max(0, self.DAILY_IMAGE_LIMIT - images_today)
        can_generate = images_today < self.DAILY_IMAGE_LIMIT
        
        return can_generate, images_today, remaining
    
    def cleanup_old_daily_data(self, days_to_keep: int = 30):
        """Clean up old daily image data to prevent file from growing too large."""
        with self._lock:
            data = self._load_usage_data()
            self._cleanup_old_daily_data_internal(data)
            self._save_usage_data(data)
    
    
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

# Global instance
usage_tracker = UsageTracker()