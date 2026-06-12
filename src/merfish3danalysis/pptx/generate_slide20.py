#!/usr/bin/env python3
"""Generate a single-slide PPTX for the pipeline overview (slide 20).

Usage:
    python generate_slide20.py [--output pipeline_overview.pptx]
"""

from __future__ import annotations

import argparse
import importlib.util
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

# ── Load slide_visuals from the same directory ─────────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "slide_visuals", Path(__file__).parent / "slide_visuals.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_visual_whole_pipeline = _mod.build_visual_whole_pipeline

# ── Geometry ───────────────────────────────────────────────────────────────────
SLIDE_W = 13.333
SLIDE_H = 7.5
TITLE_H = 0.8
NAVY    = RGBColor(0x1B, 0x2A, 0x4A)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
PAD     = 0.15


def _draw_title(slide, title: str, num: int = 20) -> None:
    box = slide.shapes.add_textbox(
        Inches(0), Inches(0), Inches(SLIDE_W), Inches(TITLE_H)
    )
    box.fill.solid()
    box.fill.fore_color.rgb = NAVY

    tf = box.text_frame
    tf.word_wrap = True
    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is not None:
        v = str(int(Inches(PAD)))
        bodyPr.set("lIns", v); bodyPr.set("rIns", v)
        bodyPr.set("tIns", str(int(Inches(0.15))))
        bodyPr.set("bIns", v)
        bodyPr.set("anchor", "ctr")

    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = f"{num:02d}  {title}"
    r.font.size = Pt(20)
    r.font.bold = True
    r.font.color.rgb = WHITE


def build(output: Path) -> None:
    prs = Presentation()
    prs.slide_width  = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_title(slide, "End-to-end pipeline summary")

    vis_left   = 0.0
    vis_top    = TITLE_H
    vis_width  = SLIDE_W
    vis_height = SLIDE_H - TITLE_H
    build_visual_whole_pipeline(slide, vis_left, vis_top, vis_width, vis_height)

    prs.save(output)
    print(f"Saved → {output}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="pipeline_overview.pptx",
                    help="Output PPTX path")
    args = ap.parse_args()
    build(Path(args.output))


if __name__ == "__main__":
    main()
