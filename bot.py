import discord
from discord.ext import commands
from discord import app_commands
import logging
import asyncio
import io
import os
import tempfile
from datetime import datetime, timedelta
from typing import List, Dict, Any

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
        # Get user's model preference
        user_model = usage_tracker.get_user_model_preference(user.id)
        logger.info(f"User {user.id} model preference: {user_model}")
        
        # Get the appropriate model generator
        generator = get_model_generator(user_model)
        
        # Check if user can generate images (for image-generating models)
        can_generate_images = usage_tracker.can_generate_image(user.id)
        daily_count_before = usage_tracker.get_daily_image_count(user.id)
        
        # Generate based on available inputs, rate limit status, and user's model preference
        generated_image = None
        genai_text_response = None
        usage_metadata = None
        
        # Handle rate limiting for image models (nanobanana and gpt)
        if user_model in ["nanobanana", "gpt"] and not can_generate_images:
            # User is rate limited for images - use text-only fallback
            logger.info(f"User {user.id} is rate limited for images ({daily_count_before}/{config.DAILY_IMAGE_LIMIT}), using text-only fallback")
            
            if text_content.strip() or images:
                prompt = text_content.strip() if text_content.strip() else "Please provide a text description or analysis of the provided content."
                generated_image, genai_text_response, usage_metadata = await generator.generate_text_only_response(prompt, images)
            else:
                await response_message.edit(content="Please provide some text or attach an image for me to work with!")
                return
        else:
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
                        text_content, images[0], streaming_callback if user_model == "gpt" else None
                    )
                else:
                    # For multiple images, use the first one (most generators don't support multiple)
                    generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_text_and_image(
                        text_content, images[0], streaming_callback if user_model == "gpt" else None
                    )
            elif images:
                # Image(s) only case - no text provided
                generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_image_only(
                    images[0], streaming_callback if user_model == "gpt" else None
                )
            elif text_content.strip():
                # Text only case
                generated_image, genai_text_response, usage_metadata = await generator.generate_image_from_text(
                    text_content, streaming_callback if user_model == "gpt" else None
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
                
                # Check if this was the user's 5th image today (and they're not elevated)
                if (images_generated > 0 and 
                    not usage_tracker.is_elevated_user(user.id) and
                    daily_count_before + images_generated >= config.DAILY_IMAGE_LIMIT):
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
        
        # Send ephemeral warning message if user just hit their limit (requirement #4)
        if send_limit_warning:
            try:
                # Get reset time (next cycle reset: noon or midnight)
                reset_timestamp = usage_tracker._get_next_reset_timestamp()
                
                warning_msg = (f"🚫 You've reached your cycle image generation limit "
                             f"({config.DAILY_IMAGE_LIMIT} images). Your limit will reset <t:{reset_timestamp}:R>.")
                
                # Try to send as ephemeral reply
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
        
        # Generate more comprehensive data for the file (no Discord character limits)
        if len(users_list) > 10:
            usage_text += "\n**📋 Complete User List:**\n"
            for i, (user_id, user_data) in enumerate(users_list, 1):
                username = user_data.get('username', 'Unknown User')
                output_tokens = user_data.get('total_output_tokens', 0)
                input_tokens = user_data.get('total_prompt_tokens', 0)
                total_tokens = user_data.get('total_tokens', 0)
                images = user_data.get('images_generated', 0)
                requests = user_data.get('requests_count', 0)
                
                usage_text += f"{i}. **{username}** (ID: {user_id})\n"
                usage_text += f"   • Output Tokens: {output_tokens:,}\n"
                usage_text += f"   • Input Tokens: {input_tokens:,}\n"
                usage_text += f"   • Total Tokens: {total_tokens:,}\n"
                usage_text += f"   • Images: {images} | Requests: {requests}\n\n"
        
        # Add timestamp
        usage_text += f"\n---\nGenerated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        
        # Create a temporary file with the usage statistics
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as temp_file:
            temp_file.write(usage_text)
            temp_file_path = temp_file.name
        
        try:
            # Send the file
            with open(temp_file_path, 'rb') as file:
                discord_file = discord.File(file, filename=f'usage_stats_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt')
                await interaction.response.send_message(
                    "📊 **Usage Statistics Report**\nHere are the current token usage statistics:",
                    file=discord_file,
                    ephemeral=True
                )
        finally:
            # Clean up the temporary file
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Error getting usage statistics: {e}")
        await interaction.response.send_message("An error occurred while retrieving usage statistics. Please try again.")

@bot.tree.command(name='log', description='Get the most recent log file (elevated users only)')
async def log_slash(interaction: discord.Interaction):
    """Get the most recent log file (slash command) - elevated users only."""
    try:
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
            # Get the user's current daily count after reset (should be 0)
            new_count = usage_tracker.get_daily_image_count(user.id)
            username = user.display_name or user.name
            
            await interaction.response.send_message(
                f"✅ Successfully reset cycle image usage for **{username}** (ID: {user.id}). "
                f"Their current cycle count is now {new_count}/{config.DAILY_IMAGE_LIMIT}.",
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
        
        # Check if user can generate images
        if not usage_tracker.can_generate_image(user.id):
            remaining_images = usage_tracker.get_remaining_images_today(user.id)
            reset_timestamp = usage_tracker._get_next_reset_timestamp()
            await interaction.followup.send(
                f"🚫 You've reached your cycle image generation limit ({config.DAILY_IMAGE_LIMIT} images). "
                f"Your limit will reset <t:{reset_timestamp}:R>."
            )
            return
        
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