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

# API retry configuration
API_MAX_RETRIES = 3  # Maximum number of retries for rate-limited requests
API_BASE_DELAY = 1   # Base delay in seconds for exponential backoff
API_MAX_DELAY = 300  # Maximum delay in seconds (5 minutes)

# Ensure generated images directory exists
os.makedirs(GENERATED_IMAGES_DIR, exist_ok=True)