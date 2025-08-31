"""
Nano Banana Discord Bot - Main Bot Implementation

This bot uses persistent Discord UI Views to prevent timeout issues:
- All View classes use timeout=None to prevent automatic timeouts
- All interactive components (buttons, selects) have custom_id for persistence
- Views are registered on bot startup to handle interactions after restarts
- Safe interaction response handling prevents token expiry issues

Architecture:
- StyleOptionsView: Handles generated image interactions (navigation, style application)
- ProcessRequestView: Handles initial request processing and prompt editing
- Both views use persistent custom_ids that survive bot restarts
"""

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

async def safe_interaction_response(interaction: discord.Interaction, **kwargs):
    """Safely respond to an interaction, handling token expiry by falling back to message editing."""
    try:
        if interaction.response.is_done():
            # Response already sent, edit the original response
            await interaction.edit_original_response(**kwargs)
        else:
            # First response, edit the message
            await interaction.response.edit_message(**kwargs)
    except discord.NotFound:
        # Interaction token expired, try to edit the message directly if we have it
        if hasattr(interaction, 'message') and interaction.message:
            try:
                await interaction.message.edit(**kwargs)
            except Exception as e:
                logger.warning(f"Failed to edit message after token expiry: {e}")
    except discord.HTTPException as e:
        if e.code == 10062:  # Unknown interaction
            # Token expired, try direct message edit
            if hasattr(interaction, 'message') and interaction.message:
                try:
                    await interaction.message.edit(**kwargs)
                except Exception as e2:
                    logger.warning(f"Failed to edit message after token expiry: {e2}")
        else:
            raise

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
                description=style_data['image_only'][:100],  # Truncate description
                emoji=style_data['emoji'],
                value=style_key
            ))
        
        super().__init__(
            placeholder="Choose a style to apply...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="process_style_select",
            row=1  # Place in second row below main buttons
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle style selection."""
        # Check if the parent view has context (not a persistent view after restart)
        if not self.request_view.text_content and not self.request_view.images:
            await self.request_view._handle_missing_context(interaction, "apply styles")
            return
            
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
                description=style_data['image_only'][:100],  # Truncate description
                emoji=style_data['emoji'],
                value=style_key
            ))
        
        super().__init__(
            placeholder="Choose a style to apply...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="style_options_select",
            row=1  # Place in second row below navigation buttons
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle style selection."""
        # Check if the parent view has context (not a persistent view after restart)
        if not self.style_view.outputs:
            await self.style_view._handle_missing_context(interaction, "apply styles")
            return
            
        selected_style = self.values[0]
        await self.style_view.apply_style(interaction, selected_style)

class StyleOptionsView(discord.ui.View):
    """View with style selection for chaining modifications on generated images."""
    
    def __init__(self, outputs: List[OutputItem], current_index: int = 0, original_text: str = "", original_images: List = None, timeout=None):
        super().__init__(timeout=timeout)
        self.outputs = outputs if outputs else []
        self.current_index = max(0, min(current_index, len(self.outputs) - 1)) if self.outputs else 0
        self.original_text = original_text
        self.original_images = original_images or []
        
        # Add the style select dropdown
        self.add_item(StyleSelect(self))
        
        self._update_button_states()
    
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
    
    async def _handle_missing_context(self, interaction: discord.Interaction, action: str):
        """Handle interactions when view lacks context due to bot restart."""
        embed = discord.Embed(
            title="🔄 Bot Restart Detected",
            description=f"I can't {action} because the bot was restarted and the interaction context was lost.",
            color=0xff9900  # Orange color for warning
        )
        embed.add_field(
            name="💡 What to do:",
            value="Please mention me again with your images or text to start a new generation session.",
            inline=False
        )
        embed.set_footer(text="This happens when the bot restarts while keeping your message active.")
        
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.errors.InteractionResponded:
            # If response is already sent, edit the original message
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception as e:
            logger.warning(f"Failed to handle missing context interaction: {e}")
    
    @discord.ui.button(emoji='⬅️', style=discord.ButtonStyle.secondary, row=0, custom_id='style_nav_left')
    async def nav_left_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Navigate to previous output."""
        # Check if this is a persistent view with no context (after restart)
        if not self.outputs:
            await self._handle_missing_context(interaction, "navigate between images")
            return
            
        if len(self.outputs) <= 1:
            await interaction.response.defer()
            return
        self.current_index = (self.current_index - 1) % len(self.outputs)
        await self._update_display(interaction)
    
    @discord.ui.button(emoji='➡️', style=discord.ButtonStyle.secondary, row=0, custom_id='style_nav_right')
    async def nav_right_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Navigate to next output."""
        # Check if this is a persistent view with no context (after restart)
        if not self.outputs:
            await self._handle_missing_context(interaction, "navigate between images")
            return
            
        if len(self.outputs) <= 1:
            await interaction.response.defer()
            return
        self.current_index = (self.current_index + 1) % len(self.outputs)
        await self._update_display(interaction)
    
    async def _update_display(self, interaction: discord.Interaction):
        """Update the display with the current output."""
        if not self.outputs:
            return
            
        current_output = self.outputs[self.current_index]
        
        # Create embed for current output
        embed = discord.Embed(
            title="🎨 Generated Image - Nano Banana Bot",
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
            embed.add_field(name="Output", value=f"{self.current_index + 1} of {len(self.outputs)}", inline=True)
        
        embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
        
        # Save current image to buffer for Discord
        img_buffer = io.BytesIO()
        current_output.image.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        
        # Send the updated result
        file = discord.File(img_buffer, filename=current_output.filename)
        embed.set_image(url=f"attachment://{current_output.filename}")
        
        await safe_interaction_response(interaction, embed=embed, view=self, attachments=[file])
        
    @discord.ui.button(label='🎨 Process Prompt', style=discord.ButtonStyle.primary, custom_id='style_process_prompt')
    async def process_prompt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Process the current generated image with a prompt."""
        # Check if this is a persistent view with no context (after restart)
        if not self.outputs:
            await self._handle_missing_context(interaction, "process the image")
            return
            
        if not self.current_output:
            return
            
        # Disable all buttons to prevent multiple clicks
        for item in self.children:
            item.disabled = True
            
        # Determine images to use - use original images if current output is stitched input
        images_to_use = [self.current_output.image]
        if (self.current_output.filename.startswith("input_stitched_") and 
            self.original_images and len(self.original_images) > 1):
            # If processing a stitched input, use the original input images
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
                
                # Create final embed with result
                embed = discord.Embed(
                    title="🎨 Generated Image - Nano Banana Bot",
                    color=0x00ff00
                )
                
                # Show prompt used for this generation
                if self.original_text and self.original_text.strip():
                    embed.add_field(name="Prompt used:", value=f"{self.original_text[:100]}{'...' if len(self.original_text) > 100 else ''}", inline=False)
                else:
                    embed.add_field(name="Prompt used:", value="Image transformation", inline=False)
                
                # Show output count if we have multiple
                if len(all_outputs) > 1:
                    embed.add_field(name="Output", value=f"{len(all_outputs)} of {len(all_outputs)}", inline=True)
                
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
    
    @discord.ui.button(label='✏️ Edit Prompt', style=discord.ButtonStyle.secondary, custom_id='style_edit_prompt')
    async def edit_prompt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show modal to edit prompt for the generated image."""
        # Check if this is a persistent view with no context (after restart)
        if not self.outputs:
            await self._handle_missing_context(interaction, "edit the prompt")
            return
            
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
                title="🎨 Generated Image - Nano Banana Bot",
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
                embed.add_field(name="Output", value=f"{self.current_index + 1} of {len(self.outputs)}", inline=True)
            
            embed.add_field(name="Status", value="✅ Generation complete!", inline=False)
            
            # Save current image to buffer for Discord
            img_buffer = io.BytesIO()
            current_output.image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            # Send the updated result
            file = discord.File(img_buffer, filename=current_output.filename)
            embed.set_image(url=f"attachment://{current_output.filename}")
            
            await interaction.edit_original_response(embed=embed, view=self, attachments=[file])
        
    
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
            style_prompt = style_template['image_only']
            
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
                
                # Create final embed with styled result
                embed = discord.Embed(
                    title="🎨 Generated Image - Nano Banana Bot",
                    color=0x00ff00
                )
                
                # Show prompt used for this generation
                embed.add_field(name="Prompt used:", value=f"{style_prompt[:100]}{'...' if len(style_prompt) > 100 else ''}", inline=False)
                
                # Show output count if we have multiple
                if len(new_outputs) > 1:
                    embed.add_field(name="Output", value=f"{len(new_outputs)} of {len(new_outputs)}", inline=True)
                
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

class ProcessRequestView(discord.ui.View):
    """View with buttons to process image generation request and apply style templates."""
    
    def __init__(self, text_content: str, images: List, existing_outputs: List[OutputItem] = None, timeout=None):
        super().__init__(timeout=timeout)
        self.text_content = text_content
        self.images = images
        self.original_text = text_content  # Keep original text for template processing
        self.existing_outputs = existing_outputs or []
        
        # Add the style select dropdown
        self.add_item(ProcessStyleSelect(self))
        
    async def _handle_missing_context(self, interaction: discord.Interaction, action: str):
        """Handle interactions when view lacks context due to bot restart."""
        embed = discord.Embed(
            title="🔄 Bot Restart Detected",
            description=f"I can't {action} because the bot was restarted and the interaction context was lost.",
            color=0xff9900  # Orange color for warning
        )
        embed.add_field(
            name="💡 What to do:",
            value="Please mention me again with your images or text to start a new generation session.",
            inline=False
        )
        embed.set_footer(text="This happens when the bot restarts while keeping your message active.")
        
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.errors.InteractionResponded:
            # If response is already sent, edit the original message
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception as e:
            logger.warning(f"Failed to handle missing context interaction: {e}")
        
    @discord.ui.button(label='🎨 Process Prompt', style=discord.ButtonStyle.primary, custom_id='process_request_button')
    async def process_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the process button click."""
        # Check if this is a persistent view with no context (after restart)
        if not self.text_content and not self.images:
            await self._handle_missing_context(interaction, "process your request")
            return
            
        await self._process_request(interaction, button)
    
    @discord.ui.button(label='✏️ Edit Prompt', style=discord.ButtonStyle.secondary, custom_id='process_edit_prompt')
    async def edit_prompt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show modal to edit the prompt."""
        # Check if this is a persistent view with no context (after restart)
        if not self.text_content and not self.images:
            await self._handle_missing_context(interaction, "edit the prompt")
            return
            
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
                    title="🎨 Generated Image - Nano Banana Bot",
                    color=0x00ff00
                )
                
                # Show prompt used for this generation
                if self.text_content.strip():
                    embed.add_field(name="Prompt used:", value=f"{self.text_content[:100]}{'...' if len(self.text_content) > 100 else ''}", inline=False)
                else:
                    embed.add_field(name="Prompt used:", value="Image transformation", inline=False)
                
                # Show output count if we have multiple
                if len(all_outputs) > 1:
                    embed.add_field(name="Output", value=f"{len(all_outputs)} of {len(all_outputs)}", inline=True)
                
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
                # Pass original images from existing outputs if available
                original_images_for_view = self.images
                if self.existing_outputs:
                    # Extract original PIL images from input OutputItems for the view
                    original_images_for_view = [output.image for output in self.existing_outputs if "input_" in output.filename]
                    if not original_images_for_view:
                        original_images_for_view = self.images
                
                style_view = StyleOptionsView(all_outputs, len(all_outputs) - 1, self.original_text, original_images_for_view)
                
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
    
    # Register persistent views for handling interactions after restarts
    # This enables the bot to handle button/select interactions on messages
    # sent before a restart, preventing "This interaction failed" errors
    # Create empty view instances for persistent interaction handling
    persistent_style_view = StyleOptionsView([], 0, "", [])
    persistent_process_view = ProcessRequestView("", [])
    
    # Add views to the bot so they can handle interactions after restarts
    # Views with custom_id can be reconstructed and will route to these handlers
    bot.add_view(persistent_style_view)
    bot.add_view(persistent_process_view)
    
    logger.info("Registered persistent views for post-restart interaction handling")

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
        
        # Delete the original message after processing inputs
        try:
            await message.delete()
            logger.info("Deleted original user message")
        except Exception as e:
            logger.warning(f"Could not delete original message: {e}")
            # Continue processing even if deletion fails
        
        # Convert input images to OutputItems for cycling interface
        input_outputs = []
        if images:
            if len(images) > 1:
                # For multiple images, create single stitched OutputItem for display
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                stitched_image = create_stitched_image(images)
                stitched_output = OutputItem(
                    image=stitched_image,
                    filename=f"input_stitched_{timestamp}.png",
                    prompt_used=f"Stitched input from {len(images)} images",
                    timestamp=timestamp
                )
                input_outputs.append(stitched_output)
                logger.info(f"Created single stitched output for {len(images)} input images")
            else:
                # For single image, keep existing behavior
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                input_output = OutputItem(
                    image=images[0],
                    filename=f"input_0_{timestamp}.png",
                    prompt_used="Input image",
                    timestamp=timestamp
                )
                input_outputs.append(input_output)
                logger.info(f"Created single input output for single image")
        
        # Create preview embed with the request details
        embed = discord.Embed(
            title="🎨 Image Generation Request - Nano Banana Bot",
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
                embed.add_field(name="Preview", value="📋 Combined preview (for display only)", inline=True)
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
                embed.add_field(name="Preview", value="📋 Combined preview (for display only)", inline=True)
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
        
        # Create the view with the process button, passing input_outputs as existing outputs
        view = ProcessRequestView(text_content, images, existing_outputs=input_outputs)
        
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