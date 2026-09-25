#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
send_to_telegram.py — Self-Contained Telegram Dispatch Infrastructure
Part of GitHub Deployment Package for Daily Content Engine

Features:
  - Rich HTML message cards (<b>, <code>, <pre>, <blockquote>, emojis, clean borders, 1-click copy blocks)
  - Single photo dispatch via Telegram Bot API 'sendPhoto'
  - Multi-image swipeable Carousels via Telegram Bot API 'sendMediaGroup' (up to 10 images with captions)
  - Intelligent tag-balancing HTML splitter for messages > 4000 chars and captions > 1000 chars
  - Automatic .env discovery from local directory or OS environment variables (GitHub Actions secrets)
  - Resilient networking with connection pooling, retries, and urllib fallback
  - UTF-8 safe input/output across Windows and Linux
"""

import os
import sys
import re
import json
import time
import argparse
import mimetypes
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

# Ensure UTF-8 output streams on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util import Retry
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request
    import urllib.parse
    import urllib.error


# ==============================================================================
# 1. Environment & Configuration Loader
# ==============================================================================

def find_env_file(explicit_path: Optional[str] = None) -> Optional[Path]:
    """Finds the .env file from explicit path, local directory, or parent trees."""
    if explicit_path:
        p = Path(explicit_path).expanduser().resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(f"Specified .env file not found: {explicit_path}")

    # Standard locations relative to this script
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / ".env",
        Path.cwd() / ".env",
        script_dir.parent / ".env",
        Path.cwd().parent / ".env",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    return None


def parse_env_file(env_path: Optional[Path]) -> Dict[str, str]:
    """Parses key=value lines from a .env file into a dictionary."""
    env_vars = {}
    if not env_path or not env_path.is_file():
        return env_vars

    with open(env_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                # Remove surrounding quotes
                if len(val) >= 2 and (
                    (val.startswith('"') and val.endswith('"')) or
                    (val.startswith("'") and val.endswith("'"))
                ):
                    val = val[1:-1]
                env_vars[key] = val
    return env_vars


def get_telegram_credentials(
    token_override: Optional[str] = None,
    chat_id_override: Optional[str] = None,
    env_file: Optional[str] = None
) -> Tuple[str, str, str]:
    """
    Returns (bot_token, chat_id, source_description).
    Precedence: CLI override > .env file > OS environment variables (GitHub Actions secrets).
    """
    env_path = find_env_file(env_file)
    file_vars = parse_env_file(env_path) if env_path else {}

    token = (
        token_override
        or file_vars.get("BOT_TOKEN")
        or file_vars.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("BOT_TOKEN")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or ""
    ).strip()

    chat_id = (
        chat_id_override
        or file_vars.get("CHANNEL")
        or file_vars.get("CHAT_ID")
        or file_vars.get("TELEGRAM_CHAT_ID")
        or os.environ.get("CHANNEL")
        or os.environ.get("CHAT_ID")
        or os.environ.get("TELEGRAM_CHAT_ID")
        or ""
    ).strip()

    source = str(env_path) if env_path else "System Environment / GitHub Secrets"
    return token, chat_id, source


# ==============================================================================
# 2. Telegram HTML Formatting & Message Card Generator
# ==============================================================================

def escape_html_chars(text: str) -> str:
    """Escapes &, <, > for safe Telegram HTML parsing."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_to_telegram_html(md_text: str) -> str:
    """
    Converts common Markdown constructs into Telegram-compliant HTML.
    Preserves already formatted Telegram HTML tags safely.
    """
    if not md_text:
        return ""

    text = md_text.replace("\r\n", "\n").replace("\r", "\n")

    # Preserve fenced code blocks ```...```
    code_blocks: List[str] = []
    def save_fenced_code(match):
        lang = match.group(1) or ""
        code = match.group(2)
        escaped_code = escape_html_chars(code.rstrip())
        idx = len(code_blocks)
        if lang:
            tag = f'<pre><code class="language-{lang}">{escaped_code}</code></pre>'
        else:
            tag = f'<pre>{escaped_code}</pre>'
        code_blocks.append(tag)
        return f"__CODE_BLOCK_{idx}__"

    text = re.sub(r'```([a-zA-Z0-9_-]*)\n?(.*?)```', save_fenced_code, text, flags=re.DOTALL)

    # Preserve inline code `...`
    inline_codes: List[str] = []
    def save_inline_code(match):
        code = match.group(1)
        escaped_code = escape_html_chars(code)
        idx = len(inline_codes)
        inline_codes.append(f'<code>{escaped_code}</code>')
        return f"__INLINE_CODE_{idx}__"

    text = re.sub(r'`([^`\n]+)`', save_inline_code, text)

    # Escape raw '&' not part of existing HTML entities
    text = re.sub(r'&(?!(?:amp|lt|gt|quot|apos);)', '&amp;', text)

    # Convert Markdown headers (# Title -> <b>Title</b>)
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

    # Bold: **bold** or __bold__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text, flags=re.DOTALL)

    # Italic: *italic* or _italic_
    text = re.sub(r'(?<!\w)\*([^*\n]+?)\*(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)_([^_\n]+?)_(?!\w)', r'<i>\1</i>', text)

    # Strikethrough: ~~strikethrough~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text, flags=re.DOTALL)

    # Blockquotes: > quote lines
    def format_blockquotes(match):
        content = match.group(0)
        lines = [re.sub(r'^>\s?', '', l) for l in content.split('\n')]
        return f"<blockquote>{chr(10).join(lines).strip()}</blockquote>"

    text = re.sub(r'(?:^>[^\n]*(?:\n>[^\n]*)*)', format_blockquotes, text, flags=re.MULTILINE)

    # Markdown links: [anchor](url)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', r'<a href="\2">\1</a>', text)

    # Unordered list bullets: * item or - item -> • item
    text = re.sub(r'^[ \t]*[-\*]\s+(.+)$', r'• \1', text, flags=re.MULTILINE)

    # Restore inline code tokens
    for i, tag in enumerate(inline_codes):
        text = text.replace(f"__INLINE_CODE_{i}__", tag)

    # Restore fenced code blocks
    for i, tag in enumerate(code_blocks):
        text = text.replace(f"__CODE_BLOCK_{i}__", tag)

    return text.strip()


def build_message_card(
    content: str,
    title: Optional[str] = None,
    platform: Optional[str] = None,
    hook: Optional[str] = None,
    comment_content: Optional[str] = None,
    footer_note: Optional[str] = None
) -> str:
    """
    Builds an upgraded Telegram HTML Message Card featuring:
      - Header banner with emojis and platform badge
      - Clean visual divider borders (━━━━━━━━━━━━━━━━━━━━━━━━━━━━━)
      - Hook / Key takeaway blockquote
      - 1-Click Copyable Post Block formatted in <pre>...</pre>
      - Optional 1st-Comment Copyable Block in <pre>...</pre>
      - Callout blockquote and status footer
    """
    lines = content.strip().splitlines()

    extracted_title = title
    extracted_platform = platform
    body_lines = []
    first_heading_found = False

    for line in lines:
        stripped = line.strip()
        if not first_heading_found and (stripped.startswith("# ") or stripped.startswith("## ")):
            if not extracted_title:
                extracted_title = stripped.lstrip("#").strip()
            first_heading_found = True
            continue
        body_lines.append(line)

    body_text = "\n".join(body_lines).strip()
    if not extracted_title:
        extracted_title = "DAILY AI DISPATCH"

    # Auto-detect platform if not provided
    if not extracted_platform:
        lower_all = (content + " " + (extracted_title or "")).lower()
        if "linkedin" in lower_all:
            extracted_platform = "LINKEDIN"
        elif "github" in lower_all:
            extracted_platform = "GITHUB"
        elif "twitter" in lower_all or " x " in lower_all or "x (" in lower_all:
            extracted_platform = "X (TWITTER)"
        elif "tiktok" in lower_all:
            extracted_platform = "TIKTOK"
        else:
            extracted_platform = "LINKEDIN / X"

    platform_emojis = {
        "LINKEDIN": "💼",
        "GITHUB": "🐙",
        "X (TWITTER)": "🐦",
        "TIKTOK": "🎵",
        "LINKEDIN / X": "🐙",
        "POST DRAFT": "📝"
    }
    badge_emoji = platform_emojis.get(extracted_platform, "🚀")

    # Hook extraction if not provided
    if not hook:
        for bl in body_lines:
            sbl = bl.strip()
            if sbl and not sbl.startswith("#") and len(sbl) > 20:
                hook = sbl
                if len(hook) > 160:
                    hook = hook[:157] + "..."
                break

    border = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    card_parts = [
        f"{badge_emoji} <b>{escape_html_chars(extracted_title.upper())}</b> • <code>{extracted_platform}</code>",
        f"<code>{border}</code>"
    ]

    # Hook / Key Takeaway Callout
    if hook:
        safe_hook = escape_html_chars(hook)
        card_parts.append(f"<blockquote>⚡ <b>Hook:</b> <i>{safe_hook}</i></blockquote>")
        card_parts.append("")

    # 1-Click Copyable Post Block:
    card_parts.append("📋 <b>1-CLICK COPYABLE POST BLOCK:</b>")
    safe_body = escape_html_chars(body_text)
    card_parts.append(f"<pre>{safe_body}</pre>")
    card_parts.append("")

    # Optional 1st-Comment Copy Block
    if comment_content:
        card_parts.append("💬 <b>1ST-COMMENT / AUTO-REPLY BLOCK:</b>")
        safe_comment = escape_html_chars(comment_content.strip())
        card_parts.append(f"<pre>{safe_comment}</pre>")
        card_parts.append("")

    # Bottom Callout & Border
    note = footer_note or "Tap the pre-formatted code block above to copy the clean text directly."
    card_parts.append(f"<blockquote>💡 <i>{escape_html_chars(note)}</i></blockquote>")
    card_parts.append(f"<code>{border}</code>")

    return "\n".join(card_parts)


# ==============================================================================
# 3. Intelligent HTML Tag-Balancing Splitter
# ==============================================================================

def _split_text_token(text: str, max_chunk_size: int) -> List[str]:
    """Splits an oversized text token along paragraph, line, and word boundaries."""
    if len(text) <= max_chunk_size:
        return [text]

    parts: List[str] = []
    lines = text.splitlines(keepends=True)
    current = ""

    for line in lines:
        if len(line) > max_chunk_size:
            words = re.split(r'(\s+)', line)
            for w in words:
                if len(current) + len(w) > max_chunk_size and current:
                    parts.append(current)
                    current = ""
                if len(w) > max_chunk_size:
                    for i in range(0, len(w), max_chunk_size):
                        sub = w[i:i + max_chunk_size]
                        if len(current) + len(sub) > max_chunk_size and current:
                            parts.append(current)
                            current = ""
                        current += sub
                else:
                    current += w
        else:
            if len(current) + len(line) > max_chunk_size and current:
                parts.append(current)
                current = ""
            current += line

    if current:
        parts.append(current)

    return parts


def split_html_message(html_content: str, max_len: int = 4000) -> List[str]:
    """
    Splits an HTML string into chunks <= max_len without breaking HTML tags.
    Maintains an open tag stack: closes all unclosed tags at the end of each chunk,
    and re-opens them at the start of the next chunk.
    """
    if not html_content:
        return []

    if len(html_content) <= max_len:
        return [html_content]

    pattern = re.compile(r'(<!--.*?-->|<[^>]+>|[^<]+)', re.DOTALL)
    raw_tokens = pattern.findall(html_content)

    safe_sub_size = max(60, max_len // 4)
    tokens: List[str] = []
    for tok in raw_tokens:
        if tok.startswith("<") and tok.endswith(">"):
            tokens.append(tok)
        else:
            tokens.extend(_split_text_token(tok, safe_sub_size))

    chunks: List[str] = []
    current_tokens: List[str] = []
    current_len = 0
    open_tags: List[Tuple[str, str]] = []

    tag_name_re = re.compile(r'^<\s*([a-zA-Z0-9_-]+)')
    close_tag_name_re = re.compile(r'^<\s*/\s*([a-zA-Z0-9_-]+)')

    for token in tokens:
        if not token:
            continue

        is_tag = token.startswith("<") and token.endswith(">")
        close_match = close_tag_name_re.match(token) if is_tag else None
        open_match = tag_name_re.match(token) if is_tag and not close_match and not token.endswith("/>") else None

        closing_tags_str = "".join(f"</{name}>" for name, _ in reversed(open_tags))

        if current_tokens and (current_len + len(token) + len(closing_tags_str) > max_len):
            chunk_content = "".join(current_tokens) + closing_tags_str
            if chunk_content.strip():
                chunks.append(chunk_content)

            reopened_str = "".join(full_tag for _, full_tag in open_tags)
            current_tokens = [reopened_str] if reopened_str else []
            current_len = len(reopened_str)

        current_tokens.append(token)
        current_len += len(token)

        if open_match:
            tag_name = open_match.group(1).lower()
            open_tags.append((tag_name, token))
        elif close_match:
            tag_name = close_match.group(1).lower()
            for i in range(len(open_tags) - 1, -1, -1):
                if open_tags[i][0] == tag_name:
                    open_tags.pop(i)
                    break

    if current_tokens:
        closing_tags_str = "".join(f"</{name}>" for name, _ in reversed(open_tags))
        chunk_content = "".join(current_tokens) + closing_tags_str
        if chunk_content.strip():
            chunks.append(chunk_content)

    return chunks


# ==============================================================================
# 4. Telegram API Dispatcher
# ==============================================================================

class TelegramDispatcher:
    def __init__(self, token: str, chat_id: str, timeout: int = 35):
        if not token:
            raise ValueError("Telegram Bot Token is required.")
        if not chat_id:
            raise ValueError("Telegram Channel / Chat ID is required.")

        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{self.token}"

        self.session = None
        if HAS_REQUESTS:
            self.session = requests.Session()
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["POST", "GET"]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)

    def _post(self, endpoint: str, data: Dict[str, Any] = None, files: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint}"
        last_err = None

        if self.session is not None:
            for attempt in range(1, 4):
                try:
                    resp = self.session.post(url, data=data, files=files, timeout=self.timeout)
                    result = resp.json()
                    if not resp.ok or not result.get("ok"):
                        error_desc = result.get("description", resp.text)
                        raise RuntimeError(f"Telegram API Error ({endpoint} - HTTP {resp.status_code}): {error_desc}")
                    return result
                except (requests.ConnectionError, requests.Timeout) as e:
                    last_err = e
                    time.sleep(attempt * 0.5)
                except Exception:
                    raise

        if not files:
            headers = {"Content-Type": "application/json; charset=utf-8"}
            req_data = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8")
                raise RuntimeError(f"Telegram API Error ({endpoint} - HTTP {e.code}): {err_body}")
            except Exception as e:
                raise RuntimeError(f"Failed to communicate with Telegram ({endpoint}): {e}")

        raise RuntimeError(f"Network error communicating with Telegram ({endpoint}): {last_err}")

    def test_connection(self) -> Dict[str, Any]:
        """Validates the bot token using getMe."""
        url = f"{self.base_url}/getMe"
        if self.session is not None:
            try:
                resp = self.session.get(url, timeout=self.timeout)
                data = resp.json()
                if not resp.ok or not data.get("ok"):
                    raise RuntimeError(f"Invalid Bot Token: {data.get('description')}")
                return data["result"]
            except Exception:
                pass

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            if not data.get("ok"):
                raise RuntimeError(f"Invalid Bot Token: {data.get('description')}")
            return data["result"]

    def send_text(self, text: str, parse_mode: str = "HTML", disable_preview: bool = False) -> List[Dict[str, Any]]:
        """Sends text message, automatically splitting long posts gracefully."""
        chunks = split_html_message(text, max_len=4000)
        results = []

        for idx, chunk in enumerate(chunks):
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "link_preview_options": json.dumps({"is_disabled": disable_preview})
            }
            res = self._post("sendMessage", data=payload)
            results.append(res)
            msg_id = res.get("result", {}).get("message_id")
            if len(chunks) > 1:
                print(f"  [✓] Sent message chunk {idx + 1}/{len(chunks)} (ID: {msg_id})")
            else:
                print(f"  [✓] Sent message (ID: {msg_id})")

        return results

    def send_photo(self, photo_path: str, caption: Optional[str] = None, parse_mode: str = "HTML") -> Dict[str, Any]:
        """Sends a high-resolution photo with HTML caption."""
        path = Path(photo_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Photo file not found: {photo_path}")

        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        caption_chunks = split_html_message(caption, max_len=1000) if caption else []
        main_caption = caption_chunks[0] if caption_chunks else None

        data = {
            "chat_id": self.chat_id,
            "parse_mode": parse_mode
        }
        if main_caption:
            data["caption"] = main_caption

        with open(path, "rb") as f:
            files = {"photo": (path.name, f, mime_type)}
            res = self._post("sendPhoto", data=data, files=files)
            msg_id = res.get("result", {}).get("message_id")
            print(f"  [✓] Sent photo: {path.name} (ID: {msg_id})")

        if len(caption_chunks) > 1:
            print(f"  [*] Caption exceeded 1000 chars. Sending {len(caption_chunks)-1} follow-up text chunk(s)...")
            for idx, follow_chunk in enumerate(caption_chunks[1:], start=2):
                follow_res = self._post("sendMessage", data={
                    "chat_id": self.chat_id,
                    "text": follow_chunk,
                    "parse_mode": parse_mode
                })
                f_id = follow_res.get("result", {}).get("message_id")
                print(f"  [✓] Sent caption continuation {idx}/{len(caption_chunks)} (ID: {f_id})")

        return res

    def send_carousel(self, image_paths: List[str], caption: Optional[str] = None, parse_mode: str = "HTML") -> List[Dict[str, Any]]:
        """Sends swipeable carousels via sendMediaGroup."""
        resolved_paths = []
        for p in image_paths:
            rp = Path(p).expanduser().resolve()
            if not rp.is_file():
                raise FileNotFoundError(f"Carousel image not found: {p}")
            resolved_paths.append(rp)

        if not resolved_paths:
            raise ValueError("No valid image paths provided for carousel.")

        if len(resolved_paths) == 1:
            print("  [*] Single image provided for carousel mode. Delegating to sendPhoto...")
            return [self.send_photo(str(resolved_paths[0]), caption=caption, parse_mode=parse_mode)]

        results = []
        caption_chunks = split_html_message(caption, max_len=1000) if caption else []
        main_caption = caption_chunks[0] if caption_chunks else None

        for batch_idx in range(0, len(resolved_paths), 10):
            batch = resolved_paths[batch_idx:batch_idx + 10]
            media_list = []
            files_dict = {}
            open_files = []

            try:
                for idx, img_path in enumerate(batch):
                    attach_key = f"photo_{batch_idx}_{idx}"
                    mime_type = mimetypes.guess_type(str(img_path))[0] or "image/jpeg"
                    f = open(img_path, "rb")
                    open_files.append(f)
                    files_dict[attach_key] = (img_path.name, f, mime_type)

                    media_item = {
                        "type": "photo",
                        "media": f"attach://{attach_key}"
                    }
                    if batch_idx == 0 and idx == 0 and main_caption:
                        media_item["caption"] = main_caption
                        media_item["parse_mode"] = parse_mode

                    media_list.append(media_item)

                data = {
                    "chat_id": self.chat_id,
                    "media": json.dumps(media_list)
                }
                res = self._post("sendMediaGroup", data=data, files=files_dict)
                results.append(res)
                print(f"  [✓] Sent carousel batch ({len(batch)} images)")
            finally:
                for f in open_files:
                    f.close()

        if len(caption_chunks) > 1:
            print(f"  [*] Carousel caption exceeded 1000 chars. Sending {len(caption_chunks)-1} follow-up text chunk(s)...")
            for idx, follow_chunk in enumerate(caption_chunks[1:], start=2):
                follow_res = self._post("sendMessage", data={
                    "chat_id": self.chat_id,
                    "text": follow_chunk,
                    "parse_mode": parse_mode
                })
                f_id = follow_res.get("result", {}).get("message_id")
                print(f"  [✓] Sent caption continuation {idx}/{len(caption_chunks)} (ID: {f_id})")

        return results

    send_media_group = send_carousel


# ==============================================================================
# 5. CLI Controller & Argument Parsing
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Self-Contained Telegram Dispatcher for Content Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-m", "--message", type=str, help="Direct message text or markdown/HTML string")
    parser.add_argument("-f", "--file-path", type=str, help="Path to text or markdown file containing post content")
    parser.add_argument("-i", "--image-paths", nargs="+", help="One or more image file paths")
    parser.add_argument("--mode", choices=["text", "photo", "carousel"], default=None, help="Dispatch mode")
    parser.add_argument("--card", action="store_true", help="Format content as a styled rich Telegram Card with 1-click copy block")
    parser.add_argument("--title", type=str, help="Custom title for the message card header")
    parser.add_argument("--platform", type=str, help="Platform badge (e.g. LinkedIn, GitHub, X)")
    parser.add_argument("--hook", type=str, help="Custom hook for the card callout")
    parser.add_argument("--comment", type=str, help="Optional 1st-comment copy block content")
    parser.add_argument("--disable-preview", action="store_true", help="Disable web page link previews")
    parser.add_argument("-c", "--chat-id", type=str, help="Override Telegram Channel or Chat ID")
    parser.add_argument("-t", "--token", type=str, help="Override Telegram Bot Token")
    parser.add_argument("-e", "--env-file", type=str, help="Explicit path to .env file")
    parser.add_argument("--dry-run", action="store_true", help="Preview formatting without sending to Telegram API")
    parser.add_argument("--test-connection", action="store_true", help="Test bot token connectivity via getMe and exit")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    token, chat_id, source = get_telegram_credentials(args.token, args.chat_id, args.env_file)

    if not token and not args.dry_run:
        print("[!] Error: BOT_TOKEN not found. Set it in .env, environment variable, or pass --token.", file=sys.stderr)
        sys.exit(1)

    if not chat_id and not args.dry_run and not args.test_connection:
        print("[!] Error: CHANNEL / CHAT_ID not found. Set it in .env, environment variable, or pass --chat-id.", file=sys.stderr)
        sys.exit(1)

    masked_token = f"{token[:8]}...{token[-5:]}" if len(token) > 13 else "***"
    print("═" * 60)
    print("  TELEGRAM DISPATCH INFRASTRUCTURE")
    print(f"  Config Source: {source}")
    print(f"  Bot Token    : {masked_token}")
    print(f"  Chat / Target: {chat_id}")
    print("═" * 60)

    dispatcher = TelegramDispatcher(token or "DUMMY:TOKEN", chat_id or "0")

    if args.test_connection:
        print("[*] Testing bot credentials...")
        try:
            bot_info = dispatcher.test_connection()
            print(f"[✓] Connected successfully as @{bot_info.get('username')} ({bot_info.get('first_name')})")
            sys.exit(0)
        except Exception as e:
            print(f"[!] Connectivity test failed: {e}", file=sys.stderr)
            sys.exit(1)

    raw_content = ""
    if args.message:
        raw_content = args.message
    elif args.file_path:
        fp = Path(args.file_path).expanduser().resolve()
        if not fp.is_file():
            print(f"[!] Error: File not found: {args.file_path}", file=sys.stderr)
            sys.exit(1)
        with open(fp, "r", encoding="utf-8-sig") as f:
            raw_content = f.read()

    images = args.image_paths or []
    mode = args.mode or ("carousel" if len(images) > 1 else "photo" if len(images) == 1 else "text")

    print(f"[*] Dispatch Mode: {mode.upper()}")

    formatted_html = ""
    if raw_content:
        if args.card:
            formatted_html = build_message_card(
                content=raw_content,
                title=args.title,
                platform=args.platform,
                hook=args.hook,
                comment_content=args.comment
            )
        else:
            formatted_html = markdown_to_telegram_html(raw_content)

    if args.dry_run:
        print("\n[DRY RUN PREVIEW]")
        print("-" * 60)
        max_chunk = 1000 if mode in ("photo", "carousel") else 4000
        chunks = split_html_message(formatted_html, max_len=max_chunk) if formatted_html else []
        print(f"Total Chunks: {len(chunks)} (Max chunk length threshold: {max_chunk})")
        for i, c in enumerate(chunks):
            print(f"\n--- Chunk {i+1}/{len(chunks)} ({len(c)} chars) ---")
            print(c)
        print("-" * 60)
        print("[✓] Dry run finished successfully. No messages were dispatched.")
        sys.exit(0)

    try:
        if mode == "text":
            if not formatted_html:
                print("[!] Error: No text content provided for 'text' mode.", file=sys.stderr)
                sys.exit(1)
            dispatcher.send_text(formatted_html, disable_preview=args.disable_preview)
        elif mode == "photo":
            dispatcher.send_photo(images[0], caption=formatted_html)
        elif mode == "carousel":
            dispatcher.send_media_group(images, caption=formatted_html)

        print("═" * 60)
        print("  [SUCCESS] Dispatched to Telegram!")
        print("═" * 60)
    except Exception as e:
        print(f"\n[!] Telegram Dispatch Failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
