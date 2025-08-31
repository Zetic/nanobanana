#!/usr/bin/env python3
"""
Quick validation that the bot can import and initialize properly.
"""

import sys
import os

def main():
    print("Validating Nano Banana Bot with persistence system...")
    
    try:
        # Test imports
        print("Testing imports...")
        from persistence import PersistenceManager, PersistedInteractionState, PersistedOutputItem
        from bot import OutputItem, StyleOptionsView, ProcessRequestView
        import config
        print("✅ All imports successful")
        
        # Test persistence manager initialization
        print("Testing persistence manager...")
        pm = PersistenceManager("/tmp/validation_test")
        interaction_id = pm.generate_interaction_id()
        print(f"✅ Generated interaction ID: {interaction_id[:8]}...")
        
        # Test data models
        print("Testing data models...")
        output_item = OutputItem(
            image=None,  # Skip actual image for validation
            filename="test.png",
            prompt_used="Test prompt",
            timestamp="20240831_120000",
            interaction_id=interaction_id
        )
        print("✅ OutputItem creation successful")
        
        # Test config access
        print("Testing configuration...")
        generated_dir = getattr(config, 'GENERATED_IMAGES_DIR', 'generated_images')
        print(f"✅ Generated images directory: {generated_dir}")
        
        # Clean up test directory
        import shutil
        shutil.rmtree("/tmp/validation_test", ignore_errors=True)
        
        print("\n🎉 Bot validation successful!")
        print("The bot should be ready to run with full persistence support.")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure all required packages are installed:")
        print("pip install -r requirements.txt")
        return False
        
    except Exception as e:
        print(f"❌ Validation error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)