# 🍌 Nano Banana Discord Bot

A Discord bot that generates images and text using Google's Gemini AI and OpenAI. The bot returns natural responses from the AI - text when the AI responds with text, images when it responds with images, or both when it responds with both.

## ✨ Features

- **Text-to-Image Generation**: Create images from descriptive text prompts
- **Image-to-Image Transformation**: Transform uploaded images using AI  
- **Multi-Image Processing**: Process multiple images simultaneously
- **Aspect Ratio Control**: Specify output aspect ratios (16:9, 21:9, 1:1, 9:16, etc.)
- **Meme Generation**: Generate nonsensical memes using OpenAI
- **Voice Bot**: Full-duplex speech-to-speech interaction using OpenAI's GPT-4o Realtime API
- **Reply Message Support**: Automatically uses images from the original message when mentioned in a reply (text from original message is ignored)
- **Bot Snitching**: Catches users who delete messages that mentioned the bot (within 8 hours) and playfully calls them out
- **Natural API Responses**: Returns whatever the AI naturally generates (text, images, or both)
- **Discord Integration**: Simple mention-based interaction
- **Smart Processing**: Automatic image resizing and optimization
- **Usage Tracking**: Track token usage per user with detailed statistics

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Discord Bot Token
- Google GenAI API Key
- OpenAI API Key (for voice bot and meme generation)
- FFmpeg (required for voice bot feature)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/Zetic/nanobanana.git
cd nanobanana
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your tokens:
# DISCORD_TOKEN=your_discord_bot_token_here
# GOOGLE_API_KEY=your_google_api_key_here
```

4. Run the bot:

**Option A: Using the automated script (recommended)**
```bash
./run_bot.sh
```
The script will automatically check dependencies, environment setup, and start the bot with helpful error messages.

**Option B: Manual start**
```bash
python main.py
```

## 🎯 Usage

### Simple Mentions

- **Mention the bot** with a text prompt:
  ```
  @Nano Banana Create a nano banana floating in space
  ```

- **Attach images** with your mention to transform them:
  ```
  @Nano Banana Make this cat look cyberpunk (with image attached)
  ```

- **Multiple images** can be processed simultaneously:
  ```
  @Nano Banana Combine these into a fantasy scene (with multiple images)
  ```

- **Reply to messages with images** to use images from the original message:
  ```
  @Nano Banana make this change (as a reply to a message with images)
  ```

- **Specify aspect ratios** for image generation:
  ```
  @Nano Banana Create a cinematic landscape -21:9
  @Nano Banana Make this portrait -9:16
  @Nano Banana Generate a square image -1:1
  ```

**Supported Aspect Ratios:**
- **Landscape**: `-21:9`, `-16:9`, `-4:3`, `-3:2`
- **Square**: `-1:1`
- **Portrait**: `-9:16`, `-3:4`, `-2:3`
- **Flexible**: `-5:4`, `-4:5`

The bot will respond naturally based on what the AI generates:
- **Text responses** when the AI provides text
- **Image responses** when the AI generates images  
- **Both text and images** when the AI provides both

When you mention the bot in a reply to another message, it will automatically include any images from the original message in addition to any images you attach to your reply. Text from the original message is ignored.

### Available Commands

**Text Commands (use with `!` prefix):**
- `!help` - Show help information

**Slash Commands (use with `/` prefix):**
- `/help` - Show help information
- `/avatar` - Transform your avatar with themed templates
- `/connect` - Join your voice channel for speech-to-speech AI interaction
- `/disconnect` - Disconnect from voice channel
- `/usage` - Show token usage statistics (elevated users only)
- `/log` - Get the most recent log file (elevated users only)
- `/reset` - Reset cycle image usage for a user (elevated users only)
- `/tier` - Assign a tier to a user (elevated users only)
- `/meme` - Generate a nonsensical meme using OpenAI

**Note:** Elevated users are configured via the `ELEVATED_USERS` environment variable (comma-separated Discord user IDs).

### Voice Bot (Speech-to-Speech)

The bot supports full-duplex speech interaction using OpenAI's GPT-4o Realtime API:

**How to use:**
1. Join a voice channel in your Discord server
2. Use `/connect` to have the bot join your voice channel
3. Speak naturally - the bot will listen and respond in real-time
4. Use `/disconnect` when you're done

**System Requirements:**
- **FFmpeg**: Required for audio processing
  ```bash
  # Ubuntu/Debian
  sudo apt-get update && sudo apt-get install -y ffmpeg
  
  # macOS
  brew install ffmpeg
  
  # Windows
  # Download from https://ffmpeg.org/download.html
  ```
- **Opus Library**: Required for Discord voice support
  ```bash
  # Ubuntu/Debian
  sudo apt-get install -y libopus0
  
  # macOS (usually bundled with discord.py)
  brew install opus
  ```

**Python Requirements:**
- OpenAI API key with access to the GPT-4o Realtime API
- `discord-ext-voice-recv` extension (included in requirements.txt) for voice input

**Discord Permissions:**
- Bot needs "Connect" and "Speak" permissions in the voice channel

**Features:**
- Full-duplex voice interaction (listen and speak simultaneously)
- Real-time OpenAI Realtime API integration
- Audio response playback into voice channel
- Server-side voice activity detection (VAD) configured
- Automatic audio format conversion (Discord 48kHz stereo ↔ OpenAI 24kHz mono)
- Proper session management and cleanup

**Docker Deployment:**
If running in Docker, add these to your Dockerfile:
```dockerfile
RUN apt-get update && apt-get install -y ffmpeg libopus0
```

### Usage Tracking & Tier System

The bot automatically tracks token usage for each Discord user:
- **Total tokens**: Combined input and output tokens
- **Images generated**: Number of images created (limited based on user tier)
- **User tier**: Rate limit tier assigned to the user

**User Tiers:**

The bot supports a flexible tier system for rate limiting:

- **Standard** (default): 3 cycling charges
- **Limited**: 2 cycling charges  
- **Strict**: 1 cycling charge
- **Extra**: 5 cycling charges
- **Unlimited**: No rate limits (never rate limited)

**Image Generation Limits:**
- Each user has a certain number of usage charges based on their tier (default: standard with 3 charges)
- Each usage charge has its own independent 8-hour timer
- Each usage charge expires 8 hours after it was used (based on server time when the image was generated)
- **You can still generate images as long as at least one slot is available**
- Rate limiting only occurs when all usage slots are full (no slots available)
- Timer Example: If you generate images at 2:00 PM, 3:00 PM, and 4:00 PM, the first slot becomes available 8 hours later at 10:00 PM, the second slot at 11:00 PM, and the third slot at 12:00 AM
- Elevated users have unlimited image generation regardless of tier
- Unlimited tier users are never rate limited

**Managing User Tiers:**

Elevated users can assign tiers using the `/tier` command:
```
/tier @user standard    # Set user to standard tier (3 charges)
/tier @user limited     # Set user to limited tier (2 charges)
/tier @user strict      # Set user to strict tier (1 charge)
/tier @user extra       # Set user to extra tier (5 charges)
/tier @user unlimited   # Set user to unlimited tier (never rate limited)
```

Example:
```
/tier @Zetic extra
```
This sets Zetic to the extra tier with 5 cycling charges.

Use `/usage` to view condensed statistics showing total tokens, images, and tier for all users (elevated users only). The output is sent as text messages and automatically split if needed for large user lists. Data is stored locally in JSON format with thread-safe operations for concurrent access.

### Bot Snitching

The bot has a playful "snitching" feature that tracks messages mentioning the bot and calls out users who delete them:

**How it works:**
- When you mention the bot in a message, the bot tracks that message for **8 hours**
- If you delete the message within those 8 hours, the bot will send a message in the same channel calling you out
- The snitching message format: *"Oh @user I thought your idea to [your original text] was interesting though..."*
- The bot mention is removed from the quoted text for readability
- Messages older than 8 hours are automatically removed from tracking

**Example:**
1. User posts: `@Nano Banana create a dancing banana`
2. User deletes the message
3. Bot responds: *"Oh @User I thought your idea to create a dancing banana was interesting though..."*

This feature encourages users to own their creative (or silly) prompts! 😄

### Logging

The bot maintains daily log files in the `logs/` directory:
- **Daily rotation**: New log file created each day (format: `bot-YYYY-MM-DD.log`)
- **Persistent logging**: Bot continues writing to the same day's log file if restarted
- **Log retrieval**: Elevated users can download the most recent log file using `/log`

All bot activities, errors, and user interactions are logged for monitoring and debugging purposes.

## 🛠️ Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DISCORD_TOKEN` | Your Discord bot token | Yes |
| `GOOGLE_API_KEY` | Your Google GenAI API key | Yes |
| `OPENAI_API_KEY` | Your OpenAI API key (for meme generation and voice bot) | Yes |
| `OPENAI_REALTIME_MODEL` | OpenAI Realtime model for voice bot (default: `gpt-4o-realtime-preview-2024-12-17`) | No |
| `ELEVATED_USERS` | Comma-separated Discord user IDs with elevated permissions | No |

### Bot Configuration

The bot can be configured in `config.py`:

- `MAX_IMAGE_SIZE`: Maximum size per image (default: 8MB)
- `MAX_IMAGES`: Maximum number of images to process (default: 10)
- `GENERATED_IMAGES_DIR`: Directory to store generated images

## 🔧 Development

### Project Structure

```
nanobanana/
├── bot.py              # Main Discord bot implementation
├── config.py           # Configuration management
├── model_interface.py  # Unified AI model interface (Gemini, GPT, Chat)
├── voice_handler.py    # Voice bot and OpenAI Realtime API integration
├── image_utils.py      # Image processing utilities
├── usage_tracker.py    # User usage tracking system
├── log_manager.py      # Logging system management
├── main.py             # Entry point
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
└── README.md           # This file
```

### API Integration

The bot uses multiple AI providers:

**Google Gemini (primary generation):**
- **Text-to-Image**: Creates images from text descriptions
- **Image-to-Image**: Transforms existing images based on prompts

**OpenAI (meme generation and voice bot):**
- **Meme Creation**: Generates nonsensical memes using DALL-E 3
- **Voice Bot**: Full-duplex speech interaction using GPT-4o Realtime API

## 📝 Examples

### Text Generation
```
@Nano Banana Create a picture of a nano banana dish in a fancy restaurant with a Gemini theme
```

### Image Transformation
```
@Nano Banana Transform this into a magical fairy tale scene
```
*(with image attached)*

### Multi-Image Processing
```
@Nano Banana Combine these characters in an epic battle scene
```
*(with multiple images attached)*

### Aspect Ratio Control
```
@Nano Banana Create a cinematic scene of a nano banana -21:9
@Nano Banana Make this portrait style -9:16
@Nano Banana Generate a square avatar -1:1
```

### Meme Generation
```
/meme
```
*Generates a nonsensical meme using OpenAI*

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is open source. See the repository for license details.
