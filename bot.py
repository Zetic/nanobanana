import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import io
import os
from datetime import datetime
from typing import List, Dict, Any

import config
from image_utils import download_image
from genai_client import ImageGenerator
from openai_client import OpenAIImageGenerator
from usage_tracker import usage_tracker

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
bot = commands.Bot(command_prefix=config.COMMAND_PREFIX, intents=intents, help_command=None)

# Initialize image generator (will be created when first used)
image_generator = None
openai_image_generator = None

def get_image_generator():
    """Get or create the image generator instance."""
    global image_generator
    if image_generator is None:
        image_generator = ImageGenerator()
    return image_generator

def get_openai_image_generator():
    """Get or create the OpenAI image generator instance."""
    global openai_image_generator
    if openai_image_generator is None:
        openai_image_generator = OpenAIImageGenerator()
    return openai_image_generator

@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Bot is in {len(bot.guilds)} guilds')
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f'Synced {len(synced)} slash commands')
    except Exception as e:
        logger.error(f'Failed to sync slash commands: {e}')

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

def split_long_message(content: str, max_length: int = 1800) -> List[str]:
    """
    Split a long message into chunks that fit within Discord's character limits.
    
    Args:
        content: The content to split
        max_length: Maximum length per chunk (default 1800 for Discord's 2000 char limit with safety margin)
    
    Returns:
        List of message chunks
    """
    if not content or len(content) <= max_length:
        return [content] if content else []
    
    chunks = []
    remaining = content
    
    while len(remaining) > max_length:
        # Find the best split point within the limit
        split_point = max_length
        
        # Try to split at paragraph boundaries first (double newlines)
        paragraph_split = remaining.rfind('\n\n', 0, max_length)
        if paragraph_split > max_length // 2:  # Don't split too early
            split_point = paragraph_split + 2
        else:
            # Try to split at sentence boundaries
            sentence_split = max(
                remaining.rfind('. ', 0, max_length),
                remaining.rfind('! ', 0, max_length),
                remaining.rfind('? ', 0, max_length)
            )
            if sentence_split > max_length // 2:
                split_point = sentence_split + 2
            else:
                # Try to split at word boundaries
                word_split = remaining.rfind(' ', 0, max_length)
                if word_split > max_length // 2:
                    split_point = word_split + 1
                else:
                    # Force split at character boundary
                    split_point = max_length
        
        # Extract the chunk and add it
        chunk = remaining[:split_point].strip()
        if chunk:
            chunks.append(chunk)
        
        # Move to the next part
        remaining = remaining[split_point:].strip()
    
    # Add the final chunk if there's remaining content
    if remaining:
        chunks.append(remaining)
    
    return chunks

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
        
        # If this is a reply message, download images from the original message (ignore text)
        if message.reference and message.reference.message_id:
            try:
                # Fetch the original message being replied to
                original_message = await message.channel.fetch_message(message.reference.message_id)
                
                # Download images from the original message (text is ignored as per issue requirements)
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
        await process_generation_request(response_message, text_content, images, message.author)
            
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

async def process_generation_request(response_message, text_content: str, images: List, user):
    """Process the generation request and edit the response message with the result."""
    try:
        # Check if user can generate images
        can_generate_images = usage_tracker.can_generate_image(user.id)
        
        # Generate based on available inputs and rate limit status
        generated_image = None
        genai_text_response = None
        usage_metadata = None
        
        if not can_generate_images:
            # User is rate limited for images - use text-only fallback
            daily_count = usage_tracker.get_daily_image_count(user.id)
            logger.info(f"User {user.id} is rate limited for images ({daily_count}/{config.DAILY_IMAGE_LIMIT}), using text-only fallback")
            
            # Generate text-only response regardless of input type
            if text_content.strip() or images:
                # Use text content if available, otherwise provide generic prompt for image analysis
                prompt = text_content.strip() if text_content.strip() else "Please provide a text description or analysis of the provided content."
                generated_image, genai_text_response, usage_metadata = await get_image_generator().generate_text_only_response(prompt, images)
                
                # Add rate limit notice to the response
                if genai_text_response:
                    genai_text_response = f"⚠️ *Image generation limit reached ({daily_count}/{config.DAILY_IMAGE_LIMIT} today). Providing text-only response.*\n\n{genai_text_response}"
                else:
                    genai_text_response = f"⚠️ **Daily image limit reached!** You've generated {daily_count}/{config.DAILY_IMAGE_LIMIT} images today. Here's a text-only response instead:"
            else:
                # No content provided
                await response_message.edit(content="Please provide some text or attach an image for me to work with!")
                return
        else:
            # User can generate images - use normal flow
            if images and text_content.strip():
                # Text + Image(s) case
                if len(images) == 1:
                    generated_image, genai_text_response, usage_metadata = await get_image_generator().generate_image_from_text_and_image(
                        text_content, images[0]
                    )
                else:
                    generated_image, genai_text_response, usage_metadata = await get_image_generator().generate_image_from_text_and_images(
                        text_content, images
                    )
            elif images:
                # Image(s) only case - no text provided
                if len(images) == 1:
                    generated_image, genai_text_response, usage_metadata = await get_image_generator().generate_image_from_image_only(images[0])
                else:
                    generated_image, genai_text_response, usage_metadata = await get_image_generator().generate_image_from_images_only(images)
            elif text_content.strip():
                # Text only case
                generated_image, genai_text_response, usage_metadata = await get_image_generator().generate_image_from_text(text_content)
            else:
                # No content provided
                await response_message.edit(content="Please provide some text or attach an image for me to work with!")
                return
        
        # Track usage if we have metadata and a user
        if usage_metadata and user and not user.bot:  # Don't track bot usage
            try:
                prompt_tokens = usage_metadata.get("prompt_token_count", 0)
                output_tokens = usage_metadata.get("candidates_token_count", 0)
                total_tokens = usage_metadata.get("total_token_count", 0)
                images_generated = 1 if generated_image else 0
                
                usage_tracker.record_usage(
                    user_id=user.id,
                    username=user.display_name or user.name,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    images_generated=images_generated
                )
            except Exception as e:
                logger.warning(f"Could not track usage: {e}")
        
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
            
            # Handle long messages by splitting them into chunks
            if content:
                message_chunks = split_long_message(content, max_length=1800)
                
                # Edit the original response with the first chunk (and any files)
                first_chunk = message_chunks[0] if message_chunks else None
                await response_message.edit(content=first_chunk, attachments=files)
                
                # Send any additional chunks as follow-up messages
                for chunk in message_chunks[1:]:
                    await response_message.channel.send(content=chunk)
            else:
                # Only files, no content
                await response_message.edit(content=None, attachments=files)
        else:
            await response_message.edit(content="I wasn't able to generate anything from your request. Please try again with different input.")
            
    except Exception as e:
        logger.error(f"Error processing generation request: {e}")
        await response_message.edit(content="An error occurred while generating. Please try again.")



# Slash command versions
@bot.tree.command(name='help', description='Show help information')
async def help_slash(interaction: discord.Interaction):
    """Show help information (slash command)."""
    # Use interaction.client.user for safety and provide fallbacks
    bot_user = interaction.client.user
    bot_name = bot_user.display_name if bot_user else "Nano Banana"
    bot_mention = bot_user.mention if bot_user else "@Nano Banana"
    
    help_text = f"""**{bot_name} - Help**

I'm a bot that generates images and text using Google's AI!

**How to use:**
Just mention me ({bot_mention}) in a message with your prompt and optionally attach images!

**Examples:**
• `{bot_mention} Create a nano banana in space`
• `{bot_mention} Make this cat magical` (with image attached)
• `{bot_mention} Transform this into cyberpunk style` (with multiple images)
• Reply to a message with images: `{bot_mention} make this change` (uses images and text from original message)

**Features:**
• Text-to-image generation
• Image-to-image transformation  
• Multiple image processing
• Reply message support (uses images from original message, ignores text)
• Natural text responses
• Powered by Google Gemini AI

**Slash Commands:**
• `/help` - Show this help message
• `/usage` - Show token usage statistics  
• `/meme` - Generate a nonsensical meme using OpenAI"""
    
    await interaction.response.send_message(help_text)

@bot.tree.command(name='usage', description='Show token usage statistics')
async def usage_slash(interaction: discord.Interaction):
    """Show token usage statistics (slash command)."""
    try:
        # Get usage statistics
        users_list = usage_tracker.get_usage_stats()
        total_stats = usage_tracker.get_total_stats()
        
        if not users_list:
            await interaction.response.send_message("No usage data available yet. Start using the bot to generate some statistics!")
            return
        
        # Build the response message
        usage_text = "**🍌 Token Usage Statistics**\n\n"
        
        # Add overall stats
        usage_text += f"**📊 Overall Statistics:**\n"
        usage_text += f"• Total Users: {total_stats['total_users']}\n"
        usage_text += f"• Total Requests: {total_stats['total_requests']}\n"
        usage_text += f"• Total Input Tokens: {total_stats['total_prompt_tokens']:,}\n"
        usage_text += f"• Total Output Tokens: {total_stats['total_output_tokens']:,}\n"
        usage_text += f"• Total Tokens: {total_stats['total_tokens']:,}\n"
        usage_text += f"• Images Generated: {total_stats['total_images_generated']}\n\n"
        
        # Add top users (limit to top 10 to avoid message length issues)
        usage_text += "**👑 Top Users by Output Tokens:**\n"
        
        top_users = users_list[:10]  # Limit to top 10
        for i, (user_id, user_data) in enumerate(top_users, 1):
            username = user_data.get('username', 'Unknown User')
            output_tokens = user_data.get('total_output_tokens', 0)
            input_tokens = user_data.get('total_prompt_tokens', 0)
            total_tokens = user_data.get('total_tokens', 0)
            images = user_data.get('images_generated', 0)
            requests = user_data.get('requests_count', 0)
            
            usage_text += f"{i}. **{username}**\n"
            usage_text += f"   • Output Tokens: {output_tokens:,}\n"
            usage_text += f"   • Input Tokens: {input_tokens:,}\n"
            usage_text += f"   • Total Tokens: {total_tokens:,}\n"
            usage_text += f"   • Images: {images} | Requests: {requests}\n\n"
        
        if len(users_list) > 10:
            usage_text += f"... and {len(users_list) - 10} more users.\n"
        
        # Handle long messages by splitting them into chunks
        message_chunks = split_long_message(usage_text, max_length=1800)
        
        # Send the first chunk as the response
        first_chunk = message_chunks[0] if message_chunks else usage_text
        await interaction.response.send_message(first_chunk)
        
        # Send any additional chunks as follow-up messages
        for chunk in message_chunks[1:]:
            await interaction.followup.send(chunk)
        
    except Exception as e:
        logger.error(f"Error getting usage statistics: {e}")
        await interaction.response.send_message("An error occurred while retrieving usage statistics. Please try again.")

@bot.tree.command(name='meme', description='Generate a nonsensical meme using OpenAI')
async def meme_slash(interaction: discord.Interaction):
    """Generate a meme using OpenAI (slash command)."""
    try:
        # Check if user can generate images (rate limiting)
        can_generate_images = usage_tracker.can_generate_image(interaction.user.id)
        
        if not can_generate_images:
            daily_count = usage_tracker.get_daily_image_count(interaction.user.id)
            await interaction.response.send_message(
                f"You've reached your daily image generation limit ({daily_count}/{config.DAILY_IMAGE_LIMIT}). "
                "Try again tomorrow!"
            )
            return
        
        # Send initial response
        await interaction.response.send_message("🎭 Generating a nonsensical meme... This might take a moment!")
        
        # Generate the meme
        try:
            generated_image = await get_openai_image_generator().generate_meme()
            
            if generated_image:
                # Save image to send as attachment
                image_buffer = io.BytesIO()
                generated_image.save(image_buffer, format='PNG')
                image_buffer.seek(0)
                
                # Create Discord file
                discord_file = discord.File(image_buffer, filename="meme.png")
                
                # Record usage (1 image generated)
                usage_tracker.record_usage(
                    user_id=interaction.user.id,
                    username=interaction.user.display_name or interaction.user.name,
                    prompt_tokens=0,  # OpenAI doesn't provide detailed token info for DALL-E
                    output_tokens=0,
                    total_tokens=0,
                    images_generated=1
                )
                
                await interaction.edit_original_response(
                    content="🎭 Here's your nonsensical meme!",
                    attachments=[discord_file]
                )
            else:
                await interaction.edit_original_response(
                    content="Sorry, I couldn't generate a meme right now. Please try again later."
                )
                
        except Exception as e:
            logger.error(f"Error generating meme: {e}")
            await interaction.edit_original_response(
                content="An error occurred while generating the meme. Please try again."
            )
            
    except Exception as e:
        logger.error(f"Error in meme command: {e}")
        try:
            await interaction.response.send_message("An error occurred. Please try again.")
        except:
            # If we can't send initial response, try to edit it
            try:
                await interaction.edit_original_response(content="An error occurred. Please try again.")
            except:
                pass



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