import io
import aiohttp
from PIL import Image
import logging
from typing import List
import math

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

def create_stitched_image(images: List[Image.Image], max_width: int = 1024, max_height: int = 1024) -> Image.Image:
    """
    Create a stitched image from multiple input images for display purposes.
    
    Args:
        images: List of PIL Images to stitch together
        max_width: Maximum width of the output image
        max_height: Maximum height of the output image
        
    Returns:
        PIL Image containing all input images arranged in a grid
    """
    if not images:
        return None
    
    if len(images) == 1:
        return images[0]
    
    # Calculate grid dimensions (prefer wider layouts)
    num_images = len(images)
    cols = math.ceil(math.sqrt(num_images))
    rows = math.ceil(num_images / cols)
    
    # Calculate individual cell size
    cell_width = max_width // cols
    cell_height = max_height // rows
    
    # Create the output image with white background
    stitched = Image.new('RGB', (cols * cell_width, rows * cell_height), 'white')
    
    for i, img in enumerate(images):
        row = i // cols
        col = i % cols
        
        # Resize image to fit cell while maintaining aspect ratio
        img_resized = img.copy()
        img_resized.thumbnail((cell_width, cell_height), Image.Resampling.LANCZOS)
        
        # Calculate position to center the image in the cell
        x_offset = col * cell_width + (cell_width - img_resized.width) // 2
        y_offset = row * cell_height + (cell_height - img_resized.height) // 2
        
        # Paste the image
        stitched.paste(img_resized, (x_offset, y_offset))
    
    return stitched