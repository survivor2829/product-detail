"""产品主色提取 + 色卡渲染 (v3.2.2 颜色保真双图锚定).

设计文档: docs/superpowers/specs/2026-04-29-color-anchor-hex-design.md

核心理念: PIL 像素级测量主色 → hex 数值锚 + 程序生成色卡, 对任意产品对称.
依赖: 仅 Pillow (已在 deps), 不引 numpy / scikit-learn.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError


@dataclass(frozen=True)
class ColorAnchor:
    """产品主色锚点 (一次提取, 12 屏共享).

    成员:
        primary_hex: '#RRGGBB' 大写, 主簇 centroid hex
        palette_hex: top-3 簇 hex (含 primary_hex 在 [0])
        confidence: 主簇像素 / 非背景像素总数, 范围 [0.0, 1.0]
        swatch_png_bytes: 512x512 纯色 PNG bytes (primary_hex 作色), 用作 image_urls[1]
    """
    primary_hex: str
    palette_hex: list[str]
    confidence: float
    swatch_png_bytes: bytes


def _filter_background_pixels(img: Image.Image) -> list[tuple[int, int, int]]:
    """返回非背景像素的 RGB 列表.

    PNG with alpha: alpha < 128 排除, 同时过滤白底 (V > 240/255 且 S < 0.05)
    其他模式 (JPG): 转 HSV, V > 240/255 且 S < 0.05 视为白背景排除
    """
    if img.mode == "RGBA":
        # RGBA 路径: 先过滤 alpha, 再过滤白底
        rgba_pixels = list(img.getdata())
        rgb_with_alpha = [(r, g, b) for r, g, b, a in rgba_pixels if a >= 128]

        # 对保留的 RGB 像素再做白底过滤 (转 HSV)
        if not rgb_with_alpha:
            return []
        temp_img = Image.new("RGB", (len(rgb_with_alpha), 1))
        temp_img.putdata(rgb_with_alpha)
        hsv_img = temp_img.convert("HSV")
        hsv_pixels = list(hsv_img.getdata())

        out = []
        for (r, g, b), (h, s, v) in zip(rgb_with_alpha, hsv_pixels):
            # V > 240/255 且 S < 0.05 视为白背景 (S 范围 0-255, 0.05 * 255 ≈ 13)
            if v > 240 and s < 13:
                continue
            out.append((r, g, b))
        return out

    # JPG / RGB 路径: 用 HSV 滤白背景
    rgb_img = img.convert("RGB") if img.mode != "RGB" else img
    hsv_img = rgb_img.convert("HSV")
    rgb_pixels = list(rgb_img.getdata())
    hsv_pixels = list(hsv_img.getdata())
    out = []
    for (r, g, b), (h, s, v) in zip(rgb_pixels, hsv_pixels):
        # V > 240/255 且 S < 0.05 视为白背景 (S 范围 0-255, 0.05 * 255 ≈ 13)
        if v > 240 and s < 13:
            continue
        out.append((r, g, b))
    return out


def _kmeans_via_quantize(
    pixels: list[tuple[int, int, int]],
    k: int = 5,
) -> list[tuple[tuple[int, int, int], int]]:
    """用 Pillow Image.quantize MEDIANCUT 做 k-means 替代品.

    返回 [(centroid_rgb, pixel_count), ...] 按 pixel_count 降序.
    """
    if not pixels:
        return []
    n = len(pixels)
    img = Image.new("RGB", (n, 1))
    img.putdata(pixels)
    quantized = img.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    palette_flat = quantized.getpalette() or []
    indices = list(quantized.getdata())
    from collections import Counter
    counts = Counter(indices)
    out: list[tuple[tuple[int, int, int], int]] = []
    for idx, cnt in counts.most_common():
        if idx * 3 + 2 >= len(palette_flat):
            continue
        rgb = (palette_flat[idx * 3], palette_flat[idx * 3 + 1], palette_flat[idx * 3 + 2])
        out.append((rgb, cnt))
    return out


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def extract_color_anchor(
    cutout_path: str | Path,
    *,
    downsample_to: int = 200,
    min_non_bg_pixels: int = 100,
    min_confidence: float = 0.30,
    swatch_size: int = 512,
) -> Optional[ColorAnchor]:
    """从 cutout 算主色 hex 锚, 失败返 None (调用方走 fallback).

    失败条件:
      - 文件不存在 / 读图失败 / 损坏
      - 非背景像素 < min_non_bg_pixels (整图基本是白底)
      - 主簇 confidence < min_confidence (产品多色无主导)
      - quantize 内部异常
    """
    p = Path(cutout_path)
    if not p.is_file():
        return None
    try:
        img = Image.open(p)
        # 下采样加速 quantize
        if max(img.size) > downsample_to:
            ratio = downsample_to / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        non_bg = _filter_background_pixels(img)
        if len(non_bg) < min_non_bg_pixels:
            return None

        clusters = _kmeans_via_quantize(non_bg, k=5)
        if not clusters:
            return None

        primary_rgb, primary_count = clusters[0]
        confidence = primary_count / len(non_bg)
        if confidence < min_confidence:
            return None

        primary_hex = _rgb_to_hex(primary_rgb)
        palette_hex = [_rgb_to_hex(rgb) for rgb, _ in clusters[:3]]
        # 不足 3 簇时填充
        while len(palette_hex) < 3:
            palette_hex.append(primary_hex)

        # swatch 在 Task 7 实现, 暂用占位
        swatch_bytes = b""

        return ColorAnchor(
            primary_hex=primary_hex,
            palette_hex=palette_hex,
            confidence=confidence,
            swatch_png_bytes=swatch_bytes,
        )
    except Exception:  # 按 spec §5.1: 任何异常 → 返 None, 不外抛
        return None
