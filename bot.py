import discord
from discord.ext import commands
import logging
import asyncio
import io
import os
from datetime import datetime
from typing import List

import config
from image_utils import download_image
from genai_client import ImageGenerator

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StyleOptionsView(discord.ui.View):
    """View with style buttons for chaining modifications on generated images."""
    
    def __init__(self, generated_image, filename: str, timeout=300):
        super().__init__(timeout=timeout)
        self.generated_image = generated_image
        self.filename = filename
        
    @discord.ui.button(label='🏷️ Make Sticker', style=discord.ButtonStyle.secondary)
    async def sticker_style_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Apply sticker style to the generated image."""
        try:
            # Disable all buttons to prevent multiple clicks
            for item in self.children:
                item.disabled = True
            
            # Update embed to show processing
            embed = discord.Embed(
                title="🏷️ Applying Sticker Style - Nano Banana Bot",
                description="Converting the generated image to sticker style...",
                color=0x9932cc
            )
            embed.add_field(name="Status", value="🔄 Applying sticker template...", inline=False)
            embed.set_footer(text="Creating sticker with black outline and vector art style")
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            # Apply sticker template to the generated image
            sticker_prompt = config.TEMPLATES['sticker']['image_only']
            
            # Generate new image with sticker style
            sticker_image = await get_image_generator().generate_image_from_text_and_image(
                sticker_prompt, self.generated_image
            )
            
            if sticker_image:
                # Save the new sticker image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                sticker_filename = f"sticker_{timestamp}.png"
                sticker_filepath = os.path.join(config.GENERATED_IMAGES_DIR, sticker_filename)
                sticker_image.save(sticker_filepath)
                
                # Create final embed with sticker result
                embed = discord.Embed(
                    title="🏷️ Sticker Style Applied - Nano Banana Bot",
                    description="**Style:** Black outline vector art sticker with transparent background",
                    color=0x00ff00
                )
                embed.add_field(name="Status", value="✅ Sticker style applied!", inline=False)
                embed.set_footer(text="Converted to sticker style")
                
                # Save image to buffer for Discord
                img_buffer = io.BytesIO()
                sticker_image.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # Create new style options view for further chaining
                new_style_view = StyleOptionsView(sticker_image, sticker_filename)
                
                # Send the sticker result
                sticker_file = discord.File(img_buffer, filename=sticker_filename)
                embed.set_image(url=f"attachment://{sticker_filename}")
                
                await interaction.edit_original_response(embed=embed, view=new_style_view, attachments=[sticker_file])
                
                logger.info(f"Successfully applied sticker style: '{sticker_filename}'")
            else:
                # Update embed to show failure
                embed = discord.Embed(
                    title="❌ Style Application Failed - Nano Banana Bot",
                    description="Failed to apply sticker style to the image.",
                    color=0xff0000
                )
                embed.add_field(name="Status", value="❌ Please try again.", inline=False)
                await interaction.edit_original_response(embed=embed, view=None)
                logger.error("Failed to apply sticker style")
                
        except Exception as e:
            logger.error(f"Error applying sticker style: {e}")
            # Update embed to show error
            embed = discord.Embed(
                title="❌ Error - Nano Banana Bot",
                description="An error occurred while applying the style.",
                color=0xff0000
            )
            embed.add_field(name="Status", value="❌ Please try again later.", inline=False)
            await interaction.edit_original_response(embed=embed, view=None)
    
    async def on_timeout(self):
        """Called when the view times out."""
        # Disable all buttons when timeout occurs
        for item in self.children:
            item.disabled = True

class ProcessRequestView(discord.ui.View):
    """View with buttons to process image generation request and apply style templates."""
    
    def __init__(self, text_content: str, images: List, timeout=300):
        super().__init__(timeout=timeout)
        self.text_content = text_content
        self.images = images
        self.original_text = text_content  # Keep original text for template processing
        
    @discord.ui.button(label='🎨 Process Request', style=discord.ButtonStyle.primary)
    async def process_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the process button click."""
        await self._process_request(interaction, button)
    
    @discord.ui.button(label='🏷️ Sticker', style=discord.ButtonStyle.secondary)
    async def sticker_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Apply sticker template and process."""
        # Apply the sticker template
        self._apply_template('sticker')
        
        # Update the embed to show the template was applied
        embed = discord.Embed(
            title="🏷️ Sticker Template Applied - Nano Banana Bot",
            description=f"**Template:** Sticker style with black outline and vector art\n**Prompt:** {self.text_content[:100] if self.text_content else 'Applied to images'}{'...' if len(self.text_content) > 100 else ''}",
            color=0x9932cc
        )
        embed.add_field(name="Status", value="🏷️ Template applied, processing...", inline=False)
        if self.images:
            embed.set_footer(text=f"Using {len(self.images)} input image(s) with sticker template")
        else:
            embed.set_footer(text="Generating sticker from text prompt")
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Process the request with the templated prompt
        await self._process_request(interaction, button, is_template_applied=True)
    
    def _apply_template(self, template_name: str):
        """Apply a template to modify the text content."""
        if template_name not in config.TEMPLATES:
            return
            
        template = config.TEMPLATES[template_name]
        
        if self.images and self.original_text.strip():
            # Image + text case
            self.text_content = template['image_and_text'].format(text=self.original_text)
        elif self.images:
            # Image only case
            self.text_content = template['image_only']
        else:
            # Text only case - use original text or a default if empty
            text_to_use = self.original_text.strip() or "an image"
            self.text_content = template['text_only'].format(text=text_to_use)
    
    async def _process_request(self, interaction: discord.Interaction, button: discord.ui.Button, is_template_applied: bool = False):
        """Handle the actual image processing."""
    async def _process_request(self, interaction: discord.Interaction, button: discord.ui.Button, is_template_applied: bool = False):
        """Handle the actual image processing."""
        try:
            # Disable all buttons to prevent multiple clicks
            for item in self.children:
                item.disabled = True
            
            if not is_template_applied:
                button.label = '⏳ Processing...'
                
                # Update embed to show processing
                embed = discord.Embed(
                    title="🎨 Processing Request - Nano Banana Bot",
                    color=0xffaa00
                )
                
                # Set description based on what we're processing
                if self.text_content.strip() and self.images:
                    embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
                    embed.set_footer(text=f"Using {len(self.images)} input image(s) with text prompt")
                elif self.text_content.strip():
                    embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
                    embed.set_footer(text="Generating from text prompt")
                elif self.images:
                    embed.description = "**Mode:** Transforming and enhancing images"
                    embed.set_footer(text=f"Processing {len(self.images)} input image(s)")
                
                embed.add_field(name="Status", value="🔄 Generating image with AI...", inline=False)
                    
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                # For template applied case, just update the existing embed
                embed = discord.Embed(
                    title="🎨 Processing Sticker Request - Nano Banana Bot",
                    description=f"**Prompt:** {self.text_content[:100] if self.text_content else 'Sticker template applied'}{'...' if len(self.text_content) > 100 else ''}",
                    color=0xffaa00
                )
                embed.add_field(name="Status", value="🔄 Generating sticker with AI...", inline=False)
                if self.images:
                    embed.set_footer(text=f"Using {len(self.images)} input image(s) with sticker template")
                else:
                    embed.set_footer(text="Generating sticker from text prompt")
                    
                await interaction.edit_original_response(embed=embed, view=self)
            
            # Generate the image based on available inputs
            generated_image = None
            if self.images and self.text_content.strip():
                # Text + Image(s) case
                if len(self.images) == 1:
                    generated_image = await get_image_generator().generate_image_from_text_and_image(
                        self.text_content, self.images[0]
                    )
                else:
                    generated_image = await get_image_generator().generate_image_from_text_and_images(
                        self.text_content, self.images
                    )
            elif self.images:
                # Image(s) only case - no text provided
                if len(self.images) == 1:
                    generated_image = await get_image_generator().generate_image_from_image_only(self.images[0])
                else:
                    generated_image = await get_image_generator().generate_image_from_images_only(self.images)
            elif self.text_content.strip():
                # Text only case
                generated_image = await get_image_generator().generate_image_from_text(self.text_content)
            else:
                # This shouldn't happen due to validation, but handle gracefully
                logger.error("No text content or images provided for generation")
                return
            
            if generated_image:
                # Save the generated image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"generated_{timestamp}.png"
                filepath = os.path.join(config.GENERATED_IMAGES_DIR, filename)
                generated_image.save(filepath)
                
                # Create final embed with result
                embed = discord.Embed(
                    title="🎨 Generated Image - Nano Banana Bot",
                    color=0x00ff00
                )
                
                # Set description and footer based on what was used for generation
                if self.text_content.strip() and self.images:
                    embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
                    embed.set_footer(text=f"Generated using {len(self.images)} input image(s) with text prompt")
                elif self.text_content.strip():
                    embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
                    embed.set_footer(text="Generated from text prompt")
                elif self.images:
                    embed.description = "**Result:** Enhanced and transformed images"
                    embed.set_footer(text=f"Generated from {len(self.images)} input image(s)")
                
                embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
                
                # Save image to buffer for Discord
                img_buffer = io.BytesIO()
                generated_image.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # Create style options view for chaining modifications
                style_view = StyleOptionsView(generated_image, filename)
                
                # Send the result as a file attachment with the embed and style options
                file = discord.File(img_buffer, filename=filename)
                embed.set_image(url=f"attachment://{filename}")
                
                # Send with style options for chaining
                await interaction.edit_original_response(embed=embed, view=style_view, attachments=[file])
                
                logger.info(f"Successfully generated and sent image for request: '{self.text_content[:50] if self.text_content.strip() else 'image-only transformation'}...'")
            else:
                # Update embed to show failure
                embed = discord.Embed(
                    title="❌ Generation Failed - Nano Banana Bot",
                    color=0xff0000
                )
                
                # Set description based on what failed
                if self.text_content.strip() and self.images:
                    embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
                elif self.text_content.strip():
                    embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
                elif self.images:
                    embed.description = f"**Failed:** Image transformation with {len(self.images)} input image(s)"
                
                embed.add_field(name="Status", value="❌ Failed to generate image. Please try again.", inline=False)
                await interaction.edit_original_response(embed=embed, view=None)
                logger.error("Failed to generate image")
                
        except Exception as e:
            logger.error(f"Error processing request: {e}")
            # Update embed to show error
            embed = discord.Embed(
                title="❌ Error - Nano Banana Bot",
                description="An error occurred while processing your request.",
                color=0xff0000
            )
            embed.add_field(name="Status", value="❌ Please try again later.", inline=False)
            await interaction.edit_original_response(embed=embed, view=None)
    
    async def on_timeout(self):
        """Called when the view times out."""
        # Disable all buttons when timeout occurs
        for item in self.children:
            item.disabled = True

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
        status_msg = await message.reply("📥 Preparing your request...")
        
        # Extract text (remove bot mention)
        text_content = message.content
        for mention in message.mentions:
            text_content = text_content.replace(f'<@{mention.id}>', '').strip()
        
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
        
        # Validate that we have either text or images (or both)
        if not text_content and not images:
            await status_msg.edit(content="❌ Please provide either text, images, or both for generation.")
            await message.add_reaction('❌')
            return
        
        # Create preview embed with the request details
        embed = discord.Embed(
            title="🎨 Image Generation Request - Nano Banana Bot",
            color=0x0099ff
        )
        
        # Set description based on what inputs we have
        if text_content and images:
            embed.description = f"**Prompt:** {text_content[:100]}{'...' if len(text_content) > 100 else ''}"
            embed.add_field(name="Input Images", value=f"📎 {len(images)} image(s) attached", inline=True)
            embed.add_field(name="Generation Type", value="🎨 Text + Image transformation", inline=True)
        elif text_content:
            embed.description = f"**Prompt:** {text_content[:100]}{'...' if len(text_content) > 100 else ''}"
            embed.add_field(name="Generation Type", value="📝 Text-to-image", inline=True)
        elif images:
            embed.description = "**Mode:** Image transformation and enhancement"
            embed.add_field(name="Input Images", value=f"📎 {len(images)} image(s) attached", inline=True)
            embed.add_field(name="Generation Type", value="🖼️ Image-only transformation", inline=True)
            
        embed.add_field(name="Status", value="⏸️ Waiting for confirmation", inline=False)
        embed.set_footer(text="Click the button below to process your request")
        
        # Create the view with the process button
        view = ProcessRequestView(text_content, images)
        
        # Update the status message with the embed and button
        await status_msg.edit(content=None, embed=embed, view=view)
        
        await message.add_reaction('📋')  # Reaction to indicate request received
        logger.info(f"Request preview created for: '{text_content[:50] if text_content.strip() else 'image-only request'}...'")
            
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
              "• Multiple image processing\n"
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