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
    'pixel_art_16bit': {
        'name': 'Pixel Art 16-bit',
        'emoji': '🕹️',
        'image_only': "Convert the image into a 16-bit pixel art style with medium resolution, defined pixels, classic arcade gaming aesthetics, and limited color palette.",
        'text_only': "Create a 16-bit pixel art style image with medium resolution, defined pixels, classic arcade gaming aesthetics, and limited color palette. The subject is {text}",
        'image_and_text': "Convert the image into a 16-bit pixel art style with medium resolution, defined pixels, classic arcade gaming aesthetics, and limited color palette. Also {text}"
    },
    'pixel_art_32bit': {
        'name': 'Pixel Art 32-bit',
        'emoji': '🎯',
        'image_only': "Convert the image into a 32-bit pixel art style with higher resolution, smooth pixels, detailed sprites, rich color depth, and modern retro gaming aesthetics.",
        'text_only': "Create a 32-bit pixel art style image with higher resolution, smooth pixels, detailed sprites, rich color depth, and modern retro gaming aesthetics. The subject is {text}",
        'image_and_text': "Convert the image into a 32-bit pixel art style with higher resolution, smooth pixels, detailed sprites, rich color depth, and modern retro gaming aesthetics. Also {text}"
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
    },
    'anime': {
        'name': 'Anime/Manga',
        'emoji': '🌸',
        'image_only': "Convert the image into Japanese anime/manga style with large expressive eyes, clean lineart, vibrant colors, and characteristic shading.",
        'text_only': "Create an anime/manga style image with large expressive eyes, clean lineart, vibrant colors, and characteristic shading. The subject is {text}",
        'image_and_text': "Convert the image into Japanese anime/manga style with large expressive eyes, clean lineart, vibrant colors, and characteristic shading. Also {text}"
    },
    'steampunk': {
        'name': 'Steampunk',
        'emoji': '⚙️',
        'image_only': "Transform the image into steampunk style with brass gears, copper pipes, Victorian era aesthetics, and mechanical elements.",
        'text_only': "Create a steampunk style image with brass gears, copper pipes, Victorian era aesthetics, and mechanical elements. The subject is {text}",
        'image_and_text': "Transform the image into steampunk style with brass gears, copper pipes, Victorian era aesthetics, and mechanical elements. Also {text}"
    },
    'cyberpunk': {
        'name': 'Cyberpunk',
        'emoji': '🤖',
        'image_only': "Convert the image into cyberpunk style with neon lights, dark urban settings, high-tech elements, and dystopian atmosphere.",
        'text_only': "Create a cyberpunk style image with neon lights, dark urban settings, high-tech elements, and dystopian atmosphere. The subject is {text}",
        'image_and_text': "Convert the image into cyberpunk style with neon lights, dark urban settings, high-tech elements, and dystopian atmosphere. Also {text}"
    },
    'art_deco': {
        'name': 'Art Deco',
        'emoji': '🏛️',
        'image_only': "Transform the image into Art Deco style with geometric patterns, elegant lines, gold accents, and 1920s luxury aesthetics.",
        'text_only': "Create an Art Deco style image with geometric patterns, elegant lines, gold accents, and 1920s luxury aesthetics. The subject is {text}",
        'image_and_text': "Transform the image into Art Deco style with geometric patterns, elegant lines, gold accents, and 1920s luxury aesthetics. Also {text}"
    },
    'pop_art': {
        'name': 'Pop Art',
        'emoji': '💥',
        'image_only': "Convert the image into pop art style with bold colors, comic book aesthetics, Ben-Day dots, and high contrast.",
        'text_only': "Create a pop art style image with bold colors, comic book aesthetics, Ben-Day dots, and high contrast. The subject is {text}",
        'image_and_text': "Convert the image into pop art style with bold colors, comic book aesthetics, Ben-Day dots, and high contrast. Also {text}"
    },
    'impressionist': {
        'name': 'Impressionist',
        'emoji': '🌅',
        'image_only': "Transform the image into impressionist painting style with visible brushstrokes, light effects, and soft color blending.",
        'text_only': "Create an impressionist painting style image with visible brushstrokes, light effects, and soft color blending. The subject is {text}",
        'image_and_text': "Transform the image into impressionist painting style with visible brushstrokes, light effects, and soft color blending. Also {text}"
    },
    'surreal': {
        'name': 'Surreal',
        'emoji': '🌀',
        'image_only': "Convert the image into surreal art style with dreamlike elements, impossible geometry, and fantastical imagery.",
        'text_only': "Create a surreal art style image with dreamlike elements, impossible geometry, and fantastical imagery. The subject is {text}",
        'image_and_text': "Convert the image into surreal art style with dreamlike elements, impossible geometry, and fantastical imagery. Also {text}"
    },
    'noir': {
        'name': 'Film Noir',
        'emoji': '🎬',
        'image_only': "Transform the image into film noir style with high contrast black and white, dramatic shadows, and moody lighting.",
        'text_only': "Create a film noir style image with high contrast black and white, dramatic shadows, and moody lighting. The subject is {text}",
        'image_and_text': "Transform the image into film noir style with high contrast black and white, dramatic shadows, and moody lighting. Also {text}"
    },
    'graffiti': {
        'name': 'Graffiti',
        'emoji': '🖌️',
        'image_only': "Convert the image into street graffiti style with spray paint effects, urban aesthetics, and bold lettering.",
        'text_only': "Create a graffiti style image with spray paint effects, urban aesthetics, and bold lettering. The subject is {text}",
        'image_and_text': "Convert the image into street graffiti style with spray paint effects, urban aesthetics, and bold lettering. Also {text}"
    },
    'paper_cut': {
        'name': 'Paper Cut',
        'emoji': '✂️',
        'image_only': "Transform the image into paper cut art style with layered paper effects, clean edges, and dimensional shadows.",
        'text_only': "Create a paper cut art style image with layered paper effects, clean edges, and dimensional shadows. The subject is {text}",
        'image_and_text': "Transform the image into paper cut art style with layered paper effects, clean edges, and dimensional shadows. Also {text}"
    },
    'stained_glass': {
        'name': 'Stained Glass',
        'emoji': '🔮',
        'image_only': "Convert the image into stained glass style with colorful glass panels, lead lines, and luminous effects.",
        'text_only': "Create a stained glass style image with colorful glass panels, lead lines, and luminous effects. The subject is {text}",
        'image_and_text': "Convert the image into stained glass style with colorful glass panels, lead lines, and luminous effects. Also {text}"
    }
}