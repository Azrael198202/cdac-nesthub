from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import textwrap
import time
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR

# A tiny valid GIF used only when Pillow is not available and dependency
# installation is disabled or failed. Keeping this as data avoids shelling out
# or hardcoding any business/domain behavior in ai_core.
_MINIMAL_GIF_BASE64 = "R0lGODlhAQABAPAAAP///wAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=="

_DEFAULT_FRAMES = 8
_MIN_FRAMES = 8
_ABSOLUTE_MAX_FRAMES = 120


def generate_text_animation(*, prompt: str, options: dict[str, Any] | None = None, provider: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate a local animated preview artifact from text.

    This provider is intentionally generic. It proves the video_generation
    artifact path when no dedicated video model, ComfyUI video workflow, or
    external API is configured. Pillow is used when available; otherwise the
    provider still returns a valid GIF placeholder instead of breaking the
    runtime route.
    """
    options = options if isinstance(options, dict) else {}
    provider = provider if isinstance(provider, dict) else {}
    prompt = str(prompt or "").strip()
    if not prompt:
        return {"ok": False, "status": "requires_input", "reason": "missing_prompt"}

    out_dir = RUNTIME_DIR / "generated" / "media" / "temp" / "generic_text_animation"
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f"{prompt}|{time.time()}".encode("utf-8")).hexdigest()[:12]
    target = out_dir / f"text_animation_{digest}.gif"

    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
        _generate_with_pillow(
            target=target,
            prompt=prompt,
            options=options,
            provider=provider,
            Image=Image,
            ImageDraw=ImageDraw,
            ImageFont=ImageFont,
        )
    except Exception as exc:
        # Do not return a single-frame placeholder as a successful video. The
        # runtime dependency recovery layer should install declared dependencies
        # such as Pillow. If rendering still fails, surface a diagnostic so the
        # next provider or setup flow can handle it.
        try:
            target.write_bytes(base64.b64decode(_MINIMAL_GIF_BASE64))
        except Exception:
            pass
        return {
            "ok": False,
            "status": "failed",
            "reason": "generic_text_animation_render_failed",
            "minimum_required_frames": _MIN_FRAMES,
            "error_type": exc.__class__.__name__,
            "error": str(exc)[-1000:],
        }

    if not target.exists() or target.stat().st_size <= 0:
        return {"ok": False, "status": "failed", "reason": "empty_animation_output"}
    frame_count = _inspect_gif_frame_count(target)
    if frame_count < _MIN_FRAMES:
        return {
            "ok": False,
            "status": "failed",
            "reason": "animation_frame_count_too_low",
            "frame_count": frame_count,
            "minimum_required_frames": _MIN_FRAMES,
            "file_path": str(target),
        }
    return {
        "ok": True,
        "status": "completed",
        "file_path": str(target),
        "artifact_metadata": {
            "frame_count": frame_count,
            "minimum_required_frames": _MIN_FRAMES,
            "duration_ms": frame_count * _int_value(options.get("frame_duration_ms") or provider.get("frame_duration_ms"), 120),
        },
    }


def _generate_with_pillow(*, target: Path, prompt: str, options: dict[str, Any], provider: dict[str, Any], Image: Any, ImageDraw: Any, ImageFont: Any) -> None:
    width = _int_value(options.get("width") or provider.get("width"), 768)
    height = _int_value(options.get("height") or provider.get("height"), 432)
    max_frames = _effective_max_frames(options=options, provider=provider)
    requested_frames = _requested_frame_count(prompt=prompt, options=options, provider=provider)
    frames_count = max(_MIN_FRAMES, min(requested_frames, max_frames))
    duration_ms = max(40, min(_int_value(options.get("frame_duration_ms") or provider.get("frame_duration_ms"), 120), 1000))

    frames = []
    font_large = _font(ImageFont, 28)
    font_small = _font(ImageFont, 18)
    wrapped = textwrap.wrap(prompt, width=42)[:5] or [prompt[:80]]

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
        draw.text((24, height - 42), "video_generation preview", fill=(170, 185, 210), font=font_small)
        frames.append(img)

    frames[0].save(target, save_all=True, append_images=frames[1:], duration=duration_ms, loop=0, optimize=True)


def _requested_frame_count(*, prompt: str, options: dict[str, Any], provider: dict[str, Any]) -> int:
    explicit = options.get("frames") or options.get("frame_count")
    if explicit is not None:
        return _int_value(explicit, _DEFAULT_FRAMES)
    text = str(prompt or "")
    patterns = [
        r"(?<!\d)(\d{1,3})\s*(?:frames?|frame\s*count)",
        r"(?<!\d)(\d{1,3})\s*(?:帧|フレーム|コマ)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _int_value(match.group(1), _DEFAULT_FRAMES)
    return _int_value(provider.get("frames"), _DEFAULT_FRAMES)


def _effective_max_frames(*, options: dict[str, Any], provider: dict[str, Any]) -> int:
    configured = _int_value(options.get("max_frames") or provider.get("max_frames"), 0)
    if configured > 0:
        return max(_MIN_FRAMES, min(configured, _ABSOLUTE_MAX_FRAMES))
    cpu_count = os.cpu_count() or 2
    memory_gb = _available_memory_gb()
    if cpu_count >= 16 and memory_gb >= 24:
        return 96
    if cpu_count >= 8 and memory_gb >= 12:
        return 64
    if cpu_count >= 4 and memory_gb >= 6:
        return 36
    return 24


def _available_memory_gb() -> float:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    kb = float(line.split()[1])
                    return kb / 1024 / 1024
    except Exception:
        return 0.0
    return 0.0


def _inspect_gif_frame_count(path: Path) -> int:
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as img:
            return int(getattr(img, "n_frames", 1) or 1)
    except Exception:
        return 1


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _font(ImageFont: Any, size: int):
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


def _draw_grid(draw: Any, width: int, height: int, t: float) -> None:
    offset = int(t * 48) % 48
    for x in range(-48 + offset, width, 48):
        draw.line((x, 0, x, height), fill=(27, 36, 58), width=1)
    for y in range(-48 + offset, height, 48):
        draw.line((0, y, width, y), fill=(27, 36, 58), width=1)


def _draw_orbit_nodes(draw: Any, width: int, height: int, t: float) -> None:
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


def _draw_center_panel(draw: Any, width: int, height: int, t: float) -> None:
    cx, cy = width // 2, height // 2
    w, h = int(width * 0.66), int(height * 0.38)
    x1, y1 = cx - w // 2, cy - h // 2
    x2, y2 = cx + w // 2, cy + h // 2
    glow = int(24 + 18 * math.sin(2 * math.pi * t))
    draw.rounded_rectangle((x1 - 8, y1 - 8, x2 + 8, y2 + 8), radius=28, fill=(20, 32 + glow // 4, 52 + glow // 3))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(30, 42, 68), outline=(100, 156, 230), width=3)
