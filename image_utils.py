import io
import aiohttp
from PIL import Image, ImageDraw
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

async def download_image(url: str) -> Image.Image:
    """Download an image from a URL and return as PIL Image."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    return Image.open(io.BytesIO(image_data))
                else:
                    logger.error(f"Failed to download image: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        return None

def stitch_images(images: List[Image.Image], max_width: int = 1024) -> Image.Image:
    """Stitch multiple images together into a single image."""
    if not images:
        return None
    
    if len(images) == 1:
        return images[0]
    
    # Calculate dimensions for the stitched image
    total_height = 0
    max_img_width = 0
    
    # Resize images to fit within max_width while maintaining aspect ratio
    resized_images = []
    for img in images:
        if img.width > max_width:
            # Calculate new height maintaining aspect ratio
            new_height = int((max_width * img.height) / img.width)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        
        resized_images.append(img)
        total_height += img.height
        max_img_width = max(max_img_width, img.width)
    
    # Create a new image with calculated dimensions
    stitched_image = Image.new('RGB', (max_img_width, total_height), (255, 255, 255))
    
    # Paste images vertically
    y_offset = 0
    for img in resized_images:
        # Center the image horizontally if it's smaller than max_img_width
        x_offset = (max_img_width - img.width) // 2
        stitched_image.paste(img, (x_offset, y_offset))
        y_offset += img.height
    
    return stitched_image

def add_text_to_image(image: Image.Image, text: str) -> Image.Image:
    """Add text overlay to an image."""
    if not text.strip():
        return image
    
    # Create a copy to avoid modifying the original
    img_with_text = image.copy()
    draw = ImageDraw.Draw(img_with_text)
    
    # Add a semi-transparent overlay for better text visibility
    overlay = Image.new('RGBA', img_with_text.size, (0, 0, 0, 128))
    img_with_text = Image.alpha_composite(img_with_text.convert('RGBA'), overlay)
    
    # Add text (simplified - in a real implementation, you'd want better text handling)
    try:
        draw = ImageDraw.Draw(img_with_text)
        # Simple text placement - could be improved with proper font sizing
        draw.text((10, 10), text[:100], fill=(255, 255, 255))  # Limit text length
    except Exception as e:
        logger.error(f"Error adding text to image: {e}")
    
    return img_with_text.convert('RGB')