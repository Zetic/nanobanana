"""
Persistence layer for storing and retrieving bot interaction state.

This module provides a JSON-based persistence system to maintain
bot interaction data across restarts, enabling true persistent views.
"""

import json
import os
import uuid
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

@dataclass
class PersistedOutputItem:
    """Persisted version of OutputItem with image paths instead of PIL objects."""
    image_path: str
    filename: str
    prompt_used: str
    timestamp: str

@dataclass
class PersistedInteractionState:
    """Complete state of an interaction that can be persisted."""
    interaction_id: str
    interaction_type: str  # "style_view" or "process_view"
    created_at: str
    original_text: str
    original_image_paths: List[str] = field(default_factory=list)
    outputs: List[PersistedOutputItem] = field(default_factory=list)
    current_index: int = 0
    
    # Additional metadata
    user_id: Optional[int] = None
    channel_id: Optional[int] = None
    message_id: Optional[int] = None

class PersistenceManager:
    """Manages persistence of interaction state and associated files."""
    
    def __init__(self, base_dir: str = "bot_data"):
        self.base_dir = Path(base_dir)
        self.states_dir = self.base_dir / "states"
        self.input_images_dir = self.base_dir / "input_images"
        self.output_images_dir = self.base_dir / "output_images"
        
        # Create directories
        self.states_dir.mkdir(parents=True, exist_ok=True)
        self.input_images_dir.mkdir(parents=True, exist_ok=True)
        self.output_images_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Persistence manager initialized with base directory: {self.base_dir}")
    
    def generate_interaction_id(self) -> str:
        """Generate a unique interaction ID."""
        return str(uuid.uuid4())
    
    def save_input_image(self, image_data: bytes, interaction_id: str, index: int = 0) -> str:
        """
        Save input image data and return the relative path.
        
        Args:
            image_data: Raw image bytes
            interaction_id: Unique interaction identifier
            index: Index for multiple images
            
        Returns:
            Relative path to saved image
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"input_{interaction_id}_{index}_{timestamp}.png"
        filepath = self.input_images_dir / filename
        
        with open(filepath, 'wb') as f:
            f.write(image_data)
        
        # Return relative path from base_dir
        return str(filepath.relative_to(self.base_dir))
    
    def save_output_image_with_id(self, image_path: str, interaction_id: str) -> str:
        """
        Copy an output image to the persistence directory with ID-based naming.
        
        Args:
            image_path: Path to existing output image
            interaction_id: Unique interaction identifier
            
        Returns:
            Relative path to saved image
        """
        if not os.path.exists(image_path):
            logger.warning(f"Output image not found: {image_path}")
            return image_path
        
        # Extract original filename
        original_filename = os.path.basename(image_path)
        name, ext = os.path.splitext(original_filename)
        
        # Create new filename with interaction ID
        new_filename = f"output_{interaction_id}_{name}{ext}"
        new_filepath = self.output_images_dir / new_filename
        
        # Copy the file
        shutil.copy2(image_path, new_filepath)
        
        # Return relative path from base_dir
        return str(new_filepath.relative_to(self.base_dir))
    
    def save_interaction_state(self, state: PersistedInteractionState) -> bool:
        """
        Save interaction state to JSON file.
        
        Args:
            state: The interaction state to save
            
        Returns:
            True if saved successfully
        """
        try:
            state_file = self.states_dir / f"{state.interaction_id}.json"
            
            with open(state_file, 'w') as f:
                json.dump(asdict(state), f, indent=2)
            
            logger.info(f"Saved interaction state: {state.interaction_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save interaction state {state.interaction_id}: {e}")
            return False
    
    def load_interaction_state(self, interaction_id: str) -> Optional[PersistedInteractionState]:
        """
        Load interaction state from JSON file.
        
        Args:
            interaction_id: Unique interaction identifier
            
        Returns:
            Loaded interaction state or None if not found
        """
        try:
            state_file = self.states_dir / f"{interaction_id}.json"
            
            if not state_file.exists():
                logger.warning(f"Interaction state not found: {interaction_id}")
                return None
            
            with open(state_file, 'r') as f:
                data = json.load(f)
            
            # Convert outputs list back to PersistedOutputItem objects
            outputs = [PersistedOutputItem(**output) for output in data.get('outputs', [])]
            data['outputs'] = outputs
            
            state = PersistedInteractionState(**data)
            logger.info(f"Loaded interaction state: {interaction_id}")
            return state
            
        except Exception as e:
            logger.error(f"Failed to load interaction state {interaction_id}: {e}")
            return None
    
    def get_absolute_path(self, relative_path: str) -> str:
        """
        Convert relative path to absolute path.
        
        Args:
            relative_path: Path relative to base_dir
            
        Returns:
            Absolute path
        """
        return str(self.base_dir / relative_path)
    
    def cleanup_old_states(self, max_age_days: int = 30) -> int:
        """
        Clean up old interaction states and associated files.
        
        Args:
            max_age_days: Maximum age in days for keeping states
            
        Returns:
            Number of states cleaned up
        """
        cutoff_timestamp = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)
        cleaned_count = 0
        
        try:
            for state_file in self.states_dir.glob("*.json"):
                if state_file.stat().st_mtime < cutoff_timestamp:
                    # Load state to get associated file paths
                    try:
                        with open(state_file, 'r') as f:
                            data = json.load(f)
                        
                        # Clean up associated image files
                        for img_path in data.get('original_image_paths', []):
                            abs_path = self.get_absolute_path(img_path)
                            if os.path.exists(abs_path):
                                os.remove(abs_path)
                        
                        for output in data.get('outputs', []):
                            abs_path = self.get_absolute_path(output['image_path'])
                            if os.path.exists(abs_path):
                                os.remove(abs_path)
                        
                        # Remove state file
                        state_file.unlink()
                        cleaned_count += 1
                        
                    except Exception as e:
                        logger.warning(f"Failed to clean up state {state_file}: {e}")
            
            logger.info(f"Cleaned up {cleaned_count} old interaction states")
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0

# Global persistence manager instance
_persistence_manager = None

def get_persistence_manager() -> PersistenceManager:
    """Get or create the global persistence manager instance."""
    global _persistence_manager
    if _persistence_manager is None:
        _persistence_manager = PersistenceManager()
    return _persistence_manager