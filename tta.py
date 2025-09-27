#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tippi Tappi Animator (tta.py)
"""

from __future__ import annotations

import os
import sys
import json
import math
import shutil
import queue
import tempfile
import threading
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Optional, Dict

# --- Optional dependency check: Pillow ---
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    PIL_OK = True
except Exception as e:
    PIL_OK = False
    PIL_IMPORT_ERROR = e

# --- Optional dependency check: Tkinter (for GUI) ---
GUI_AVAILABLE = True
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except Exception:
    GUI_AVAILABLE = False


# -------------------------------
# Theming
# -------------------------------

@dataclass
class Theme:
    name: str
    bg_color: Tuple[int,int,int,int]
    chat_bg: Tuple[int,int,int,int]
    divider_color: Tuple[int,int,int,int]
    user_bubble: Tuple[int,int,int,int]
    user_border: Tuple[int,int,int,int]
    ai_bubble: Tuple[int,int,int,int]
    ai_border: Tuple[int,int,int,int]
    system_bubble: Tuple[int,int,int,int]
    system_border: Tuple[int,int,int,int]
    text_color: Tuple[int,int,int,int]
    meta_text: Tuple[int,int,int,int]
    typing_dots: Tuple[int,int,int,int]
    accent: Tuple[int,int,int,int]
    profile_border: Tuple[int,int,int,int]
    scanline_alpha: int

THEME_MATRIX = Theme(
    name="matrix",
    bg_color=(11, 15, 16, 255),
    chat_bg=(9, 12, 13, 255),
    divider_color=(20, 50, 35, 255),
    user_bubble=(18, 26, 22, 255),
    user_border=(0, 175, 95, 180),
    ai_bubble=(16, 20, 22, 255),
    ai_border=(0, 190, 140, 180),
    system_bubble=(22, 24, 24, 255),
    system_border=(60, 65, 65, 160),
    text_color=(210, 255, 210, 255),
    meta_text=(120, 180, 140, 255),
    typing_dots=(0, 255, 140, 220),
    accent=(0, 200, 120, 160),
    profile_border=(0, 200, 120, 200),
    scanline_alpha=22,
)

THEME_LIGHT = Theme(
    name="light",
    bg_color=(245, 247, 250, 255),
    chat_bg=(255, 255, 255, 255),
    divider_color=(220, 226, 230, 255),
    user_bubble=(230, 244, 255, 255),
    user_border=(120, 190, 255, 180),
    ai_bubble=(236, 255, 236, 255),
    ai_border=(140, 220, 160, 180),
    system_bubble=(245, 245, 245, 255),
    system_border=(200, 200, 200, 160),
    text_color=(24, 24, 24, 255),
    meta_text=(90, 90, 95, 255),
    typing_dots=(150, 150, 150, 255),
    accent=(120, 180, 255, 120),
    profile_border=(120, 180, 255, 200),
    scanline_alpha=0,
)

THEMES = {"matrix": THEME_MATRIX, "dark": THEME_MATRIX, "light": THEME_LIGHT}


# -------------------------------
# Utility and configuration
# -------------------------------

ROLES_USER = {"user", "user2"}
ROLES_AI = {"assistant", "ai"}
ROLES_SYSTEM = {"system"}

ALL_ROLES = ROLES_USER | ROLES_AI | ROLES_SYSTEM

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30
DEFAULT_LENGTH = 60  # seconds

# Layout ratios/margins
PAUSE_BETWEEN_MSGS = 5.0  # seconds between messages

# Make avatar area bigger (chat panel is 55% now, avatar gets 45%)
CHAT_PANEL_RATIO = 0.55  # width ratio of chat panel vs avatar panel (was 0.60)

# Base spacing unit (kept for vertical rhythm and legacy uses)
MARGIN = 24

# New: precise layout controls
BUBBLE_RADIUS = 16
PROFILE_SIZE = 48
LINE_SPACING = 6

# Extra side gutter for the chat panel so messages don't hug the edge
CHAT_SIDE_PADDING = 40

# Inner padding for text inside each bubble
BUBBLE_PADDING = 24

# Tighter margin around the avatar to enlarge the image within its panel
AVATAR_MARGIN = 12

MAX_CHARS_PER_SEC = 30.0  # clamp typing speed
MIN_CHARS_PER_SEC = 8.0
MIN_TYPE_SECONDS = 3.0

ASSETS = {
    "avatar_step1": "step1.png",
    "avatar_step2": "step2.png",
    "avatar_idle": "idle.png",
    "profile_user": "profile_user.jpg",
    "profile_ai": "profile_ai.jpg",
}

PLACEHOLDER_COLORS = {
    "avatar_step1": (20, 40, 28),
    "avatar_step2": (20, 45, 35),
    "avatar_idle": (30, 32, 34),
    "profile_user": (40, 120, 80),
    "profile_ai": (40, 120, 100),
}


def which_ffmpeg() -> Optional[str]:
    cmd = ["ffmpeg", "-version"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode == 0:
            return "ffmpeg"
    except Exception:
        pass
    if os.name == "nt":
        cmd = ["ffmpeg.exe", "-version"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True)
            if out.returncode == 0:
                return "ffmpeg.exe"
        except Exception:
            pass
    return None


def ensure_pillow_or_exit(gui_mode: bool):
    if PIL_OK:
        return
    msg = (
        "Missing dependency: Pillow (PIL)\\n\\n"
        f"Import error: {PIL_IMPORT_ERROR}\\n\\n"
        "Install with:\\n    pip install pillow\\n"
    )
    if gui_mode and GUI_AVAILABLE:
        messagebox.showerror("Dependency missing", msg)
    else:
        print(msg, file=sys.stderr)
    sys.exit(2)


def _safe_text_size(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        w = max(0, bbox[2] - bbox[0]); h = max(0, bbox[3] - bbox[1])
        return (w, h)
    except Exception:
        try:
            bbox = font.getbbox(text)
            w = max(0, bbox[2] - bbox[0]); h = max(0, bbox[3] - bbox[1])
            return (w, h)
        except Exception:
            try:
                return font.getsize(text)
            except Exception:
                avg_w = 0.6 * (getattr(font, "size", 20))
                return (int(avg_w * len(text)), int(getattr(font, "size", 20) * 1.2))


# Pillow resampling compatibility (Pillow 10+ uses Image.Resampling)
try:
    _Resampling = getattr(Image, "Resampling")
    LANCZOS_RESAMPLE = getattr(_Resampling, "LANCZOS")
except Exception:
    LANCZOS_RESAMPLE = getattr(Image, "LANCZOS", getattr(Image, "BICUBIC", 1))


def try_find_font():
    # Prefer monospace for Matrix vibe
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/System/Library/Fonts/Supplemental/Consolas.ttf",
        os.path.join(os.environ.get("WINDIR", "C:\\\\Windows"), "Fonts", "consola.ttf"),
        os.path.join(os.environ.get("WINDIR", "C:\\\\Windows"), "Fonts", "cour.ttf"),
        # Sans fallbacks
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        os.path.join(os.environ.get("WINDIR", "C:\\\\Windows"), "Fonts", "arial.ttf"),
        os.path.join(os.environ.get("WINDIR", "C:\\\\Windows"), "Fonts", "segoeui.ttf"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, 28)
            except Exception:
                continue
    return ImageFont.load_default()


def load_or_make_placeholder(path: str, size: Tuple[int, int], label: str, bg_color: Tuple[int,int,int]) -> Image.Image:
    if os.path.isfile(path):
        try:
            img = Image.open(path).convert("RGBA")
            return img
        except Exception:
            pass
    w, h = size
    img = Image.new("RGBA", (w, h), bg_color + (255,))
    draw = ImageDraw.Draw(img)
    try:
        font = try_find_font()
        if hasattr(font, "size"):
            try:
                font = ImageFont.truetype(getattr(font, "path", ""), max(16, min(28, int(h*0.2))))
            except Exception:
                pass
    except Exception:
        font = ImageFont.load_default()
    tw, th = _safe_text_size(draw, label, font)
    draw.text(((w - tw) / 2, (h - th) / 2), label, fill=(200,255,210,255), font=font)
    return img


def rounded_rectangle(draw: ImageDraw.ImageDraw, xy, radius, fill, outline=None, width=1):
    (x1, y1, x2, y2) = xy
    r = max(0, int(radius))
    if fill is not None:
        draw.rectangle([x1 + r, y1, x2 - r, y2], fill=fill, outline=None)
        draw.rectangle([x1, y1 + r, x2, y2 - r], fill=fill, outline=None)
        draw.pieslice([x1, y1, x1 + 2*r, y1 + 2*r], 180, 270, fill=fill, outline=None)
        draw.pieslice([x2 - 2*r, y1, x2, y1 + 2*r], 270, 360, fill=fill, outline=None)
        draw.pieslice([x1, y2 - 2*r, x1 + 2*r, y2], 90, 180, fill=fill, outline=None)
        draw.pieslice([x2 - 2*r, y2 - 2*r, x2, y2], 0, 90, fill=fill, outline=None)
    if outline is not None and width > 0:
        for i in range(width):
            rect = (x1 + i, y1 + i, x2 - i, y2 - i)
            draw.arc([rect[0], rect[1], rect[0]+2*r, rect[1]+2*r], 180, 270, fill=outline)
            draw.arc([rect[2]-2*r, rect[1], rect[2], rect[1]+2*r], 270, 360, fill=outline)
            draw.arc([rect[0], rect[3]-2*r, rect[0]+2*r, rect[3]], 90, 180, fill=outline)
            draw.arc([rect[2]-2*r, rect[3]-2*r, rect[2], rect[3]], 0, 90, fill=outline)
            draw.line([rect[0]+r, rect[1], rect[2]-r, rect[1]], fill=outline)
            draw.line([rect[0]+r, rect[3], rect[2]-r, rect[3]], fill=outline)
            draw.line([rect[0], rect[1]+r, rect[0], rect[3]-r], fill=outline)
            draw.line([rect[2], rect[1]+r, rect[2], rect[3]-r], fill=outline)


@dataclass
class MessageItem:
    role: str
    text: str
    chars: int = 0
    t_start: float = 0.0
    t_type_end: float = 0.0
    t_end_with_pause: float = 0.0

    def is_avatar_active(self) -> bool:
        return self.role in ROLES_USER


def parse_json_messages(json_path: str) -> List[MessageItem]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "messages" in data:
        items = data["messages"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("JSON must be a list of messages or an object with a 'messages' list.")

    results: List[MessageItem] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        role = str(it.get("role") or it.get("speaker") or "system").lower().strip()
        if role not in ALL_ROLES:
            if role == "ai":
                role = "assistant"
            elif role not in ALL_ROLES:
                role = "system"
        text = str(it.get("message") or it.get("text") or "")
        text = text.replace("\\r\\n", "\\n").replace("\\r", "\\n")
        results.append(MessageItem(role=role, text=text, chars=len(text)))
    if not results:
        raise ValueError("No valid messages found in JSON.")
    return results


DEFAULT_TOTAL_LENGTH = 60.0
PAUSE_BETWEEN_MSGS = 5.0
TAIL_HOLD_SECONDS = 5.0

def compute_timeline(messages: List[MessageItem], total_length: float, pause_between: float = PAUSE_BETWEEN_MSGS, tail_hold: float = TAIL_HOLD_SECONDS) -> None:
    total_chars = sum(max(1, m.chars) for m in messages)
    num_pauses = max(0, len(messages) - 1)
    reserved_pause = pause_between * num_pauses
    reserved_tail = max(0.0, tail_hold)
    available_for_typing = max(0.5, total_length - reserved_pause - reserved_tail)

    cps = total_chars / available_for_typing if available_for_typing > 0 else MAX_CHARS_PER_SEC
    cps = min(MAX_CHARS_PER_SEC, max(MIN_CHARS_PER_SEC, cps))

    typing_durations = []
    for m in messages:
        dur = max(MIN_TYPE_SECONDS, m.chars / cps)
        typing_durations.append(dur)

    sum_typing = sum(typing_durations)
    if sum_typing > available_for_typing and sum_typing > 0:
        scale = available_for_typing / sum_typing
        typing_durations = [max(MIN_TYPE_SECONDS, d * scale) for d in typing_durations]
        sum_typing = sum(typing_durations)

    t = 0.0
    for idx, m in enumerate(messages):
        m.t_start = t
        m.t_type_end = t + typing_durations[idx]
        t = m.t_type_end
        if idx < len(messages) - 1:
            t += pause_between
        else:
            t += reserved_tail
        m.t_end_with_pause = t


def text_wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
    if text is None or text == "":
        return [""]
    paragraphs = str(text).split("\\n")
    out_lines: List[str] = []
    for para in paragraphs:
        words = para.split(" ") if para else [""]
        current = ""
        for word in words:
            candidate = word if current == "" else current + " " + word
            w, _ = _safe_text_size(draw, candidate, font)
            if w <= max_width:
                current = candidate
            else:
                if current:
                    out_lines.append(current)
                w_word, _ = _safe_text_size(draw, word, font)
                if w_word <= max_width:
                    current = word
                else:
                    tmp = ""
                    for ch in word:
                        w_tmp, _ = _safe_text_size(draw, tmp + ch, font)
                        if w_tmp <= max_width:
                            tmp += ch
                        else:
                            if tmp:
                                out_lines.append(tmp)
                            tmp = ch
                    current = tmp
        if current != "" or para == "":
            out_lines.append(current)
    return out_lines



class FrameRenderer:
    def __init__(self,
                 messages: List[MessageItem],
                 width: int = DEFAULT_WIDTH,
                 height: int = DEFAULT_HEIGHT,
                 fps: int = DEFAULT_FPS,
                 chat_panel_ratio: float = CHAT_PANEL_RATIO,
                 assets_dir: str = ".",
                 output_path: str = "output.mp4",
                 theme: Theme = THEME_MATRIX,
                 title: Optional[str] = None):
        if not PIL_OK:
            raise RuntimeError("Pillow is required to render frames. Install with 'pip install pillow'.")
        self.messages = messages
        self.width = width
        self.height = height
        self.fps = fps
        self.chat_panel_ratio = chat_panel_ratio
        self.assets_dir = assets_dir
        self.output_path = output_path
        self.theme = theme
        self.title_text = (title or "").strip()

        # Layout
        self.chat_w = int(self.width * self.chat_panel_ratio)
        self.avatar_w = self.width - self.chat_w
        self.chat_x = self.avatar_w
        self.avatar_x = 0

        # Colors
        self.bg_color = theme.bg_color
        self.divider_color = theme.divider_color
        self.chat_bg = theme.chat_bg
        self.user_bubble = theme.user_bubble
        self.user_border = theme.user_border
        self.ai_bubble = theme.ai_bubble
        self.ai_border = theme.ai_border
        self.system_bubble = theme.system_bubble
        self.system_border = theme.system_border
        self.text_color = theme.text_color
        self.meta_text = theme.meta_text
        self.typing_dots = theme.typing_dots
        self.accent = theme.accent
        self.profile_border = theme.profile_border

        # Fonts
        self.font_main = try_find_font()
        try:
            if hasattr(self.font_main, "size"):
                size_meta = max(16, int(getattr(self.font_main, "size", 28) * 0.7))
                path_attr = getattr(self.font_main, "path", None)
                if path_attr:
                    self.font_meta = ImageFont.truetype(path_attr, size_meta)
                else:
                    self.font_meta = ImageFont.load_default()
            else:
                self.font_meta = ImageFont.load_default()
        except Exception:
            self.font_meta = ImageFont.load_default()

        # Title font
        try:
            base_sz = getattr(self.font_main, "size", 28)
            title_sz = max(22, int(base_sz * 1.15))
            path_attr = getattr(self.font_main, "path", None)
            if path_attr:
                self.font_title = ImageFont.truetype(path_attr, title_sz)
            else:
                self.font_title = ImageFont.load_default()
        except Exception:
            self.font_title = ImageFont.load_default()

        # Header sizing
        self.header_h = 0
        if self.title_text:
            dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
            d = ImageDraw.Draw(dummy)
            _, th = _safe_text_size(d, self.title_text, self.font_title)
            # generous vertical padding so it never clashes
            self.header_pad_y = max(10, int(th * 0.35))
            self.header_h = th + 2 * self.header_pad_y

        # Effective content area (everything below the header)
        self.content_height = max(1, self.height - self.header_h)

        # Assets
        self.assets = self._load_assets()

        # Precompute frame count
        self.total_duration = self.messages[-1].t_end_with_pause if self.messages else 0.0
        self.total_frames = int(math.ceil(self.total_duration * self.fps))
        if self.total_frames < 1:
            self.total_frames = 1

    def _load_assets(self) -> Dict[str, Image.Image]:
        assets: Dict[str, Image.Image] = {}
        # Larger avatar within its panel by using a tighter margin, respecting header space
        avatar_target_size = (
            max(10, self.avatar_w - 2*AVATAR_MARGIN),
            max(10, self.content_height - 2*AVATAR_MARGIN)
        )
        for key, filename in ASSETS.items():
            pth = os.path.join(self.assets_dir, filename)
            bg = PLACEHOLDER_COLORS.get(key, (22, 24, 24))
            label = key.replace("avatar_", "").replace("profile_", "").upper()
            if key.startswith("avatar_"):
                img = load_or_make_placeholder(pth, avatar_target_size, label, bg)
                img = ImageOps.contain(img, avatar_target_size, method=LANCZOS_RESAMPLE)
                canvas = Image.new("RGBA", avatar_target_size, (255,255,255,0))
                off_x = (avatar_target_size[0] - img.width)//2
                off_y = (avatar_target_size[1] - img.height)//2
                canvas.paste(img, (off_x, off_y), img if img.mode == "RGBA" else None)
                assets[key] = canvas
            else:
                img = load_or_make_placeholder(pth, (PROFILE_SIZE, PROFILE_SIZE), label, bg)
                img = ImageOps.fit(img, (PROFILE_SIZE, PROFILE_SIZE), method=LANCZOS_RESAMPLE)
                mask = Image.new("L", (PROFILE_SIZE, PROFILE_SIZE), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0,0,PROFILE_SIZE,PROFILE_SIZE), fill=255)
                rounded = Image.new("RGBA", (PROFILE_SIZE, PROFILE_SIZE), (255,255,255,0))
                rounded.paste(img, (0,0), mask)
                assets[key] = rounded
        return assets

    def _current_message_index(self, t: float) -> int:
        for i, m in enumerate(self.messages):
            if m.t_start <= t < m.t_end_with_pause:
                return i
        return len(self.messages) - 1

    def _typed_chars_by_time(self, m: MessageItem, t: float) -> int:
        if t <= m.t_start:
            return 0
        if t >= m.t_type_end:
            return m.chars
        dur = max(0.001, (m.t_type_end - m.t_start))
        progress = (t - m.t_start) / dur
        count = int(math.floor(progress * m.chars))
        return max(0, min(m.chars, count))

    def _avatar_frame_for_time(self, t: float) -> Image.Image:
        idx = self._current_message_index(t)
        m = self.messages[idx]
        if (not m.is_avatar_active()) or not (m.t_start <= t < m.t_type_end):
            return self.assets['avatar_idle']
        typed = self._typed_chars_by_time(m, t)
        if typed <= 0:
            return self.assets['avatar_idle']
        phase = ((typed - 1) // 2) % 2
        return self.assets['avatar_step1'] if (phase == 0) else self.assets['avatar_step2']

    def _apply_scanlines(self, img: Image.Image) -> Image.Image:
        if THEMES["matrix"].scanline_alpha <= 0:
            return img
        overlay = Image.new("RGBA", img.size, (0,0,0,0))
        d = ImageDraw.Draw(overlay)
        a = THEMES["matrix"].scanline_alpha
        for y in range(0, img.height, 3):
            d.line([(0, y), (img.width, y)], fill=(0, 0, 0, a))
        return Image.alpha_composite(img, overlay)

    def _draw_header(self, base: Image.Image) -> None:
        if not self.title_text:
            return
        d = ImageDraw.Draw(base)
        # Header background
        d.rectangle([0, 0, self.width, self.header_h], fill=self.chat_bg)
        # Bottom divider
        d.line([(0, self.header_h-1), (self.width, self.header_h-1)], fill=self.divider_color, width=2)
        # Title text
        tx = CHAT_SIDE_PADDING
        dummy = Image.new("RGBA", (10,10), (0,0,0,0))
        draw_dummy = ImageDraw.Draw(dummy)
        tw, th = _safe_text_size(draw_dummy, self.title_text, self.font_title)
        ty = (self.header_h - th) // 2
        d.text((tx, ty), self.title_text, fill=self.meta_text, font=self.font_title)

    def _draw_avatar_panel(self, base: Image.Image, t: float) -> None:
        panel = Image.new("RGBA", (self.avatar_w, self.content_height), self.bg_color)
        d = ImageDraw.Draw(panel)
        step = 24
        acc = self.accent
        grid_alpha = 35
        for x in range(0, self.avatar_w, step):
            d.line([(x,0),(x,self.content_height)], fill=(acc[0], acc[1], acc[2], grid_alpha))
        for y in range(0, self.content_height, step):
            d.line([(0,y),(self.avatar_w,y)], fill=(acc[0], acc[1], acc[2], grid_alpha//2))
        d.rectangle([self.avatar_w-3, 0, self.avatar_w-1, self.content_height], fill=self.accent)

        avatar = self._avatar_frame_for_time(t)
        pos = (AVATAR_MARGIN, AVATAR_MARGIN)
        box = (pos[0]-6, pos[1]-6, pos[0]+avatar.width+6, pos[1]+avatar.height+6)
        rounded_rectangle(d, box, radius=10, fill=None, outline=self.accent, width=1)
        panel.paste(avatar, pos, avatar if avatar.mode == "RGBA" else None)

        panel = self._apply_scanlines(panel)
        base.paste(panel, (self.avatar_x, self.header_h))

    def _bubble_colors_for_role(self, role: str) -> Tuple[Tuple[int,int,int,int], str]:
        if role in ROLES_USER:
            return self.user_bubble, "user"
        if role in ROLES_AI:
            return self.ai_bubble, "assistant"
        return self.system_bubble, "system"

    def _draw_chat_panel(self, base: Image.Image, t: float) -> None:
        all_visible = []
        for m in self.messages:
            if t < m.t_start:
                break
            typed = m.chars if t >= m.t_type_end else self._typed_chars_by_time(m, t)
            all_visible.append((m, typed))

        chat_w = self.chat_w

        x_left = CHAT_SIDE_PADDING
        x_right = chat_w - CHAT_SIDE_PADDING
        PROFILE_GAP = max(10, MARGIN // 2)
        max_text_w = chat_w - 2*CHAT_SIDE_PADDING - PROFILE_SIZE - PROFILE_GAP - 2*BUBBLE_PADDING
        max_text_w = max(50, max_text_w)
        V_GAP = max(10, PROFILE_SIZE // 3)

        dummy = Image.new("RGBA", (10,10), (0,0,0,0))
        draw_dummy = ImageDraw.Draw(dummy)

        entries = []
        if not all_visible:
            banner = "Conversation starting…"
            w, h = _safe_text_size(draw_dummy, banner, self.font_meta)
            entries.append({"type": "banner", "size": (w, h)})
            content_h = MARGIN + h + MARGIN
        else:
            content_h = MARGIN
            for (m, typed) in all_visible:
                bubble_color, role_norm = self._bubble_colors_for_role(m.role)
                is_user = (role_norm == "user")
                profile_img = self.assets["profile_user"] if is_user else self.assets["profile_ai"]
                display_text = m.text[:typed]

                lines = text_wrap(draw_dummy, display_text, self.font_main, max_text_w)
                is_current = (m.t_start <= t < m.t_type_end)
                if is_current:
                    blink_on = (int((t - m.t_start) * 2) % 2) == 0
                    if blink_on:
                        if lines:
                            lines[-1] = lines[-1] + "|"
                        else:
                            lines.append("|")

                text_w = 0; text_h = 0; line_heights = []
                for line in lines:
                    w, h = _safe_text_size(draw_dummy, line, self.font_main)
                    text_w = max(text_w, w); text_h += h + LINE_SPACING; line_heights.append(h)
                if lines:
                    text_h -= LINE_SPACING

                bubble_w = text_w + 2*BUBBLE_PADDING
                bubble_h = text_h + 2*BUBBLE_PADDING

                entries.append({
                    "type": "msg",
                    "m": m,
                    "is_user": is_user,
                    "bubble_color": bubble_color,
                    "role_norm": role_norm,
                    "profile_img": profile_img,
                    "lines": lines,
                    "line_heights": line_heights,
                    "bubble_size": (bubble_w, bubble_h),
                })
                content_h += max(bubble_h, PROFILE_SIZE) + V_GAP
            content_h += MARGIN

        panel_h = max(self.content_height, content_h)
        tall = Image.new("RGBA", (chat_w, panel_h), self.chat_bg)
        d = ImageDraw.Draw(tall)
        d.line([(0,0),(0,panel_h)], fill=self.divider_color, width=2)

        y = MARGIN
        if len(entries) == 1 and entries[0].get("type") == "banner":
            banner = "Conversation starting…"
            d.text((CHAT_SIDE_PADDING, y), banner, fill=self.meta_text, font=self.font_meta)
            y += entries[0]["size"][1] + MARGIN
        else:
            for ent in entries:
                if ent["type"] != "msg":
                    continue
                bubble_w, bubble_h = ent["bubble_size"]
                is_user = ent["is_user"]
                profile_img = ent["profile_img"]
                lines = ent["lines"]
                line_heights = ent["line_heights"]
                role_norm = ent["role_norm"]
                bubble_color = ent["bubble_color"]

                if is_user:
                    bubble_x2 = x_right - PROFILE_SIZE - PROFILE_GAP
                    bubble_x1 = bubble_x2 - bubble_w
                    profile_pos = (x_right - PROFILE_SIZE, y)
                    border_color = self.user_border
                else:
                    bubble_x1 = x_left + PROFILE_SIZE + PROFILE_GAP
                    bubble_x2 = bubble_x1 + bubble_w
                    profile_pos = (x_left, y)
                    border_color = self.ai_border if role_norm == "assistant" else self.system_border

                ring = Image.new("RGBA", (PROFILE_SIZE+6, PROFILE_SIZE+6), (0,0,0,0))
                dr = ImageDraw.Draw(ring)
                dr.ellipse((0,0,PROFILE_SIZE+6,PROFILE_SIZE+6), fill=(0,0,0,0), outline=self.profile_border, width=2)
                tall.paste(ring, (profile_pos[0]-3, profile_pos[1]-3), ring)
                tall.paste(profile_img, profile_pos, profile_img)

                bubble_y1 = y
                bubble_y2 = y + bubble_h
                rounded_rectangle(d, (bubble_x1, bubble_y1, bubble_x2, bubble_y2),
                                  radius=BUBBLE_RADIUS, fill=bubble_color, outline=border_color, width=2)

                tx = bubble_x1 + BUBBLE_PADDING
                ty = bubble_y1 + BUBBLE_PADDING
                for line, lh in zip(lines, line_heights):
                    d.text((tx, ty), line, fill=self.text_color, font=self.font_main)
                    ty += lh + LINE_SPACING

                y += max(bubble_h, PROFILE_SIZE) + V_GAP

        if panel_h > self.content_height:
            offset = panel_h - self.content_height
            panel = tall.crop((0, offset, chat_w, offset + self.content_height))
        else:
            panel = tall

        panel = self._apply_scanlines(panel)
        base.paste(panel, (self.chat_x, self.header_h))

    def render_frame(self, t: float) -> Image.Image:
        base = Image.new("RGBA", (self.width, self.height), self.bg_color)
        # Draw header first so panels can paste below it
        self._draw_header(base)
        self._draw_avatar_panel(base, t)
        self._draw_chat_panel(base, t)
        return base

    def render_all_frames(self, tmp_dir: str, progress_cb=None) -> None:
        for i in range(self.total_frames):
            t = i / float(self.fps)
            frame = self.render_frame(t)
            out_path = os.path.join(tmp_dir, f"frame_{i:06d}.png")
            frame_rgb = frame.convert("RGB")
            frame_rgb.save(out_path, format="PNG", compress_level=1)
            if progress_cb and i % max(1, self.fps // 2) == 0:
                progress_cb(i+1, self.total_frames)

    def encode_with_ffmpeg(self, tmp_dir: str, ffmpeg_path: str) -> Tuple[bool, str]:
        pattern = os.path.join(tmp_dir, "frame_%06d.png")
        cmd = [
            ffmpeg_path, "-y",
            "-framerate", str(self.fps),
            "-i", pattern,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-r", str(self.fps),
            self.output_path
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            ok = (proc.returncode == 0)
            return ok, (proc.stdout + "\\n" + proc.stderr)
        except Exception as e:
            return False, str(e)


# -------------------------------
# GUI Application
# -------------------------------

class TippiTappiGUI:
    def __init__(self):
        if not GUI_AVAILABLE:
            print("Tkinter is not available in this Python environment.", file=sys.stderr)
            sys.exit(2)

        self.root = tk.Tk()
        self.root.title("Tippi Tappi Animator — Matrix Edition")
        self.root.geometry("1000x680")

        self.messages: List[MessageItem] = []
        self.json_path: Optional[str] = None

        # UI State
        self.total_len_var = tk.DoubleVar(value=DEFAULT_LENGTH)
        self.fps_var = tk.IntVar(value=DEFAULT_FPS)
        self.width_var = tk.IntVar(value=DEFAULT_WIDTH)
        self.height_var = tk.IntVar(value=DEFAULT_HEIGHT)
        self.output_path_var = tk.StringVar(value=self._default_output_path())
        self.assets_dir_var = tk.StringVar(value=os.getcwd())
        self.theme_var = tk.StringVar(value="matrix")
        self.title_var = tk.StringVar(value="")

        self._build_ui()

    def _default_output_path(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.abspath(f"tta_render_{stamp}.mp4")

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        ttk.Button(top, text="Load JSON…", command=self.load_json).pack(side="left")
        self.json_label = ttk.Label(top, text="No file loaded")
        self.json_label.pack(side="left", padx=10)

        settings = ttk.LabelFrame(self.root, text="Video Settings")
        settings.pack(fill="x", **pad)

        row1 = ttk.Frame(settings); row1.pack(fill="x", **pad)
        ttk.Label(row1, text="Total length (sec):").pack(side="left")
        length_scale = ttk.Scale(row1, from_=10, to=600, orient="horizontal", variable=self.total_len_var)
        length_scale.pack(side="left", fill="x", expand=True, padx=10)
        ttk.Entry(row1, textvariable=self.total_len_var, width=8).pack(side="left")

        row2 = ttk.Frame(settings); row2.pack(fill="x", **pad)
        ttk.Label(row2, text="FPS:").pack(side="left")
        ttk.Entry(row2, textvariable=self.fps_var, width=6).pack(side="left", padx=(0,20))

        ttk.Label(row2, text="Width:").pack(side="left")
        ttk.Entry(row2, textvariable=self.width_var, width=8).pack(side="left", padx=(0,10))

        ttk.Label(row2, text="Height:").pack(side="left")
        ttk.Entry(row2, textvariable=self.height_var, width=8).pack(side="left", padx=(0,10))

        row_theme = ttk.Frame(settings); row_theme.pack(fill="x", **pad)
        ttk.Label(row_theme, text="Theme:").pack(side="left")
        ttk.Combobox(row_theme, textvariable=self.theme_var, values=["matrix","light"], width=10, state="readonly").pack(side="left", padx=(10,0))

        row_title = ttk.Frame(settings); row_title.pack(fill="x", **pad)
        ttk.Label(row_title, text="Title/Label (optional):").pack(side="left")
        ttk.Entry(row_title, textvariable=self.title_var, width=50).pack(side="left", padx=(10,0), fill="x", expand=True)

        row3 = ttk.Frame(settings); row3.pack(fill="x", **pad)
        ttk.Label(row3, text="Assets folder:").pack(side="left")
        ttk.Entry(row3, textvariable=self.assets_dir_var, width=50).pack(side="left", padx=(0,10))
        ttk.Button(row3, text="Browse…", command=self.browse_assets_dir).pack(side="left")

        row4 = ttk.Frame(settings); row4.pack(fill="x", **pad)
        ttk.Label(row4, text="Output file:").pack(side="left")
        ttk.Entry(row4, textvariable=self.output_path_var, width=50).pack(side="left", padx=(0,10))
        ttk.Button(row4, text="Choose…", command=self.choose_output).pack(side="left")

        actions = ttk.Frame(self.root); actions.pack(fill="x", **pad)
        ttk.Button(actions, text="Render video", command=self.render_video).pack(side="left")

        progframe = ttk.LabelFrame(self.root, text="Progress")
        progframe.pack(fill="both", expand=True, **pad)

        self.progress = ttk.Progressbar(progframe, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=10)

        self.log = tk.Text(progframe, height=16, wrap="word")
        self.log.pack(fill="both", expand=True, padx=10, pady=(0,10))

        self._log("Ready. Load a JSON to begin.")

    def _log(self, msg: str):
        self.log.insert("end", msg + "\\n")
        self.log.see("end")
        self.root.update_idletasks()

    def browse_assets_dir(self):
        d = filedialog.askdirectory(title="Choose assets folder", initialdir=self.assets_dir_var.get())
        if d:
            self.assets_dir_var.set(d)

    def choose_output(self):
        path = filedialog.asksaveasfilename(
            title="Choose output file",
            defaultextension=".mp4",
            filetypes=[("MP4 video","*.mp4"), ("All files","*.*")],
            initialfile=os.path.basename(self.output_path_var.get())
        )
        if path:
            self.output_path_var.set(path)

    def load_json(self):
        path = filedialog.askopenfilename(
            title="Open conversation JSON",
            filetypes=[("JSON files","*.json"), ("All files","*.*")]
        )
        if not path:
            return
        try:
            msgs = parse_json_messages(path)
        except Exception as e:
            messagebox.showerror("Invalid JSON", f"Failed to parse JSON:\\n\\n{e}")
            return
        self.messages = msgs
        self.json_path = path
        self.json_label.config(text=f"{os.path.basename(path)}  ({len(msgs)} messages)")
        self._log(f"Loaded {len(msgs)} messages from: {path}")

    def render_video(self):
        if not self.messages:
            messagebox.showwarning("No messages", "Please load a JSON conversation first.")
            return

        ensure_pillow_or_exit(gui_mode=True)

        ffmpeg = which_ffmpeg()
        if not ffmpeg:
            messagebox.showerror("ffmpeg not found",
                                 "ffmpeg is required to encode the video.\\n"
                                 "Install from https://ffmpeg.org and ensure it's on your PATH.")
            return

        try:
            total_len = float(self.total_len_var.get())
            fps = int(self.fps_var.get())
            width = int(self.width_var.get())
            height = int(self.height_var.get())
            assets_dir = str(self.assets_dir_var.get())
            output_path = str(self.output_path_var.get())
            theme_name = self.theme_var.get()
        except Exception as e:
            messagebox.showerror("Invalid settings", f"Please check video settings:\\n\\n{e}")
            return

        if total_len <= 5 or fps < 5 or width < 320 or height < 240:
            messagebox.showerror("Settings out of range", "Please choose sensible values for length, FPS, and resolution.")
            return

        msgs = [MessageItem(role=m.role, text=m.text, chars=m.chars) for m in self.messages]
        compute_timeline(msgs, total_len, pause_between=PAUSE_BETWEEN_MSGS)

        self.progress["value"] = 0
        self._log("Starting render…")

        self._progress_queue = queue.Queue()
        self._render_thread = threading.Thread(
            target=self._render_worker,
            args=(msgs, width, height, fps, assets_dir, output_path, ffmpeg, theme_name, str(self.title_var.get() or "")),
            daemon=True
        )
        self._render_thread.start()
        self.root.after(100, self._poll_progress)

    def _poll_progress(self):
        try:
            while True:
                item = self._progress_queue.get_nowait()
                kind = item.get("kind")
                if kind == "progress":
                    done = item["done"]; total = item["total"]
                    pct = int(100 * done / max(1,total))
                    self.progress["value"] = pct
                elif kind == "log":
                    self._log(item["msg"])
                elif kind == "done":
                    if item.get("ok"):
                        messagebox.showinfo("Render complete", f"Video saved to:\\n{item['path']}")
                    else:
                        messagebox.showerror("Render failed", f"ffmpeg error:\\n\\n{item.get('err','Unknown error')}")
                    self.progress["value"] = 0
        except queue.Empty:
            pass
        if getattr(self, "_render_thread", None) and self._render_thread.is_alive():
            self.root.after(200, self._poll_progress)
        else:
            self._log("Ready.")

    def _render_worker(self, msgs, width, height, fps, assets_dir, output_path, ffmpeg_path, theme_name, title_text):
        try:
            theme = THEMES.get(theme_name, THEME_MATRIX)
            renderer = FrameRenderer(messages=msgs, width=width, height=height, fps=fps,
                                     chat_panel_ratio=CHAT_PANEL_RATIO, assets_dir=assets_dir,
                                     output_path=output_path, theme=theme, title=title_text)
        except Exception as e:
            self._progress_queue.put({"kind": "log", "msg": f"Renderer init failed: {e}"})
            self._progress_queue.put({"kind": "done", "ok": False, "err": str(e)})
            return

        self._progress_queue.put({"kind": "log", "msg": f"Total frames: {renderer.total_frames}  (duration ~{renderer.total_duration:.2f}s)"})
        tmp_dir = tempfile.mkdtemp(prefix="tta_frames_")
        try:
            def pcb(done, total):
                self._progress_queue.put({"kind": "progress", "done": done, "total": total})
            renderer.render_all_frames(tmp_dir, progress_cb=pcb)
            self._progress_queue.put({"kind": "log", "msg": "Encoding with ffmpeg…"})
            ok, log = renderer.encode_with_ffmpeg(tmp_dir, ffmpeg_path=ffmpeg_path)
            if not ok:
                self._progress_queue.put({"kind": "done", "ok": False, "err": log})
            else:
                self._progress_queue.put({"kind": "done", "ok": True, "path": output_path})
        except Exception as e:
            self._progress_queue.put({"kind": "done", "ok": False, "err": str(e)})
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# -------------------------------
# CLI entry point
# -------------------------------

def run_cli(args: List[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Tippi Tappi Animator - render faux chat + avatar video.")
    parser.add_argument("--cli", action="store_true", help="Run in command-line mode (no GUI).")
    parser.add_argument("--json", required=True, help="Path to conversation JSON.")
    parser.add_argument("--length", type=float, default=DEFAULT_LENGTH, help="Total video length in seconds.")
    parser.add_argument("--out", default=None, help="Output .mp4 path.")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Video width.")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Video height.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Frames per second.")
    parser.add_argument("--assets", default=".", help="Assets directory containing avatar/profile images.")
    parser.add_argument("--theme", choices=["matrix","dark","light"], default="matrix", help="Color theme.")
    parser.add_argument("--title", default=None, help="Optional header/title displayed at the top.")
    ns = parser.parse_args(args)

    ensure_pillow_or_exit(gui_mode=False)

    ffmpeg = which_ffmpeg()
    if not ffmpeg:
        print("Error: ffmpeg not found on PATH. Install from https://ffmpeg.org", file=sys.stderr)
        return 2

    try:
        msgs = parse_json_messages(ns.json)
    except Exception as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        return 2

    compute_timeline(msgs, ns.length, pause_between=PAUSE_BETWEEN_MSGS)

    out_path = ns.out or os.path.abspath(f"tta_render_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
    theme = THEMES.get(ns.theme, THEME_MATRIX)
    renderer = FrameRenderer(messages=msgs, width=ns.width, height=ns.height, fps=ns.fps,
                             chat_panel_ratio=CHAT_PANEL_RATIO, assets_dir=ns.assets,
                             output_path=out_path, theme=theme, title=ns.title)

    print(f"Rendering {renderer.total_frames} frames (~{renderer.total_duration:.2f}s) …")
    tmp_dir = tempfile.mkdtemp(prefix="tta_frames_")
    try:
        last_pct = -1
        def pcb(done, total):
            nonlocal last_pct
            pct = int(100 * done / max(1,total))
            if pct != last_pct:
                print(f"\\rFrames: {done}/{total}  ({pct}%)", end="")
                last_pct = pct
        renderer.render_all_frames(tmp_dir, progress_cb=pcb)
        print("\\nEncoding with ffmpeg…")
        ok, log = renderer.encode_with_ffmpeg(tmp_dir, ffmpeg_path=ffmpeg)
        if not ok:
            print("ffmpeg failed:\\n", log, file=sys.stderr)
            return 2
        print(f"Done. Saved to: {out_path}")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    if "--cli" in sys.argv:
        args = [a for a in sys.argv[1:]]
        return run_cli(args)
    else:
        if not GUI_AVAILABLE:
            print("Tkinter GUI not available in this environment. Use --cli mode.", file=sys.stderr)
            return 2
        ensure_pillow_or_exit(gui_mode=True)
        app = TippiTappiGUI()
        app.root.mainloop()
        return 0


if __name__ == "__main__":
    sys.exit(main())
