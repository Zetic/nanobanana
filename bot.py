import discord
from discord.ext import commands
import logging
import asyncio
import io
import os
from datetime import datetime
from typing import List

import config
from image_utils import download_image, stitch_images
from genai_client import ImageGenerator

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Check if the bot is mentioned
    if bot.user in message.mentions:
        await handle_generation_request(message)
    
    # Process commands
    await bot.process_commands(message)

async def handle_generation_request(message):
    """Handle image generation request when bot is mentioned."""
    try:
        # Send initial response
        await message.add_reaction('🎨')
        status_msg = await message.reply("🎨 Processing your image generation request...")
        
        # Extract text (remove bot mention)
        text_content = message.content
        for mention in message.mentions:
            text_content = text_content.replace(f'<@{mention.id}>', '').strip()
        
        # If no text provided, use a default prompt
        if not text_content:
            text_content = "Create a picture of a nano banana dish in a fancy restaurant with a Gemini theme"
        
        logger.info(f"Processing request with text: '{text_content}'")
        
        # Extract images from attachments
        images = []
        if message.attachments:
            await status_msg.edit(content="📥 Downloading images...")
            for attachment in message.attachments[:config.MAX_IMAGES]:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    if attachment.size <= config.MAX_IMAGE_SIZE:
                        image = await download_image(attachment.url)
                        if image:
                            images.append(image)
                            logger.info(f"Downloaded image: {attachment.filename}")
                    else:
                        logger.warning(f"Image too large: {attachment.filename} ({attachment.size} bytes)")
        
        # Generate image
        generated_image = None
        
        if images:
            # Stitch images together if multiple images
            await status_msg.edit(content="🔧 Processing images...")
            if len(images) > 1:
                stitched_image = stitch_images(images)
                logger.info(f"Stitched {len(images)} images together")
            else:
                stitched_image = images[0]
            
            # Generate image with both text and image input
            await status_msg.edit(content="🎨 Generating image with AI...")
            generated_image = await get_image_generator().generate_image_from_text_and_image(
                text_content, stitched_image
            )
        else:
            # Generate image from text only
            await status_msg.edit(content="🎨 Generating image from text...")
            generated_image = await get_image_generator().generate_image_from_text(text_content)
        
        if generated_image:
            # Save and send the generated image
            await status_msg.edit(content="📤 Sending generated image...")
            
            # Save image to buffer
            img_buffer = io.BytesIO()
            generated_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            # Also save to disk for reference
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"generated_{timestamp}.png"
            filepath = os.path.join(config.GENERATED_IMAGES_DIR, filename)
            generated_image.save(filepath)
            
            # Send the image
            file = discord.File(img_buffer, filename=filename)
            embed = discord.Embed(
                title="🎨 Generated Image - Nano Banana Bot",
                description=f"**Prompt:** {text_content[:100]}{'...' if len(text_content) > 100 else ''}",
                color=0x00ff00
            )
            embed.set_image(url=f"attachment://{filename}")
            embed.set_footer(text=f"Generated using {len(images)} input image(s)" if images else "Generated from text prompt")
            
            await message.reply(file=file, embed=embed)
            await status_msg.delete()
            await message.add_reaction('✅')
            
            logger.info(f"Successfully generated and sent image for prompt: '{text_content[:50]}...'")
        else:
            await status_msg.edit(content="❌ Failed to generate image. Please try again.")
            await message.add_reaction('❌')
            logger.error("Failed to generate image")
            
    except Exception as e:
        logger.error(f"Error handling generation request: {e}")
        try:
            await message.reply("❌ An error occurred while processing your request. Please try again.")
            await message.add_reaction('❌')
        except:
            pass

@bot.command(name='info')
async def info_command(ctx):
    """Show help information."""
    embed = discord.Embed(
        title="🍌 Nano Banana Bot - Help",
        description="I'm a bot that generates images using Google's AI!",
        color=0xffff00
    )
    embed.add_field(
        name="📋 How to use",
        value="Just mention me (@Nano Banana) in a message with your prompt and optionally attach images!",
        inline=False
    )
    embed.add_field(
        name="🎨 Examples",
        value="• `@Nano Banana Create a nano banana in space`\n"
              "• `@Nano Banana Make this cat magical` (with image attached)\n"
              "• `@Nano Banana Transform this into cyberpunk style` (with multiple images)",
        inline=False
    )
    embed.add_field(
        name="📝 Features",
        value="• Text-to-image generation\n"
              "• Image-to-image transformation\n"
              "• Multiple image stitching\n"
              "• Powered by Google Gemini AI",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(name='status')
async def status_command(ctx):
    """Show bot status."""
    embed = discord.Embed(
        title="🤖 Bot Status",
        color=0x00ff00
    )
    embed.add_field(name="Status", value="✅ Online", inline=True)
    embed.add_field(name="Guilds", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)
    await ctx.send(embed=embed)

def main():
    """Main function to run the bot."""
    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not found in environment variables")
        return
    
    if not config.GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not found in environment variables")
        return
    
    logger.info("Starting Nano Banana Discord Bot...")
    bot.run(config.DISCORD_TOKEN)

if __name__ == "__main__":
    main()