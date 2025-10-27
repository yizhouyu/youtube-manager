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

    def analyze_image_for_text_placement(self, image_data):
        """
        Use Claude's vision API to analyze the image and suggest text placement.

        Args:
            image_data: BytesIO object containing the image

        Returns:
            dict with placement suggestions:
            {
                'position': 'top'|'center'|'bottom',
                'reasoning': 'Why this placement works',
                'has_face': bool
            }
        """
        import base64
        from PIL import Image

        # Open image to detect format
        image_data.seek(0)
        img = Image.open(image_data)
        image_format = img.format.lower()  # 'jpeg', 'png', etc.
        image_data.seek(0)

        # Map PIL formats to MIME types
        mime_types = {
            'jpeg': 'image/jpeg',
            'jpg': 'image/jpeg',
            'png': 'image/png',
            'webp': 'image/webp',
            'gif': 'image/gif'
        }
        media_type = mime_types.get(image_format, 'image/jpeg')

        print(f"[DEBUG] Detected image format: {image_format}, using media_type: {media_type}")

        # Convert image to base64
        image_data.seek(0)
        image_base64 = base64.b64encode(image_data.read()).decode('utf-8')
        image_data.seek(0)

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,  # Use detected media type
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": """Analyze this image for YouTube thumbnail text placement.

**Your task:**
1. Detect if there are any FACES or PEOPLE in the image
2. Identify the main subject/focus area
3. Suggest the best vertical position for text overlay

**Positioning options:**
- "top": Place text in upper third (avoid if face/subject is there)
- "center": Place text in middle (avoid if face/subject is centered)
- "bottom": Place text in lower third (avoid if face/subject is there)

**Priority:** NEVER cover faces or main subjects!

Return ONLY a JSON object:
{
    "position": "top"|"center"|"bottom",
    "has_face": true|false,
    "reasoning": "Brief explanation (e.g., 'Face detected in center, place text at bottom')"
}"""
                        }
                    ]
                }]
            )

            # Parse response
            import json
            response_text = message.content[0].text.strip()

            # Extract JSON
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            result = json.loads(response_text)
            print(f"[DEBUG] Vision Analysis Result: {result}")
            return result

        except Exception as e:
            print(f"[ERROR] Error analyzing image: {e}")
            print(f"[ERROR] Response was: {response_text if 'response_text' in locals() else 'N/A'}")
            # Fallback to bottom position (safest)
            return {
                "position": "bottom",
                "has_face": False,
                "reasoning": "Fallback to bottom position (error occurred)"
            }

    def suggest_thumbnail_text(self, title, description, location=None, style="bold", language="zh-CN"):
        """
        Use Claude to suggest 3 compelling thumbnail text options based on video context.

        Args:
            title: Video title
            description: Video description
            location: Optional location/destination
            style: Text style (bold, minimal, dramatic)
            language: Target language (zh-CN or en)

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
        location_context = f"\n- 地点: {location}" if location and language == 'zh-CN' else (f"\n- Location: {location}" if location else "")

        # Use language-specific prompts for better adherence
        if language == 'zh-CN':
            prompt = f"""你是一位专精于旅游内容的 YouTube 封面文字专家。

**严格语言要求：**
- 目标语言：简体中文
- **所有封面文字必须使用简体中文，绝对不能使用英文**
- 示例词汇：惊艳、绝美、必看、秘境、隐藏、必去、震撼、顶级

视频信息：
- 标题：{title}
- 描述：{description[:500]}{location_context}
- 风格：{style}

请为这个视频建议 3 个不同的封面文字方案，以最大化点击率。每个方案应该采用不同的角度/方法。

要求：
1. **主文字**：最多 3-5 个词，醒目、吸引眼球
   - 使用简洁有力的词语
   - 数字效果好（提升点击率）
   - 制造好奇心或承诺价值
   - **必须使用简体中文**

2. **副标题**（可选）：简短的辅助文字
   - 2-4 个词
   - 增加上下文或紧迫感
   - **必须使用简体中文**

3. **最佳实践**：
   - 避免标题党 - 保持真实
   - 符合视频的实际内容
   - 使用情感化、吸引眼球的中文词汇

4. **多样性**：让每个方案都不同：
   - 方案 1：大胆/戏剧性的方法
   - 方案 2：好奇心/问题式方法
   - 方案 3：价值/收益式方法

5. **颜色设计**：为每个方案建议文字和描边颜色：
   - 符合视频的情绪和主题
   - 确保高可见度和对比度
   - 创造情感冲击
   - 示例：
     * 日落/冒险：橙色文字 (#FFA500) + 红色描边 (#FF4500)
     * 海洋/平静：青色文字 (#00FFFF) + 蓝色描边 (#0066FF)
     * 自然/清新：绿色文字 (#00FF00) + 深绿描边 (#006400)
     * 活力/激动：黄色文字 (#FFFF00) + 橙色描边 (#FF6600)
     * 奢华/高端：金色文字 (#FFD700) + 黑色描边 (#000000)
     * 神秘/暗黑：白色文字 (#FFFFFF) + 紫色描边 (#800080)

**只返回 JSON 数组**，包含 3 个对象：
[
    {{
        "main_text": "方案1文字",
        "subtitle": "可选副标题或空字符串",
        "reasoning": "为什么这个方案有效的简短解释",
        "text_color": "#RRGGBB 主文字的十六进制颜色",
        "outline_color": "#RRGGBB 描边的十六进制颜色",
        "color_reasoning": "为什么这些颜色适合这个视频"
    }},
    {{
        "main_text": "方案2文字",
        "subtitle": "可选副标题或空字符串",
        "reasoning": "为什么这个方案有效的简短解释",
        "text_color": "#RRGGBB 颜色",
        "outline_color": "#RRGGBB 颜色",
        "color_reasoning": "为什么这些颜色有效"
    }},
    {{
        "main_text": "方案3文字",
        "subtitle": "可选副标题或空字符串",
        "reasoning": "为什么这个方案有效的简短解释",
        "text_color": "#RRGGBB 颜色",
        "outline_color": "#RRGGBB 颜色",
        "color_reasoning": "为什么这些颜色有效"
    }}
]"""
        else:  # English
            prompt = f"""You are a YouTube thumbnail text expert specializing in travel content.

**CRITICAL LANGUAGE REQUIREMENT:**
- Target language: English
- **ALL thumbnail text MUST be in English. DO NOT use Chinese characters.**
- Example words: AMAZING, MUST-SEE, HIDDEN GEM, SECRET SPOT, STUNNING, TOP-TIER

Given this video context:
- Title: {title}
- Description: {description[:500]}{location_context}
- Style: {style}

Suggest 3 DIFFERENT compelling thumbnail text options that will maximize click-through rate.
Each option should have a different approach/angle.

Requirements:
1. **Main Text**: 3-5 words maximum, BOLD and attention-grabbing
   - Use simple, powerful words
   - Numbers work well (enhance click-through rate)
   - Create curiosity or promise value
   - **MUST be in English with ALL CAPS**

2. **Subtitle** (optional): Short supporting text if needed
   - 2-4 words
   - Adds context or urgency
   - **MUST be in English**

3. **Best Practices**:
   - Use ALL CAPS for maximum impact
   - Avoid clickbait - be authentic
   - Match the video's actual content
   - Use emotive, attention-grabbing English words

4. **Variety**: Make each option different:
   - Option 1: Bold/dramatic approach
   - Option 2: Curiosity/question approach
   - Option 3: Value/benefit approach

5. **Color Design**: For each option, suggest text and outline colors that:
   - Match the video's mood and theme
   - Ensure high visibility and contrast
   - Create emotional impact
   - Examples:
     * Sunset/Adventure: Orange text (#FFA500) with red outline (#FF4500)
     * Ocean/Calm: Cyan text (#00FFFF) with blue outline (#0066FF)
     * Nature/Fresh: Green text (#00FF00) with dark green outline (#006400)
     * Energy/Exciting: Yellow text (#FFFF00) with orange outline (#FF6600)
     * Luxury/Premium: Gold text (#FFD700) with black outline (#000000)
     * Mystery/Dark: White text (#FFFFFF) with purple outline (#800080)

Return ONLY a JSON array with 3 objects:
[
    {{
        "main_text": "OPTION 1 TEXT HERE",
        "subtitle": "Optional subtitle or empty string",
        "reasoning": "Brief explanation why this works",
        "text_color": "#RRGGBB hex color for main text",
        "outline_color": "#RRGGBB hex color for outline",
        "color_reasoning": "Why these colors work for this video"
    }},
    {{
        "main_text": "OPTION 2 TEXT HERE",
        "subtitle": "Optional subtitle or empty string",
        "reasoning": "Brief explanation why this works",
        "text_color": "#RRGGBB hex color",
        "outline_color": "#RRGGBB hex color",
        "color_reasoning": "Why these colors work"
    }},
    {{
        "main_text": "OPTION 3 TEXT HERE",
        "subtitle": "Optional subtitle or empty string",
        "reasoning": "Brief explanation why this works",
        "text_color": "#RRGGBB hex color",
        "outline_color": "#RRGGBB hex color",
        "color_reasoning": "Why these colors work"
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

            print(f"[DEBUG] Claude text generation response: {response_text[:500]}...")
            result = json.loads(response_text)
            print(f"[DEBUG] Generated {len(result)} text suggestions, first one: {result[0]['main_text']}")
            return result

        except Exception as e:
            print(f"[ERROR] Error generating thumbnail text: {e}")
            print(f"[ERROR] Raw response: {response_text if 'response_text' in locals() else 'N/A'}")
            # Fallback to simple text based on title with default colors
            return [
                {
                    "main_text": title[:30].upper(),
                    "subtitle": "",
                    "reasoning": "Fallback suggestion (bold)",
                    "text_color": "#FFFF00",  # Yellow
                    "outline_color": "#FF6600",  # Orange
                    "color_reasoning": "High-energy yellow for attention"
                },
                {
                    "main_text": title[:25].upper() + "!",
                    "subtitle": "WATCH NOW",
                    "reasoning": "Fallback suggestion (urgent)",
                    "text_color": "#00FFFF",  # Cyan
                    "outline_color": "#0066FF",  # Blue
                    "color_reasoning": "Modern cyan for tech appeal"
                },
                {
                    "main_text": "MUST SEE: " + title[:20].upper(),
                    "subtitle": "",
                    "reasoning": "Fallback suggestion (value)",
                    "text_color": "#FFFFFF",  # White
                    "outline_color": "#000000",  # Black
                    "color_reasoning": "Classic high contrast"
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

    def generate_thumbnail_options(
        self,
        image_path,
        title,
        description,
        location=None,
        style="bold",
        language="zh-CN",
        manual_position=None,
        manual_text_size=None
    ):
        """
        Complete workflow: Generate 3 thumbnail options with different text overlays.

        Args:
            image_path: Path to base image or BytesIO
            title: Video title
            description: Video description
            location: Optional location
            style: Text style for suggestions
            language: Target language (zh-CN or en)
            manual_position: Manual override for text position (top/center/bottom)

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

        # Determine text position
        if manual_position:
            # Use manual override
            text_position = manual_position
            placement_analysis = {
                'position': manual_position,
                'reasoning': f'Manual override: User selected {manual_position} position',
                'has_face': False
            }
            print(f"[INFO] Using manual position override: {manual_position}")
        else:
            # Analyze image for smart text placement (avoid faces)
            placement_analysis = self.analyze_image_for_text_placement(image_path)
            text_position = placement_analysis['position']
            print(f"[INFO] AI selected position: {text_position} - {placement_analysis['reasoning']}")

        # Get 3 text suggestions from Claude (with color suggestions)
        suggestions = self.suggest_thumbnail_text(title, description, location, style, language)

        results = []

        # Helper function to convert hex color to RGB tuple
        def hex_to_rgb(hex_color):
            """Convert hex color (#RRGGBB) to RGB tuple (R, G, B)"""
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

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

            # Get Claude-suggested colors for this option
            text_color = hex_to_rgb(suggestion.get('text_color', '#FFFFFF'))
            outline_color = hex_to_rgb(suggestion.get('outline_color', '#000000'))

            # Calculate font sizes (use manual override if provided, otherwise use defaults)
            if manual_text_size:
                font_size_main = manual_text_size
                font_size_subtitle = manual_text_size // 2  # Subtitle is half the main text size
            else:
                font_size_main = 120
                font_size_subtitle = 60

            # Generate thumbnail with this text, Claude's suggested colors, and smart positioning
            result_image = self.add_text_to_image(
                img_copy,
                main_text=suggestion['main_text'],
                subtitle=suggestion.get('subtitle', ''),
                output_path=None,  # Return BytesIO
                font_size_main=font_size_main,
                font_size_subtitle=font_size_subtitle,
                text_color=text_color,
                outline_color=outline_color,
                outline_width=10,  # Fixed outline width for consistency
                position=text_position  # Smart position to avoid faces
            )

            # Convert to base64 for web display
            result_image.seek(0)
            image_data = base64.b64encode(result_image.read()).decode('utf-8')
            image_base64 = f"data:image/jpeg;base64,{image_data}"

            results.append({
                'image_base64': image_base64,
                'main_text': suggestion['main_text'],
                'subtitle': suggestion.get('subtitle', ''),
                'reasoning': suggestion.get('reasoning', ''),
                'color_reasoning': suggestion.get('color_reasoning', ''),
                'placement_reasoning': placement_analysis['reasoning'],
                'text_position': text_position,
                'text_color': suggestion.get('text_color', '#FFFFFF'),
                'outline_color': suggestion.get('outline_color', '#000000')
            })

        return results

    def generate_thumbnail_options_with_cached_text(
        self,
        image_path,
        cached_suggestions,
        manual_position,
        manual_text_size=None
    ):
        """
        Generate thumbnail options reusing cached text suggestions (for repositioning).
        This avoids unnecessary API calls when only changing text position.

        Args:
            image_path: Path to base image or BytesIO
            cached_suggestions: List of 3 text suggestion dicts from previous generation
            manual_position: Text position (top/center/bottom)

        Returns:
            List of 3 thumbnail options with new positions but same text
        """
        import base64

        text_position = manual_position
        placement_analysis = {
            'position': manual_position,
            'reasoning': f'Manual override: User selected {manual_position} position',
            'has_face': False
        }

        print(f"[INFO] Repositioning text to {manual_position} without API call")

        results = []

        # Helper function to convert hex color to RGB tuple
        def hex_to_rgb(hex_color):
            """Convert hex color (#RRGGBB) to RGB tuple (R, G, B)"""
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

        # Generate thumbnail for each cached suggestion
        for idx, suggestion in enumerate(cached_suggestions):
            # Read image fresh for each option (if it's a file path)
            if isinstance(image_path, str):
                img_copy = image_path
            else:
                # For BytesIO, we need to seek back to beginning
                image_path.seek(0)
                img_copy = BytesIO(image_path.read())
                image_path.seek(0)

            # Get colors from cached suggestion
            text_color = hex_to_rgb(suggestion.get('text_color', '#FFFFFF'))
            outline_color = hex_to_rgb(suggestion.get('outline_color', '#000000'))

            # Calculate font sizes (use manual override if provided, otherwise use defaults)
            if manual_text_size:
                font_size_main = manual_text_size
                font_size_subtitle = manual_text_size // 2  # Subtitle is half the main text size
            else:
                font_size_main = 120
                font_size_subtitle = 60

            # Generate thumbnail with cached text but new position/size
            result_image = self.add_text_to_image(
                img_copy,
                main_text=suggestion['main_text'],
                subtitle=suggestion.get('subtitle', ''),
                output_path=None,  # Return BytesIO
                font_size_main=font_size_main,
                font_size_subtitle=font_size_subtitle,
                text_color=text_color,
                outline_color=outline_color,
                outline_width=10,
                position=text_position  # New position
            )

            # Convert to base64 for web display
            result_image.seek(0)
            image_data = base64.b64encode(result_image.read()).decode('utf-8')
            image_base64 = f"data:image/jpeg;base64,{image_data}"

            results.append({
                'image_base64': image_base64,
                'main_text': suggestion['main_text'],
                'subtitle': suggestion.get('subtitle', ''),
                'reasoning': suggestion.get('reasoning', ''),
                'color_reasoning': suggestion.get('color_reasoning', ''),
                'placement_reasoning': placement_analysis['reasoning'],
                'text_position': text_position,
                'text_color': suggestion.get('text_color', '#FFFFFF'),
                'outline_color': suggestion.get('outline_color', '#000000')
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
