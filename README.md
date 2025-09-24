# 🍌 Nano Banana Discord Bot

A Discord bot that generates images and text using Google's Gemini AI and OpenAI. The bot returns natural responses from the AI - text when the AI responds with text, images when it responds with images, or both when it responds with both.

## ✨ Features

- **Text-to-Image Generation**: Create images from descriptive text prompts
- **Image-to-Image Transformation**: Transform uploaded images using AI  
- **Multi-Image Processing**: Process multiple images simultaneously
- **Meme Generation**: Generate nonsensical memes using OpenAI
- **Reply Message Support**: Automatically uses images from the original message when mentioned in a reply (text from original message is ignored)
- **Natural API Responses**: Returns whatever the AI naturally generates (text, images, or both)
- **Discord Integration**: Simple mention-based interaction
- **Smart Processing**: Automatic image resizing and optimization
- **Usage Tracking**: Track token usage per user with detailed statistics

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Discord Bot Token
- Google GenAI API Key

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
- `/usage` - Show token usage statistics (elevated users only) - returns file
- `/log` - Get the most recent log file (elevated users only)
- `/reset` - Reset cycle image usage for a user (elevated users only)
- `/meme` - Generate a nonsensical meme using OpenAI

**Note:** Elevated users are configured via the `ELEVATED_USERS` environment variable (comma-separated Discord user IDs).

### Usage Tracking

The bot automatically tracks token usage for each Discord user:
- **Input tokens**: Tokens used for prompts and image inputs
- **Output tokens**: Tokens used for generated responses  
- **Total tokens**: Combined input and output tokens
- **Images generated**: Number of images created (limited to 15 per cycle)
- **Request count**: Total number of requests made

**Image Generation Limits:**
- Users can generate up to **15 images per cycle**
- Cycles reset at **noon (12:00 PM)** and **midnight (00:00 AM)**
- Morning cycle: 00:00 - 11:59
- Afternoon cycle: 12:00 - 23:59
- Elevated users have unlimited image generation

Use `/usage` to view statistics sorted by output token usage (elevated users only). Data is stored locally in JSON format with thread-safe operations for concurrent access.

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
| `OPENAI_API_KEY` | Your OpenAI API key (for meme generation) | Yes |
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

**OpenAI (meme generation):**
- **Meme Creation**: Generates nonsensical memes using DALL-E 3

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
