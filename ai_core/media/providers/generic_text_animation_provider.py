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
        visual_plan = _analyze_prompt_visual_intent(prompt)
        _generate_with_pillow(
            target=target,
            prompt=prompt,
            options=options,
            provider=provider,
            Image=Image,
            ImageDraw=ImageDraw,
            ImageFont=ImageFont,
            visual_plan=visual_plan,
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
            "render_mode": "semantic_procedural_preview",
        },
    }


def _generate_with_pillow(*, target: Path, prompt: str, options: dict[str, Any], provider: dict[str, Any], Image: Any, ImageDraw: Any, ImageFont: Any, visual_plan: dict[str, Any] | None = None) -> None:
    width = _int_value(options.get("width") or provider.get("width"), 768)
    height = _int_value(options.get("height") or provider.get("height"), 432)
    max_frames = _effective_max_frames(options=options, provider=provider)
    requested_frames = _requested_frame_count(prompt=prompt, options=options, provider=provider)
    frames_count = max(_MIN_FRAMES, min(requested_frames, max_frames))
    duration_ms = max(40, min(_int_value(options.get("frame_duration_ms") or provider.get("frame_duration_ms"), 120), 1000))

    frames = []
    font_large = _font(ImageFont, 28)
    font_small = _font(ImageFont, 18)
    visual_plan = visual_plan if isinstance(visual_plan, dict) else _analyze_prompt_visual_intent(prompt)
    title = _prompt_title(prompt)

    for index in range(frames_count):
        t = index / max(frames_count - 1, 1)
        camera = _camera_offset(t, width, height, visual_plan)
        bg = (8, 12, 24) if visual_plan.get("dark") else (16, 20, 32)
        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)
        _draw_grid(draw, width, height, t, visual_plan, camera)
        if visual_plan.get("task_graph"):
            _draw_task_graph_scene(draw, width, height, t, visual_plan, camera, font_small)
        else:
            _draw_orbit_nodes(draw, width, height, t, camera)
        if visual_plan.get("agents"):
            _draw_agent_characters(draw, width, height, t, visual_plan, camera)
        if visual_plan.get("routing"):
            _draw_routing_pulses(draw, width, height, t, visual_plan, camera)
        _draw_prompt_badge(draw, width, height, title, font_large, font_small, visual_plan)
        draw.text((24, height - 42), "semantic procedural animation preview", fill=(170, 185, 210), font=font_small)
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


def _draw_grid(draw: Any, width: int, height: int, t: float, visual_plan: dict[str, Any] | None = None, camera: tuple[int, int] = (0, 0)) -> None:
    visual_plan = visual_plan if isinstance(visual_plan, dict) else {}
    ox, oy = camera
    spacing = 40 if visual_plan.get("cinematic") else 48
    offset = int(t * spacing) % spacing
    line = (22, 34, 58) if visual_plan.get("dark") else (27, 36, 58)
    for x in range(-spacing + offset + ox % spacing, width, spacing):
        draw.line((x, 0, x, height), fill=line, width=1)
    for y in range(-spacing + offset + oy % spacing, height, spacing):
        draw.line((0, y, width, y), fill=line, width=1)


def _draw_orbit_nodes(draw: Any, width: int, height: int, t: float, camera: tuple[int, int] = (0, 0)) -> None:
    ox, oy = camera
    cx, cy = width // 2 + ox, height // 2 + oy
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


def _analyze_prompt_visual_intent(prompt: str) -> dict[str, Any]:
    """Convert text into generic visual instructions for the zero-config preview.

    This is not a domain workflow. It is a lightweight procedural renderer plan
    for artifact preview only. Real semantic video generation should be handled
    by a configured video model/provider.
    """
    text = str(prompt or "").lower()
    agent_count = 0
    if re.search(r"\b(three|3)\b|三|３", text):
        agent_count = 3
    elif re.search(r"\b(two|2)\b|二|２", text):
        agent_count = 2
    elif re.search(r"agent|character|cartoon|person|people|キャラクター|エージェント|人物|角色", text):
        agent_count = 1
    return {
        "agents": agent_count > 0,
        "agent_count": agent_count or 0,
        "task_graph": bool(re.search(r"graph|workflow|task|node|runtime|flow|pipeline|グラフ|ワークフロー|节点|節点|任务|流程", text)),
        "routing": bool(re.search(r"routing|route|dynamic|execution|manage|collaborat|control|dispatch|ルーティング|経路|実行|管理|动态|路由|执行", text)),
        "cinematic": bool(re.search(r"cinematic|camera|smooth|high-end|sci-fi|movie|3d|３d|カメラ|映画|镜头|电影|高级", text)),
        "dark": bool(re.search(r"dark|night|futuristic|sci-fi|cyber|glow|glowing|未来|暗|发光|光る", text)),
        "floating": bool(re.search(r"floating|float|空中|浮遊|悬浮|浮か", text)),
        "glow": bool(re.search(r"glow|glowing|neon|light|sci-fi|cyber|発光|光|霓虹", text)),
    }


def _prompt_title(prompt: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(prompt or "")).strip()
    if len(cleaned) <= 72:
        return cleaned
    return cleaned[:69].rstrip() + "..."


def _camera_offset(t: float, width: int, height: int, visual_plan: dict[str, Any]) -> tuple[int, int]:
    if not visual_plan.get("cinematic"):
        return (0, 0)
    return (int(math.sin(t * math.pi * 2) * width * 0.025), int(math.cos(t * math.pi * 2) * height * 0.018))


def _draw_task_graph_scene(draw: Any, width: int, height: int, t: float, visual_plan: dict[str, Any], camera: tuple[int, int], font_small: Any) -> None:
    ox, oy = camera
    center_y = int(height * (0.52 if visual_plan.get("floating") else 0.50)) + oy
    xs = [int(width * p) + ox for p in (0.18, 0.38, 0.58, 0.78)]
    ys = [center_y + int(math.sin((t + i * 0.18) * math.pi * 2) * 24) for i in range(len(xs))]
    labels = ["input", "plan", "execute", "result"]
    for i in range(len(xs) - 1):
        draw.line((xs[i] + 70, ys[i], xs[i + 1] - 70, ys[i + 1]), fill=(78, 125, 190), width=3)
        pulse_x = int(xs[i] + (xs[i + 1] - xs[i]) * ((t * 1.8 + i * 0.18) % 1.0))
        pulse_y = int(ys[i] + (ys[i + 1] - ys[i]) * ((t * 1.8 + i * 0.18) % 1.0))
        draw.ellipse((pulse_x - 6, pulse_y - 6, pulse_x + 6, pulse_y + 6), fill=(130, 210, 255))
    for i, (x, y) in enumerate(zip(xs, ys)):
        fill = (26, 40, 70)
        outline = (112, 174, 250) if i == int(t * len(xs)) % len(xs) else (70, 112, 180)
        if visual_plan.get("glow"):
            draw.rounded_rectangle((x - 82, y - 38, x + 82, y + 38), radius=20, fill=(18, 30, 58))
        draw.rounded_rectangle((x - 72, y - 28, x + 72, y + 28), radius=16, fill=fill, outline=outline, width=3)
        bbox = draw.textbbox((0, 0), labels[i], font=font_small)
        draw.text((x - (bbox[2]-bbox[0]) // 2, y - 9), labels[i], fill=(230, 238, 255), font=font_small)


def _draw_agent_characters(draw: Any, width: int, height: int, t: float, visual_plan: dict[str, Any], camera: tuple[int, int]) -> None:
    ox, oy = camera
    count = max(1, min(int(visual_plan.get("agent_count") or 1), 5))
    base_y = int(height * 0.72) + oy
    if count == 1:
        positions = [(width // 2 + ox, base_y)]
    else:
        span = min(width * 0.54, 360)
        positions = [(int(width / 2 - span / 2 + span * i / max(count - 1, 1)) + ox, base_y + int(math.sin(t * math.pi * 2 + i) * 10)) for i in range(count)]
    for i, (x, y) in enumerate(positions):
        bob = int(math.sin(t * math.pi * 2 + i * 0.9) * 8)
        y += bob
        # shadow
        draw.ellipse((x - 34, y + 38, x + 34, y + 50), fill=(5, 8, 16))
        # body
        draw.rounded_rectangle((x - 28, y - 10, x + 28, y + 44), radius=18, fill=(55, 90, 150), outline=(145, 205, 255), width=2)
        # head
        draw.ellipse((x - 30, y - 58, x + 30, y + 2), fill=(82, 132, 210), outline=(188, 225, 255), width=3)
        # ears/antenna
        draw.line((x, y - 58, x + int(math.sin(t * math.pi * 2 + i) * 10), y - 76), fill=(160, 215, 255), width=3)
        draw.ellipse((x - 4 + int(math.sin(t * math.pi * 2 + i) * 10), y - 82, x + 4 + int(math.sin(t * math.pi * 2 + i) * 10), y - 74), fill=(130, 220, 255))
        # face
        eye_dx = int(math.sin(t * math.pi * 2) * 2)
        draw.ellipse((x - 15 + eye_dx, y - 34, x - 7 + eye_dx, y - 26), fill=(235, 250, 255))
        draw.ellipse((x + 7 + eye_dx, y - 34, x + 15 + eye_dx, y - 26), fill=(235, 250, 255))
        draw.arc((x - 14, y - 28, x + 14, y - 10), 20, 160, fill=(235, 250, 255), width=2)
        # arms
        arm = int(math.sin(t * math.pi * 2 + i) * 16)
        draw.line((x - 28, y + 8, x - 50, y + 10 + arm), fill=(130, 190, 245), width=4)
        draw.line((x + 28, y + 8, x + 50, y + 10 - arm), fill=(130, 190, 245), width=4)


def _draw_routing_pulses(draw: Any, width: int, height: int, t: float, visual_plan: dict[str, Any], camera: tuple[int, int]) -> None:
    ox, oy = camera
    cx, cy = width // 2 + ox, int(height * 0.48) + oy
    for i in range(10):
        angle = 2 * math.pi * ((i / 10) + t * 0.7)
        r = width * (0.18 + 0.16 * ((i % 3) / 3))
        x = int(cx + math.cos(angle) * r)
        y = int(cy + math.sin(angle) * r * 0.48)
        size = 3 + (i % 3)
        draw.ellipse((x - size, y - size, x + size, y + size), fill=(120, 230, 255))


def _draw_prompt_badge(draw: Any, width: int, height: int, title: str, font_large: Any, font_small: Any, visual_plan: dict[str, Any]) -> None:
    badge_w = int(width * 0.74)
    x1 = (width - badge_w) // 2
    y1 = 24
    x2 = x1 + badge_w
    y2 = 98
    draw.rounded_rectangle((x1, y1, x2, y2), radius=20, fill=(19, 29, 52), outline=(92, 150, 225), width=2)
    label = "Semantic text-to-animation preview" if visual_plan.get("task_graph") else "Text-to-animation preview"
    draw.text((x1 + 22, y1 + 12), label, fill=(160, 205, 255), font=font_small)
    shown = title if len(title) <= 58 else title[:55] + "..."
    bbox = draw.textbbox((0, 0), shown, font=font_large)
    draw.text((x1 + 22, y1 + 38), shown, fill=(238, 244, 255), font=font_large)


def _draw_center_panel(draw: Any, width: int, height: int, t: float) -> None:
    cx, cy = width // 2, height // 2
    w, h = int(width * 0.66), int(height * 0.38)
    x1, y1 = cx - w // 2, cy - h // 2
    x2, y2 = cx + w // 2, cy + h // 2
    glow = int(24 + 18 * math.sin(2 * math.pi * t))
    draw.rounded_rectangle((x1 - 8, y1 - 8, x2 + 8, y2 + 8), radius=28, fill=(20, 32 + glow // 4, 52 + glow // 3))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(30, 42, 68), outline=(100, 156, 230), width=3)
