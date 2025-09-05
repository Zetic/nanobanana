import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Discord configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Google GenAI configuration
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# Google Custom Search configuration
GOOGLE_SEARCH_ENGINE_ID = os.getenv('GOOGLE_SEARCH_ENGINE_ID')
GOOGLE_SEARCH_API_KEY = os.getenv('GOOGLE_SEARCH_API_KEY', GOOGLE_API_KEY)  # Default to GenAI key if not specified

# Bot configuration
COMMAND_PREFIX = '!'
MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8MB max per image
MAX_IMAGES = 10  # Maximum number of images to process
GENERATED_IMAGES_DIR = 'generated_images'

# Ensure directories exist
os.makedirs(GENERATED_IMAGES_DIR, exist_ok=True)