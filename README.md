# 🍌 Nano Banana Discord Bot

A Discord bot that generates stunning images using Google's Gemini AI image generation capabilities. The bot can create images from text prompts, transform existing images, and even stitch multiple images together for enhanced AI generation.

## ✨ Features

- **Text-to-Image Generation**: Create images from descriptive text prompts
- **Image-to-Image Transformation**: Transform uploaded images using AI
- **Multi-Image Stitching**: Combine multiple images and generate new content
- **Discord Integration**: Simple mention-based interaction
- **Smart Processing**: Automatic image resizing and optimization

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
```bash
python main.py
```

## 🎯 Usage

### Basic Commands

- **Mention the bot** with a text prompt to generate an image:
  ```
  @Nano Banana Create a nano banana floating in space
  ```

- **Attach images** with your mention to transform them:
  ```
  @Nano Banana Make this cat look cyberpunk (with image attached)
  ```

- **Multiple images** will be stitched together automatically:
  ```
  @Nano Banana Combine these into a fantasy scene (with multiple images)
  ```

### Available Commands

- `!info` - Show help information
- `!status` - Display bot status

## 🛠️ Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DISCORD_TOKEN` | Your Discord bot token | Yes |
| `GOOGLE_API_KEY` | Your Google GenAI API key | Yes |

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
├── genai_client.py     # Google GenAI integration
├── image_utils.py      # Image processing utilities
├── main.py             # Entry point
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
└── README.md           # This file
```

### API Integration

The bot uses Google's Gemini 2.5 Flash Image Preview model for generation:

- **Text-to-Image**: Creates images from text descriptions
- **Image-to-Image**: Transforms existing images based on prompts

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

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project is open source. See the repository for license details.
