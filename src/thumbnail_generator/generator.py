"""
AI-powered YouTube thumbnail generator using Claude + Pillow
"""

import os
import anthropic
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap


class ThumbnailGenerator:
    """
    Generates YouTube thumbnails by:
    1. Using Claude to suggest compelling text based on video context
    2. Using Pillow to overlay text on user-provided base images
    """

    def __init__(self, api_key=None):
        """
        Initialize the thumbnail generator.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def suggest_thumbnail_text(self, title, description, location=None, style="bold"):
        """
        Use Claude to suggest 3 compelling thumbnail text options based on video context.

        Args:
            title: Video title
            description: Video description
            location: Optional location/destination
            style: Text style (bold, minimal, dramatic)

        Returns:
            list of 3 dicts with text suggestions:
            [
                {
                    'main_text': 'Primary text (3-5 words)',
                    'subtitle': 'Optional subtitle',
                    'reasoning': 'Why this text works'
                },
                ...
            ]
        """
        location_context = f"\n- Location: {location}" if location else ""

        prompt = f"""You are a YouTube thumbnail text expert specializing in travel content.

Given this video context:
- Title: {title}
- Description: {description[:500]}{location_context}
- Style: {style}

Suggest 3 DIFFERENT compelling thumbnail text options that will maximize click-through rate.
Each option should have a different approach/angle.

**CRITICAL: If the content is in Chinese, you MUST use Simplified Chinese (简体中文), NOT Traditional Chinese (繁體中文).**

Requirements:
1. **Main Text**: 3-5 words maximum, BOLD and attention-grabbing
   - Use simple, powerful words
   - Numbers work well (e.g., "5个隐藏景点" for Chinese, "5 HIDDEN GEMS" for English)
   - Create curiosity or promise value
   - **IMPORTANT: For Chinese content, use ONLY Simplified Chinese characters (简体中文)**
   - Examples of Simplified Chinese: 惊艳, 绝美, 必看, 秘境
   - DO NOT use Traditional Chinese: 驚艷, 絕美, 必看, 秘境

2. **Subtitle** (optional): Short supporting text if needed
   - 2-4 words
   - Adds context or urgency
   - **Also use Simplified Chinese if main text is Chinese**

3. **Best Practices**:
   - Use ALL CAPS for English text
   - For Chinese, use emotive words like: 惊艳(amazing), 隐藏(hidden), 必看(must-see), 秘境(secret)
   - Avoid clickbait - be authentic
   - Match the video's actual content

4. **Variety**: Make each option different:
   - Option 1: Bold/dramatic approach
   - Option 2: Curiosity/question approach
   - Option 3: Value/benefit approach

Return ONLY a JSON array with 3 objects:
[
    {{
        "main_text": "OPTION 1 TEXT HERE",
        "subtitle": "Optional subtitle or empty string",
        "reasoning": "Brief explanation why this works"
    }},
    {{
        "main_text": "OPTION 2 TEXT HERE",
        "subtitle": "Optional subtitle or empty string",
        "reasoning": "Brief explanation why this works"
    }},
    {{
        "main_text": "OPTION 3 TEXT HERE",
        "subtitle": "Optional subtitle or empty string",
        "reasoning": "Brief explanation why this works"
    }}
]"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse Claude's JSON response
            import json
            response_text = message.content[0].text.strip()

            # Extract JSON from response (handle markdown code blocks)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            result = json.loads(response_text)
            return result

        except Exception as e:
            print(f"Error generating thumbnail text: {e}")
            # Fallback to simple text based on title
            return [
                {
                    "main_text": title[:30].upper(),
                    "subtitle": "",
                    "reasoning": "Fallback suggestion (bold)"
                },
                {
                    "main_text": title[:25].upper() + "!",
                    "subtitle": "WATCH NOW",
                    "reasoning": "Fallback suggestion (urgent)"
                },
                {
                    "main_text": "MUST SEE: " + title[:20].upper(),
                    "subtitle": "",
                    "reasoning": "Fallback suggestion (value)"
                }
            ]

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
        position="center"
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

        # Resize to YouTube thumbnail dimensions (1280x720)
        target_size = (1280, 720)
        img.thumbnail(target_size, Image.Resampling.LANCZOS)

        # Create new image with target size and paste resized image centered
        final_img = Image.new('RGB', target_size, (0, 0, 0))
        offset = ((target_size[0] - img.size[0]) // 2, (target_size[1] - img.size[1]) // 2)
        final_img.paste(img, offset)

        draw = ImageDraw.Draw(final_img)

        # Detect if text contains Chinese characters
        def has_chinese(text):
            return any('\u4e00' <= char <= '\u9fff' for char in text)

        is_chinese = has_chinese(main_text)

        # Load fonts with better Chinese support
        font_paths_to_try = []
        if is_chinese:
            # Chinese-optimized fonts (macOS)
            font_paths_to_try = [
                "/System/Library/Fonts/PingFang.ttc",  # PingFang SC - best for Chinese
                "/System/Library/Fonts/STHeiti Light.ttc",  # STHeiti
                "/System/Library/Fonts/Hiragino Sans GB.ttc",  # Hiragino
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",  # Arial Unicode
            ]
        else:
            # English fonts (bold)
            font_paths_to_try = [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
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
        if position == "top":
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

    def generate_thumbnail_options(
        self,
        image_path,
        title,
        description,
        location=None,
        style="bold"
    ):
        """
        Complete workflow: Generate 3 thumbnail options with different text overlays.

        Args:
            image_path: Path to base image or BytesIO
            title: Video title
            description: Video description
            location: Optional location
            style: Text style for suggestions

        Returns:
            List of 3 thumbnail options:
            [
                {
                    'image_base64': 'data:image/jpeg;base64,...',
                    'main_text': '...',
                    'subtitle': '...',
                    'reasoning': '...'
                },
                ...
            ]
        """
        import base64
        from copy import deepcopy

        # Get 3 text suggestions from Claude
        suggestions = self.suggest_thumbnail_text(title, description, location, style)

        results = []

        # Generate thumbnail for each suggestion
        for idx, suggestion in enumerate(suggestions):
            # Read image fresh for each option (if it's a file path)
            if isinstance(image_path, str):
                img_copy = image_path
            else:
                # For BytesIO, we need to seek back to beginning
                image_path.seek(0)
                img_copy = BytesIO(image_path.read())
                image_path.seek(0)

            # Generate thumbnail with this text
            result_image = self.add_text_to_image(
                img_copy,
                main_text=suggestion['main_text'],
                subtitle=suggestion.get('subtitle', ''),
                output_path=None  # Return BytesIO
            )

            # Convert to base64 for web display
            result_image.seek(0)
            image_data = base64.b64encode(result_image.read()).decode('utf-8')
            image_base64 = f"data:image/jpeg;base64,{image_data}"

            results.append({
                'image_base64': image_base64,
                'main_text': suggestion['main_text'],
                'subtitle': suggestion.get('subtitle', ''),
                'reasoning': suggestion.get('reasoning', '')
            })

        return results

    def generate_thumbnail(
        self,
        image_path,
        title,
        description,
        location=None,
        style="bold",
        custom_text=None,
        output_path=None
    ):
        """
        Generate single thumbnail with specified text (for final selection).

        Args:
            image_path: Path to base image or BytesIO
            title: Video title
            description: Video description
            location: Optional location
            style: Text style for suggestions
            custom_text: Custom text dict {'main_text': '...', 'subtitle': '...'}
            output_path: Where to save result

        Returns:
            {
                'image': BytesIO or file path,
                'text_used': {'main_text': '...', 'subtitle': '...'}
            }
        """
        if not custom_text:
            raise ValueError("Must provide custom_text for single thumbnail generation")

        # Add text to image
        result_image = self.add_text_to_image(
            image_path,
            main_text=custom_text['main_text'],
            subtitle=custom_text.get('subtitle', ''),
            output_path=output_path
        )

        return {
            'image': result_image,
            'text_used': custom_text
        }
