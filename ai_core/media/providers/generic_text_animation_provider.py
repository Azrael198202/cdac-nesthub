from __future__ import annotations

import hashlib
import math
import textwrap
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ai_core.config.paths import RUNTIME_DIR


def generate_text_animation(*, prompt: str, options: dict[str, Any] | None = None, provider: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate a local animated preview artifact from text.

    This provider is intentionally generic. It is a runtime-safe fallback for
    proving the video_generation artifact path when no dedicated video model,
    ComfyUI video workflow, or external API is configured. It does not encode
    any business/domain behavior; it converts prompt text into a simple animated
    GIF so the video route can complete with real material instead of falling
    back to chat.
    """
    options = options if isinstance(options, dict) else {}
    provider = provider if isinstance(provider, dict) else {}
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "status": "requires_input", "reason": "missing_prompt"}

    width = _int_value(options.get("width") or provider.get("width"), 768)
    height = _int_value(options.get("height") or provider.get("height"), 432)
    frames_count = max(8, min(_int_value(options.get("frames") or provider.get("frames"), 36), 120))
    duration_ms = max(40, min(_int_value(options.get("frame_duration_ms") or provider.get("frame_duration_ms"), 90), 1000))

    out_dir = RUNTIME_DIR / "generated" / "media" / "temp" / "generic_text_animation"
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{prompt}|{time.time()}".encode("utf-8")).hexdigest()[:12]
    target = out_dir / f"text_animation_{digest}.gif"

    frames = []
    font_large = _font(28)
    font_small = _font(18)
    wrapped = textwrap.wrap(prompt, width=42)[:5]
    if not wrapped:
        wrapped = [prompt[:80]]

    for index in range(frames_count):
        t = index / max(frames_count - 1, 1)
        img = Image.new("RGB", (width, height), (16, 20, 32))
        draw = ImageDraw.Draw(img)
        _draw_grid(draw, width, height, t)
        _draw_orbit_nodes(draw, width, height, t)
        _draw_center_panel(draw, width, height, t)
        y = int(height * 0.43)
        for line in wrapped:
            bbox = draw.textbbox((0, 0), line, font=font_large)
            x = (width - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), line, fill=(238, 242, 255), font=font_large)
            y += 34
        label = "video_generation preview"
        draw.text((24, height - 42), label, fill=(170, 185, 210), font=font_small)
        frames.append(img)

    frames[0].save(target, save_all=True, append_images=frames[1:], duration=duration_ms, loop=0, optimize=True)
    if not target.exists() or target.stat().st_size <= 0:
        return {"ok": False, "status": "failed", "reason": "empty_animation_output"}
    return {"ok": True, "status": "completed", "file_path": str(target)}


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_grid(draw: ImageDraw.ImageDraw, width: int, height: int, t: float) -> None:
    offset = int(t * 48) % 48
    for x in range(-48 + offset, width, 48):
        draw.line((x, 0, x, height), fill=(27, 36, 58), width=1)
    for y in range(-48 + offset, height, 48):
        draw.line((0, y, width, y), fill=(27, 36, 58), width=1)


def _draw_orbit_nodes(draw: ImageDraw.ImageDraw, width: int, height: int, t: float) -> None:
    cx, cy = width // 2, height // 2
    radius_x, radius_y = width * 0.34, height * 0.24
    points = []
    for i in range(8):
        angle = 2 * math.pi * (i / 8 + t)
        x = int(cx + math.cos(angle) * radius_x)
        y = int(cy + math.sin(angle) * radius_y)
        points.append((x, y))
    for i, (x, y) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        draw.line((x, y, x2, y2), fill=(60, 95, 145), width=2)
    for i, (x, y) in enumerate(points):
        pulse = int(4 * (1 + math.sin(2 * math.pi * (t + i / 8))))
        r = 8 + pulse
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(80, 150, 230), outline=(188, 220, 255), width=2)


def _draw_center_panel(draw: ImageDraw.ImageDraw, width: int, height: int, t: float) -> None:
    cx, cy = width // 2, height // 2
    w, h = int(width * 0.66), int(height * 0.38)
    x1, y1 = cx - w // 2, cy - h // 2
    x2, y2 = cx + w // 2, cy + h // 2
    glow = int(24 + 18 * math.sin(2 * math.pi * t))
    draw.rounded_rectangle((x1 - 8, y1 - 8, x2 + 8, y2 + 8), radius=28, fill=(20, 32 + glow // 4, 52 + glow // 3))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(30, 42, 68), outline=(100, 156, 230), width=3)
