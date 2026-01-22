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
OPENAI_REALTIME_MODEL = os.getenv('OPENAI_REALTIME_MODEL', 'gpt-4o-realtime-preview-2024-12-17')

# XAI configuration
XAI_API_KEY = os.getenv('XAI_API_KEY')
XAI_VOICE_MODEL = os.getenv('XAI_VOICE_MODEL', 'grok-2-voice-1212')
XAI_VOICE = os.getenv('XAI_VOICE', 'ara')

# Bot configuration
COMMAND_PREFIX = '!'
MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8MB max per image
MAX_IMAGES = 10  # Maximum number of images to process
GENERATED_IMAGES_DIR = 'generated_images'

# Rate limiting configuration
DAILY_IMAGE_LIMIT = 3  # Maximum images per user (each with independent 8-hour timer)

# Elevated users configuration (Discord IDs)
# Users in this list are not bound by usage limitations and can use special commands
# Read from environment variable as comma-separated list
_elevated_users_str = os.getenv('ELEVATED_USERS', '')
ELEVATED_USERS = []
if _elevated_users_str.strip():
    try:
        ELEVATED_USERS = [int(user_id.strip()) for user_id in _elevated_users_str.split(',') if user_id.strip()]
    except ValueError:
        print("Warning: Invalid ELEVATED_USERS format in environment variable. Expected comma-separated integers.")
        ELEVATED_USERS = []

# Logs configuration
LOGS_DIR = 'logs'

# Debug logging configuration
# Set DEBUG_LOGGING=true in environment to enable detailed voice pipeline logging
# This provides timing information and event tracking for diagnosing slow response times
DEBUG_LOGGING = os.getenv('DEBUG_LOGGING', 'false').lower() in ('true', '1', 'yes')

# Ensure directories exist
os.makedirs(GENERATED_IMAGES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)