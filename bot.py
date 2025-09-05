import discord
from discord.ext import commands
import logging
import asyncio
import io
import os
from datetime import datetime
from typing import List, Dict, Any

import config
from image_utils import download_image, create_stitched_image
from genai_client import ImageGenerator

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# All UI classes removed - bot now returns natural API responses directly

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=config.COMMAND_PREFIX, intents=intents)

# Initialize image generator (will be created when first used)
image_generator = None

def get_image_generator():
    """Get or create the image generator instance."""
    global image_generator
    if image_generator is None:
        image_generator = ImageGenerator()
    return image_generator

@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Bot is in {len(bot.guilds)} guilds')

@bot.event
async def on_message(message):
    """Handle incoming messages."""
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Handle commands first
    await bot.process_commands(message)
    
    # Check if bot is directly mentioned in the message content (not just in a reply)
    if is_directly_mentioned(message.content, bot.user.id):
        await handle_generation_request(message)

def is_directly_mentioned(message_content, bot_user_id):
    """
    Check if the bot is directly mentioned in the message content
    (not just mentioned in a replied-to message)
    """
    # Standard mention format
    standard_mention = f'<@{bot_user_id}>'
    # Nickname mention format  
    nickname_mention = f'<@!{bot_user_id}>'
    
    return standard_mention in message_content or nickname_mention in message_content

async def extract_text_from_message(message):
    """Extract text content from a message, removing bot mentions."""
    content = message.content
    
    # Remove bot mention
    content = content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '')
    
    # Clean up whitespace
    content = content.strip()
    
    return content

async def handle_generation_request(message):
    """Handle image generation request when bot is mentioned."""
    try:
        # Send immediate response
        response_message = await message.reply("Generating response...")
        
        # Extract text content and download images
        text_content = await extract_text_from_message(message)
        images = []
        
        # Download attached images from the mentioning message
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                if attachment.size > config.MAX_IMAGE_SIZE:
                    await response_message.edit(content=f"Image {attachment.filename} is too large. Maximum size is {config.MAX_IMAGE_SIZE // (1024*1024)}MB.")
                    return
                
                image = await download_image(attachment.url)
                if image:
                    images.append(image)
                    logger.info(f"Downloaded image: {attachment.filename}")
        
        # If this is a reply message, also download images and extract text from the original message
        if message.reference and message.reference.message_id:
            try:
                # Fetch the original message being replied to
                original_message = await message.channel.fetch_message(message.reference.message_id)
                
                # Extract text content from the original message
                original_text_content = await extract_text_from_message(original_message)
                if original_text_content.strip():
                    # Combine original message text with reply text
                    if text_content.strip():
                        text_content = f"{text_content} {original_text_content}"
                    else:
                        text_content = original_text_content
                    logger.info(f"Combined text from original message: {original_text_content}")
                
                # Download images from the original message
                for attachment in original_message.attachments:
                    if attachment.content_type and attachment.content_type.startswith('image/'):
                        if attachment.size > config.MAX_IMAGE_SIZE:
                            logger.warning(f"Skipping large image from original message: {attachment.filename}")
                            continue
                        
                        image = await download_image(attachment.url)
                        if image:
                            images.append(image)
                            logger.info(f"Downloaded image from original message: {attachment.filename}")
                            
            except Exception as e:
                logger.error(f"Error fetching original message: {e}")
                # Continue processing even if we can't fetch the original message
        
        # Process based on inputs
        await process_generation_request(response_message, text_content, images)
            
    except Exception as e:
        logger.error(f"Error handling generation request: {e}")
        try:
            # Try to edit the response message if it exists, otherwise reply to original
            if 'response_message' in locals():
                await response_message.edit(content="An error occurred while processing your request. Please try again.")
            else:
                await message.reply("An error occurred while processing your request. Please try again.")
        except:
            pass

async def process_generation_request(response_message, text_content: str, images: List):
    """Process the generation request and edit the response message with the result."""
    try:
        # Generate based on available inputs
        generated_image = None
        genai_text_response = None
        
        if images and text_content.strip():
            # Text + Image(s) case
            if len(images) == 1:
                generated_image, genai_text_response = await get_image_generator().generate_image_from_text_and_image(
                    text_content, images[0]
                )
            else:
                generated_image, genai_text_response = await get_image_generator().generate_image_from_text_and_images(
                    text_content, images
                )
        elif images:
            # Image(s) only case - no text provided
            if len(images) == 1:
                generated_image, genai_text_response = await get_image_generator().generate_image_from_image_only(images[0])
            else:
                generated_image, genai_text_response = await get_image_generator().generate_image_from_images_only(images)
        elif text_content.strip():
            # Text only case
            generated_image, genai_text_response = await get_image_generator().generate_image_from_text(text_content)
        else:
            # No content provided
            await response_message.edit(content="Please provide some text or attach an image for me to work with!")
            return
        
        # Send natural response based on what the API returned
        responses = []
        
        # Add text response if available
        if genai_text_response and genai_text_response.strip():
            responses.append(genai_text_response)
        
        # Add image if available
        files = []
        if generated_image:
            # Save and send the image
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"generated_{timestamp}.png"
            
            # Save to disk
            filepath = os.path.join(config.GENERATED_IMAGES_DIR, filename)
            generated_image.save(filepath)
            
            # Save to buffer for Discord
            img_buffer = io.BytesIO()
            generated_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            files.append(discord.File(img_buffer, filename=filename))
        
        # Edit response message with the final result
        if responses or files:
            content = "\n".join(responses) if responses else None
            await response_message.edit(content=content, attachments=files)
        else:
            await response_message.edit(content="I wasn't able to generate anything from your request. Please try again with different input.")
            
    except Exception as e:
        logger.error(f"Error processing generation request: {e}")
        await response_message.edit(content="An error occurred while generating. Please try again.")

@bot.command(name='info')
async def info_command(ctx):
    """Show help information."""
    help_text = f"""**{bot.user.display_name} - Help**

I'm a bot that generates images and text using Google's AI!

**How to use:**
Just mention me ({bot.user.mention}) in a message with your prompt and optionally attach images!

**Examples:**
• `{bot.user.mention} Create a nano banana in space`
• `{bot.user.mention} Make this cat magical` (with image attached)
• `{bot.user.mention} Transform this into cyberpunk style` (with multiple images)
• Reply to a message with images: `{bot.user.mention} make this change` (uses images and text from original message)

**Features:**
• Text-to-image generation
• Image-to-image transformation  
• Multiple image processing
• Reply message support (uses images and text from original message)
• Natural text responses
• Powered by Google Gemini AI"""
    
    await ctx.send(help_text)

@bot.command(name='status')
async def status_command(ctx):
    """Show bot status."""
    status_text = f"""**Bot Status**

**Status:** Online
**Guilds:** {len(bot.guilds)}
**Latency:** {round(bot.latency * 1000)}ms"""
    
    await ctx.send(status_text)

def main():
    """Main function to run the bot."""
    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not found in environment variables")
        return
    
    if not config.GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not found in environment variables")
        return
    
    logger.info("Starting Discord Bot...")
    bot.run(config.DISCORD_TOKEN)

if __name__ == "__main__":
    main()