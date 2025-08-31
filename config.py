import os
from dotenv import load_dotenv
from styles import TEMPLATES

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

# Job persistence configuration
JOBS_FILE = 'jobs.json'
JOBS_DIR = 'jobs'

# Ensure directories exist
os.makedirs(GENERATED_IMAGES_DIR, exist_ok=True)
os.makedirs(JOBS_DIR, exist_ok=True)