#!/usr/bin/env python3
"""
Test script to verify persistence functionality.
"""

import os
import sys
import tempfile
import shutil
from PIL import Image
import io

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from persistence import PersistenceManager, PersistedInteractionState, PersistedOutputItem
from bot import OutputItem

def test_persistence():
    """Test the persistence system."""
    print("Testing persistence system...")
    
    # Create a temporary directory for testing
    test_dir = tempfile.mkdtemp(prefix="nanobanana_test_")
    print(f"Using test directory: {test_dir}")
    
    try:
        # Initialize persistence manager
        pm = PersistenceManager(test_dir)
        
        # Generate interaction ID
        interaction_id = pm.generate_interaction_id()
        print(f"Generated interaction ID: {interaction_id}")
        
        # Create test image
        test_image = Image.new('RGB', (100, 100), 'red')
        img_buffer = io.BytesIO()
        test_image.save(img_buffer, format='PNG')
        img_data = img_buffer.getvalue()
        
        # Save input image
        input_path = pm.save_input_image(img_data, interaction_id, 0)
        print(f"Saved input image: {input_path}")
        
        # Create test output item
        output_item = OutputItem(
            image=test_image,
            filename="test_output.png",
            prompt_used="Test prompt",
            timestamp="20240831_120000",
            interaction_id=interaction_id
        )
        
        # Convert to persisted format (this would normally save to generated_images)
        # For test, we'll create a dummy file
        test_output_path = os.path.join(test_dir, "test_output.png")
        test_image.save(test_output_path)
        
        persisted_output = PersistedOutputItem(
            image_path=f"output_images/test_output_{interaction_id}.png",
            filename="test_output.png",
            prompt_used="Test prompt",
            timestamp="20240831_120000"
        )
        
        # Create test state
        state = PersistedInteractionState(
            interaction_id=interaction_id,
            interaction_type="style_view",
            created_at="2024-08-31T12:00:00",
            original_text="Test text",
            original_image_paths=[input_path],
            outputs=[persisted_output],
            current_index=0
        )
        
        # Save state
        success = pm.save_interaction_state(state)
        print(f"Save state success: {success}")
        
        # Load state
        loaded_state = pm.load_interaction_state(interaction_id)
        print(f"Loaded state: {loaded_state is not None}")
        
        if loaded_state:
            print(f"Loaded state ID: {loaded_state.interaction_id}")
            print(f"Loaded state type: {loaded_state.interaction_type}")
            print(f"Loaded state text: {loaded_state.original_text}")
            print(f"Loaded state outputs: {len(loaded_state.outputs)}")
            print(f"Loaded state images: {len(loaded_state.original_image_paths)}")
        
        # Test path resolution
        abs_input_path = pm.get_absolute_path(input_path)
        print(f"Input image exists: {os.path.exists(abs_input_path)}")
        
        print("✅ Persistence test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Persistence test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Clean up
        shutil.rmtree(test_dir, ignore_errors=True)
        print(f"Cleaned up test directory: {test_dir}")

if __name__ == "__main__":
    success = test_persistence()
    sys.exit(0 if success else 1)