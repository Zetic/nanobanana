"""Style templates for image generation."""

# Template definitions for style selection
TEMPLATES = {
    'sticker': {
        'name': 'Sticker',
        'emoji': '🏷️',
        'image_only': "Use the subject of the images to create a sticker that should have a black outline and vector artstyle. The background must be transparent.",
        'text_only': "Create a sticker that should have a black outline and vector artstyle. The background must be transparent. The subject is {text}",
        'image_and_text': "Use the subject of the images to create a sticker that should have a black outline and vector artstyle. The background must be transparent. Also {text}"
    },
    'pixel_art': {
        'name': 'Pixel Art',
        'emoji': '🎮',
        'image_only': "Convert the image into a pixel art style with low resolution, blocky pixels, and retro gaming aesthetics.",
        'text_only': "Create a pixel art style image with low resolution, blocky pixels, and retro gaming aesthetics. The subject is {text}",
        'image_and_text': "Convert the image into a pixel art style with low resolution, blocky pixels, and retro gaming aesthetics. Also {text}"
    },
    'watercolor': {
        'name': 'Watercolor',
        'emoji': '🎨',
        'image_only': "Transform the image into a soft watercolor painting style with flowing colors, gentle blending, and artistic brush strokes.",
        'text_only': "Create a watercolor painting style image with flowing colors, gentle blending, and artistic brush strokes. The subject is {text}",
        'image_and_text': "Transform the image into a soft watercolor painting style with flowing colors, gentle blending, and artistic brush strokes. Also {text}"
    },
    'oil_painting': {
        'name': 'Oil Painting',
        'emoji': '🖼️',
        'image_only': "Convert the image into a classical oil painting style with rich textures, thick paint strokes, and traditional artistic techniques.",
        'text_only': "Create an oil painting style image with rich textures, thick paint strokes, and traditional artistic techniques. The subject is {text}",
        'image_and_text': "Convert the image into a classical oil painting style with rich textures, thick paint strokes, and traditional artistic techniques. Also {text}"
    },
    'sketch': {
        'name': 'Sketch',
        'emoji': '✏️',
        'image_only': "Transform the image into a detailed pencil sketch with fine lines, shading, and artistic drawing techniques.",
        'text_only': "Create a pencil sketch style image with fine lines, shading, and artistic drawing techniques. The subject is {text}",
        'image_and_text': "Transform the image into a detailed pencil sketch with fine lines, shading, and artistic drawing techniques. Also {text}"
    },
    'neon': {
        'name': 'Neon',
        'emoji': '🌈',
        'image_only': "Convert the image into a vibrant neon cyberpunk style with glowing colors, electric effects, and futuristic aesthetics.",
        'text_only': "Create a neon cyberpunk style image with glowing colors, electric effects, and futuristic aesthetics. The subject is {text}",
        'image_and_text': "Convert the image into a vibrant neon cyberpunk style with glowing colors, electric effects, and futuristic aesthetics. Also {text}"
    },
    'vintage': {
        'name': 'Vintage',
        'emoji': '📻',
        'image_only': "Transform the image into a vintage retro style with faded colors, aged textures, and nostalgic film aesthetics.",
        'text_only': "Create a vintage retro style image with faded colors, aged textures, and nostalgic film aesthetics. The subject is {text}",
        'image_and_text': "Transform the image into a vintage retro style with faded colors, aged textures, and nostalgic film aesthetics. Also {text}"
    },
    'cartoon': {
        'name': 'Cartoon',
        'emoji': '🎭',
        'image_only': "Convert the image into a vibrant cartoon style with bold colors, clean lines, and animated character aesthetics.",
        'text_only': "Create a cartoon style image with bold colors, clean lines, and animated character aesthetics. The subject is {text}",
        'image_and_text': "Convert the image into a vibrant cartoon style with bold colors, clean lines, and animated character aesthetics. Also {text}"
    },
    'photorealistic': {
        'name': 'Photorealistic',
        'emoji': '📸',
        'image_only': "Enhance the image to be ultra-photorealistic with perfect lighting, sharp details, and lifelike textures.",
        'text_only': "Create an ultra-photorealistic image with perfect lighting, sharp details, and lifelike textures. The subject is {text}",
        'image_and_text': "Enhance the image to be ultra-photorealistic with perfect lighting, sharp details, and lifelike textures. Also {text}"
    },
    'abstract': {
        'name': 'Abstract',
        'emoji': '🎪',
        'image_only': "Transform the image into an abstract art style with geometric shapes, bold colors, and artistic interpretation.",
        'text_only': "Create an abstract art style image with geometric shapes, bold colors, and artistic interpretation. The subject is {text}",
        'image_and_text': "Transform the image into an abstract art style with geometric shapes, bold colors, and artistic interpretation. Also {text}"
    },
    'minimalist': {
        'name': 'Minimalist',
        'emoji': '⚪',
        'image_only': "Convert the image into a clean minimalist style with simple forms, limited colors, and elegant simplicity.",
        'text_only': "Create a minimalist style image with simple forms, limited colors, and elegant simplicity. The subject is {text}",
        'image_and_text': "Convert the image into a clean minimalist style with simple forms, limited colors, and elegant simplicity. Also {text}"
    },
    'gothic': {
        'name': 'Gothic',
        'emoji': '🦇',
        'image_only': "Transform the image into a dark gothic style with dramatic shadows, mysterious atmosphere, and haunting aesthetics.",
        'text_only': "Create a gothic style image with dramatic shadows, mysterious atmosphere, and haunting aesthetics. The subject is {text}",
        'image_and_text': "Transform the image into a dark gothic style with dramatic shadows, mysterious atmosphere, and haunting aesthetics. Also {text}"
    }
}