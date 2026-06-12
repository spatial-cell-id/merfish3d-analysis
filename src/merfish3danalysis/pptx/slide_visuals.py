"""Visual builder functions for generate_slides.py.

Each builder receives (slide, left, top, width, height) in inches and draws
into that zone. Builders for slides the user handles image assets for are
not registered here — generate_slides.py falls back to a white placeholder.
"""

from __future__ import annotations

import io
from typing import Callable

from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
from lxml import etree

# ── Colour palette (shared with generate_slides) ──────────────────────────────
NAVY     = RGBColor(0x1B, 0x2A, 0x4A)
WHITE    = RGBColor(0xFF, 0xFF, 0xFF)
BLACK    = RGBColor(0x00, 0x00, 0x00)
GRAY_BG  = RGBColor(0xF0, 0xF0, 0xF0)
GRAY_FG  = RGBColor(0x77, 0x77, 0x77)
GREEN_BG = RGBColor(0xEA, 0xF4, 0xEA)
GREEN_FG = RGBColor(0x2E, 0x7D, 0x32)
BLUE_BG  = RGBColor(0xEA, 0xF0, 0xF8)
BLUE_FG  = RGBColor(0x15, 0x65, 0xC0)
ORANGE   = RGBColor(0xFF, 0x8F, 0x00)
PURPLE   = RGBColor(0x6A, 0x1B, 0x9A)
TEAL     = RGBColor(0x00, 0x69, 0x6D)
AMBER_BG = RGBColor(0xFF, 0xF8, 0xE1)
AMBER_FG = RGBColor(0xF5, 0x7F, 0x17)


# ── Low-level helpers ──────────────────────────────────────────────────────────

def _box(slide, left, top, w, h, fill: RGBColor | None = None,
         border_color: RGBColor | None = None, border_pt: float = 0.75,
         radius: bool = False):
    """Add a rectangle (or rounded rect) shape, return the shape."""
    from pptx.util import Emu
    from pptx.enum.shapes import MSO_SHAPE_TYPE  # noqa: F401

    if radius:
        from pptx.util import Emu as _E
        shape = slide.shapes.add_shape(
            # MSO_SHAPE.ROUNDED_RECTANGLE = 5
            5,
            Inches(left), Inches(top), Inches(w), Inches(h),
        )
    else:
        shape = slide.shapes.add_shape(
            1,  # MSO_SHAPE.RECTANGLE
            Inches(left), Inches(top), Inches(w), Inches(h),
        )

    if fill is not None:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    else:
        shape.fill.background()

    ln = shape.line
    if border_color is not None:
        ln.color.rgb = border_color
        ln.width = Pt(border_pt)
    else:
        ln.fill.background()

    return shape


def _oval(slide, left, top, w, h, fill: RGBColor, border_color: RGBColor | None = None):
    shape = slide.shapes.add_shape(
        9,  # MSO_SHAPE.OVAL
        Inches(left), Inches(top), Inches(w), Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if border_color:
        shape.line.color.rgb = border_color
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    return shape


def _label(slide, left, top, w, h, text: str, font_pt: int = 11,
           color: RGBColor = BLACK, bold: bool = False,
           align: PP_ALIGN = PP_ALIGN.CENTER, italic: bool = False,
           fill: RGBColor | None = None):
    """Add a text-only box (no background by default)."""
    box = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(w), Inches(h)
    )
    if fill is not None:
        box.fill.solid()
        box.fill.fore_color.rgb = fill
    else:
        box.fill.background()
    box.line.fill.background()

    tf = box.text_frame
    tf.word_wrap = True
    _set_ins(tf)

    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is not None:
        bodyPr.set("anchor", "ctr")

    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.size = Pt(font_pt)
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = color


def _set_ins(tf, pad: float = 0.05):
    bodyPr = tf._txBody.find(qn("a:bodyPr"))
    if bodyPr is not None:
        v = str(int(Inches(pad)))
        bodyPr.set("lIns", v)
        bodyPr.set("rIns", v)
        bodyPr.set("tIns", v)
        bodyPr.set("bIns", v)


def _arrow_right(slide, x1, y, x2, color: RGBColor = GRAY_FG, pt: float = 1.5):
    """Draw a horizontal right-pointing arrow connector."""
    from pptx.util import Emu
    cxn = slide.shapes.add_connector(
        1,  # MSO_CONNECTOR.STRAIGHT
        Inches(x1), Inches(y), Inches(x2), Inches(y),
    )
    cxn.line.color.rgb = color
    cxn.line.width = Pt(pt)
    # arrowhead via XML
    ln_el = cxn._element.spPr.find(qn("a:ln"))
    if ln_el is None:
        ln_el = etree.SubElement(cxn._element.spPr, qn("a:ln"))
    tailEnd = ln_el.find(qn("a:tailEnd"))
    if tailEnd is None:
        tailEnd = etree.SubElement(ln_el, qn("a:tailEnd"))
    tailEnd.set("type", "none")
    headEnd = ln_el.find(qn("a:headEnd"))
    if headEnd is None:
        headEnd = etree.SubElement(ln_el, qn("a:headEnd"))
    headEnd.set("type", "arrow")


def _arrow_down(slide, x, y1, y2, color: RGBColor = GRAY_FG, pt: float = 1.5):
    cxn = slide.shapes.add_connector(
        1,
        Inches(x), Inches(y1), Inches(x), Inches(y2),
    )
    cxn.line.color.rgb = color
    cxn.line.width = Pt(pt)
    ln_el = cxn._element.spPr.find(qn("a:ln"))
    if ln_el is None:
        ln_el = etree.SubElement(cxn._element.spPr, qn("a:ln"))
    headEnd = ln_el.find(qn("a:headEnd"))
    if headEnd is None:
        headEnd = etree.SubElement(ln_el, qn("a:headEnd"))
    headEnd.set("type", "arrow")


def _mpl_to_buf(fig) -> io.BytesIO:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150,
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf


def _insert_mpl(slide, fig, left, top, width, height):
    buf = _mpl_to_buf(fig)
    slide.shapes.add_picture(buf, Inches(left), Inches(top),
                             Inches(width), Inches(height))


# ── Slide 2 — Funnel diagram ───────────────────────────────────────────────────

def build_visual_02(slide, left, top, width, height):
    cx = left + width / 2
    pad = 0.25

    # Three trapezoid-like sections drawn as stacked rectangles that narrow
    levels = [
        ("Raw data: 6 dimensions\nrounds × tiles × channels × z × y × x",
         BLUE_BG, BLUE_FG, 0.85),
        ("processing", GRAY_BG, GRAY_FG, 0.55),
        ("decoded transcripts + cell outlines", GREEN_BG, GREEN_FG, 0.35),
    ]

    box_h = (height - 2 * pad) / 3 - 0.15
    y = top + pad

    widths = [width * f for _, _, _, f in levels]
    for i, (text, bg, fg, frac) in enumerate(levels):
        bw = width * frac
        bx = cx - bw / 2
        shape = _box(slide, bx, y, bw, box_h, fill=bg,
                     border_color=fg, border_pt=1.0, radius=True)
        _label(slide, bx, y, bw, box_h, text,
               font_pt=10, color=fg, bold=(i != 1))
        if i < 2:
            _arrow_down(slide, cx, y + box_h, y + box_h + 0.15,
                        color=GRAY_FG, pt=1.5)
        y += box_h + 0.15

    # annotation
    _label(slide, left + width * 0.72, top + pad + 0.1, width * 0.26, 0.4,
           "gigabytes → petabytes", font_pt=9, color=GRAY_FG, italic=True,
           align=PP_ALIGN.RIGHT)


# ── Slide 3 — Barcode table ────────────────────────────────────────────────────

def build_visual_03(slide, left, top, width, height):
    import random
    random.seed(42)

    genes = ["Barcode_1", "Barcode_2", "Barcode_3", "Barcode_4", "Barcode_5"]
    n_bits = 16
    n_rows = len(genes) + 1  # +1 header
    n_cols = n_bits + 1      # +1 gene name column

    pad = 0.3
    tbl_w = width - 2 * pad
    tbl_h = height - 2 * pad
    tbl_l = left + pad
    tbl_t = top + pad

    tbl = slide.shapes.add_table(n_rows, n_cols,
                                 Inches(tbl_l), Inches(tbl_t),
                                 Inches(tbl_w), Inches(tbl_h)).table

    col_w_gene = Inches(tbl_w * 0.18)
    col_w_bit  = Inches(tbl_w * 0.82 / n_bits)

    tbl.columns[0].width = col_w_gene
    for c in range(1, n_cols):
        tbl.columns[c].width = col_w_bit

    # header row
    _tbl_cell(tbl, 0, 0, "Gene", NAVY, WHITE, bold=True, pt=9)
    for c in range(1, n_cols):
        _tbl_cell(tbl, 0, c, str(c), NAVY, WHITE, bold=True, pt=8)

    # barcodes — each gene has ~4 "on" bits
    for r, gene in enumerate(genes, start=1):
        bits = [0] * n_bits
        on_positions = random.sample(range(n_bits), 4)
        for p in on_positions:
            bits[p] = 1
        _tbl_cell(tbl, r, 0, gene, GRAY_BG, BLACK, pt=8)
        for c, bit in enumerate(bits, start=1):
            if bit:
                _tbl_cell(tbl, r, c, "1", NAVY, WHITE, bold=True, pt=8)
            else:
                _tbl_cell(tbl, r, c, "0", RGBColor(0xFF, 0xFF, 0xFF),
                          GRAY_FG, pt=8)

    # side label
    _label(slide, left + width - 1.8, top + 0.12, 1.6, 0.35,
           "round + channel → bit index", font_pt=8, color=BLUE_FG,
           italic=True, align=PP_ALIGN.RIGHT)


def _tbl_cell(tbl, row, col, text, bg: RGBColor, fg: RGBColor,
              bold=False, pt=10):
    cell = tbl.cell(row, col)
    cell.fill.solid()
    cell.fill.fore_color.rgb = bg
    tf = cell.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    if p.runs:
        r = p.runs[0]
    else:
        r = p.add_run()
    r.text = text
    r.font.size = Pt(pt)
    r.font.bold = bold
    r.font.color.rgb = fg


# ── Slide 4 — Hub-and-spoke ────────────────────────────────────────────────────

def build_visual_04(slide, left, top, width, height):
    cx = left + width / 2
    cy = top  + height / 2

    hub_w, hub_h = 2.4, 0.9
    _oval(slide, cx - hub_w / 2, cy - hub_h / 2, hub_w, hub_h,
          fill=NAVY, border_color=None)
    _label(slide, cx - hub_w / 2, cy - hub_h / 2, hub_w, hub_h,
           "qi2labDataStore", font_pt=11, color=WHITE, bold=True)

    spokes = [
        ("DataRegistration",    cx - 4.2,  top + 0.5,     2.4, 0.75, BLUE_BG, BLUE_FG),
        ("PixelDecoder",        cx + 1.8,  top + 0.5,     2.4, 0.75, GREEN_BG, GREEN_FG),
        ("Segmentation\n/ Stitching", cx - 1.2, top + height - 1.1, 2.4, 0.85, AMBER_BG, AMBER_FG),
    ]

    for name, bx, by, bw, bh, bg, fg in spokes:
        _box(slide, bx, by, bw, bh, fill=bg, border_color=fg, border_pt=1.2, radius=True)
        _label(slide, bx, by, bw, bh, name, font_pt=10, color=fg, bold=True)
        # connector: box-center to hub-center
        _connector(slide, bx + bw / 2, by + bh / 2, cx, cy, fg)

    # outer icons row
    icons = [
        ("GPU chip", left + 0.3,  top + height - 0.55),
        ("Zarr file", cx - 0.55, top + height - 0.55),
        ("codebook table", cx + 0.8, top + height - 0.55),
    ]
    for txt, ix, iy in icons:
        _label(slide, ix, iy, 1.6, 0.4, txt, font_pt=8, color=GRAY_FG, italic=True)


def _connector(slide, x1, y1, x2, y2, color: RGBColor):
    cxn = slide.shapes.add_connector(
        1,
        Inches(x1), Inches(y1), Inches(x2), Inches(y2),
    )
    cxn.line.color.rgb = color
    cxn.line.width = Pt(1.0)


# ── Slide 5 — Pipeline flow ────────────────────────────────────────────────────

def build_visual_05(slide, left, top, width, height):
    steps = [
        ("Raw\nTIFF /\nNDTiff",   GRAY_BG,  GRAY_FG),
        ("create\ndatastore",     BLUE_BG,  BLUE_FG),
        ("qi2lab\nDataStore\n(Zarr)", NAVY, WHITE),
        ("preprocess\nregister +\ndeconvolve", BLUE_BG, BLUE_FG),
        ("global reg\n+ segment", AMBER_BG, AMBER_FG),
        ("pixel\ndecode",         GREEN_BG, GREEN_FG),
        ("transcripts\nCSV/Parquet", GRAY_BG, GRAY_FG),
        ("Proseg /\nBaysor",      AMBER_BG, AMBER_FG),
        ("cell ×\ngene\ncounts",  GREEN_BG, GREEN_FG),
    ]

    n = len(steps)
    pad = 0.2
    arrow_w = 0.18
    box_w = (width - 2 * pad - (n - 1) * arrow_w) / n
    box_h = height * 0.58
    by = top + (height - box_h) / 2
    x = left + pad

    for i, (text, bg, fg) in enumerate(steps):
        _box(slide, x, by, box_w, box_h, fill=bg,
             border_color=fg, border_pt=0.75, radius=True)
        _label(slide, x, by, box_w, box_h, text,
               font_pt=8, color=fg, bold=True)
        if i < n - 1:
            ax = x + box_w
            ay = by + box_h / 2
            _arrow_right(slide, ax, ay, ax + arrow_w, color=GRAY_FG, pt=1.2)
        x += box_w + arrow_w

    # dashed branch: transcripts → F1
    f1_x = left + pad + 6 * (box_w + arrow_w) + box_w / 2
    f1_y = by + box_h + 0.1
    _label(slide, f1_x - 1.0, f1_y, 2.0, 0.4,
           "↓  F1 score vs ground truth (simulation)",
           font_pt=8, color=GRAY_FG, italic=True, align=PP_ALIGN.CENTER)


# ── Slide 6 — Filing cabinet ───────────────────────────────────────────────────

def build_visual_06(slide, left, top, width, height):
    pad = 0.3
    cab_w = width * 0.55
    cab_h = height - 2 * pad
    cab_x = left + (width - cab_w) / 2
    cab_y = top + pad

    # Cabinet body
    _box(slide, cab_x, cab_y, cab_w, cab_h,
         fill=RGBColor(0xE8, 0xEC, 0xF0), border_color=NAVY, border_pt=1.5)
    _label(slide, cab_x, cab_y - 0.02, cab_w, 0.35,
           "qi2labDataStore", font_pt=10, color=NAVY, bold=True)

    drawers = [
        ("Metadata",             BLUE_BG,  BLUE_FG),
        ("Calibrations",         BLUE_BG,  BLUE_FG),
        ("Codebook",             GREEN_BG, GREEN_FG),
        ("PSFs",                 GREEN_BG, GREEN_FG),
        ("Per-tile images",      BLUE_BG,  BLUE_FG),
        ("Pipeline state (JSON) 🔒", AMBER_BG, AMBER_FG),
    ]

    drawer_margin = 0.15
    drawer_h = (cab_h - 0.4 - len(drawers) * 0.08) / len(drawers)
    dy = cab_y + 0.38

    for name, bg, fg in drawers:
        _box(slide, cab_x + drawer_margin, dy,
             cab_w - 2 * drawer_margin, drawer_h - 0.05,
             fill=bg, border_color=fg, border_pt=0.5)
        _label(slide, cab_x + drawer_margin, dy,
               cab_w - 2 * drawer_margin, drawer_h - 0.05,
               name, font_pt=9, color=fg, bold=False)
        dy += drawer_h

    # arrows from all three tools pointing at cabinet
    tool_labels = [
        ("DataRegistration", left + 0.1, top + 0.7),
        ("PixelDecoder",     left + 0.1, top + height / 2 - 0.2),
        ("Segmentation",     left + 0.1, top + height - 1.1),
    ]
    for txt, tx, ty in tool_labels:
        _label(slide, tx, ty, 1.6, 0.35, txt, font_pt=8.5,
               color=GRAY_FG, italic=True, align=PP_ALIGN.LEFT)
        _connector(slide, tx + 1.62, ty + 0.175,
                   cab_x - 0.04, cab_y + cab_h / 2, GRAY_FG)


# ── Slide 12 — 16-bit bar chart (matplotlib) ──────────────────────────────────

def build_visual_12(slide, left, top, width, height):
    import matplotlib.pyplot as plt
    import numpy as np

    rng = np.random.default_rng(7)
    intensities = rng.uniform(0.1, 0.4, 16)
    on_bits = [2, 3, 7, 8, 12, 14]
    for b in on_bits:
        intensities[b] = rng.uniform(0.75, 1.0)

    fig, ax = plt.subplots(figsize=(width * 1.05, height * 0.82),
                           facecolor="#FFFFFF")
    colors = ["#1B2A4A" if i in on_bits else "#CCCCCC" for i in range(16)]
    bars = ax.bar(range(1, 17), intensities, color=colors, edgecolor="white",
                  linewidth=0.5)
    ax.set_xticks(range(1, 17))
    ax.set_xticklabels([str(i) for i in range(1, 17)], fontsize=8)
    ax.set_xlabel("Bit index", fontsize=9)
    ax.set_ylabel("Normalised intensity", fontsize=9)
    ax.set_title("16-bit intensity trace  →  nearest barcode match",
                 fontsize=10, pad=6)
    ax.set_ylim(0, 1.15)
    ax.axhline(0.5, color="#AAAAAA", lw=0.8, ls="--")
    ax.text(16.3, 0.52, "threshold", fontsize=7, color="#888888", va="bottom")

    # z-plane annotation
    for spine in ax.spines.values():
        spine.set_linewidth(0.5)
    ax.tick_params(labelsize=8)

    _insert_mpl(slide, fig, left + 0.15, top + 0.15,
                width - 0.3, height - 0.3)


# ── Slide 13 — 2D scatter (matplotlib) ────────────────────────────────────────

def build_visual_13(slide, left, top, width, height):
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    rng = np.random.default_rng(13)
    n = 300

    # Accepted points
    dist_acc = rng.uniform(0.0, 0.35, n)
    mag_acc  = rng.uniform(0.25, 0.85, n)

    # Rejected — too far
    dist_rej_far = rng.uniform(0.45, 0.9, 120)
    mag_rej_far  = rng.uniform(0.1, 0.95, 120)

    # Rejected — too dim
    dist_rej_dim = rng.uniform(0.0, 0.6, 80)
    mag_rej_dim  = rng.uniform(0.0, 0.20, 80)

    # Rejected — too bright
    dist_rej_bright = rng.uniform(0.0, 0.6, 50)
    mag_rej_bright  = rng.uniform(0.90, 1.1, 50)

    fig, ax = plt.subplots(figsize=(width * 0.85, height * 0.82),
                           facecolor="#FFFFFF")

    ax.scatter(dist_rej_far, mag_rej_far, s=6, color="#DDDDDD",
               alpha=0.6, label="rejected")
    ax.scatter(dist_rej_dim, mag_rej_dim, s=6, color="#DDDDDD", alpha=0.6)
    ax.scatter(dist_rej_bright, mag_rej_bright, s=6, color="#DDDDDD", alpha=0.6)
    ax.scatter(dist_acc, mag_acc, s=8, color="#1B2A4A", alpha=0.7, label="accepted")

    # threshold lines
    d_thresh = 0.40
    m_low    = 0.22
    m_high   = 0.88
    ax.axvline(d_thresh, color="#E53935", lw=1.2, ls="--")
    ax.axhline(m_low,    color="#43A047", lw=1.2, ls="--")
    ax.axhline(m_high,   color="#43A047", lw=1.2, ls="--")

    # accepted box
    rect = mpatches.FancyBboxPatch(
        (0, m_low), d_thresh, m_high - m_low,
        boxstyle="square,pad=0", linewidth=0,
        facecolor="#1B2A4A", alpha=0.07,
    )
    ax.add_patch(rect)

    ax.set_xlabel("Distance to nearest barcode", fontsize=9)
    ax.set_ylabel("Signal magnitude", fontsize=9)
    ax.set_title("Two-threshold caller: accepted (dark) vs rejected (gray)",
                 fontsize=9, pad=5)
    ax.set_xlim(0, 0.95)
    ax.set_ylim(-0.05, 1.15)

    ax.text(d_thresh + 0.01, 1.05, "distance\nthreshold",
            fontsize=7, color="#E53935", va="top")
    ax.text(0.42, m_low - 0.04, "magnitude low", fontsize=7, color="#43A047")
    ax.text(0.42, m_high + 0.01, "magnitude high", fontsize=7, color="#43A047")
    ax.text(0.02, (m_low + m_high) / 2, "ACCEPTED",
            fontsize=8, color="#1B2A4A", alpha=0.5, va="center",
            fontweight="bold")

    for spine in ax.spines.values():
        spine.set_linewidth(0.5)
    ax.tick_params(labelsize=8)

    _insert_mpl(slide, fig, left + 0.1, top + 0.15,
                width - 0.2, height - 0.3)


# ── Slide 14 — Filter funnel ───────────────────────────────────────────────────

def build_visual_14(slide, left, top, width, height):
    cx = left + width * 0.42
    pad = 0.2

    stages = [
        ("all raw barcode calls",          GRAY_BG,  GRAY_FG,  0.80),
        ("blank-barcode fraction filter",  BLUE_BG,  BLUE_FG,  0.65),
        ("logistic-regression FDR filter", BLUE_BG,  BLUE_FG,  0.50),
        ("tile-overlap de-duplication",    BLUE_BG,  BLUE_FG,  0.38),
        ("filtered transcripts",           GREEN_BG, GREEN_FG, 0.28),
    ]

    box_h = (height - 2 * pad - 0.2) / len(stages) - 0.08
    y = top + pad

    for i, (text, bg, fg, frac) in enumerate(stages):
        bw = width * 0.80 * frac
        bx = cx - bw / 2
        _box(slide, bx, y, bw, box_h, fill=bg,
             border_color=fg, border_pt=0.8, radius=True)
        _label(slide, bx, y, bw, box_h, text, font_pt=9, color=fg, bold=(i == 0 or i == 4))
        if i < len(stages) - 1:
            _arrow_down(slide, cx, y + box_h, y + box_h + 0.09, GRAY_FG, 1.2)
        y += box_h + 0.09

    # FDR gauge
    gx = left + width * 0.80
    gy = top + height * 0.5
    _box(slide, gx, gy, 1.1, 0.55, fill=GREEN_BG,
         border_color=GREEN_FG, border_pt=1.0, radius=True)
    _label(slide, gx, gy, 1.1, 0.55, "FDR ≤ 5%",
           font_pt=10, color=GREEN_FG, bold=True)


# ── Slide 16 — GPU stack ───────────────────────────────────────────────────────

def build_visual_16(slide, left, top, width, height):
    layers = [
        ("Nvidia GPU + CUDA 12.8",                   RGBColor(0x1B, 0x2A, 0x4A), WHITE),
        ("RAPIDS: cupy · cucim · cuvs · cudnn\n+ custom CUDA kernels",
                                                      RGBColor(0x0D, 0x47, 0xA1), WHITE),
        ("Ryomen out-of-core tiling",                 RGBColor(0x1A, 0x23, 0x7E), WHITE),
        ("Tensorstore + Zarr v2 storage",             RGBColor(0x00, 0x69, 0x6D), WHITE),
        ("merfish3d-analysis classes",                RGBColor(0x2E, 0x7D, 0x32), WHITE),
    ]

    pad = 0.3
    n = len(layers)
    layer_h = (height - 2 * pad) / n - 0.08
    stack_w = width * 0.78
    sx = left + (width - stack_w) / 2
    y = top + pad + (n - 1) * (layer_h + 0.08)  # bottom to top

    for i, (text, bg, fg) in enumerate(layers):
        w_frac = 0.65 + 0.35 * (i / (n - 1))
        lw = stack_w * w_frac
        lx = sx + (stack_w - lw) / 2
        _box(slide, lx, y, lw, layer_h, fill=bg,
             border_color=None, border_pt=0)
        _label(slide, lx, y, lw, layer_h, text,
               font_pt=9, color=fg, bold=(i == n - 1 or i == 0))
        y -= layer_h + 0.08

    # callouts
    _label(slide, left + width * 0.82, top + pad, width * 0.17, 0.6,
           "Linux +\nNvidia only", font_pt=8, color=AMBER_FG,
           bold=True, align=PP_ALIGN.CENTER)
    _label(slide, left + width * 0.82, top + pad + 0.7, width * 0.17, 0.5,
           "multi-GPU =\n1 process/GPU", font_pt=8, color=GRAY_FG,
           italic=True, align=PP_ALIGN.CENTER)


# ── Slide 17 — Two parallel CLI tracks ────────────────────────────────────────

def build_visual_17(slide, left, top, width, height):
    pad = 0.3
    track_w = width * 0.34
    gap = width - 2 * track_w - 2 * pad
    lx = left + pad
    rx = lx + track_w + gap

    left_steps  = ["qi2lab-datastore", "qi2lab-preprocess",
                   "qi2lab-globalregister", "qi2lab-segment", "qi2lab-decode"]
    right_steps = ["sim-convert", "sim-datastore",
                   "sim-preprocess", "sim-decode", "sim-f1score"]

    step_h = (height - 2 * pad - 0.5) / len(left_steps) - 0.1
    step_y_start = top + pad + 0.45

    # Track headers
    _box(slide, lx, top + pad, track_w, 0.38,
         fill=BLUE_BG, border_color=BLUE_FG, border_pt=1.0, radius=True)
    _label(slide, lx, top + pad, track_w, 0.38,
           "qi2lab_microscopes\n(real data)", font_pt=9, color=BLUE_FG, bold=True)

    _box(slide, rx, top + pad, track_w, 0.38,
         fill=AMBER_BG, border_color=AMBER_FG, border_pt=1.0, radius=True)
    _label(slide, rx, top + pad, track_w, 0.38,
           "statphysbio_simulation\n(validation)", font_pt=9, color=AMBER_FG, bold=True)

    for i, (lstep, rstep) in enumerate(zip(left_steps, right_steps)):
        y = step_y_start + i * (step_h + 0.1)

        _box(slide, lx, y, track_w, step_h,
             fill=BLUE_BG, border_color=BLUE_FG, border_pt=0.75)
        _label(slide, lx, y, track_w, step_h, lstep, font_pt=9, color=BLUE_FG)

        _box(slide, rx, y, track_w, step_h,
             fill=AMBER_BG, border_color=AMBER_FG, border_pt=0.75)
        _label(slide, rx, y, track_w, step_h, rstep, font_pt=9, color=AMBER_FG)

        if i < len(left_steps) - 1:
            mid_y = y + step_h / 2
            _arrow_down(slide, lx + track_w / 2, y + step_h,
                        y + step_h + 0.12, BLUE_FG, 1.0)
            _arrow_down(slide, rx + track_w / 2, y + step_h,
                        y + step_h + 0.12, AMBER_FG, 1.0)

    # Bridge arrow + label
    mid_y = step_y_start + 2 * (step_h + 0.1) + step_h / 2
    bx1 = lx + track_w + 0.05
    bx2 = rx - 0.05
    cxn = slide.shapes.add_connector(
        1,
        Inches(bx1), Inches(mid_y), Inches(bx2), Inches(mid_y),
    )
    cxn.line.color.rgb = GRAY_FG
    cxn.line.width = Pt(1.2)
    cxn.line.dash_style = 4  # dash
    _label(slide, bx1 + 0.05, mid_y - 0.28, bx2 - bx1 - 0.1, 0.28,
           "same core engine", font_pt=8, color=GRAY_FG, italic=True)


# ── Slide 18 — Numbered checklist ─────────────────────────────────────────────

def build_visual_18(slide, left, top, width, height):
    steps = [
        ("1", "conda create -n merfish3d python=3.12",
         "Create an isolated Python 3.12 environment"),
        ("2", "pip install -e .",
         "Install the package in editable mode"),
        ("3", "setup-merfish3d",
         "Set up CUDA libs + create merfish3d-stitcher env"),
        ("4", "qi2lab-datastore → qi2lab-preprocess → qi2lab-globalregister → qi2lab-segment → qi2lab-decode",
         "Run pipeline steps in order"),
        ("5", "python -m pytest tests/test_simulation_example_pipeline.py -q",
         "Validate on simulated data"),
    ]

    pad = 0.25
    row_h = (height - 2 * pad) / len(steps)
    y = top + pad

    for num, cmd, desc in steps:
        # number bubble
        _oval(slide, left + pad, y + row_h * 0.15,
              0.38, 0.38, fill=NAVY)
        _label(slide, left + pad, y + row_h * 0.15, 0.38, 0.38,
               num, font_pt=10, color=WHITE, bold=True)

        # command chip
        chip_x = left + pad + 0.5
        chip_w = width - chip_x - pad - left - 0.1
        _box(slide, chip_x, y + 0.05, chip_w, row_h * 0.48,
             fill=RGBColor(0xF5, 0xF5, 0xF5),
             border_color=RGBColor(0xCC, 0xCC, 0xCC), border_pt=0.5, radius=True)
        _label(slide, chip_x + 0.08, y + 0.05, chip_w - 0.16, row_h * 0.48,
               cmd, font_pt=8, color=NAVY, bold=True, align=PP_ALIGN.LEFT)

        # plain-language annotation
        _label(slide, chip_x + 0.08, y + row_h * 0.53, chip_w - 0.16, row_h * 0.42,
               desc, font_pt=8, color=GRAY_FG, italic=True, align=PP_ALIGN.LEFT)

        y += row_h


# ── Slide 19 — Glossary table ──────────────────────────────────────────────────

def build_visual_19(slide, left, top, width, height):
    rows = [
        ("MERFISH",         "imaging method — thousands of genes via multi-round on/off barcodes",   "bio"),
        ("FISH",            "lighting up specific RNA molecules as bright dots",                      "bio"),
        ("Codebook",        "table mapping each gene to its barcode pattern (codebook.csv)",          "eng"),
        ("Bit",             "one yes/no measurement: did this spot light up in this round+color",     "bio"),
        ("Round",           "one repeat of the imaging cycle; multiple rounds build the barcode",     "bio"),
        ("Fiducial",        "reference bead imaged every round, used as alignment anchor",            "bio"),
        ("Registration",    "nudging / rotating / warping rounds so they line up exactly",            "eng"),
        ("Deconvolution",   "mathematically un-blurring the microscope's known blur (PSF)",           "eng"),
        ("PSF",             "point spread function — the microscope's characteristic blur",           "eng"),
        ("Segmentation",    "tracing the outline of each cell",                                       "bio"),
        ("Transcript",      "one detected RNA molecule — gene identity + 3D location",                "bio"),
        ("Blank barcode",   "unused code; its appearance flags a misidentification / error rate",     "eng"),
        ("FDR",             "false-discovery rate: expected fraction of calls that are wrong (≤5%)", "eng"),
        ("GPU / CUDA / RAPIDS", "graphics-card computing that makes terabyte-scale processing feasible", "eng"),
        ("Zarr / Tensorstore",  "chunked compressed storage for huge image arrays",                   "eng"),
        ("Voxel",           "one 3D pixel — has a real-world size in microns",                        "bio"),
    ]

    pad = 0.2
    tbl_w = width - 2 * pad
    tbl_h = height - 2 * pad
    tbl_l = left + pad
    tbl_t = top + pad

    n_rows = len(rows) + 1
    n_cols = 2
    tbl = slide.shapes.add_table(n_rows, n_cols,
                                 Inches(tbl_l), Inches(tbl_t),
                                 Inches(tbl_w), Inches(tbl_h)).table

    tbl.columns[0].width = Inches(tbl_w * 0.28)
    tbl.columns[1].width = Inches(tbl_w * 0.72)

    _tbl_cell(tbl, 0, 0, "Term",         NAVY, WHITE, bold=True, pt=9)
    _tbl_cell(tbl, 0, 1, "Plain meaning", NAVY, WHITE, bold=True, pt=9)

    for r, (term, meaning, kind) in enumerate(rows, start=1):
        bg = BLUE_BG if kind == "eng" else GREEN_BG
        fg = BLUE_FG if kind == "eng" else GREEN_FG
        _tbl_cell(tbl, r, 0, term,    bg, fg,    bold=True, pt=8)
        _tbl_cell(tbl, r, 1, meaning, RGBColor(0xFF, 0xFF, 0xFF), BLACK, pt=8)


# ── Slide 20 — Full pipeline overview ─────────────────────────────────────────

def build_visual_whole_pipeline(slide, left, top, width, height):
    pad       = 0.25
    n_steps   = 6
    arrow_w   = 0.20
    strip_h   = 0.55
    lbl_h     = 0.28
    usable_w  = width - 2 * pad
    box_h     = height - 2 * pad - strip_h - 0.12 - 2 * lbl_h
    box_w     = (usable_w - (n_steps - 1) * arrow_w) / n_steps
    box_top   = top + pad + lbl_h
    strip_top = box_top + box_h + lbl_h + 0.10

    steps = [
        ("create\ndatastore", BLUE_BG,  BLUE_FG),
        ("preprocess",        BLUE_BG,  BLUE_FG),
        ("global\nregister",  BLUE_BG,  BLUE_FG),
        ("segment",           AMBER_BG, AMBER_FG),
        ("pixel\ndecode",     GREEN_BG, GREEN_FG),
        ("3-D\nre-segment",   AMBER_BG, AMBER_FG),
    ]

    between_labels = [
        "qi2labDataStore",
        "registered tiles",
        "fused OME-Zarr",
        "Cellpose masks",
        "transcripts (Parquet)",
    ]

    xs = []
    x = left + pad
    for i, (text, bg, fg) in enumerate(steps):
        _box(slide, x, box_top, box_w, box_h, fill=bg,
             border_color=fg, border_pt=1.0, radius=True)
        _label(slide, x, box_top, box_w, box_h, text,
               font_pt=10, color=fg, bold=True)
        xs.append(x)
        x += box_w + arrow_w

    # input label above first box
    _label(slide, xs[0], top + pad - 0.02, box_w, lbl_h,
           "Raw TIFF / NDTiff", font_pt=8, color=GRAY_FG, italic=True,
           align=PP_ALIGN.CENTER)

    # arrows + artefact labels
    arrow_y = box_top + box_h / 2
    for i, lbl in enumerate(between_labels):
        ax1 = xs[i] + box_w
        ax2 = ax1 + arrow_w
        _arrow_right(slide, ax1, arrow_y, ax2, color=GRAY_FG, pt=1.4)
        _label(slide, ax1 - 0.05, arrow_y + 0.06,
               arrow_w + 0.10, lbl_h,
               lbl, font_pt=7, color=GRAY_FG, italic=True,
               align=PP_ALIGN.CENTER)

    # final output label below last box
    _label(slide, xs[-1], box_top + box_h + 0.04, box_w, lbl_h,
           "cell × gene counts", font_pt=8, color=GREEN_FG, bold=True,
           align=PP_ALIGN.CENTER)

    # ── component-ownership strip ────────────────────────────────────────────────
    full_w = xs[-1] + box_w - xs[0]
    _box(slide, xs[0], strip_top, full_w, strip_h * 0.44,
         fill=NAVY, border_color=None)
    _label(slide, xs[0], strip_top, full_w, strip_h * 0.44,
           "qi2labDataStore  (central I/O hub)", font_pt=8, color=WHITE, bold=True)

    chip_top = strip_top + strip_h * 0.50
    chip_h   = strip_h * 0.46

    def _chip(i_start, i_end, label, bg, fg):
        cx = xs[i_start]
        cw = xs[i_end] + box_w - xs[i_start]
        _box(slide, cx, chip_top, cw, chip_h, fill=bg,
             border_color=fg, border_pt=0.6, radius=True)
        _label(slide, cx, chip_top, cw, chip_h, label,
               font_pt=8, color=fg)

    _chip(0, 0, "qi2labDataStore",    RGBColor(0xE3, 0xE8, 0xF0), NAVY)
    _chip(1, 2, "DataRegistration",   BLUE_BG,  BLUE_FG)
    _chip(3, 3, "Segmentation",       AMBER_BG, AMBER_FG)
    _chip(4, 4, "PixelDecoder",       GREEN_BG, GREEN_FG)
    _chip(5, 5, "Segmentation/Baysor", AMBER_BG, AMBER_FG)


# ── Dispatch dict ──────────────────────────────────────────────────────────────

VISUAL_BUILDERS: dict[int, Callable] = {
    2:  build_visual_02,
    3:  build_visual_03,
    4:  build_visual_04,
    5:  build_visual_05,
    6:  build_visual_06,
    12: build_visual_12,
    13: build_visual_13,
    14: build_visual_14,
    16: build_visual_16,
    17: build_visual_17,
    18: build_visual_18,
    19: build_visual_19,
    20: build_visual_whole_pipeline,
}
