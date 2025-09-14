import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Discord configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Google GenAI configuration
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# OpenAI configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Bot configuration
COMMAND_PREFIX = '!'
MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8MB max per image
MAX_IMAGES = 10  # Maximum number of images to process
GENERATED_IMAGES_DIR = 'generated_images'

# Rate limiting configuration
DAILY_IMAGE_LIMIT = 5  # Maximum images per user per day

# Elevated users configuration (Discord IDs)
# Users in this list are not bound by usage limitations and can use special commands
ELEVATED_USERS = [
    # Add Discord user IDs here, e.g.:
    # 123456789012345678,
    # 987654321098765432,
]

# Ensure directories exist
os.makedirs(GENERATED_IMAGES_DIR, exist_ok=True)