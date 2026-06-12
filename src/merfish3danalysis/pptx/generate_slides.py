#!/usr/bin/env python3
"""Generate a PowerPoint deck from slide_brief.md.

Usage:
    python generate_slides.py [--brief slide_brief.md] [--output merfish3d_slides.pptx]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Inches, Pt
except ImportError:
    print("Install python-pptx first:  pip install python-pptx", file=sys.stderr)
    sys.exit(1)

# ── Colours ────────────────────────────────────────────────────────────────────
NAVY = RGBColor(0x1B, 0x2A, 0x4A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0x00, 0x00, 0x00)
GREEN_BG = RGBColor(0xEA, 0xF4, 0xEA)
BLUE_BG = RGBColor(0xEA, 0xF0, 0xF8)
GREEN_FG = RGBColor(0x2E, 0x7D, 0x32)
BLUE_FG = RGBColor(0x15, 0x65, 0xC0)
GRAY_FG = RGBColor(0x77, 0x77, 0x77)

# ── Geometry (inches) ─────────────────────────────────────────────────────────
SLIDE_W = 13.333
SLIDE_H = 7.5
TITLE_H = 0.8
PAD = 0.15

# "wide" layout: full-width visual + bio/eng side-by-side at bottom
WIDE_VIS_H = 4.0
WIDE_TEXT_H = SLIDE_H - TITLE_H - WIDE_VIS_H   # 2.7"
HALF_W = SLIDE_W / 2                        # 6.667"

# "split" layout: visual fills left 60%, bio/eng stacked on right 40%
SPLIT_VIS_W = SLIDE_W * 0.60    # 8.0"
SPLIT_TEXT_W = SLIDE_W - SPLIT_VIS_W  # 5.333"
SPLIT_VIS_H = SLIDE_H - TITLE_H     # 6.7"
SPLIT_HALF_H = SPLIT_VIS_H / 2       # 3.35"

# Per-slide layout assignment
SLIDE_LAYOUTS: dict[int, str] = {
    1:  "title",
    2:  "split",
    3:  "wide",
    4:  "split",
    5:  "wide",
    6:  "split",
    7:  "wide",
    8:  "wide",
    9:  "wide",
    10: "wide",
    11: "split",
    12: "wide",
    13: "split",
    14: "split",
    15: "wide",
    16: "split",
    17: "split",
    18: "split",
    19: "wide",
    20: "title",
}


# ── Parsing ────────────────────────────────────────────────────────────────────

def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


def parse_brief(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    sections = re.split(r"\n---\n", raw)

    slides = []
    for section in sections:
        m = re.search(r"^## Slide (\d+) — (.+)$", section, re.MULTILINE)
        if not m:
            continue

        slide_num = int(m.group(1))
        heading = m.group(2).strip()

        fields: dict[str, list[str]] = {}
        current_key: str | None = None
        current_parts: list[str] = []

        for line in section.splitlines():
            top = re.match(r"^- \*\*(.+?):\*\*\s*(.*)", line)
            if top:
                if current_key is not None and current_parts:
                    fields.setdefault(current_key, []).append(
                        " ".join(current_parts).strip()
                    )
                current_key = top.group(1).strip().lower()
                val = top.group(2).strip()
                current_parts = [val] if val else []
            elif current_key is not None:
                sub = re.match(r"^ {2,}- (.+)$", line)
                if sub:
                    current_parts.append(sub.group(1).strip())
                elif line.strip() and not line.startswith("#") and not line.startswith("-"):
                    current_parts.append(line.strip())

        if current_key is not None and current_parts:
            fields.setdefault(current_key, []).append(
                " ".join(current_parts).strip()
            )

        def get(target: str, exclude: str = "") -> str:
            vals = []
            for k, vs in fields.items():
                if target in k:
                    if exclude and exclude in k:
                        continue
                    vals.extend(vs)
            return _strip_md("\n".join(v for v in vals if v))

        slides.append(
            {
                "slide_num": slide_num,
                "heading":   heading,
                "title":     get("title"),
                "visual":    get("visual"),
                "biologist": get("biologist", exclude="engineer"),
                "engineer":  get("engineer"),
                "notes":     get("speaker notes"),
            }
        )

    return slides


# ── Layout helpers ─────────────────────────────────────────────────────────────

def _set_insets(tf, left: float = PAD, right: float = PAD,
                top: float = PAD, bottom: float = PAD) -> None:
    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is not None:
        bodyPr.set("lIns", str(int(Inches(left))))
        bodyPr.set("rIns", str(int(Inches(right))))
        bodyPr.set("tIns", str(int(Inches(top))))
        bodyPr.set("bIns", str(int(Inches(bottom))))


def _add_text_box(
    slide,
    left: float,
    top: float,
    width: float,
    height: float,
    label: str,
    body: str,
    bg: RGBColor,
    label_color: RGBColor,
    body_pt: int = 11,
    body_color: RGBColor = BLACK,
    italic: bool = False,
) -> None:
    box = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    box.fill.solid()
    box.fill.fore_color.rgb = bg

    tf = box.text_frame
    tf.word_wrap = True
    _set_insets(tf)

    p_lbl = tf.paragraphs[0]
    p_lbl.alignment = PP_ALIGN.LEFT
    r_lbl = p_lbl.add_run()
    r_lbl.text = label
    r_lbl.font.size = Pt(7)
    r_lbl.font.bold = True
    r_lbl.font.color.rgb = label_color

    p_body = tf.add_paragraph()
    p_body.alignment = PP_ALIGN.LEFT
    r_body = p_body.add_run()
    r_body.text = body or "(none)"
    r_body.font.size = Pt(body_pt)
    r_body.font.italic = italic
    r_body.font.color.rgb = body_color


# ── Title strip ────────────────────────────────────────────────────────────────

def _draw_title(slide, data: dict) -> None:
    box = slide.shapes.add_textbox(
        Inches(0), Inches(0), Inches(SLIDE_W), Inches(TITLE_H)
    )
    box.fill.solid()
    box.fill.fore_color.rgb = NAVY

    tf = box.text_frame
    tf.word_wrap = True
    _set_insets(tf, top=0.15)

    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is not None:
        bodyPr.set("anchor", "ctr")

    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = f"{data['slide_num']:02d}  {data['title']}"
    r.font.size = Pt(20)
    r.font.bold = True
    r.font.color.rgb = WHITE


# ── Layout renderers — return (left, top, width, height) of visual zone ────────

def _draw_layout_wide(slide, data: dict) -> tuple[float, float, float, float]:
    text_top = TITLE_H + WIDE_VIS_H
    _add_text_box(
        slide,
        left=0, top=text_top, width=HALF_W, height=WIDE_TEXT_H,
        label="BIOLOGIST",
        body=data["biologist"],
        bg=GREEN_BG, label_color=GREEN_FG,
        body_pt=11,
    )
    _add_text_box(
        slide,
        left=HALF_W, top=text_top, width=HALF_W, height=WIDE_TEXT_H,
        label="ENGINEER",
        body=data["engineer"],
        bg=BLUE_BG, label_color=BLUE_FG,
        body_pt=10,
    )
    return (0.0, TITLE_H, SLIDE_W, WIDE_VIS_H)


def _draw_layout_split(slide, data: dict) -> tuple[float, float, float, float]:
    bio_top = TITLE_H
    eng_top = TITLE_H + SPLIT_HALF_H
    _add_text_box(
        slide,
        left=SPLIT_VIS_W, top=bio_top, width=SPLIT_TEXT_W, height=SPLIT_HALF_H,
        label="BIOLOGIST",
        body=data["biologist"],
        bg=GREEN_BG, label_color=GREEN_FG,
        body_pt=10,
    )
    _add_text_box(
        slide,
        left=SPLIT_VIS_W, top=eng_top, width=SPLIT_TEXT_W, height=SPLIT_HALF_H,
        label="ENGINEER",
        body=data["engineer"],
        bg=BLUE_BG, label_color=BLUE_FG,
        body_pt=9,
    )
    return (0.0, TITLE_H, SPLIT_VIS_W, SPLIT_VIS_H)


def _draw_layout_title(slide, data: dict) -> tuple[float, float, float, float]:
    # No bio/eng blocks — visual fills the entire area below the title
    return (0.0, TITLE_H, SLIDE_W, SLIDE_H - TITLE_H)


def _draw_layout(slide, data: dict, layout: str) -> tuple[float, float, float, float]:
    if layout == "split":
        return _draw_layout_split(slide, data)
    if layout == "title":
        return _draw_layout_title(slide, data)
    return _draw_layout_wide(slide, data)


# ── Visual dispatch ────────────────────────────────────────────────────────────

def _draw_visual(slide, data: dict, rect: tuple[float, float, float, float]) -> None:
    try:
        import importlib.util as _ilu
        import pathlib as _pl
        _spec = _ilu.spec_from_file_location(
            "slide_visuals",
            _pl.Path(__file__).parent / "slide_visuals.py",
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        VISUAL_BUILDERS = _mod.VISUAL_BUILDERS
    except Exception:
        VISUAL_BUILDERS = {}

    left, top, width, height = rect
    builder = VISUAL_BUILDERS.get(data["slide_num"])
    if builder is not None:
        builder(slide, left, top, width, height)
    else:
        _image_placeholder(slide, left, top, width, height)


def _image_placeholder(
    slide, left: float, top: float, width: float, height: float
) -> None:
    from pptx.util import Pt
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn
    from lxml import etree

    box = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # thin gray border
    ln = box._element.spPr.find(qn("a:ln"))
    if ln is None:
        ln = etree.SubElement(box._element.spPr, qn("a:ln"))
    ln.set("w", "9525")  # 0.75 pt
    solidFill = etree.SubElement(ln, qn("a:solidFill"))
    srgb = etree.SubElement(solidFill, qn("a:srgbClr"))
    srgb.set("val", "CCCCCC")

    tf = box.text_frame
    _set_insets(tf)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER

    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is not None:
        bodyPr.set("anchor", "ctr")

    r = p.add_run()
    r.text = "[ image ]"
    r.font.size = Pt(14)
    r.font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)


# ── Slide builder ──────────────────────────────────────────────────────────────

def build_slide(prs: Presentation, data: dict) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    layout = SLIDE_LAYOUTS.get(data["slide_num"], "wide")

    _draw_title(slide, data)
    vis_rect = _draw_layout(slide, data, layout)
    _draw_visual(slide, data, vis_rect)

    if data["notes"]:
        slide.notes_slide.notes_text_frame.text = data["notes"]


def build_presentation(slides: list[dict]) -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    for data in slides:
        build_slide(prs, data)
    return prs


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--brief",  default="slide_brief.md",
                    help="Path to brief markdown")
    ap.add_argument("--output", default="merfish3d_slides.pptx",
                    help="Output PPTX path")
    args = ap.parse_args()

    brief = Path(args.brief)
    if not brief.exists():
        print(f"Error: {brief} not found", file=sys.stderr)
        sys.exit(1)

    slides = parse_brief(brief)
    if not slides:
        print("No slides found — check that the brief has '## Slide N —' headings.", file=sys.stderr)
        sys.exit(1)

    prs = build_presentation(slides)
    out = Path(args.output)
    prs.save(out)
    print(f"Saved {len(slides)} slides → {out}")


if __name__ == "__main__":
    main()
