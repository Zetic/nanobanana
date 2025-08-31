import discord
from discord.ext import commands
import logging
import asyncio
import io
import os
from datetime import datetime
from typing import List, Dict, Any
from dataclasses import dataclass

import config
from image_utils import download_image, create_stitched_image
from genai_client import ImageGenerator

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class OutputItem:
    """Represents a generated output with its metadata."""
    image: Any  # PIL Image or similar
    filename: str
    prompt_used: str  # The prompt that generated this output
    timestamp: str

class PromptModal(discord.ui.Modal):
    """Modal for editing the prompt text."""
    
    def __init__(self, current_prompt: str = "", title: str = "Edit Prompt"):
        super().__init__(title=title)
        self.prompt_input = discord.ui.TextInput(
            label="Prompt",
            placeholder="Enter your prompt here...",
            default=current_prompt,
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False
        )
        self.add_item(self.prompt_input)
        self.new_prompt = None
    
    async def on_submit(self, interaction: discord.Interaction):
        self.new_prompt = self.prompt_input.value
        await interaction.response.defer()

class ProcessStyleSelect(discord.ui.Select):
    """Dropdown select for choosing art styles in ProcessRequestView."""
    
    def __init__(self, request_view):
        self.request_view = request_view
        options = []
        
        # Create options from available templates
        for style_key, style_data in config.TEMPLATES.items():
            options.append(discord.SelectOption(
                label=style_data['name'],
                description=style_data['template'][:100],  # Truncate description
                emoji=style_data['emoji'],
                value=style_key
            ))
        
        super().__init__(
            placeholder="Choose a style to apply...",
            min_values=1,
            max_values=1,
            options=options,
            row=1  # Place in second row below main buttons
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle style selection."""
        selected_style = self.values[0]
        await self.request_view.apply_style_and_process(interaction, selected_style)

class StyleSelect(discord.ui.Select):
    """Dropdown select for choosing art styles."""
    
    def __init__(self, style_view):
        self.style_view = style_view
        options = []
        
        # Create options from available templates
        for style_key, style_data in config.TEMPLATES.items():
            options.append(discord.SelectOption(
                label=style_data['name'],
                description=style_data['template'][:100],  # Truncate description
                emoji=style_data['emoji'],
                value=style_key
            ))
        
        super().__init__(
            placeholder="Choose a style to apply...",
            min_values=1,
            max_values=1,
            options=options,
            row=1  # Place in second row below navigation buttons
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle style selection."""
        selected_style = self.values[0]
        await self.style_view.apply_style(interaction, selected_style)

class StyleOptionsView(discord.ui.View):
    """View with style selection for chaining modifications on generated images."""
    
    def __init__(self, outputs: List[OutputItem], current_index: int = 0, original_text: str = "", original_images: List = None, timeout=300):
        super().__init__(timeout=timeout)
        self.outputs = outputs if outputs else []
        self.current_index = max(0, min(current_index, len(self.outputs) - 1)) if self.outputs else 0
        self.original_text = original_text
        self.original_images = original_images or []
        self.message = None  # Will be set when the view is first used
        self._timeout_disabled = False  # Flag to disable timeout handling
        
        # Add the style select dropdown
        self.add_item(StyleSelect(self))
        
        self._update_button_states()
    
    def disable_timeout_handling(self):
        """Disable timeout handling for this view to prevent staggered updates."""
        self._timeout_disabled = True
        # Stop the timeout by setting it to None, which cancels the timer
        self.timeout = None
    
    def _update_button_states(self):
        """Update button states based on number of outputs."""
        has_multiple = len(self.outputs) > 1
        
        # Find navigation buttons and update their disabled state
        for item in self.children:
            if hasattr(item, 'emoji') and item.emoji in ['⬅️', '➡️']:
                item.disabled = not has_multiple
    
    @property
    def current_output(self) -> OutputItem:
        """Get the currently selected output."""
        if self.outputs and 0 <= self.current_index < len(self.outputs):
            return self.outputs[self.current_index]
        return None
    
    @discord.ui.button(emoji='⬅️', style=discord.ButtonStyle.secondary, row=0)
    async def nav_left_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Navigate to previous output."""
        if len(self.outputs) <= 1:
            await interaction.response.defer()
            return
        self.current_index = (self.current_index - 1) % len(self.outputs)
        await self._update_display(interaction)
    
    @discord.ui.button(emoji='➡️', style=discord.ButtonStyle.secondary, row=0)
    async def nav_right_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Navigate to next output."""
        if len(self.outputs) <= 1:
            await interaction.response.defer()
            return
        self.current_index = (self.current_index + 1) % len(self.outputs)
        await self._update_display(interaction)
    
    async def _update_display(self, interaction: discord.Interaction):
        """Update the display with the current output."""
        if not self.outputs:
            return
        
        # Store message reference for timeout handling
        if self.message is None:
            self.message = interaction.message
            
        current_output = self.outputs[self.current_index]
        
        # Create embed for current output
        embed = discord.Embed(
            title=f"🎨 Generated Image - {bot.user.display_name}",
            color=0x00ff00
        )
        
        # Show both prompts if we have them
        prompt_used = current_output.prompt_used
        current_prompt = self.original_text
        
        if prompt_used:
            embed.add_field(name="Prompt used:", value=f"{prompt_used[:100]}{'...' if len(prompt_used) > 100 else ''}", inline=False)
        
        if current_prompt and current_prompt != prompt_used:
            embed.add_field(name="Current Prompt:", value=f"{current_prompt[:100]}{'...' if len(current_prompt) > 100 else ''}", inline=False)
        elif not prompt_used:
            embed.add_field(name="Current Prompt:", value=f"{current_prompt[:100] if current_prompt else 'No prompt'}{'...' if len(current_prompt) > 100 else ''}", inline=False)
        
        if len(self.outputs) > 1:
            embed.add_field(name="Step", value=f"{self.current_index + 1} of {len(self.outputs)}", inline=True)
        
        embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
        
        # Save current image to buffer for Discord
        img_buffer = io.BytesIO()
        current_output.image.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        # Send the updated result
        file = discord.File(img_buffer, filename=current_output.filename)
        embed.set_image(url=f"attachment://{current_output.filename}")
        
        await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
        
    @discord.ui.button(label='🎨 Process Prompt', style=discord.ButtonStyle.primary)
    async def process_prompt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Process the current generated image with a prompt."""
        if not self.current_output:
            return
            
        # Disable all buttons to prevent multiple clicks
        for item in self.children:
            item.disabled = True
            
        # Determine images to use - only use multiple original images when viewing a stitched preview
        images_to_use = [self.current_output.image]
        if (self.original_images and len(self.original_images) > 1 and 
            self.current_output.filename.startswith("stitched_")):
            # Only use multiple original images when viewing a stitched image preview
            images_to_use = self.original_images
        
        # Update button label to show processing
        button.label = '⏳ Processing...'
        
        # Update embed to show processing
        embed = discord.Embed(
            title="🎨 Processing Request - Nano Banana Bot",
            color=0xffaa00
        )
        
        # Set description based on what we're processing
        if self.original_text and self.original_text.strip():
            embed.description = f"**Prompt:** {self.original_text[:100]}{'...' if len(self.original_text) > 100 else ''}"
            embed.set_footer(text=f"Using {len(images_to_use)} input image(s) with text prompt")
        else:
            embed.description = "**Mode:** Transforming and enhancing images"
            embed.set_footer(text=f"Processing {len(images_to_use)} input image(s)")
        
        # Add input image to embed
        attachments = []
        if len(images_to_use) > 1:
            display_image = create_stitched_image(images_to_use)
        else:
            display_image = images_to_use[0]
        img_buffer = io.BytesIO()
        display_image.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        input_filename = f"processing_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        file = discord.File(img_buffer, filename=input_filename)
        embed.set_image(url=f"attachment://{input_filename}")
        attachments.append(file)
        
        embed.add_field(name="Status", value="🔄 Generating image with AI...", inline=False)
        
        await interaction.response.edit_message(embed=embed, view=self, attachments=attachments)
        
        # Process the image generation
        try:
            # Generate the image based on available inputs
            generated_image = None
            if self.original_text and self.original_text.strip():
                # Text + Image(s) case
                if len(images_to_use) == 1:
                    generated_image = await get_image_generator().generate_image_from_text_and_image(
                        self.original_text, images_to_use[0]
                    )
                else:
                    generated_image = await get_image_generator().generate_image_from_text_and_images(
                        self.original_text, images_to_use
                    )
            else:
                # Image(s) only case - no text provided
                if len(images_to_use) == 1:
                    generated_image = await get_image_generator().generate_image_from_image_only(images_to_use[0])
                else:
                    generated_image = await get_image_generator().generate_image_from_images_only(images_to_use)
            
            if generated_image:
                # Save the generated image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"generated_{timestamp}.png"
                filepath = os.path.join(config.GENERATED_IMAGES_DIR, filename)
                generated_image.save(filepath)
                
                # Create new output item
                new_output = OutputItem(
                    image=generated_image,
                    filename=filename,
                    prompt_used=self.original_text.strip() or "Image transformation",
                    timestamp=timestamp
                )
                
                # Add to existing outputs to create history
                all_outputs = self.outputs + [new_output]
                
                # Disable current view's timeout handling to prevent staggered updates
                self.disable_timeout_handling()
                
                # Create final embed with result
                embed = discord.Embed(
                    title=f"🎨 Generated Image - {bot.user.display_name}",
                    color=0x00ff00
                )
                
                # Show prompt used for this generation
                if self.original_text and self.original_text.strip():
                    embed.add_field(name="Prompt used:", value=f"{self.original_text[:100]}{'...' if len(self.original_text) > 100 else ''}", inline=False)
                else:
                    embed.add_field(name="Prompt used:", value="Image transformation", inline=False)
                
                # Show output count if we have multiple
                if len(all_outputs) > 1:
                    embed.add_field(name="Step", value=f"{len(all_outputs)} of {len(all_outputs)}", inline=True)
                
                embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
                
                # Set footer based on what was used for generation
                if self.original_text and self.original_text.strip():
                    embed.set_footer(text=f"Generated using {len(images_to_use)} input image(s) with text prompt")
                else:
                    embed.set_footer(text=f"Generated from {len(images_to_use)} input image(s)")
                
                # Save image to buffer for Discord
                img_buffer = io.BytesIO()
                generated_image.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # Create style options view for chaining modifications
                style_view = StyleOptionsView(all_outputs, len(all_outputs) - 1, self.original_text, self.original_images)
                
                # Send the result as a file attachment with the embed and style options
                file = discord.File(img_buffer, filename=filename)
                embed.set_image(url=f"attachment://{filename}")
                
                # Send with style options for chaining
                await interaction.edit_original_response(embed=embed, view=style_view, attachments=[file])
                
                # Store message reference for timeout handling
                style_view.message = await interaction.original_response()
                
                logger.info(f"Successfully generated and sent image for request: '{self.original_text[:50] if self.original_text and self.original_text.strip() else 'image-only transformation'}...'")
            else:
                # Update embed to show failure
                embed = discord.Embed(
                    title="❌ Generation Failed - Nano Banana Bot",
                    color=0xff0000
                )
                
                # Set description based on what failed
                if self.original_text and self.original_text.strip():
                    embed.description = f"**Prompt:** {self.original_text[:100]}{'...' if len(self.original_text) > 100 else ''}"
                else:
                    embed.description = f"**Failed:** Image transformation with {len(images_to_use)} input image(s)"
                
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
    
    
    async def _process_add_image(self, interaction: discord.Interaction, message, instruction_msg):
        """Process the uploaded image(s) and create a new stitched step."""
        try:
            # Check if message contains text - if so, update the current prompt
            if message.content.strip():
                self.original_text = message.content.strip()
            
            # Download all image attachments
            new_images = []
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    if attachment.size > config.MAX_IMAGE_SIZE:
                        await interaction.followup.send(
                            f"❌ **Image too large** - Maximum size is {config.MAX_IMAGE_SIZE // (1024*1024)}MB", 
                            ephemeral=True
                        )
                        return
                    
                    new_image = await download_image(attachment.url)
                    if new_image:
                        new_images.append(new_image)
                    else:
                        await interaction.followup.send("❌ **Failed to download image** - Please try again.", ephemeral=True)
                        return
            
            if not new_images:
                await interaction.followup.send("❌ **No valid images found** - Please try again.", ephemeral=True)
                return
            
            # Determine source images for the current output
            source_images = self._get_source_images_for_current_output()
            
            # Add the new images to the source images
            all_images = source_images + new_images
            
            # Create new stitched step (preview for display, not saved to disk)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stitched_image = create_stitched_image(all_images)
            
            # Create new output item (stitched preview for steps, not saved to disk)
            filename = f"stitched_{timestamp}.png"
            
            # Create new output item (stitched step for display)
            new_output = OutputItem(
                image=stitched_image,
                filename=filename,
                prompt_used=f"Combined from {len(source_images)} original image(s) + {len(new_images)} added image(s)",
                timestamp=timestamp
            )
            
            # Add to outputs and update current index to the new output
            self.outputs.append(new_output)
            self.current_index = len(self.outputs) - 1
            
            # Update original_images to include the new images
            self.original_images = all_images
            
            # Update the display to show the new output
            await self._update_display_after_add(interaction)
            
            # Delete the user's message with the image attachment to clean up
            try:
                await message.delete()
            except:
                pass  # Ignore if we can't delete
            
            # Delete the instruction message to clean up ephemeral messages
            try:
                await instruction_msg.delete()
            except:
                pass  # Ignore if we can't delete
            
        except Exception as e:
            logger.error(f"Error processing added image: {e}")
            await interaction.followup.send("❌ **Error processing image** - Please try again.", ephemeral=True)
    
    def _get_source_images_for_current_output(self):
        """Get the source images for the current output."""
        if not self.current_output:
            return []
            
        current_output = self.current_output
        
        # If the current output is from original input images, use those
        if current_output.filename.startswith("input_") and self.original_images:
            return self.original_images.copy()
        
        # If it's a generated output and we have original images, use those
        if self.original_images:
            return self.original_images.copy()
        
        # Fallback: use the current output image
        return [current_output.image]
    
    async def _update_display_after_add(self, interaction: discord.Interaction):
        """Update the display after adding an image (similar to _update_display but for followup)."""
        if not self.outputs:
            return
        
        current_output = self.outputs[self.current_index]
        
        # Create embed for current output
        embed = discord.Embed(
            title=f"🎨 Generated Image - {bot.user.display_name}",
            color=0x00ff00
        )
        
        # Show prompts
        prompt_used = current_output.prompt_used
        current_prompt = self.original_text
        
        if prompt_used:
            embed.add_field(name="Prompt used:", value=f"{prompt_used[:100]}{'...' if len(prompt_used) > 100 else ''}", inline=False)
        
        if current_prompt and current_prompt != prompt_used:
            embed.add_field(name="Current Prompt:", value=f"{current_prompt[:100]}{'...' if len(current_prompt) > 100 else ''}", inline=False)
        elif not prompt_used:
            embed.add_field(name="Current Prompt:", value=f"{current_prompt[:100] if current_prompt else 'No prompt'}{'...' if len(current_prompt) > 100 else ''}", inline=False)
        
        if len(self.outputs) > 1:
            embed.add_field(name="Step", value=f"{self.current_index + 1} of {len(self.outputs)}", inline=True)
        
        embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
        
        # Save current image to buffer for Discord
        img_buffer = io.BytesIO()
        current_output.image.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        # Update the original message with the new output
        file = discord.File(img_buffer, filename=current_output.filename)
        embed.set_image(url=f"attachment://{current_output.filename}")
        
        # Update button states
        self._update_button_states()
        
        await interaction.edit_original_response(embed=embed, view=self, attachments=[file])



    @discord.ui.button(label='✏️ Edit Prompt', style=discord.ButtonStyle.secondary)
    async def edit_prompt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show modal to edit prompt for the generated image."""
        # Use the current output's prompt_used as the default value
        default_prompt = ""
        if self.current_output and self.current_output.prompt_used:
            default_prompt = self.current_output.prompt_used
        
        modal = PromptModal(default_prompt, "Edit Prompt for Generated Image")
        await interaction.response.send_modal(modal)
        
        # Wait for modal submission
        await modal.wait()
        
        if modal.new_prompt is not None:
            # Update the current prompt and refresh the display
            new_text = modal.new_prompt.strip()
            self.original_text = new_text  # Update the current prompt
            
            # Refresh the display with the updated prompt using edit_original_response
            if not self.outputs:
                return
                
            current_output = self.outputs[self.current_index]
            
            # Create embed for current output
            embed = discord.Embed(
                title=f"🎨 Generated Image - {bot.user.display_name}",
                color=0x00ff00
            )
            
            # Show both prompts if we have them
            prompt_used = current_output.prompt_used
            current_prompt = self.original_text
            
            if prompt_used:
                embed.add_field(name="Prompt used:", value=f"{prompt_used[:100]}{'...' if len(prompt_used) > 100 else ''}", inline=False)
            
            if current_prompt and current_prompt != prompt_used:
                embed.add_field(name="Current Prompt:", value=f"{current_prompt[:100]}{'...' if len(current_prompt) > 100 else ''}", inline=False)
            elif not prompt_used:
                embed.add_field(name="Current Prompt:", value=f"{current_prompt[:100] if current_prompt else 'No prompt'}{'...' if len(current_prompt) > 100 else ''}", inline=False)
            
            if len(self.outputs) > 1:
                embed.add_field(name="Step", value=f"{self.current_index + 1} of {len(self.outputs)}", inline=True)
            
            embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
            
            # Save current image to buffer for Discord
            img_buffer = io.BytesIO()
            current_output.image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            # Send the updated result
            file = discord.File(img_buffer, filename=current_output.filename)
            embed.set_image(url=f"attachment://{current_output.filename}")
            
            await interaction.edit_original_response(embed=embed, view=self, attachments=[file])
        
    @discord.ui.button(label='📎 Add Image', style=discord.ButtonStyle.secondary)
    async def add_image_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Add an image to the current output for combined processing."""
        # Defer the interaction to keep it bound to the original message
        await interaction.response.defer()
        
        # Send instructions to user for uploading an image
        instruction_msg = await interaction.followup.send(
            "📎 **Upload image(s) now**", 
            ephemeral=True
        )
        
        # Set up a temporary listener for the next message from this user
        def check(message):
            return (message.author.id == interaction.user.id and 
                   message.channel.id == interaction.channel.id and
                   message.attachments and
                   any(attachment.filename.lower().endswith(ext) 
                       for attachment in message.attachments 
                       for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']))
        
        try:
            # Wait for user to send a message with an image attachment
            message = await interaction.client.wait_for('message', check=check, timeout=60.0)
            
            # Process the attached image
            await self._process_add_image(interaction, message, instruction_msg)
            
        except asyncio.TimeoutError:
            # Just delete the instruction message on timeout, no additional message
            try:
                await instruction_msg.delete()
            except:
                pass
    
    async def apply_style(self, interaction: discord.Interaction, style_key: str):
        """Apply selected style to the generated image."""
        if not self.current_output:
            return
            
        try:
            # Disable all buttons to prevent multiple clicks
            for item in self.children:
                item.disabled = True
            
            # Get style template
            style_template = config.TEMPLATES.get(style_key)
            if not style_template:
                logger.error(f"Unknown style: {style_key}")
                return
                
            style_name = style_template['name']
            style_prompt = style_template['template']
            
            # Update embed to show processing (using consistent embed style)
            embed = discord.Embed(
                title="🎨 Processing Request - Nano Banana Bot",
                color=0xffaa00
            )
            
            embed.description = f"**Prompt:** {style_prompt[:100]}{'...' if len(style_prompt) > 100 else ''}"
            embed.set_footer(text=f"Using 1 input image(s) with {style_name.lower()} template")
            
            # Add input image to embed
            img_buffer = io.BytesIO()
            self.current_output.image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            input_filename = f"{style_key}_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            file = discord.File(img_buffer, filename=input_filename)
            embed.set_image(url=f"attachment://{input_filename}")
            
            embed.add_field(name="Status", value=f"🔄 Generating {style_name.lower()} with AI...", inline=False)
            
            await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
            
            # Generate new image with selected style
            styled_image = await get_image_generator().generate_image_from_text_and_image(
                style_prompt, self.current_output.image
            )
            
            if styled_image:
                # Save the new styled image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                styled_filename = f"{style_key}_{timestamp}.png"
                styled_filepath = os.path.join(config.GENERATED_IMAGES_DIR, styled_filename)
                styled_image.save(styled_filepath)
                
                # Create new output item for the styled image
                styled_output = OutputItem(
                    image=styled_image,
                    filename=styled_filename,
                    prompt_used=f"{style_name} style: {style_prompt}",
                    timestamp=timestamp
                )
                
                # Add to outputs history
                new_outputs = self.outputs + [styled_output]
                
                # Disable current view's timeout handling to prevent staggered updates
                self.disable_timeout_handling()
                
                # Create final embed with styled result
                embed = discord.Embed(
                    title=f"🎨 Generated Image - {bot.user.display_name}",
                    color=0x00ff00
                )
                
                # Show prompt used for this generation
                embed.add_field(name="Prompt used:", value=f"{style_prompt[:100]}{'...' if len(style_prompt) > 100 else ''}", inline=False)
                
                # Show output count if we have multiple
                if len(new_outputs) > 1:
                    embed.add_field(name="Step", value=f"{len(new_outputs)} of {len(new_outputs)}", inline=True)
                
                embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
                
                # Set footer based on what was used for generation
                embed.set_footer(text=f"Generated using 1 input image(s) with {style_name.lower()} template")
                
                # Save image to buffer for Discord
                img_buffer = io.BytesIO()
                styled_image.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # Create new style options view for further chaining
                new_style_view = StyleOptionsView(new_outputs, len(new_outputs) - 1, self.original_text, self.original_images)
                
                # Send the styled result
                styled_file = discord.File(img_buffer, filename=styled_filename)
                embed.set_image(url=f"attachment://{styled_filename}")
                
                await interaction.edit_original_response(embed=embed, view=new_style_view, attachments=[styled_file])
                
                # Store message reference for timeout handling
                new_style_view.message = await interaction.original_response()
                
                logger.info(f"Successfully applied {style_name} style: '{styled_filename}'")
            else:
                # Update embed to show failure
                embed = discord.Embed(
                    title="❌ Generation Failed - Nano Banana Bot",
                    description=f"Failed to apply {style_name.lower()} style to the image.",
                    color=0xff0000
                )
                embed.add_field(name="Status", value="❌ Please try again.", inline=False)
                await interaction.edit_original_response(embed=embed, view=None)
                logger.error(f"Failed to apply {style_name} style")
                
        except Exception as e:
            logger.error(f"Error applying {style_key} style: {e}")
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
        # If timeout handling is disabled, don't process timeout
        if self._timeout_disabled:
            return
            
        # Disable all buttons when timeout occurs
        for item in self.children:
            item.disabled = True
        
        # If no message reference or no outputs, just disable buttons
        if not self.message or not self.outputs:
            try:
                await self.message.edit(view=None)
            except:
                pass  # Message might be deleted or inaccessible
            return
        
        try:
            # Create files and embeds for all outputs (up to Discord's limit)
            # Filter out stitched images, only show true outputs
            true_outputs = [output for output in self.outputs if not output.filename.startswith("stitched_")]
            files = []
            embeds = []
            
            # Discord has a limit of 10 embeds per message
            max_embeds = min(10, len(true_outputs))
            
            for i, output in enumerate(true_outputs[:max_embeds]):
                # Create file for this output
                img_buffer = io.BytesIO()
                output.image.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # Create unique filename to avoid conflicts
                timeout_filename = f"timeout_{i}_{output.filename}"
                file = discord.File(img_buffer, filename=timeout_filename)
                files.append(file)
                
                # Create embed for this output
                embed = discord.Embed(
                    title=f"🕒 Final Output {i + 1}/{len(true_outputs)} (Timed Out)",
                    color=0xff9900
                )
                
                # Add prompt information
                if output.prompt_used:
                    embed.add_field(
                        name="Prompt used:", 
                        value=f"{output.prompt_used[:100]}{'...' if len(output.prompt_used) > 100 else ''}", 
                        inline=False
                    )
                
                # Add timestamp
                embed.add_field(name="Generated:", value=output.timestamp, inline=True)
                
                # Set the image for this embed
                embed.set_image(url=f"attachment://{timeout_filename}")
                
                # Add footer for the first embed
                if i == 0:
                    if len(true_outputs) > max_embeds:
                        embed.set_footer(text=f"Session timed out. Showing {max_embeds} of {len(true_outputs)} outputs.")
                    else:
                        embed.set_footer(text="Session timed out. Here are all your outputs.")
                
                embeds.append(embed)
            
            # If no outputs were generated, create a single embed indicating that
            if not embeds:
                embed = discord.Embed(
                    title="🕒 Session Timed Out",
                    description="No outputs were generated during this session.",
                    color=0xff9900
                )
                embed.set_footer(text="The interactive session has expired.")
                embeds.append(embed)
            
            # Update the original message with all outputs
            content = "🕒 **Timed out!** Here are all your output images:"
            if len(true_outputs) > max_embeds:
                content += f"\n*Showing {max_embeds} of {len(true_outputs)} outputs due to Discord limits.*"
            elif not true_outputs:
                content = "🕒 **Timed out!** No images were generated during this session."
            
            await self.message.edit(
                content=content,
                embeds=embeds,
                attachments=files,
                view=None
            )
            
            logger.info(f"Successfully updated timeout message with {len(embeds)} embeds and {len(files)} files")
            
        except Exception as e:
            logger.error(f"Error updating message on timeout: {e}")
            # Fallback - just disable the view
            try:
                await self.message.edit(view=None)
            except:
                pass

class ProcessRequestView(discord.ui.View):
    """View with buttons to process image generation request and apply style templates."""
    
    def __init__(self, text_content: str, images: List, existing_outputs: List[OutputItem] = None, timeout=300):
        super().__init__(timeout=timeout)
        self.text_content = text_content
        self.images = images
        self.original_text = text_content  # Keep original text for template processing
        self.existing_outputs = existing_outputs or []
        
        # Add the style select dropdown
        self.add_item(ProcessStyleSelect(self))
        
    @discord.ui.button(label='🎨 Process Prompt', style=discord.ButtonStyle.primary)
    async def process_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the process button click."""
        await self._process_request(interaction, button)
    
    @discord.ui.button(label='✏️ Edit Prompt', style=discord.ButtonStyle.secondary)
    async def edit_prompt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show modal to edit the prompt."""
        modal = PromptModal(self.text_content, "Edit Prompt")
        await interaction.response.send_modal(modal)
        
        # Wait for modal submission
        await modal.wait()
        
        if modal.new_prompt is not None:
            # Update the text content
            self.text_content = modal.new_prompt.strip()
            self.original_text = self.text_content  # Update original text as well
            
            # Update the embed to show the new prompt
            embed = discord.Embed(
                title="🎨 Image Generation Request - Nano Banana Bot",
                color=0x0099ff
            )
            
            # Set description based on what inputs we have
            if self.text_content and self.images:
                embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
                embed.add_field(name="Input Images", value=f"📎 {len(self.images)} image(s) attached", inline=True)
                embed.add_field(name="Generation Type", value="🎨 Text + Image transformation", inline=True)
            elif self.text_content:
                embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
                embed.add_field(name="Generation Type", value="📝 Text-to-image", inline=True)
            elif self.images:
                embed.description = "**Mode:** Image transformation and enhancement"
                embed.add_field(name="Input Images", value=f"📎 {len(self.images)} image(s) attached", inline=True)
                embed.add_field(name="Generation Type", value="🖼️ Image-only transformation", inline=True)
                
            embed.add_field(name="Status", value="⏸️ Waiting for confirmation", inline=False)
            embed.set_footer(text="Click the button below to process your request")
            
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
    
    @discord.ui.button(label='📎 Add Image', style=discord.ButtonStyle.secondary)
    async def add_image_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Add an image to the current request before processing."""
        # Defer the interaction to keep it bound to the original message
        await interaction.response.defer()
        
        # Send instructions to user for uploading an image
        instruction_msg = await interaction.followup.send(
            "📎 **Upload image(s) now**", 
            ephemeral=True
        )
        
        # Set up a temporary listener for the next message from this user
        def check(message):
            return (message.author.id == interaction.user.id and 
                   message.channel.id == interaction.channel.id and
                   message.attachments and
                   any(attachment.filename.lower().endswith(ext) 
                       for attachment in message.attachments 
                       for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']))
        
        try:
            # Wait for user to send a message with an image attachment
            message = await interaction.client.wait_for('message', check=check, timeout=60.0)
            
            # Process the attached image
            await self._process_add_image_to_request(interaction, message, instruction_msg)
            
        except asyncio.TimeoutError:
            # Just delete the instruction message on timeout, no additional message
            try:
                await instruction_msg.delete()
            except:
                pass
    
    async def _process_add_image_to_request(self, interaction: discord.Interaction, message, instruction_msg):
        """Process the uploaded image(s) and add them to the current request."""
        try:
            # Check if message contains text - if so, update the current prompt
            if message.content.strip():
                self.text_content = message.content.strip()
                self.original_text = message.content.strip()  # Update original text as well
            
            # Download all image attachments
            new_images = []
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    if attachment.size > config.MAX_IMAGE_SIZE:
                        await interaction.followup.send(
                            f"❌ **Image too large** - Maximum size is {config.MAX_IMAGE_SIZE // (1024*1024)}MB", 
                            ephemeral=True
                        )
                        return
                    
                    new_image = await download_image(attachment.url)
                    if new_image:
                        new_images.append(new_image)
                    else:
                        await interaction.followup.send("❌ **Failed to download image** - Please try again.", ephemeral=True)
                        return
            
            if not new_images:
                await interaction.followup.send("❌ **No valid images found** - Please try again.", ephemeral=True)
                return
            
            # Add the images to the request
            self.images.extend(new_images)
            
            # Update the display to show the new request configuration
            await self._update_request_display_after_add(interaction)
            
            # Delete the user's message with the image attachment to clean up
            try:
                await message.delete()
            except:
                pass  # Ignore if we can't delete
            
            # Delete the instruction message to clean up ephemeral messages
            try:
                await instruction_msg.delete()
            except:
                pass  # Ignore if we can't delete
            
        except Exception as e:
            logger.error(f"Error adding image to request: {e}")
            await interaction.followup.send("❌ **Error processing image** - Please try again.", ephemeral=True)
    
    async def _update_request_display_after_add(self, interaction: discord.Interaction):
        """Update the request display after adding an image."""
        # Create updated embed
        embed = discord.Embed(
            title="🎨 Image Generation Request - Nano Banana Bot",
            color=0x0099ff
        )
        
        # Set description based on what inputs we have
        if self.text_content and self.images:
            embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
            embed.add_field(name="Input Images", value=f"📎 {len(self.images)} image(s) attached", inline=True)
            embed.add_field(name="Generation Type", value="🎨 Text + Image transformation", inline=True)
        elif self.text_content:
            embed.description = f"**Prompt:** {self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}"
            embed.add_field(name="Generation Type", value="📝 Text-to-image", inline=True)
        elif self.images:
            embed.description = "**Mode:** Image transformation and enhancement"
            embed.add_field(name="Input Images", value=f"📎 {len(self.images)} image(s) attached", inline=True)
            embed.add_field(name="Generation Type", value="🖼️ Image-only transformation", inline=True)
            
        embed.add_field(name="Status", value="⏸️ Waiting for confirmation", inline=False)
        embed.set_footer(text="Click the button below to process your request")
        
        # Show preview image if we have images
        attachments = []
        if self.images:
            if len(self.images) > 1:
                display_image = create_stitched_image(self.images)
            else:
                display_image = self.images[0]
            img_buffer = io.BytesIO()
            display_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            preview_filename = f"preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            file = discord.File(img_buffer, filename=preview_filename)
            embed.set_image(url=f"attachment://{preview_filename}")
            attachments.append(file)
        
        await interaction.edit_original_response(embed=embed, view=self, attachments=attachments)

    
    async def apply_style_and_process(self, interaction: discord.Interaction, style_key: str):
        """Apply selected style template and process."""
        # Apply the selected template
        self._apply_template(style_key)
        
        # Get style info
        style_template = config.TEMPLATES.get(style_key)
        if not style_template:
            logger.error(f"Unknown style: {style_key}")
            return
            
        style_name = style_template['name']
        
        # Update the embed to show processing (using consistent style)
        embed = discord.Embed(
            title="🎨 Processing Request - Nano Banana Bot",
            description=f"**Prompt:** {self.text_content[:100] if self.text_content else f'{style_name} template applied'}{'...' if len(self.text_content) > 100 else ''}",
            color=0xffaa00
        )
        embed.add_field(name="Status", value=f"🔄 Generating {style_name.lower()} with AI...", inline=False)
        if self.images:
            embed.set_footer(text=f"Using {len(self.images)} input image(s) with {style_name.lower()} template")
        else:
            embed.set_footer(text=f"Generating {style_name.lower()} from text prompt")
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Process the request with the templated prompt
        await self._process_request(interaction, None, is_template_applied=True)
    
    def _apply_template(self, template_name: str):
        """Apply a template to modify the text content."""
        if template_name not in config.TEMPLATES:
            return
            
        template = config.TEMPLATES[template_name]
        
        # Simply replace the text content with the template
        self.text_content = template['template']
    
    async def _process_request(self, interaction: discord.Interaction, button: discord.ui.Button = None, is_template_applied: bool = False):
        """Handle the actual image processing."""
        try:
            # Disable all buttons to prevent multiple clicks
            for item in self.children:
                item.disabled = True
            
            if not is_template_applied:
                if button:
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
                
                # Add input image to embed if available
                attachments = []
                if self.images:
                    # Use stitched image for display when multiple images, single image otherwise
                    if len(self.images) > 1:
                        display_image = create_stitched_image(self.images)
                    else:
                        display_image = self.images[0]
                    img_buffer = io.BytesIO()
                    display_image.save(img_buffer, format='PNG')
                    img_buffer.seek(0)
                    input_filename = f"processing_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    file = discord.File(img_buffer, filename=input_filename)
                    embed.set_image(url=f"attachment://{input_filename}")
                    attachments.append(file)
                
                embed.add_field(name="Status", value="🔄 Generating image with AI...", inline=False)
                    
                await interaction.response.edit_message(embed=embed, view=self, attachments=attachments)
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
                    # Use stitched image for display when multiple images, single image otherwise
                    if len(self.images) > 1:
                        display_image = create_stitched_image(self.images)
                    else:
                        display_image = self.images[0]
                    img_buffer = io.BytesIO()
                    display_image.save(img_buffer, format='PNG')
                    img_buffer.seek(0)
                    input_filename = f"sticker_input_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    file = discord.File(img_buffer, filename=input_filename)
                    embed.set_image(url=f"attachment://{input_filename}")
                    await interaction.edit_original_response(embed=embed, view=self, attachments=[file])
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
                
                # Create new output item
                new_output = OutputItem(
                    image=generated_image,
                    filename=filename,
                    prompt_used=self.text_content.strip() or "Image transformation",
                    timestamp=timestamp
                )
                
                # Add to existing outputs to create history (input images first, then generated)
                all_outputs = self.existing_outputs + [new_output]
                
                # Create final embed with result
                embed = discord.Embed(
                    title=f"🎨 Generated Image - {bot.user.display_name}",
                    color=0x00ff00
                )
                
                # Show prompt used for this generation
                if self.text_content.strip():
                    embed.add_field(name="Prompt used:", value=f"{self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}", inline=False)
                else:
                    embed.add_field(name="Prompt used:", value="Image transformation", inline=False)
                
                # Show output count if we have multiple
                if len(all_outputs) > 1:
                    embed.add_field(name="Step", value=f"{len(all_outputs)} of {len(all_outputs)}", inline=True)
                
                embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
                
                # Set footer based on what was used for generation
                if self.text_content.strip() and self.images:
                    embed.set_footer(text=f"Generated using {len(self.images)} input image(s) with text prompt")
                elif self.text_content.strip():
                    embed.set_footer(text="Generated from text prompt")
                elif self.images:
                    embed.set_footer(text=f"Generated from {len(self.images)} input image(s)")
                
                # Save image to buffer for Discord
                img_buffer = io.BytesIO()
                generated_image.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                
                # Create style options view for chaining modifications
                # Use the original images from the request
                original_images_for_view = self.images
                
                style_view = StyleOptionsView(all_outputs, len(all_outputs) - 1, self.original_text, original_images_for_view)
                
                # Send the result as a file attachment with the embed and style options
                file = discord.File(img_buffer, filename=filename)
                embed.set_image(url=f"attachment://{filename}")
                
                # Send with style options for chaining
                await interaction.edit_original_response(embed=embed, view=style_view, attachments=[file])
                
                # Store message reference for timeout handling
                style_view.message = await interaction.original_response()
                
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
    
    # Debug logging for mention detection
    logger.debug(f"Message from {message.author.id}: '{message.content[:50]}...'")
    logger.debug(f"Message mentions: {[user.id for user in message.mentions]}")
    logger.debug(f"Bot user ID: {bot.user.id}")
    logger.debug(f"Is reply: {message.reference is not None}")
    if message.reference:
        logger.debug(f"Reply to message ID: {message.reference.message_id}")
    
    # Only process messages that mention the bot
    # This includes:
    # - Direct mentions: "@BotName create an image" 
    # - Replies with mentions: "@BotName use this image" (reply to bot's message)
    # This excludes:
    # - Replies without mentions: "use this image" (reply to bot's message without @)
    # - Regular messages without mentions: "hello"
    
    # Check if bot is mentioned AND the mention is explicit in the message content
    bot_mentioned_explicitly = (
        bot.user in message.mentions and 
        (f'<@{bot.user.id}>' in message.content or f'<@!{bot.user.id}>' in message.content)
    )
    
    if bot_mentioned_explicitly:
        logger.info(f"Processing message from {message.author.id} (explicitly mentioned bot)")
        await handle_generation_request(message)
    else:
        if bot.user in message.mentions:
            logger.warning(f"Bot in mentions list but not explicitly mentioned in content. Message: '{message.content}' | Mentions: {[f'<@{u.id}>' for u in message.mentions]}")
        logger.debug(f"Ignoring message from {message.author.id} (no explicit bot mention)")
    
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
        
        # Check if this is a reply and extract images from the referenced message
        if message.reference and message.reference.message_id:
            try:
                # Fetch the referenced message
                channel = message.channel
                referenced_message = await channel.fetch_message(message.reference.message_id)
                
                # Log information about the referenced message
                if referenced_message.author == bot.user:
                    logger.info(f"Referenced message is from bot itself - extracting images from bot's own message")
                    logger.info(f"Bot message has {len(referenced_message.attachments)} attachments")
                else:
                    logger.info(f"Referenced message is from user {referenced_message.author.id}")
                    logger.info(f"User message has {len(referenced_message.attachments)} attachments")
                
                # Extract images from the referenced message (including bot's own messages)
                if referenced_message.attachments:
                    await status_msg.edit(content="📥 Downloading images from reply...")
                    logger.info(f"Processing {len(referenced_message.attachments)} attachments from referenced message")
                    for attachment in referenced_message.attachments[:config.MAX_IMAGES - len(images)]:
                        logger.info(f"Processing attachment: {attachment.filename} ({attachment.size} bytes) - URL: {attachment.url}")
                        if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                            if attachment.size <= config.MAX_IMAGE_SIZE:
                                logger.info(f"Attempting to download image: {attachment.filename}")
                                image = await download_image(attachment.url)
                                if image:
                                    images.append(image)
                                    logger.info(f"Successfully downloaded and added image from reply: {attachment.filename}")
                                else:
                                    logger.error(f"Failed to download image from reply: {attachment.filename}")
                            else:
                                logger.warning(f"Image too large in reply: {attachment.filename} ({attachment.size} bytes)")
                        else:
                            logger.debug(f"Skipping non-image attachment: {attachment.filename}")
                        
                        # Stop if we've reached the maximum number of images
                        if len(images) >= config.MAX_IMAGES:
                            logger.info(f"Reached maximum image limit ({config.MAX_IMAGES}), stopping")
                            break
                else:
                    if referenced_message.author == bot.user:
                        logger.warning(f"Bot message has no attachments! This might indicate the bot's images aren't being saved as attachments")
                        logger.info(f"Bot message content: '{referenced_message.content[:100]}...'")
                        logger.info(f"Bot message embeds: {len(referenced_message.embeds)}")
                        if referenced_message.embeds:
                            for i, embed in enumerate(referenced_message.embeds):
                                logger.info(f"Embed {i}: title='{embed.title}', image_url='{embed.image.url if embed.image else 'None'}'")
                                
                                # Try to extract image from embed
                                if embed.image and embed.image.url:
                                    if len(images) < config.MAX_IMAGES:
                                        logger.info(f"Attempting to download image from embed: {embed.image.url}")
                                        await status_msg.edit(content="📥 Downloading image from embed...")
                                        image = await download_image(embed.image.url)
                                        if image:
                                            images.append(image)
                                            logger.info(f"Successfully downloaded and added image from bot's embed")
                                        else:
                                            logger.error(f"Failed to download image from bot's embed: {embed.image.url}")
                                    else:
                                        logger.info(f"Reached maximum image limit, skipping embed image")
                    else:
                        logger.info(f"Referenced user message has no attachments to extract")
                            
            except Exception as e:
                logger.warning(f"Could not fetch referenced message: {e}")
        
        # Set default text if no text content provided
        if not text_content:
            text_content = "A banana"
            logger.info("No text provided, using default prompt: 'A banana'")
        
        # Log final image count and summary
        logger.info(f"Final processing summary: {len(images)} images extracted, text content: '{text_content[:50]}{'...' if len(text_content) > 50 else ''}'")
        if images:
            logger.info(f"Images will be used for image-to-image generation with prompt: '{text_content}'")
        else:
            logger.info(f"No images found, will do text-to-image generation with prompt: '{text_content}'")
        
        # Keep the original message (no longer deleting it)
        
        # Don't create any OutputItems for initial uploads - show images directly in embed
        input_outputs = []
        
        # Create preview embed with the request details
        embed = discord.Embed(
            title=f"🎨 Image Generation Request - {bot.user.display_name}",
            color=0x0099ff
        )
        
        # Set description based on what inputs we have
        attachments = []
        if text_content and images:
            embed.description = f"**Prompt:** {text_content[:100]}{'...' if len(text_content) > 100 else ''}"
            embed.add_field(name="Input Images", value=f"📎 {len(images)} image(s) attached", inline=True)
            embed.add_field(name="Generation Type", value="🎨 Text + Image transformation", inline=True)
            # Use stitched image for display when multiple images, single image otherwise
            if len(images) > 1:
                display_image = create_stitched_image(images)
                embed.add_field(name="Preview", value="📋 Stitched preview", inline=True)
            else:
                display_image = images[0]
            img_buffer = io.BytesIO()
            display_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            preview_filename = f"preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            file = discord.File(img_buffer, filename=preview_filename)
            embed.set_image(url=f"attachment://{preview_filename}")
            attachments.append(file)
        elif text_content:
            embed.description = f"**Prompt:** {text_content[:100]}{'...' if len(text_content) > 100 else ''}"
            embed.add_field(name="Generation Type", value="📝 Text-to-image", inline=True)
        elif images:
            embed.description = "**Mode:** Image transformation and enhancement"
            embed.add_field(name="Input Images", value=f"📎 {len(images)} image(s) attached", inline=True)
            embed.add_field(name="Generation Type", value="🖼️ Image-only transformation", inline=True)
            # Use stitched image for display when multiple images, single image otherwise
            if len(images) > 1:
                display_image = create_stitched_image(images)
                embed.add_field(name="Preview", value="📋 Stitched preview", inline=True)
            else:
                display_image = images[0]
            img_buffer = io.BytesIO()
            display_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            preview_filename = f"preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            file = discord.File(img_buffer, filename=preview_filename)
            embed.set_image(url=f"attachment://{preview_filename}")
            attachments.append(file)
            
        embed.add_field(name="Status", value="⏸️ Waiting for confirmation", inline=False)
        embed.set_footer(text="Click the button below to process your request")
        
        # Create the view with the process button (no existing outputs since we don't create OutputItems for initial uploads)
        view = ProcessRequestView(text_content, images, existing_outputs=[])
        
        # Update the status message with the embed and button
        await status_msg.edit(content=None, embed=embed, view=view, attachments=attachments)
        
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
        title=f"🍌 {bot.user.display_name} - Help",
        description="I'm a bot that generates images using Google's AI!",
        color=0xffff00
    )
    embed.add_field(
        name="📋 How to use",
        value=f"Just mention me ({bot.user.mention}) in a message with your prompt and optionally attach images!",
        inline=False
    )
    embed.add_field(
        name="🎨 Examples",
        value=f"• `{bot.user.mention} Create a nano banana in space`\n"
              f"• `{bot.user.mention} Make this cat magical` (with image attached)\n"
              f"• `{bot.user.mention} Transform this into cyberpunk style` (with multiple images)",
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
    
    logger.info("Starting Discord Bot...")
    bot.run(config.DISCORD_TOKEN)

if __name__ == "__main__":
    main()