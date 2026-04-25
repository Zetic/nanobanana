import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import io
import os
import re
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import config
from image_utils import download_image
from model_interface import get_model_generator
from usage_tracker import usage_tracker
from log_manager import log_manager  # importing this module configures logging
from wordplay_game import session_manager, generate_word_pair_with_gemini, generate_word_image

logger = logging.getLogger(__name__)

# Honour the DEBUG_LOGGING env-var flag
if config.DEBUG_LOGGING:
    log_manager.set_debug_logging(True)
    logger.info("Debug logging enabled via DEBUG_LOGGING environment variable")

# All UI classes removed - bot now returns natural API responses directly

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=config.COMMAND_PREFIX, intents=intents, help_command=None)

# Bot snitching feature - track messages that mention the bot
# Structure: {message_id: {'content': str, 'author_id': int, 'channel_id': int, 'timestamp': datetime}}
tracked_messages: Dict[int, Dict[str, Any]] = {}
DEFAULT_SNITCH_CONTENT = "use me"  # Fallback text when message only contained bot mention

# Discord embed character limits
EMBED_DESCRIPTION_MAX_LENGTH = 4096
EMBED_FIELD_VALUE_MAX_LENGTH = 1024

def get_git_commit_hash() -> Optional[str]:
    """Return the current git commit hash shortened to 7 characters, or None if unavailable."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short=7', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f'Failed to get git commit hash: {e}')
    return None


def cleanup_old_tracked_messages():
    """Remove tracked messages older than 8 hours."""
    current_time = datetime.now()
    expired_ids = []
    
    for message_id, data in tracked_messages.items():
        if current_time - data['timestamp'] > timedelta(hours=8):
            expired_ids.append(message_id)
    
    for message_id in expired_ids:
        del tracked_messages[message_id]
    
    if expired_ids:
        logger.info(f"Cleaned up {len(expired_ids)} expired tracked messages")

@bot.event
async def on_ready():
    """Called when the bot is ready."""
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Bot is in {len(bot.guilds)} guilds')

    # Set bot status to the current git commit hash
    commit_hash = get_git_commit_hash()
    if commit_hash:
        logger.info(f'Setting bot status to git commit: {commit_hash}')
        await bot.change_presence(activity=discord.Game(name=commit_hash))
    else:
        logger.warning('Could not determine git commit hash; bot status will not be set')

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
    
    # Track messages that mention the bot for snitching feature
    if is_directly_mentioned(message.content, bot.user.id):
        # Clean up old tracked messages before adding new one
        cleanup_old_tracked_messages()
        
        # Track this message
        tracked_messages[message.id] = {
            'content': message.content,
            'author_id': message.author.id,
            'channel_id': message.channel.id,
            'timestamp': datetime.now()
        }
        logger.info(f"Tracking message {message.id} from user {message.author.id} in channel {message.channel.id}")
    
    # Check if user has reached usage limit (only for non-elevated users)
    if not usage_tracker.is_elevated_user(message.author.id):
        has_limit, next_available = usage_tracker.has_reached_usage_limit(message.author.id)
        if has_limit:
            # Only apply this auto-blocking behavior to prefix commands
            is_command = message.content.startswith(config.COMMAND_PREFIX)
            
            if is_command:
                # React with wilted_rose emoji (no message)
                try:
                    await message.add_reaction("🥀")  # wilted_rose emoji
                except Exception as e:
                    logger.warning(f"Failed to add reaction: {e}")
                logger.info(f"Blocked user {message.author.id} from using bot - usage limit reached")
                return
    
    # Handle commands first
    await bot.process_commands(message)
    
    bot_mentioned = is_directly_mentioned(message.content, bot.user.id)
    replied_to_bot = await is_reply_to_bot_message(message)
    if bot_mentioned or replied_to_bot:
        await handle_conversation_request(message)

@bot.event
async def on_message_delete(message):
    """Handle deleted messages - snitch on users who delete messages that mentioned the bot."""
    # Check if this message was tracked
    if message.id in tracked_messages:
        tracked_data = tracked_messages[message.id]
        
        try:
            # Get the channel where the message was deleted
            channel = bot.get_channel(tracked_data['channel_id'])
            if not channel:
                logger.warning(f"Could not find channel {tracked_data['channel_id']} for snitching")
                return
            
            # Get the user who sent (and deleted) the message
            user = await bot.fetch_user(tracked_data['author_id'])
            if not user:
                logger.warning(f"Could not find user {tracked_data['author_id']} for snitching")
                return
            
            # Remove bot mentions from the original content
            content = tracked_data['content']
            content = content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '')
            content = content.strip()
            
            # If content is empty after removing mentions, use a generic message
            if not content:
                content = DEFAULT_SNITCH_CONTENT
            
            # Construct the snitching message
            snitch_message = f"Oh {user.mention} I thought your idea to {content} was interesting though..."
            
            # Send the snitching message
            await channel.send(snitch_message)
            logger.info(f"Snitched on user {user.id} for deleting message {message.id}")
            
        except Exception as e:
            logger.error(f"Error snitching on deleted message {message.id}: {e}")
        finally:
            # Remove the tracked message
            del tracked_messages[message.id]

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

async def is_reply_to_bot_message(message) -> bool:
    """Check whether this message is a reply to a bot-authored message."""
    if not message.reference or not message.reference.message_id:
        return False
    
    referenced = message.reference.cached_message
    if referenced is None:
        try:
            referenced = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            return False
    
    return bool(referenced and referenced.author and referenced.author.id == bot.user.id)

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

async def handle_conversation_request(message):
    """Handle text-only conversational responses for mentions/replies."""
    try:
        response_message = await message.reply("Thinking...")
        text_content = await extract_text_from_message(message)
        
        if not text_content.strip():
            await response_message.edit(content="Please include some text in your message.")
            return
        
        generator = get_model_generator("chat")
        _, text_response, _ = await generator.generate_text_only_response(text_content)
        
        if not text_response or not text_response.strip():
            await response_message.edit(content="I couldn't generate a response. Please try again.")
            return
        
        chunks = split_long_message(text_response, max_length=1800)
        await response_message.edit(content=chunks[0])
        for chunk in chunks[1:]:
            await response_message.channel.send(content=chunk)
    except Exception as e:
        logger.error(f"Error handling conversation request: {e}")
        await message.reply("An error occurred while processing your request. Please try again.")


async def generate_image_for_model(model_type: str, text_content: str, images: List, aspect_ratio: Optional[str] = None):
    """Generate an image/text response for the requested model."""
    generator = get_model_generator(model_type)
    
    if images and text_content.strip():
        if len(images) == 1:
            return await generator.generate_image_from_text_and_image(text_content, images[0], None, aspect_ratio)
        return await generator.generate_image_from_text_and_image(text_content, images[0], None, aspect_ratio, images[1:])
    if images:
        if len(images) == 1:
            return await generator.generate_image_from_image_only(images[0], None, aspect_ratio)
        return await generator.generate_image_from_image_only(images[0], None, aspect_ratio, images[1:])
    if text_content.strip():
        return await generator.generate_image_from_text(text_content, None, aspect_ratio)
    return None, None, None


async def download_command_images(attachments: List[discord.Attachment], interaction: discord.Interaction) -> Optional[List]:
    """Validate and download slash-command image attachments."""
    images = []
    for attachment in attachments:
        if not attachment:
            continue
        if not attachment.content_type or not attachment.content_type.startswith('image/'):
            await interaction.followup.send(f"❌ `{attachment.filename}` is not an image file.", ephemeral=True)
            return None
        if attachment.size > config.MAX_IMAGE_SIZE:
            await interaction.followup.send(
                f"❌ `{attachment.filename}` is too large. Maximum size is {config.MAX_IMAGE_SIZE // (1024*1024)}MB.",
                ephemeral=True
            )
            return None
        
        image = await download_image(attachment.url)
        if image:
            images.append(image)
    
    return images



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
    
    # Use interaction.client.user for safety and provide fallbacks
    bot_user = interaction.client.user
    bot_name = bot_user.display_name if bot_user else "Nano Banana"
    bot_mention = bot_user.mention if bot_user else "@Nano Banana"
    
    help_text = f"""**{bot_name} - Help**

I'm a multi-model bot for conversational text and image generation.

**How to use:**
• Mention me ({bot_mention}) or reply to one of my messages for a text-only response
• Use slash commands for image generation

**Supported Aspect Ratios:**
• Landscape: `-21:9`, `-16:9`, `-4:3`, `-3:2`
• Square: `-1:1`
• Portrait: `-9:16`, `-3:4`, `-2:3`
• Flexible: `-5:4`, `-4:5`

**Slash Commands:**
• `/help` - Show this help message
• `/gemini-image` - Generate/edit images with Gemini (prompt + optional image attachments)
• `/gpt-image` - Generate/edit images with OpenAI gpt-image-2 (prompt + optional image attachments)
• `/wordplay` - Play a word puzzle game! Guess the extra letter between two words (1 puzzle every 8 hours)
• `/avatar` - Transform your avatar with themed templates (Halloween, Christmas, New Year). Optionally specify a user to transform their avatar instead.
• `/usage` - Show token usage statistics (elevated users only)
• `/log` - Get the most recent log file (elevated users only)
• `/reset` - Reset cycle image usage for a user (elevated users only)
• `/tier` - Assign a tier to a user (elevated users only)"""
    
    await interaction.response.send_message(help_text)


async def run_image_command(
    interaction: discord.Interaction,
    model_type: str,
    prompt: str,
    image_1: Optional[discord.Attachment] = None,
    image_2: Optional[discord.Attachment] = None,
    image_3: Optional[discord.Attachment] = None,
    image_4: Optional[discord.Attachment] = None
):
    """Shared implementation for image slash commands."""
    reserved_slots = 0
    usage_consumed = False
    
    if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
        await interaction.response.send_message(
            "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
            ephemeral=True
        )
        return
    
    if await check_usage_limit_and_respond(interaction):
        return
    
    reservation_successful, next_available = usage_tracker.reserve_usage_slots(
        interaction.user.id,
        slots=1,
        username=interaction.user.display_name or interaction.user.name
    )
    if not reservation_successful:
        if next_available:
            time_until_available = next_available - datetime.now()
            hours = int(time_until_available.total_seconds() // 3600)
            minutes = int((time_until_available.total_seconds() % 3600) // 60)
            await interaction.response.send_message(
                f"⏰ You've reached your usage limit. Please try again in {hours}h {minutes}m.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "⏰ You've reached your usage limit. Please try again later.",
                ephemeral=True
            )
        return
    
    reserved_slots = 1
    
    try:
        await interaction.response.defer()
        
        attachments = [image_1, image_2, image_3, image_4]
        images = await download_command_images(attachments, interaction)
        if images is None:
            return
        
        aspect_ratio, cleaned_prompt = extract_aspect_ratio(prompt)
        generated_image, text_response, usage_metadata = await generate_image_for_model(model_type, cleaned_prompt, images, aspect_ratio)
        
        if usage_metadata and not interaction.user.bot:
            prompt_tokens = usage_metadata.get("prompt_token_count", 0)
            output_tokens = usage_metadata.get("candidates_token_count", 0)
            total_tokens = usage_metadata.get("total_token_count", 0)
            images_generated = 1 if generated_image else 0
            usage_tracker.record_usage(
                user_id=interaction.user.id,
                username=interaction.user.display_name or interaction.user.name,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                images_generated=images_generated,
                consume_reserved_slots=images_generated
            )
            usage_consumed = images_generated > 0
        
        file = None
        filename = None
        if generated_image:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{model_type}_{timestamp}.png"
            filepath = os.path.join(config.GENERATED_IMAGES_DIR, filename)
            generated_image.save(filepath)
            img_buffer = io.BytesIO()
            generated_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            file = discord.File(img_buffer, filename=filename)
        
        if not (text_response and text_response.strip()) and not file:
            await interaction.followup.send("I wasn't able to generate anything from your request. Please try again.")
            return
        
        # Build response embed with image information
        model_name_display = "Gemini" if model_type == "nanobanana" else "GPT Image 2"
        embed = discord.Embed(color=discord.Color.blue())
        
        # Text response from model in embed description
        # Skip description if it's just echoing the prompt (e.g. gpt-image), since the Prompt field already shows it
        text_response_stripped = text_response.strip() if text_response else ""
        is_prompt_echo = text_response_stripped and cleaned_prompt and text_response_stripped == cleaned_prompt.strip()
        if text_response_stripped and not is_prompt_echo:
            desc = text_response_stripped
            if len(desc) > EMBED_DESCRIPTION_MAX_LENGTH:
                desc = desc[:EMBED_DESCRIPTION_MAX_LENGTH - 3] + "..."
            embed.description = desc
        
        # Prompt field
        prompt_value = cleaned_prompt if cleaned_prompt and cleaned_prompt.strip() else "(no prompt)"
        if len(prompt_value) > EMBED_FIELD_VALUE_MAX_LENGTH:
            prompt_value = prompt_value[:EMBED_FIELD_VALUE_MAX_LENGTH - 3] + "..."
        embed.add_field(name="Prompt", value=prompt_value, inline=False)
        
        # Resolution field (only if an image was generated)
        if generated_image:
            width, height = generated_image.size
            pixel_count = width * height
            embed.add_field(name="Resolution", value=f"{width}×{height} ({pixel_count:,} pixels)", inline=True)
        
        # Aspect ratio field (if one was specified)
        if aspect_ratio:
            embed.add_field(name="Aspect Ratio", value=aspect_ratio, inline=True)
        
        # Model field
        embed.add_field(name="Model", value=model_name_display, inline=True)
        
        # Reference output image inline in the embed
        if file:
            embed.set_image(url=f"attachment://{filename}")
        
        # Build small embeds for each input image used
        input_attachments = [a for a in [image_1, image_2, image_3, image_4] if a is not None]
        input_embeds = []
        for attachment in input_attachments:
            input_embed = discord.Embed(color=discord.Color.light_grey())
            input_embed.set_image(url=attachment.url)
            input_embeds.append(input_embed)
        
        embeds = input_embeds + [embed]
        
        if file:
            await interaction.followup.send(embeds=embeds, file=file)
        else:
            await interaction.followup.send(embeds=embeds)
    finally:
        if reserved_slots > 0 and not usage_consumed:
            usage_tracker.release_reserved_usage_slots(interaction.user.id, slots=reserved_slots)


@bot.tree.command(name='gemini-image', description='Generate or edit images with Gemini')
@app_commands.describe(
    prompt='Prompt for image generation/editing (supports -16:9 style aspect ratio flags)',
    image_1='Optional first image attachment',
    image_2='Optional second image attachment',
    image_3='Optional third image attachment',
    image_4='Optional fourth image attachment'
)
async def gemini_image_slash(
    interaction: discord.Interaction,
    prompt: str,
    image_1: Optional[discord.Attachment] = None,
    image_2: Optional[discord.Attachment] = None,
    image_3: Optional[discord.Attachment] = None,
    image_4: Optional[discord.Attachment] = None
):
    """Generate/edit images with Gemini."""
    await run_image_command(interaction, "nanobanana", prompt, image_1, image_2, image_3, image_4)


@bot.tree.command(name='gpt-image', description='Generate or edit images with OpenAI gpt-image-2')
@app_commands.describe(
    prompt='Prompt for image generation/editing (supports -16:9 style aspect ratio flags)',
    image_1='Optional first image attachment',
    image_2='Optional second image attachment',
    image_3='Optional third image attachment',
    image_4='Optional fourth image attachment'
)
async def gpt_image_slash(
    interaction: discord.Interaction,
    prompt: str,
    image_1: Optional[discord.Attachment] = None,
    image_2: Optional[discord.Attachment] = None,
    image_3: Optional[discord.Attachment] = None,
    image_4: Optional[discord.Attachment] = None
):
    """Generate/edit images with OpenAI gpt-image-2."""
    await run_image_command(interaction, "gpt", prompt, image_1, image_2, image_3, image_4)

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
            
            # Get active usage count and tier for this user
            user_id_int = int(user_id)
            active_count = usage_tracker.get_daily_image_count(user_id_int)
            user_tier = usage_tracker.get_user_tier(user_id_int)
            
            # Get tier limit for display
            from usage_tracker import TIER_LIMITS
            tier_limit = TIER_LIMITS.get(user_tier, config.DAILY_IMAGE_LIMIT)
            
            if user_tier == 'unlimited' or tier_limit == float('inf'):
                usage_rate = f"{active_count}/∞"
            else:
                usage_rate = f"{active_count}/{int(tier_limit)}"
            
            usage_text += f"{i}. {username} ({user_tier}): {total_tokens:,} tokens, {images} images, {usage_rate} active\n"
        
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


@bot.tree.command(name='tier', description='Assign a tier to a user (elevated users only)')
@app_commands.describe(
    user='The Discord user to assign a tier to',
    tier='The tier to assign (standard, limited, strict, extra, unlimited)'
)
@app_commands.choices(tier=[
    app_commands.Choice(name='Standard (3 charges)', value='standard'),
    app_commands.Choice(name='Limited (2 charges)', value='limited'),
    app_commands.Choice(name='Strict (1 charge)', value='strict'),
    app_commands.Choice(name='Extra (5 charges)', value='extra'),
    app_commands.Choice(name='Unlimited', value='unlimited')
])
async def tier_slash(interaction: discord.Interaction, user: discord.User, tier: app_commands.Choice[str]):
    """Assign a tier to a user (elevated users only)."""
    try:
        # Check if interaction is from a DM channel and user is not elevated
        if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
                ephemeral=True
            )
            logger.info(f"Blocked non-elevated user {interaction.user.id} from using /tier in DM channel")
            return
        
        # Check if the command caller has elevated status
        if not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command. Only elevated users can assign tiers.",
                ephemeral=True
            )
            return
        
        # Set the tier for the user
        username = user.display_name or user.name
        success = usage_tracker.set_user_tier(user.id, tier.value, username)
        
        if success:
            # Get tier details for display
            from usage_tracker import TIER_LIMITS
            tier_limit = TIER_LIMITS.get(tier.value, 3)
            
            if tier.value == 'unlimited':
                limit_text = "unlimited charges (never rate limited)"
            else:
                limit_text = f"{int(tier_limit)} cycling charges"
            
            await interaction.response.send_message(
                f"✅ Successfully set **{username}** (ID: {user.id}) to **{tier.value}** tier with {limit_text}.",
                ephemeral=True
            )
            logger.info(f"Elevated user {interaction.user.id} set tier '{tier.value}' for user {user.id}")
        else:
            await interaction.response.send_message(
                f"❌ Failed to set tier. Invalid tier value.",
                ephemeral=True
            )
            
    except Exception as e:
        logger.error(f"Error in tier command: {e}")
        await interaction.response.send_message(
            "An error occurred while setting user tier. Please try again.",
            ephemeral=True
        )


@bot.tree.command(name='avatar', description='Transform your avatar with a themed template')
@app_commands.describe(
    template='The template theme to apply to your avatar',
    user='Optional: Use another user\'s avatar instead of your own'
)
@app_commands.choices(template=[
    app_commands.Choice(name='Halloween', value='halloween'),
    app_commands.Choice(name='Christmas', value='christmas'),
    app_commands.Choice(name='New Year', value='newyear')
])
async def avatar_slash(interaction: discord.Interaction, template: app_commands.Choice[str], user: Optional[discord.User] = None):
    """Transform user's avatar with a themed template."""
    reserved_slots = 0
    usage_consumed = False
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
        
        reservation_successful, next_available = usage_tracker.reserve_usage_slots(
            interaction.user.id,
            slots=1,
            username=interaction.user.display_name or interaction.user.name
        )
        if not reservation_successful:
            if next_available:
                time_until_available = next_available - datetime.now()
                hours = int(time_until_available.total_seconds() // 3600)
                minutes = int((time_until_available.total_seconds() % 3600) // 60)
                await interaction.response.send_message(
                    f"⏰ You've reached your usage limit. Please try again in {hours}h {minutes}m.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "⏰ You've reached your usage limit. Please try again later.",
                    ephemeral=True
                )
            return
        
        reserved_slots = 1
        
        # Defer the response since this will take some time
        await interaction.response.defer()
        
        # Use the specified user's avatar, or the caller's avatar if not specified
        target_user = user if user else interaction.user
        avatar_url = target_user.display_avatar.url
        
        logger.info(f"User {interaction.user.id} ({interaction.user.name}) requesting avatar transformation with template: {template.value} for user {target_user.id} ({target_user.name})")
        
        # Download the target user's avatar
        avatar_image = await download_image(avatar_url)
        if not avatar_image:
            await interaction.followup.send("❌ Failed to download the avatar. Please try again.")
            return
        
        # Get the prompt based on the template
        template_prompts = {
            'halloween': "Modify this users avatar so that it is Halloween themed. Attempt to provide the subject of the avatar so that it is wearing a Halloween outfit that best suits the subject",
            'christmas': "Christmasify this image",
            'newyear': "Represent this image in a New Year's party setting for 2026"
        }
        
        # Theme emojis for response messages
        template_emojis = {
            'halloween': '🎃',
            'christmas': '🎄',
            'newyear': '🎆'
        }
        
        prompt = template_prompts.get(template.value, template_prompts['halloween'])
        emoji = template_emojis.get(template.value, '🎨')
        
        # Always use the default Gemini model
        generator = get_model_generator("nanobanana")
        
        # Generate the transformed avatar
        generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_text_and_image(
            prompt, avatar_image
        )
        
        # Track usage (use interaction.user for tracking, not target_user)
        if usage_metadata and not interaction.user.bot:
            try:
                prompt_tokens = usage_metadata.get("prompt_token_count", 0)
                output_tokens = usage_metadata.get("candidates_token_count", 0)
                total_tokens = usage_metadata.get("total_token_count", 0)
                images_generated = 1 if generated_image else 0
                
                usage_tracker.record_usage(
                    user_id=interaction.user.id,
                    username=interaction.user.display_name or interaction.user.name,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    images_generated=images_generated,
                    consume_reserved_slots=images_generated
                )
                usage_consumed = images_generated > 0
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
            content = f"{emoji} **{template.name} Avatar Transformation**"
            if genai_text_response and genai_text_response.strip():
                content += f"\n\n{genai_text_response}"
            
            await interaction.followup.send(
                content=content,
                file=discord.File(img_buffer, filename=filename)
            )
            logger.info(f"Successfully generated {template.value} avatar for user {target_user.id}")
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
    finally:
        if reserved_slots > 0 and not usage_consumed:
            usage_tracker.release_reserved_usage_slots(interaction.user.id, slots=reserved_slots)




# Modal for wordplay answer submission
class WordplayAnswerModal(discord.ui.Modal, title="Submit Your Answer"):
    """Modal for submitting a wordplay puzzle answer."""
    
    def __init__(self, message_id: int, letter_count: int = 1):
        super().__init__()
        self.message_id = message_id
        
        # Create dynamic text input based on expected letter count
        if letter_count == 1:
            label = "Enter the extra letter"
            placeholder = "Type a single letter (A-Z)"
        else:
            label = f"Enter the {letter_count} extra letters"
            placeholder = f"Type {letter_count} letters (e.g., ABC or A,B,C)"
        
        # Calculate max length: letters + (letter_count - 1) separators + buffer for spaces
        SEPARATOR_BUFFER = 10  # Extra space for commas and spaces
        max_input_length = letter_count + (letter_count - 1) + SEPARATOR_BUFFER
        
        self.answer = discord.ui.TextInput(
            label=label,
            placeholder=placeholder,
            min_length=letter_count,
            max_length=max_input_length,
            required=True,
            style=discord.TextStyle.short
        )
        self.add_item(self.answer)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle the modal submission."""
        try:
            # Get the session for this message
            session = session_manager.get_session(self.message_id)
            
            if not session:
                await interaction.response.send_message(
                    "❌ This puzzle is no longer active. Use `/wordplay` to start a new puzzle.",
                    ephemeral=True
                )
                return
            
            # Check if user already solved it
            if interaction.user.id in session.solved_by_users:
                await interaction.response.send_message(
                    "✅ You've already solved this puzzle! Great job! 🎉",
                    ephemeral=True
                )
                return
            
            # Check the answer for this specific user
            user_answer = self.answer.value.strip()
            is_correct = session.check_answer(interaction.user.id, user_answer)
            
            if is_correct:
                # Correct answer! Award point if not already awarded to this user
                if interaction.user.id not in session.point_awarded_users:
                    session.point_awarded_users.add(interaction.user.id)
                    new_score = usage_tracker.increment_wordplay_score(
                        interaction.user.id,
                        interaction.user.display_name or interaction.user.name
                    )
                    score_text = f"\n🏆 **Your total wordplay score: {new_score}**"
                else:
                    score_text = ""
                
                await interaction.response.send_message(
                    f"🎉 **Correct!** The extra letter{'s' if len(session.extra_letters) > 1 else ''} {'are' if len(session.extra_letters) > 1 else 'is'} **{session.extra_letters}**!\n\n"
                    f"The word pair was: **{session.shorter_word}** → **{session.longer_word}**\n"
                    f"Great job solving the puzzle! 🎊{score_text}",
                    ephemeral=True
                )
                # Don't remove session - let other users attempt it too
                logger.info(f"User {interaction.user.id} solved wordplay puzzle correctly (message {self.message_id})")
            else:
                # Incorrect answer
                if session.has_attempts_remaining(interaction.user.id):
                    attempts_left = session.get_attempts_remaining(interaction.user.id)
                    await interaction.response.send_message(
                        f"❌ Sorry, that's not correct. You have **{attempts_left}** attempts remaining.\n"
                        f"Click the button again to try once more!",
                        ephemeral=True
                    )
                    logger.info(f"User {interaction.user.id} incorrect wordplay answer, {attempts_left} attempts left (message {self.message_id})")
                else:
                    # No more attempts for this user
                    await interaction.response.send_message(
                        f"❌ Sorry, no more attempts remaining for you!\n\n"
                        f"The correct answer was **{session.extra_letters}**.\n"
                        f"The word pair was: **{session.shorter_word}** → **{session.longer_word}**\n\n"
                        f"Better luck next time! Use `/wordplay` to try another puzzle.",
                        ephemeral=True
                    )
                    # Don't remove session - let other users attempt it too
                    logger.info(f"User {interaction.user.id} failed wordplay puzzle - no attempts remaining (message {self.message_id})")
        
        except Exception as e:
            logger.error(f"Error in wordplay answer modal: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while checking your answer. Please try again.",
                ephemeral=True
            )


# View with button to open the modal
class WordplayAnswerView(discord.ui.View):
    """View with a button to submit an answer to the wordplay puzzle."""
    
    def __init__(self, message_id: int):
        super().__init__(timeout=None)  # No timeout since puzzles don't expire
        self.message_id = message_id
        # Create button with unique custom_id
        submit_button = discord.ui.Button(
            label="Submit Answer",
            style=discord.ButtonStyle.primary,
            emoji="✍️",
            custom_id=f"wordplay_submit_{message_id}"
        )
        submit_button.callback = self.submit_answer
        self.add_item(submit_button)
    
    async def submit_answer(self, interaction: discord.Interaction):
        """Open the modal for submitting an answer."""
        # Check if there's an active session for this message
        session = session_manager.get_session(self.message_id)
        
        if not session:
            await interaction.response.send_message(
                "❌ This puzzle is no longer active. Use `/wordplay` to start a new puzzle.",
                ephemeral=True
            )
            return
        
        # Get the expected letter count from session
        letter_count = len(session.extra_letters)
        
        # Open the modal with the message_id and letter_count
        modal = WordplayAnswerModal(self.message_id, letter_count)
        await interaction.response.send_modal(modal)


@bot.tree.command(name='wordplay', description='Play a wordplay puzzle - guess the extra letter!')
@app_commands.describe(
    word_length='Minimum length for the shorter word (default: 4)',
    letter_difference='Number of letters to add/remove (default: 1)',
    style='Art style for the images (e.g., "anime", "watercolor"). Default is graphite pencil sketch.'
)
async def wordplay_slash(
    interaction: discord.Interaction,
    word_length: Optional[int] = None,
    letter_difference: Optional[int] = None,
    style: Optional[str] = None
):
    """Start a wordplay puzzle where users guess the extra letter between two words."""
    reserved_slots = 0
    usage_consumed = False
    try:
        # Set defaults
        min_word_length = word_length if word_length is not None else 4
        num_letters = letter_difference if letter_difference is not None else 1
        
        # Validate parameters
        if min_word_length < 3:
            await interaction.response.send_message(
                "❌ Minimum word length must be at least 3 letters.",
                ephemeral=True
            )
            return
        
        if num_letters < 1 or num_letters > 5:
            await interaction.response.send_message(
                "❌ Letter difference must be between 1 and 5.",
                ephemeral=True
            )
            return
        # Check if interaction is from a DM channel and user is not elevated
        if is_dm_channel(interaction.channel) and not usage_tracker.is_elevated_user(interaction.user.id):
            await interaction.response.send_message(
                "❌ You don't have permission to use this bot in DMs. Only elevated users can use the bot in direct messages.",
                ephemeral=True
            )
            logger.info(f"Blocked non-elevated user {interaction.user.id} from using /wordplay in DM channel")
            return
        
        # Reserve usage slots up front to prevent over-queueing
        reservation_successful, next_available_time = usage_tracker.reserve_usage_slots(
            interaction.user.id,
            slots=2,
            username=interaction.user.display_name or interaction.user.name
        )
        if not reservation_successful:
            if next_available_time:
                # Calculate time until next available use
                time_until_available = next_available_time - datetime.now()
                hours = int(time_until_available.total_seconds() // 3600)
                minutes = int((time_until_available.total_seconds() % 3600) // 60)
                
                await interaction.response.send_message(
                    f"⏰ You've reached your usage limit. Please try again in {hours}h {minutes}m.\n"
                    f"(Usage limit: 1 puzzle every 8 hours)",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "⏰ You've reached your usage limit. Please try again later.",
                    ephemeral=True
                )
            return
        
        reserved_slots = 2
        
        # Defer response since this will take time
        await interaction.response.defer()
        
        # Gemini generator for text tasks (word-pair generation, style prompts)
        text_generator = get_model_generator("nanobanana")
        # GPT generator for image generation (uses gpt-image-2)
        image_generator = get_model_generator("gpt")
        
        # Generate word pair with custom parameters
        word_pair = await generate_word_pair_with_gemini(text_generator, min_word_length, num_letters)
        
        if not word_pair:
            await interaction.followup.send(
                "❌ Failed to generate a word puzzle. Please try again.",
                ephemeral=True
            )
            logger.error(f"Failed to generate word pair for user {interaction.user.id}")
            return
        
        shorter_word, longer_word, extra_letters = word_pair
        logger.info(f"Generated word pair for {interaction.user.id}: {shorter_word} -> {longer_word} (extra: {extra_letters})")
        
        # Generate images for both words using gpt-image-2
        status_msg = await interaction.followup.send("🎨 Generating puzzle images...", wait=True)
        
        image1 = await generate_word_image(image_generator, shorter_word, style, text_generator=text_generator)
        image2 = await generate_word_image(image_generator, longer_word, style, text_generator=text_generator)
        
        # Check if both images were generated successfully
        if not image1 or not image2:
            # Delete the status message before showing error
            try:
                await status_msg.delete()
            except (discord.NotFound, discord.HTTPException) as e:
                logger.warning(f"Could not delete status message: {e}")
            
            await interaction.followup.send(
                "❌ Failed to generate puzzle images. Please try again.",
                ephemeral=True
            )
            logger.error(f"Failed to generate images for word pair: {shorter_word}, {longer_word}")
            return
        
        # Delete the status message before showing the puzzle
        try:
            await status_msg.delete()
        except (discord.NotFound, discord.HTTPException) as e:
            logger.warning(f"Could not delete status message: {e}")
        
        # Generate a unique puzzle ID with microseconds to ensure uniqueness
        puzzle_id = f"{interaction.user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        # Record usage for rate limiting
        # Note: Token counting is handled internally by the model generator.
        # For wordplay, we primarily track image generation count for rate limiting.
        # The wordplay command uses the 8-hour cycling rate limit based on images_generated,
        # not token consumption, so token counts are intentionally set to 0.
        usage_tracker.record_usage(
            user_id=interaction.user.id,
            username=interaction.user.display_name or interaction.user.name,
            prompt_tokens=0,
            output_tokens=0,
            total_tokens=0,
            images_generated=2,  # Two images generated per puzzle
            consume_reserved_slots=2
        )
        usage_consumed = True
        
        # Save images to buffers for Discord
        img1_buffer = io.BytesIO()
        img2_buffer = io.BytesIO()
        image1.save(img1_buffer, format='PNG')
        image2.save(img2_buffer, format='PNG')
        img1_buffer.seek(0)
        img2_buffer.seek(0)
        
        # Save images to disk
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename1 = f"wordplay_{shorter_word}_{timestamp}_1.png"
        filename2 = f"wordplay_{longer_word}_{timestamp}_2.png"
        
        filepath1 = os.path.join(config.GENERATED_IMAGES_DIR, filename1)
        filepath2 = os.path.join(config.GENERATED_IMAGES_DIR, filename2)
        image1.save(filepath1)
        image2.save(filepath2)
        
        # Create Discord files
        file1 = discord.File(img1_buffer, filename=filename1)
        file2 = discord.File(img2_buffer, filename=filename2)
        
        # Create embed with puzzle (we'll update attempts count after creating session)
        # Prepare text for singular/plural handling
        letter_text = f"{num_letters} additional letter{'s' if num_letters > 1 else ''}"
        letter_plural = 's' if num_letters > 1 else ''
        verb_form = 's' if num_letters == 1 else ''
        
        embed = discord.Embed(
            title="🎯 Wordplay Puzzle",
            description=(
                f"**Two images, two words, {letter_text}!**\n\n"
                "Look at the images below. Each represents a different word.\n"
                f"One word is identical to the other except for **{letter_text}**.\n\n"
                f"**Your task:** Find the extra letter{letter_plural} that turn{verb_form} the shorter word into the longer word.\n\n"
                f"💡 **Hint:** The words differ by exactly {num_letters} letter{letter_plural}, and letter order stays the same.\n"
                f"🎲 **Attempts:** 3 remaining\n"
                f"🏆 **Reward:** 1 point for solving correctly!"
            ),
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📸 Image 1",
            value="Represents one word",
            inline=True
        )
        embed.add_field(
            name="📸 Image 2",
            value="Represents another word",
            inline=True
        )
        
        embed.add_field(
            name="How to answer:",
            value="Click the 'Submit Answer' button below to enter your guess!",
            inline=False
        )
        
        embed.set_footer(text="Good luck! 🍀")
        
        # Send the puzzle first to get the message ID
        puzzle_message = await interaction.followup.send(
            embed=embed,
            files=[file1, file2],
            wait=True
        )
        
        # Now create session with the message ID
        session = session_manager.create_session(
            puzzle_message.id,
            interaction.user.id,
            shorter_word,
            longer_word,
            extra_letters,
            puzzle_id
        )
        
        # Create view with answer button that has the message_id
        view = WordplayAnswerView(puzzle_message.id)
        
        # Edit the message to add the view
        await puzzle_message.edit(view=view)
        
        logger.info(f"Wordplay puzzle sent to user {interaction.user.id}")
        
    except Exception as e:
        logger.error(f"Error in wordplay command: {e}", exc_info=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "❌ An error occurred while creating the puzzle. Please try again.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ An error occurred while creating the puzzle. Please try again.",
                    ephemeral=True
                )
        except discord.DiscordException as discord_error:
            logger.error(f"Could not send error message: {discord_error}")
    finally:
        if reserved_slots > 0 and not usage_consumed:
            usage_tracker.release_reserved_usage_slots(interaction.user.id, slots=reserved_slots)


def main():
    """Main function to run the bot."""
    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not found in environment variables")
        return
    
    if not config.GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not found in environment variables")
        return
    
    if not config.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables")
        return
    
    logger.info("Starting Discord Bot...")
    bot.run(config.DISCORD_TOKEN)

if __name__ == "__main__":
    main()
