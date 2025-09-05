import io
import aiohttp
from PIL import Image
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

