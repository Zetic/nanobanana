import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Discord configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Google GenAI configuration
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# Bot configuration
COMMAND_PREFIX = '!'
MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8MB max per image
MAX_IMAGES = 10  # Maximum number of images to process
GENERATED_IMAGES_DIR = 'generated_images'

# Template definitions for style buttons
TEMPLATES = {
    'sticker': {
        'name': '🏷️ Sticker',
        'image_only': "Use the subject of the images to create a sticker that should have a black outline and vector artstyle. The background must be transparent.",
        'text_only': "Create a sticker that should have a black outline and vector artstyle. The background must be transparent. The subject is {text}",
        'image_and_text': "Use the subject of the images to create a sticker that should have a black outline and vector artstyle. The background must be transparent. Also {text}"
    }
}

# Ensure directories exist
os.makedirs(GENERATED_IMAGES_DIR, exist_ok=True)