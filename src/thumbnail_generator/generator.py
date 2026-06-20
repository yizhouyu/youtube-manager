"""
AI-powered YouTube thumbnail generator using Claude + Pillow
"""

import os
import tempfile
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap




class ThumbnailGenerator:
    """
    Generates YouTube thumbnails by:
    1. Using Claude (via the Claude Code CLI) to suggest compelling text based on
       video context
    2. Using Pillow to overlay text on user-provided base images
    """

    def __init__(self, api_key=None):
        """
        Initialize the thumbnail generator.

        Args:
            api_key: Deprecated/ignored. Generation now routes through the Claude
                Code CLI (your subscription), so no API key is needed.
        """
        self.api_key = api_key


    def add_text_to_image(
        self,
        image_path,
        main_text,
        subtitle="",
        output_path=None,
        font_size_main=120,
        font_size_subtitle=60,
        text_color=(255, 255, 255),
        outline_color=(0, 0, 0),
        outline_width=8,
        position="center"  # Can be "center", "top", "bottom", or float 0.0-1.0 for custom Y position
    ):
        """
        Add text overlay to an image using Pillow.

        Args:
            image_path: Path to base image or BytesIO object
            main_text: Primary text to display
            subtitle: Secondary text (optional)
            output_path: Where to save result (if None, returns BytesIO)
            font_size_main: Font size for main text
            font_size_subtitle: Font size for subtitle
            text_color: RGB tuple for text color
            outline_color: RGB tuple for outline/stroke
            outline_width: Width of text outline
            position: Text position (center, top, bottom)

        Returns:
            BytesIO object or path to saved file
        """
        # Open image
        if isinstance(image_path, (BytesIO, bytes)):
            img = Image.open(image_path)
        else:
            img = Image.open(image_path)

        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Resize to YouTube thumbnail dimensions (1280x720) - FILL completely
        target_size = (1280, 720)
        target_ratio = target_size[0] / target_size[1]  # 16:9
        img_ratio = img.size[0] / img.size[1]

        if img_ratio > target_ratio:
            # Image is wider - scale by height, then crop width
            new_height = target_size[1]
            new_width = int(new_height * img_ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            # Crop to center
            left = (new_width - target_size[0]) // 2
            img = img.crop((left, 0, left + target_size[0], target_size[1]))
        else:
            # Image is taller - scale by width, then crop height
            new_width = target_size[0]
            new_height = int(new_width / img_ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            # Crop to center
            top = (new_height - target_size[1]) // 2
            img = img.crop((0, top, target_size[0], top + target_size[1]))

        final_img = img  # Image now fills entire canvas

        draw = ImageDraw.Draw(final_img)

        # Detect if text contains Chinese characters
        def has_chinese(text):
            return any('\u4e00' <= char <= '\u9fff' for char in text)

        is_chinese = has_chinese(main_text)

        # Load fonts with modern, light-hearted style
        font_paths_to_try = []
        if is_chinese:
            # Modern Chinese fonts (macOS) - rounded, friendly style
            font_paths_to_try = [
                "/System/Library/Fonts/PingFang.ttc",  # PingFang SC - modern, clean
                "/System/Library/Fonts/Supplemental/Songti.ttc",  # Songti - elegant
                "/System/Library/Fonts/STHeiti Medium.ttc",  # STHeiti Medium - friendly weight
                "/System/Library/Fonts/Hiragino Sans GB.ttc",  # Hiragino - soft
                "/System/Library/Fonts/Supplemental/Kaiti.ttc",  # Kaiti - handwritten feel
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",  # Fallback
            ]
        else:
            # Modern English fonts - bold but friendly
            font_paths_to_try = [
                "/System/Library/Fonts/Supplemental/Impact.ttf",  # Impact - bold, modern
                "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",  # Rounded
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",  # Clean bold
                "/Library/Fonts/Arial Bold.ttf",
            ]

        # Add Linux fallbacks
        font_paths_to_try.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",  # Chinese support on Linux
        ])

        font_main = None
        font_subtitle = None

        for font_path in font_paths_to_try:
            try:
                font_main = ImageFont.truetype(font_path, font_size_main)
                font_subtitle = ImageFont.truetype(font_path, font_size_subtitle)
                break
            except:
                continue

        # Final fallback to default font
        if font_main is None:
            font_main = ImageFont.load_default()
            font_subtitle = ImageFont.load_default()

        # Wrap text if too long
        max_chars_per_line = 20
        wrapped_main = textwrap.fill(main_text, max_chars_per_line)
        lines_main = wrapped_main.split('\n')

        # Calculate positions
        img_width, img_height = final_img.size

        # Helper function to draw text with outline
        def draw_text_with_outline(text, font, position, fill, outline, outline_width):
            x, y = position
            # Draw outline
            for adj_x in range(-outline_width, outline_width + 1):
                for adj_y in range(-outline_width, outline_width + 1):
                    draw.text((x + adj_x, y + adj_y), text, font=font, fill=outline)
            # Draw main text
            draw.text((x, y), text, font=font, fill=fill)

        # Calculate total height of text block
        total_height = sum(draw.textbbox((0, 0), line, font=font_main)[3] for line in lines_main)
        if subtitle:
            total_height += draw.textbbox((0, 0), subtitle, font=font_subtitle)[3] + 20

        # Determine Y position based on position parameter
        if isinstance(position, (int, float)):
            # Custom Y position as percentage (0.0 = top, 1.0 = bottom)
            # Position value represents where the TOP of the text should be
            current_y = img_height * position
        elif position == "top":
            current_y = img_height * 0.15
        elif position == "bottom":
            current_y = img_height * 0.75 - total_height
        else:  # center
            current_y = (img_height - total_height) / 2

        # Draw main text (line by line if wrapped)
        for line in lines_main:
            bbox = draw.textbbox((0, 0), line, font=font_main)
            text_width = bbox[2] - bbox[0]
            text_x = (img_width - text_width) / 2

            draw_text_with_outline(
                line, font_main, (text_x, current_y),
                text_color, outline_color, outline_width
            )
            current_y += bbox[3] - bbox[1] + 10

        # Draw subtitle if provided
        if subtitle:
            bbox = draw.textbbox((0, 0), subtitle, font=font_subtitle)
            text_width = bbox[2] - bbox[0]
            text_x = (img_width - text_width) / 2
            current_y += 20

            draw_text_with_outline(
                subtitle, font_subtitle, (text_x, current_y),
                text_color, outline_color, outline_width // 2
            )

        # Save or return
        if output_path:
            final_img.save(output_path, 'JPEG', quality=95)
            return output_path
        else:
            output = BytesIO()
            final_img.save(output, format='JPEG', quality=95)
            output.seek(0)
            return output
