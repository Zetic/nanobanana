import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import io
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import config
from image_utils import download_image
from model_interface import get_model_generator
from usage_tracker import usage_tracker
from log_manager import log_manager

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
    
    # Check if message is from a DM channel and user is not elevated
    if is_dm_channel(message.channel) and not usage_tracker.is_elevated_user(message.author.id):
        # Don't respond to non-elevated users in DM channels
        logger.info(f"Blocked non-elevated user {message.author.id} from using bot in DM channel")
        return
    
    # Check if user has reached usage limit (only for non-elevated users)
    if not usage_tracker.is_elevated_user(message.author.id):
        has_limit, next_available = usage_tracker.has_reached_usage_limit(message.author.id)
        if has_limit:
            # Check if this message involves the bot (mention or command)
            bot_mentioned = is_directly_mentioned(message.content, bot.user.id)
            is_command = message.content.startswith(config.COMMAND_PREFIX)
            
            if bot_mentioned or is_command:
                # Send ephemeral message via DM (only that user sees it) and react with wilted_rose
                try:
                    await message.author.send("Zetic doesn't pay me enough to cover that request so try again later")
                except discord.Forbidden:
                    # If DM fails (user has DMs disabled), fall back to a reply that deletes quickly
                    logger.warning(f"Could not DM user {message.author.id}, using reply instead")
                    await message.reply("Zetic doesn't pay me enough to cover that request so try again later", 
                                      delete_after=10)
                except Exception as e:
                    logger.error(f"Error sending rate limit message to user {message.author.id}: {e}")
                
                try:
                    await message.add_reaction("🥀")  # wilted_rose emoji
                except Exception as e:
                    logger.warning(f"Failed to add reaction: {e}")
                logger.info(f"Blocked user {message.author.id} from using bot - usage limit reached")
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

def is_dm_channel(channel) -> bool:
    """
    Check if a channel is a DM (Direct Message) channel.
    Returns True for DMChannel and GroupChannel.
    """
    return isinstance(channel, (discord.DMChannel, discord.GroupChannel))

async def check_usage_limit_and_respond(interaction: discord.Interaction) -> bool:
    """
    Check if user has reached usage limit and send appropriate message.
    Returns True if user should be blocked (limit reached), False if they can proceed.
    """
    # Elevated users are never blocked
    if usage_tracker.is_elevated_user(interaction.user.id):
        return False
    
    # Check if user has reached limit
    has_limit, next_available = usage_tracker.has_reached_usage_limit(interaction.user.id)
    if has_limit:
        await interaction.response.send_message(
            "Zetic doesn't pay me enough to cover that request so try again later",
            ephemeral=True
        )
        logger.info(f"Blocked user {interaction.user.id} from using slash command - usage limit reached")
        return True
    
    return False


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

def extract_aspect_ratio(text: str) -> Tuple[Optional[str], str]:
    """
    Extract aspect ratio from text in the format -X:Y (e.g., -16:9).
    Only accepts specific valid aspect ratios.
    
    Args:
        text: The input text to search for aspect ratio
        
    Returns:
        Tuple of (aspect_ratio, cleaned_text) where aspect_ratio is None if not found
        or invalid, and cleaned_text has the aspect ratio pattern removed.
    """
    # Supported aspect ratios as specified in the issue
    VALID_ASPECT_RATIOS = {
        '21:9', '16:9', '4:3', '3:2',  # Landscape
        '1:1',  # Square
        '9:16', '3:4', '2:3',  # Portrait
        '5:4', '4:5'  # Flexible
    }
    
    # Pattern to match -X:Y format where X and Y are numbers
    # Use word boundaries to avoid matching in the middle of text
    pattern = r'-(\d+:\d+)\b'
    
    match = re.search(pattern, text)
    
    if match:
        aspect_ratio = match.group(1)
        # Only return if it's a valid aspect ratio
        if aspect_ratio in VALID_ASPECT_RATIOS:
            # Remove the aspect ratio pattern from the text
            cleaned_text = re.sub(pattern, '', text, count=1).strip()
            # Clean up any double spaces
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
            return aspect_ratio, cleaned_text
    
    # No valid aspect ratio found, return original text
    return None, text

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
        
        # Extract aspect ratio from text content
        aspect_ratio, text_content = extract_aspect_ratio(text_content)
        if aspect_ratio:
            logger.info(f"Aspect ratio detected: {aspect_ratio}")
        
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
        await process_generation_request(response_message, text_content, images, message.author, aspect_ratio)
            
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

async def process_generation_request(response_message, text_content: str, images: List, user, aspect_ratio: Optional[str] = None):
    """Process the generation request and edit the response message with the result."""
    try:
        # Get user's model preference
        user_model = usage_tracker.get_user_model_preference(user.id)
        logger.info(f"User {user.id} model preference: {user_model}")
        
        # Get the appropriate model generator
        generator = get_model_generator(user_model)
        
        # Generate based on available inputs, rate limit status, and user's model preference
        generated_image = None
        genai_text_response = None
        usage_metadata = None
        
        # Create streaming callback for image-generating models that support it (gpt)
        async def streaming_callback(message_text, partial_image=None):
            """Update Discord message with streaming progress and partial images."""
            try:
                if partial_image:
                    # Send partial image to Discord instead of just text
                    # Save partial image to buffer for Discord
                    img_buffer = io.BytesIO()
                    partial_image.save(img_buffer, format='PNG')
                    img_buffer.seek(0)
                    
                    # Create Discord file from buffer
                    import discord
                    discord_file = discord.File(img_buffer, filename=f"partial_image.png")
                    
                    # Update message with partial image
                    await response_message.edit(content=message_text, attachments=[discord_file])
                else:
                    # Fallback to text-only update
                    await response_message.edit(content=message_text)
            except Exception as e:
                logger.warning(f"Failed to update streaming message: {e}")
                # Fallback to text-only if image fails
                try:
                    await response_message.edit(content=message_text)
                except Exception as e2:
                    logger.warning(f"Failed to update with text fallback: {e2}")
        
        # User can generate images or is using chat model
        if images and text_content.strip():
            # Text + Image(s) case
            if len(images) == 1:
                generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_text_and_image(
                    text_content, images[0], streaming_callback if user_model == "gpt" else None, aspect_ratio
                )
            else:
                # For multiple images, pass first as primary and rest as additional
                generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_text_and_image(
                    text_content, images[0], streaming_callback if user_model == "gpt" else None, aspect_ratio, images[1:]
                )
        elif images:
            # Image(s) only case - no text provided
            if len(images) == 1:
                generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_image_only(
                    images[0], streaming_callback if user_model == "gpt" else None, aspect_ratio
                )
            else:
                # For multiple images, pass first as primary and rest as additional
                generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_image_only(
                    images[0], streaming_callback if user_model == "gpt" else None, aspect_ratio, images[1:]
                )
        elif text_content.strip():
            # Text only case
            generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_text(
                text_content, streaming_callback if user_model == "gpt" else None, aspect_ratio
            )
        else:
            # No content provided
            await response_message.edit(content="Please provide some text or attach an image for me to work with!")
            return
        
        # Track usage if we have metadata and a user
        send_limit_warning = False
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
                
                # Check if this usage filled both slots (and they're not elevated)
                available_after = usage_tracker._get_available_usage_slots(user.id)
                if (images_generated > 0 and 
                    not usage_tracker.is_elevated_user(user.id) and
                    available_after == 0):
                    send_limit_warning = True
                    
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
        
        # Send warning message if user just hit their limit
        if send_limit_warning:
            try:
                # Get next available time
                next_available = usage_tracker._get_next_available_time(user.id)
                
                if next_available:
                    next_timestamp = int(next_available.timestamp())
                    warning_msg = (f"⚠️ You've used both of your image generation slots. "
                                 f"Your next slot will be available <t:{next_timestamp}:R>.")
                else:
                    warning_msg = (f"⚠️ You've used both of your image generation slots. "
                                 f"Each slot resets 8 hours after use.")
                
                # Send as a message that auto-deletes
                if hasattr(response_message, 'channel'):
                    await response_message.channel.send(warning_msg, delete_after=30)
            except Exception as e:
                logger.warning(f"Could not send limit warning: {e}")
            
    except Exception as e:
        logger.error(f"Error processing generation request: {e}")
        await response_message.edit(content="An error occurred while generating. Please try again.")



# Slash command versions
@bot.tree.command(name='help', description='Show help information')
async def help_slash(interaction: discord.Interaction):
    """Show help information (slash command)."""
    # Check if interaction is from a DM channel and user is not elevated
    if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
        await interaction.response.send_message(
            "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
            ephemeral=True
        )
        logger.info(f"Blocked non-elevated user {interaction.user.id} from using /help in DM channel")
        return
    
    # Check usage limit
    if await check_usage_limit_and_respond(interaction):
        return
    
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
• `{bot_mention} Create a landscape photo -16:9` (specify aspect ratio)
• Reply to a message with images: `{bot_mention} make this change` (uses images and text from original message)

**Features:**
• Text-to-image generation
• Image-to-image transformation  
• Multiple image processing
• Aspect ratio control (use `-16:9`, `-21:9`, `-4:3`, `-1:1`, `-9:16`, etc.)
• Reply message support (uses images from original message, ignores text)
• Natural text responses
• Powered by Google Gemini AI

**Supported Aspect Ratios:**
• Landscape: `-21:9`, `-16:9`, `-4:3`, `-3:2`
• Square: `-1:1`
• Portrait: `-9:16`, `-3:4`, `-2:3`
• Flexible: `-5:4`, `-4:5`

**Slash Commands:**
• `/help` - Show this help message
• `/avatar` - Transform your avatar with themed templates (Halloween, etc.)
• `/model` - Switch between AI models (nanobanana, GPT-5, or chat)
• `/usage` - Show token usage statistics (elevated users only)
• `/log` - Get the most recent log file (elevated users only)
• `/reset` - Reset cycle image usage for a user (elevated users only)"""
    
    await interaction.response.send_message(help_text)

@bot.tree.command(name='usage', description='Show token usage statistics (elevated users only)')
async def usage_slash(interaction: discord.Interaction):
    """Show token usage statistics (slash command) - elevated users only."""
    try:
        # Check if interaction is from a DM channel and user is not elevated
        if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
                ephemeral=True
            )
            logger.info(f"Blocked non-elevated user {interaction.user.id} from using /usage in DM channel")
            return
        
        # Check if the command caller has elevated status
        if not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command. Only elevated users can view usage statistics.",
                ephemeral=True
            )
            return
        # Get usage statistics
        users_list = usage_tracker.get_usage_stats()
        total_stats = usage_tracker.get_total_stats()
        
        if not users_list:
            await interaction.response.send_message("No usage data available yet. Start using the bot to generate some statistics!")
            return
        
        # Build the condensed response message
        usage_text = "**🍌 Token Usage Statistics**\n\n"
        
        # Add overall stats (condensed)
        usage_text += f"**📊 Overall:**\n"
        usage_text += f"Total Users: {total_stats['total_users']} | "
        usage_text += f"Total Tokens: {total_stats['total_tokens']:,} | "
        usage_text += f"Images: {total_stats['total_images_generated']}\n\n"
        
        # Add all users with condensed info
        usage_text += "**👤 Users:**\n"
        for i, (user_id, user_data) in enumerate(users_list, 1):
            username = user_data.get('username', 'Unknown User')
            total_tokens = user_data.get('total_tokens', 0)
            images = user_data.get('images_generated', 0)
            
            # Get active usage count for this user (within 8-hour window)
            active_count = usage_tracker.get_daily_image_count(int(user_id))
            usage_rate = f"{active_count}/{config.DAILY_IMAGE_LIMIT}"
            
            usage_text += f"{i}. {username}: {total_tokens:,} tokens, {images} images, {usage_rate} active\n"
        
        # Split message into chunks if needed and send
        chunks = split_long_message(usage_text)
        
        # Send the first chunk as response
        await interaction.response.send_message(chunks[0], ephemeral=True)
        
        # Send remaining chunks as follow-ups
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)
        
    except Exception as e:
        logger.error(f"Error getting usage statistics: {e}")
        # Check if we've already responded
        if interaction.response.is_done():
            await interaction.followup.send("An error occurred while retrieving usage statistics. Please try again.", ephemeral=True)
        else:
            await interaction.response.send_message("An error occurred while retrieving usage statistics. Please try again.", ephemeral=True)

@bot.tree.command(name='log', description='Get the most recent log file (elevated users only)')
async def log_slash(interaction: discord.Interaction):
    """Get the most recent log file (slash command) - elevated users only."""
    try:
        # Check if interaction is from a DM channel and user is not elevated
        if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
                ephemeral=True
            )
            logger.info(f"Blocked non-elevated user {interaction.user.id} from using /log in DM channel")
            return
        
        # Check if the command caller has elevated status
        if not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command. Only elevated users can access log files.",
                ephemeral=True
            )
            return
        
        # Get the most recent log file
        log_file_path = log_manager.get_most_recent_log_file()
        
        if not log_file_path or not os.path.exists(log_file_path):
            await interaction.response.send_message(
                "📁 No log files found. The bot may not have generated any logs yet.",
                ephemeral=True
            )
            return
        
        # Get file info
        file_size = os.path.getsize(log_file_path)
        file_name = os.path.basename(log_file_path)
        
        # Discord has a file size limit of 8MB for non-premium servers
        if file_size > 8 * 1024 * 1024:  # 8MB
            await interaction.response.send_message(
                f"📁 **Log file too large**\n"
                f"The log file `{file_name}` is {file_size / (1024*1024):.2f}MB, which exceeds Discord's file size limit. "
                f"Please check the server's log directory directly.",
                ephemeral=True
            )
            return
        
        try:
            # Send the log file
            with open(log_file_path, 'rb') as file:
                discord_file = discord.File(file, filename=file_name)
                await interaction.response.send_message(
                    f"📋 **Most Recent Log File**\n"
                    f"Filename: `{file_name}`\n"
                    f"Size: {file_size / 1024:.2f}KB",
                    file=discord_file,
                    ephemeral=True
                )
                logger.info(f"Elevated user {interaction.user.id} downloaded log file {file_name}")
        except Exception as file_error:
            logger.error(f"Error reading log file {log_file_path}: {file_error}")
            await interaction.response.send_message(
                "❌ Error reading the log file. Please try again later.",
                ephemeral=True
            )
            
    except Exception as e:
        logger.error(f"Error in log command: {e}")
        await interaction.response.send_message(
            "An error occurred while retrieving the log file. Please try again.",
            ephemeral=True
        )

@bot.tree.command(name='reset', description='Reset cycle image usage for a user (elevated users only)')
@app_commands.describe(user='The Discord user whose usage should be reset')
async def reset_slash(interaction: discord.Interaction, user: discord.User):
    """Reset cycle image usage for a user (elevated users only)."""
    try:
        # Check if interaction is from a DM channel and user is not elevated
        if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
                ephemeral=True
            )
            logger.info(f"Blocked non-elevated user {interaction.user.id} from using /reset in DM channel")
            return
        
        # Check if the command caller has elevated status
        if not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command. Only elevated users can reset usage.",
                ephemeral=True
            )
            return
        
        # Attempt to reset the target user's usage
        success = usage_tracker.reset_daily_usage(user.id)
        
        if success:
            # Get the user's current active count after reset (should be 0)
            new_count = usage_tracker.get_daily_image_count(user.id)
            username = user.display_name or user.name
            
            await interaction.response.send_message(
                f"✅ Successfully reset usage timestamps for **{username}** (ID: {user.id}). "
                f"Their current active usage count is now {new_count}/{config.DAILY_IMAGE_LIMIT}.",
                ephemeral=True
            )
            logger.info(f"Elevated user {interaction.user.id} reset usage for user {user.id}")
        else:
            await interaction.response.send_message(
                f"⚠️ Could not reset usage for **{user.display_name or user.name}** (ID: {user.id}). "
                "This user may not have any recorded usage yet.",
                ephemeral=True
            )
            
    except Exception as e:
        logger.error(f"Error in reset command: {e}")
        await interaction.response.send_message(
            "An error occurred while resetting user usage. Please try again.",
            ephemeral=True
        )


@bot.tree.command(name='avatar', description='Transform your avatar with a themed template')
@app_commands.describe(template='The template theme to apply to your avatar')
@app_commands.choices(template=[
    app_commands.Choice(name='Halloween', value='halloween')
])
async def avatar_slash(interaction: discord.Interaction, template: app_commands.Choice[str]):
    """Transform user's avatar with a themed template."""
    try:
        # Check if interaction is from a DM channel and user is not elevated
        if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
                ephemeral=True
            )
            logger.info(f"Blocked non-elevated user {interaction.user.id} from using /avatar in DM channel")
            return
        
        # Check usage limit
        if await check_usage_limit_and_respond(interaction):
            return
        
        # Defer the response since this will take some time
        await interaction.response.defer()
        
        # Get the user's avatar URL
        user = interaction.user
        avatar_url = user.display_avatar.url
        
        logger.info(f"User {user.id} ({user.name}) requesting avatar transformation with template: {template.value}")
        
        # Download the user's avatar
        avatar_image = await download_image(avatar_url)
        if not avatar_image:
            await interaction.followup.send("❌ Failed to download your avatar. Please try again.")
            return
        
        # Get the prompt based on the template
        template_prompts = {
            'halloween': "Modify this users avatar so that it is Halloween themed. Attempt to provide the subject of the avatar so that it is wearing a Halloween outfit that best suits the subject"
        }
        
        prompt = template_prompts.get(template.value, template_prompts['halloween'])
        
        # Get user's model preference
        user_model = usage_tracker.get_user_model_preference(user.id)
        generator = get_model_generator(user_model)
        
        # Generate the transformed avatar
        generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_text_and_image(
            prompt, avatar_image
        )
        
        # Track usage
        if usage_metadata and not user.bot:
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
        
        # Send the result
        if generated_image:
            # Save the image
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"avatar_{template.value}_{timestamp}.png"
            
            # Save to disk
            filepath = os.path.join(config.GENERATED_IMAGES_DIR, filename)
            generated_image.save(filepath)
            
            # Save to buffer for Discord
            img_buffer = io.BytesIO()
            generated_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            # Prepare the message
            content = f"🎃 **{template.name} Avatar Transformation**"
            if genai_text_response and genai_text_response.strip():
                content += f"\n\n{genai_text_response}"
            
            await interaction.followup.send(
                content=content,
                file=discord.File(img_buffer, filename=filename)
            )
            logger.info(f"Successfully generated {template.value} avatar for user {user.id}")
        else:
            error_msg = "❌ Failed to generate your transformed avatar. Please try again."
            if genai_text_response and genai_text_response.strip():
                error_msg += f"\n\n{genai_text_response}"
            await interaction.followup.send(error_msg)
            
    except Exception as e:
        logger.error(f"Error in avatar command: {e}")
        try:
            await interaction.followup.send(
                "An error occurred while transforming your avatar. Please try again.",
                ephemeral=True
            )
        except:
            # If followup fails, try to send a regular response
            pass


@bot.tree.command(name='model', description='Switch between AI models for your generations')
@app_commands.describe(model='The AI model to use for your generations (leave empty to see current model)')
@app_commands.choices(model=[
    app_commands.Choice(name='Nanobanana (Gemini - Default)', value='nanobanana'),
    app_commands.Choice(name='GPT-5 (OpenAI Image Generation)', value='gpt'),
    app_commands.Choice(name='Chat (Text-Only Responses)', value='chat')
])
async def model_slash(interaction: discord.Interaction, model: app_commands.Choice[str] = None):
    """Switch between AI models for your generations."""
    try:
        # Check if interaction is from a DM channel and user is not elevated
        if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
                ephemeral=True
            )
            logger.info(f"Blocked non-elevated user {interaction.user.id} from using /model in DM channel")
            return
        
        # Check usage limit
        if await check_usage_limit_and_respond(interaction):
            return
        
        username = interaction.user.display_name or interaction.user.name
        current_model = usage_tracker.get_user_model_preference(interaction.user.id)
        
        if model is None:
            # Show current model preference
            model_descriptions = {
                'nanobanana': 'Nanobanana (Gemini) - Image generation and transformation using Google\'s Gemini AI',
                'gpt': 'GPT-5 - Advanced image generation using OpenAI\'s latest model', 
                'chat': 'Chat - Text-only responses without image generation'
            }
            
            current_description = model_descriptions.get(current_model, current_model)
            await interaction.response.send_message(
                f"**Your current AI model:**\n\n"
                f"🤖 **{current_model.title()}**\n"
                f"📝 {current_description}\n\n"
                f"To change your model, use `/model` and select a different option.",
                ephemeral=True
            )
        else:
            # Set new model preference
            model_value = model.value
            success = usage_tracker.set_user_model_preference(interaction.user.id, username, model_value)
            
            if success:
                model_descriptions = {
                    'nanobanana': 'Nanobanana (Gemini) - Image generation and transformation using Google\'s Gemini AI',
                    'gpt': 'GPT-5 - Advanced image generation using OpenAI\'s latest model',
                    'chat': 'Chat - Text-only responses without image generation'
                }
                
                description = model_descriptions.get(model_value, model_value)
                await interaction.response.send_message(
                    f"✅ **Model preference updated!**\n\n"
                    f"Previous model: **{current_model.title()}**\n"
                    f"New model: **{model.name}**\n"
                    f"Description: {description}\n\n"
                    f"All your future generations will now use this model until you change it again.",
                    ephemeral=True
                )
                logger.info(f"User {username} ({interaction.user.id}) changed model preference from {current_model} to: {model_value}")
            else:
                await interaction.response.send_message(
                    "❌ **Error updating model preference**\n\n"
                    "There was an issue saving your model preference. Please try again.",
                    ephemeral=True
                )
            
    except Exception as e:
        logger.error(f"Error in model command: {e}")
        await interaction.response.send_message(
            "An error occurred while updating your model preference. Please try again.",
            ephemeral=True
        )



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