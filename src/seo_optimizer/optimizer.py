"""SEO optimizer using Claude API for bilingual Chinese-English metadata."""

import os
import re
from typing import Dict, Optional
from anthropic import Anthropic


class BilingualSEOOptimizer:
    """Generates SEO-optimized bilingual metadata for travel videos."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the SEO optimizer.

        Args:
            api_key: Anthropic API key (if None, reads from ANTHROPIC_API_KEY env var)
        """
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError(
                "Anthropic API key not found. Set ANTHROPIC_API_KEY environment variable "
                "or pass it to the constructor."
            )
        self.client = Anthropic(api_key=self.api_key)

    def _detect_primary_language(
        self,
        title: str,
        description: str,
        default_language: Optional[str] = None,
        default_audio_language: Optional[str] = None
    ) -> str:
        """
        Detect the primary language of the video content.

        Uses multiple signals in priority order:
        1. YouTube API language fields (defaultLanguage, defaultAudioLanguage)
        2. Character analysis of title (Chinese vs English characters)
        3. Character analysis of description as fallback

        Args:
            title: Video title
            description: Video description
            default_language: YouTube's defaultLanguage field
            default_audio_language: YouTube's defaultAudioLanguage field

        Returns:
            'chinese' or 'english'
        """
        # Priority 1: Use YouTube API language fields
        language_hints = [default_language, default_audio_language]
        for lang in language_hints:
            if lang:
                lang_lower = lang.lower()
                # Chinese language codes: zh, zh-CN, zh-TW, zh-Hans, zh-Hant, etc.
                if lang_lower.startswith('zh'):
                    return 'chinese'
                # English language codes: en, en-US, en-GB, etc.
                elif lang_lower.startswith('en'):
                    return 'english'

        # Priority 2: Analyze title characters (title is most indicative)
        title_chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', title))
        title_english_chars = len(re.findall(r'[a-zA-Z]', title))

        # If title has substantial Chinese content, it's a Chinese video
        if title_chinese_chars > 5:  # At least 5 Chinese characters
            return 'chinese'

        # If title is predominantly English (>70% English characters)
        title_total = title_chinese_chars + title_english_chars
        if title_total > 0 and title_english_chars / title_total > 0.7:
            return 'english'

        # Priority 3: Fallback to description analysis
        combined_text = title + " " + description
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', combined_text))
        english_chars = len(re.findall(r'[a-zA-Z]', combined_text))

        # Primary language is the one with more characters
        return 'chinese' if chinese_chars > english_chars else 'english'

    def generate_metadata(
        self,
        current_title: str,
        current_description: str,
        current_tags: list = None,
        video_context: Optional[str] = None,
        default_language: Optional[str] = None,
        default_audio_language: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Generate SEO-optimized bilingual metadata for a travel video.

        Args:
            current_title: Current video title (in Chinese)
            current_description: Current video description
            current_tags: Current tags (if any)
            video_context: Additional context about the video content

        Returns:
            Dictionary with optimized metadata:
            {
                'title': str,           # Optimized Chinese title
                'description': str,     # Bilingual description (Chinese + English)
                'tags': list,          # Mix of Chinese and English tags
                'hashtags': list       # Bilingual hashtags
            }
        """
        current_tags_str = ', '.join(current_tags) if current_tags else 'None'

        # Detect primary language using all available signals
        primary_lang = self._detect_primary_language(
            current_title,
            current_description,
            default_language,
            default_audio_language
        )

        # Build language-specific prompt
        if primary_lang == 'chinese':
            lang_instruction = """**1. TITLE (MUST be in Chinese)**
- CRITICAL: The title MUST be in Chinese. DO NOT translate to English.
- Keep it in Chinese (60 characters optimal, max 70)
- Include the most important keywords FIRST
- Use engaging words like: 必看, 攻略, 完整版, 深度, 实拍, 最新
- Make it clickable but not clickbait
- Natural and appealing to Chinese viewers
- If the original title has some English (like brand names or technical terms), you may keep them mixed in naturally

**2. DESCRIPTION (Bilingual)**
IMPORTANT: Preserve all existing useful information:
- Music credits and attributions
- Timestamps and chapters
- Links and resources
- Social media handles
- Location details
- Equipment/gear used
- Any other valuable metadata

Structure:
```
[Chinese Section - 250+ words]
- First 25 words MUST contain primary keywords
- Include detailed information, tips, and value
- Natural keyword integration (2-4 times)
- Engaging and informative
- KEEP all music credits, timestamps, links from original

---

[English Section - 150+ words]
- Translate/summarize the Chinese content
- Include English keywords naturally
- Appeal to international audience
- SEO-optimized for English search

---

[Original Metadata - if present]
- Music credits
- Timestamps/chapters
- Links and resources
- Other attributions
```"""
            example_hashtags = "#中国旅行 #TravelChina #旅行Vlog #ChinaTravel #旅游攻略"
        else:  # english
            lang_instruction = """**1. TITLE (MUST be in English)**
- CRITICAL: The title MUST be in English. DO NOT translate to Chinese.
- Keep it in English (60 characters optimal, max 70)
- Include the most important keywords FIRST
- Use engaging words like: Ultimate, Complete Guide, Best, Essential, Must-See
- Make it clickable but not clickbait
- Natural and appealing to English viewers

**2. DESCRIPTION (Bilingual)**
IMPORTANT: Preserve all existing useful information:
- Music credits and attributions
- Timestamps and chapters
- Links and resources
- Social media handles
- Location details
- Equipment/gear used
- Any other valuable metadata

Structure:
```
[English Section - 250+ words]
- First 25 words MUST contain primary keywords
- Include detailed information, tips, and value
- Natural keyword integration (2-4 times)
- Engaging and informative
- KEEP all music credits, timestamps, links from original

---

[Chinese Section - 150+ words]
- Translate/summarize the English content
- Include Chinese keywords naturally
- Appeal to Chinese-speaking audience
- SEO-optimized for Chinese search

---

[Original Metadata - if present]
- Music credits
- Timestamps/chapters
- Links and resources
- Other attributions
```"""
            example_hashtags = "#PersonalGrowth #读书 #Productivity #ReadingChallenge #自我提升"

        prompt = f"""You are an expert in YouTube SEO. Your task is to optimize metadata for this video to improve discoverability for both primary and secondary language audiences.

**Current Video Information:**
- Title: {current_title}
- Description: {current_description}
- Current Tags: {current_tags_str}
{f"- Additional Context: {video_context}" if video_context else ""}

**CRITICAL: Content Preservation**
The current description may contain important information such as:
- Music credits and attributions (e.g., "Music: [song name] by [artist]")
- Timestamps and chapter markers (e.g., "0:00 Intro", "2:30 Main content")
- Social media links and handles
- Equipment/gear information
- Location details
- External links and resources

YOU MUST PRESERVE ALL OF THIS INFORMATION in the optimized description. Do not remove or omit any credits, timestamps, links, or metadata that exists in the current description.

**Your Task:**
Generate SEO-optimized metadata following these requirements:

{lang_instruction}

**3. TAGS (8-12 tags, mixed Chinese & English)**
- First tag should be the most relevant keyword
- Mix of Chinese and English tags appropriate to the content
- Topic-specific tags in both languages
- Balance between broad and niche keywords

**4. HASHTAGS (3-5 bilingual hashtags)**
- First 3 hashtags will appear above video title (most visible)
- Mix of broad reach and niche specificity
- Bilingual approach for maximum discoverability
- Focused on main keywords and topics
- Examples: {example_hashtags}
- Avoid generic tags like #video or #youtube

**Output Format (JSON):**
```json
{{
  "title": "optimized title in original language",
  "description": "Primary language section\\n\\n---\\n\\nSecondary language section",
  "tags": ["tag1", "tag2", "tag3", ...],
  "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"]
}}
```

Please generate the optimized metadata now. Return ONLY the JSON output, nothing else."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Extract JSON from response
            response_text = response.content[0].text.strip()

            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1]) if len(lines) > 2 else response_text
                if response_text.startswith('json'):
                    response_text = response_text[4:].strip()

            # Parse JSON
            import json
            metadata = json.loads(response_text)

            return metadata

        except Exception as e:
            raise Exception(f"Error generating metadata with Claude API: {e}")

    def generate_new_video_metadata(
        self,
        topic: str,
        locations: Optional[str] = None,
        key_points: Optional[str] = None
    ) -> Dict[str, any]:
        """
        Generate metadata for a new video based on topic and key information.

        Args:
            topic: Main topic/title of the video (can be in Chinese or English)
            locations: Locations covered in the video
            key_points: Key highlights or points covered

        Returns:
            Dictionary with optimized metadata
        """
        prompt = f"""You are an expert in YouTube SEO for travel content. Generate complete SEO-optimized metadata for a NEW Chinese travel video.

**Video Information:**
- Topic: {topic}
{f"- Locations: {locations}" if locations else ""}
{f"- Key Points: {key_points}" if key_points else ""}

**Your Task:**
Create compelling, SEO-optimized metadata from scratch.

**1. TITLE (Chinese)**
- 60 characters optimal, max 70
- Primary keywords FIRST
- Engaging words: 必看, 攻略, 完整版, 深度, 实拍, 最新
- Clickable but authentic

**2. DESCRIPTION (Bilingual)**
```
[Chinese Section - 250+ words]
- Keywords in first 25 words
- Detailed travel guide/information
- Natural keyword usage (2-4 times)
- Value-packed content

---

[English Section - 150+ words]
- Translation/summary
- English SEO keywords
- International appeal
```

**3. TAGS (8-12 tags, Chinese & English mixed)**
- Most relevant tag first
- Chinese: 中国旅行, 旅游攻略, 旅行vlog, etc.
- English: China travel, travel guide, travel vlog, etc.
- Location-specific
- Broad + niche keywords

**4. HASHTAGS (3-5 bilingual)**
- First 3 will appear above video title (most visible)
- Mix broad reach + niche specificity
- Main keyword focused
- Example: #中国旅行 #TravelChina #旅游攻略 #ChinaVlog #旅行日记

**Output Format (JSON only):**
```json
{{
  "title": "optimized title",
  "description": "Chinese section\\n\\n---\\n\\nEnglish section",
  "tags": ["tag1", "tag2", ...],
  "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"]
}}
```

Return ONLY the JSON output."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            response_text = response.content[0].text.strip()

            # Clean up markdown code blocks
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1]) if len(lines) > 2 else response_text
                if response_text.startswith('json'):
                    response_text = response_text[4:].strip()

            import json
            metadata = json.loads(response_text)

            return metadata

        except Exception as e:
            raise Exception(f"Error generating metadata with Claude API: {e}")

    def compress_description_for_bilibili(
        self,
        description: str,
        max_length: int = 250,
        video_title: Optional[str] = None
    ) -> str:
        """
        Intelligently compress a description for Bilibili using LLM.

        This method preserves the most important information while fitting
        within Bilibili's character limits. It prioritizes Chinese content
        and maintains key details like locations, highlights, and calls-to-action.

        Args:
            description: Full description (bilingual or Chinese)
            max_length: Maximum character length for Bilibili (default 250)
            video_title: Optional video title for context

        Returns:
            Compressed description that fits within max_length
        """
        # If already within limit, return as-is
        if len(description) <= max_length:
            return description

        prompt = f"""You are an expert at compressing video descriptions while preserving maximum information value.

**Task:** Compress the following video description to fit within {max_length} characters while keeping the MOST important information.

{f"**Video Title:** {video_title}" if video_title else ""}

**Original Description:**
{description}

**Compression Guidelines:**
1. **Prioritize Chinese content** - If the description is bilingual, focus on Chinese section
2. **Keep essential information:**
   - Main topic/location
   - Key highlights and activities
   - Important tips or recommendations
   - Call-to-action (subscribe/follow if present)
3. **Remove or shorten:**
   - Redundant descriptions
   - Overly detailed explanations
   - Generic filler words
   - English section if bilingual (keep only Chinese)
   - Timestamps (if necessary for space)
   - Social media links (if necessary for space)
4. **Writing style:**
   - Concise and punchy
   - Use emojis if they save space and add clarity
   - Break into short, scannable lines
   - Keep most engaging parts

**Critical Requirements:**
- Output MUST be {max_length} characters or less
- Must remain in Chinese (if original is Chinese/bilingual)
- Should feel complete, not abruptly cut off
- Preserve the video's core value proposition

**Output:** Return ONLY the compressed description, nothing else. No explanations, no JSON, just the compressed text."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            compressed = response.content[0].text.strip()

            # Safety check: if Claude exceeded limit, do hard truncation
            if len(compressed) > max_length:
                # Try to truncate at sentence boundary
                truncated = compressed[:max_length]
                sentence_endings = ['。', '！', '？', '.', '!', '?', '\n']
                best_break = -1

                for i in range(len(truncated) - 1, max(0, len(truncated) - 50), -1):
                    if truncated[i] in sentence_endings:
                        best_break = i + 1
                        break

                if best_break > 0:
                    compressed = truncated[:best_break].strip()
                else:
                    compressed = truncated.rstrip()

            return compressed

        except Exception as e:
            # Fallback to simple truncation if LLM fails
            console.print(f"[yellow]Warning: LLM compression failed ({e}), falling back to simple truncation[/yellow]")
            return self._simple_truncate(description, max_length)

    def _simple_truncate(self, text: str, max_length: int) -> str:
        """
        Simple truncation fallback (used if LLM compression fails).

        Args:
            text: Text to truncate
            max_length: Maximum length

        Returns:
            Truncated text
        """
        if len(text) <= max_length:
            return text

        truncated = text[:max_length]
        sentence_endings = ['。', '！', '？', '.', '!', '?', '\n']

        # Search backwards for sentence ending
        for i in range(len(truncated) - 1, max(0, len(truncated) - 50), -1):
            if truncated[i] in sentence_endings:
                return truncated[:i + 1].strip()

        return truncated.rstrip()
