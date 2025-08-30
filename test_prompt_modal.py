#!/usr/bin/env python3
"""
Simple test to validate the PromptModal class functionality.
"""

# Mock discord module for testing
class MockTextStyle:
    paragraph = "paragraph"

class MockTextInput:
    def __init__(self, label=None, placeholder=None, default=None, style=None, max_length=None, required=None):
        self.label = label
        self.placeholder = placeholder
        self.default = default
        self.style = style
        self.max_length = max_length
        self.required = required
        self.value = default or ""

class MockModal:
    def __init__(self, title=None):
        self.title = title
        self.items = []
    
    def add_item(self, item):
        self.items.append(item)

class MockUI:
    Modal = MockModal
    TextInput = MockTextInput
    TextStyle = MockTextStyle

class MockDiscord:
    ui = MockUI

# Inject mock
import sys
sys.modules['discord'] = MockDiscord()

# Now test our PromptModal class by importing just the class definition
def test_prompt_modal():
    # Extract just the PromptModal class from bot.py
    with open('bot.py', 'r') as f:
        bot_content = f.read()
    
    # Find the PromptModal class definition
    lines = bot_content.split('\n')
    modal_start = None
    modal_end = None
    
    for i, line in enumerate(lines):
        if line.startswith('class PromptModal('):
            modal_start = i
        elif modal_start is not None and line.startswith('class ') and not line.startswith('class PromptModal('):
            modal_end = i
            break
    
    if modal_start is None:
        print("❌ PromptModal class not found")
        return False
    
    if modal_end is None:
        modal_end = len(lines)
    
    # Extract the class code
    modal_code = '\n'.join(lines[modal_start:modal_end])
    
    # Execute the class definition
    exec_globals = {
        'discord': MockDiscord(),
        '__name__': '__main__'
    }
    
    try:
        exec(modal_code, exec_globals)
        PromptModal = exec_globals['PromptModal']
        
        # Test creating modal with default prompt
        modal1 = PromptModal()
        assert modal1.title == "Edit Prompt"
        assert modal1.prompt_input.default == ""
        assert modal1.new_prompt is None
        
        # Test creating modal with custom prompt and title
        modal2 = PromptModal("Test prompt", "Custom Title")
        assert modal2.title == "Custom Title"
        assert modal2.prompt_input.default == "Test prompt"
        assert modal2.new_prompt is None
        
        # Test prompt input properties
        assert modal2.prompt_input.label == "Prompt"
        assert modal2.prompt_input.placeholder == "Enter your prompt here..."
        assert modal2.prompt_input.max_length == 1000
        assert modal2.prompt_input.required == False
        
        print("✅ PromptModal class tests passed")
        return True
        
    except Exception as e:
        print(f"❌ PromptModal test failed: {e}")
        return False

def test_button_labels():
    """Test that the button labels were changed correctly."""
    with open('bot.py', 'r') as f:
        content = f.read()
    
    # Check for the new button labels
    tests = [
        ("🎨 Process Prompt", "Main process button label"),
        ("✏️ Edit Prompt", "Edit prompt button label"),
        ("🏷️ Make Sticker", "Sticker button label"),
    ]
    
    all_passed = True
    for label, description in tests:
        if label in content:
            print(f"✅ {description} found: {label}")
        else:
            print(f"❌ {description} missing: {label}")
            all_passed = False
    
    # Check that old "Process Request" label is replaced
    if "Process Request" not in content:
        print("✅ Old 'Process Request' label successfully replaced")
    else:
        print("❌ Old 'Process Request' label still found")
        all_passed = False
    
    return all_passed

if __name__ == "__main__":
    print("Testing PromptModal functionality...")
    modal_test = test_prompt_modal()
    
    print("\nTesting button labels...")
    label_test = test_button_labels()
    
    if modal_test and label_test:
        print("\n✅ All tests passed!")
        exit(0)
    else:
        print("\n❌ Some tests failed!")
        exit(1)