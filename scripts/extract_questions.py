#!/usr/bin/env python3
"""
Extract individual questions from exam PDFs as cropped images and PDFs.

Designed for UK-style exam papers (AQA, Edexcel, OCR, etc.) but works
with most structured exam formats where questions are numbered.

Usage:
    python extract_questions.py input.pdf output_dir [--split-subparts] [--dpi 200] [--padding 20]

    --split-subparts    Split sub-parts (a), (b), (c) into separate files
    --dpi N             Render resolution (default: 200, higher = sharper but larger)
    --padding N         Pixels of padding around each cropped question (default: 20)
    --format png|pdf|both  Output format (default: both)
"""

import fitz  # PyMuPDF
import re
import os
import sys
import argparse
from PIL import Image
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SpanInfo:
    """A single text span with full metadata."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_num: int
    font_size: float
    font_name: str
    is_bold: bool
    line_y0: float  # y-position of the containing line


@dataclass
class QuestionBoundary:
    """Marks where a question starts on a specific page."""
    label: str            # e.g., "Q1", "Q2a"
    page_num: int         # 0-indexed page number
    y_pos: float          # y-coordinate on the page (top of question)
    is_subpart: bool = False
    parent_question: Optional[str] = None  # e.g., "Q1" for "Q1a"


@dataclass
class QuestionRegion:
    """A complete question spanning one or more pages."""
    label: str
    start_page: int
    start_y: float
    end_page: int
    end_y: float          # y-coordinate where question ends (or page bottom)
    is_subpart: bool = False
    parent_question: Optional[str] = None


# --- Question Number Detection ---

# Patterns for main question numbers
MAIN_Q_PATTERNS = [
    # "Question 1", "QUESTION 2"
    re.compile(r'^\s*[Qq]uestion\s+(\d+)', re.IGNORECASE),
    # "Q1", "Q.1", "Q 1"
    re.compile(r'^\s*Q\.?\s*(\d+)\b'),
    # "1." or "1)" at start — but NOT "1.5" or "100."
    re.compile(r'^\s*(\d{1,2})\s*[.)]\s+(?!\d)'),
    # Bare number (font check done in code)
    re.compile(r'^\s*(\d{1,2})\s*$'),
]

# Patterns for sub-parts
SUBPART_PATTERNS = [
    # "(a)", "(b)", "(i)", "(ii)" etc.
    re.compile(r'^\s*\(([a-z])\)'),
    re.compile(r'^\s*\(([ivxlc]+)\)', re.IGNORECASE),
    # "a)", "b)" at start
    re.compile(r'^\s*([a-z])\)\s'),
    # "(a)(i)" compound sub-parts
    re.compile(r'^\s*\(([a-z])\)\s*\(([ivxlc]+)\)', re.IGNORECASE),
]


def extract_spans(page: fitz.Page, page_num: int) -> list[SpanInfo]:
    """Extract individual text spans with full position and font metadata."""
    spans = []
    text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_y0 = line["bbox"][1]
            for span in line.get("spans", []):
                text = span["text"].strip()
                if not text:
                    continue
                font_name = span.get("font", "")
                is_bold = "bold" in font_name.lower() or "heavy" in font_name.lower()
                spans.append(SpanInfo(
                    text=text,
                    x0=span["bbox"][0],
                    y0=span["bbox"][1],
                    x1=span["bbox"][2],
                    y1=span["bbox"][3],
                    page_num=page_num,
                    font_size=span["size"],
                    font_name=font_name,
                    is_bold=is_bold,
                    line_y0=line_y0,
                ))
    return spans


def compute_body_font_size(all_spans: list[SpanInfo]) -> float:
    """Estimate the most common (body) font size across all pages."""
    sizes = {}
    for s in all_spans:
        rounded = round(s.font_size * 2) / 2
        sizes[rounded] = sizes.get(rounded, 0) + len(s.text)
    if not sizes:
        return 10.0
    return max(sizes, key=sizes.get)


def is_header_or_footer(span: SpanInfo, page_height: float) -> bool:
    """Check if a span is likely a header or footer (small font at top/bottom)."""
    if span.font_size <= 9.0:
        if span.y0 < 50 or span.y0 > page_height - 50:
            return True
    return False


def is_continuation_marker(span: SpanInfo) -> bool:
    """Check if span is a 'Question N continued' marker."""
    text = span.text.lower().strip()
    return "continued" in text or "turn over" in text


@dataclass
class PageContentZone:
    """The vertical region of a page that contains actual question content,
    excluding headers, footers, horizontal rules, and continuation markers."""
    content_top: float    # y-coordinate where content starts (below header)
    content_bottom: float # y-coordinate where content ends (above footer)


def compute_content_zones(
    all_spans: list[SpanInfo],
    doc: fitz.Document,
    page_heights: dict[int, float],
) -> dict[int, PageContentZone]:
    """
    For each page, determine the vertical zone that contains actual question
    content — everything between the header/footer and any separator lines.

    This is used during cropping so that multi-page questions don't include
    repeated headers, footers, or page-separator rules in the stitched output.
    """
    zones = {}

    for pg_num, pg_height in page_heights.items():
        page = doc[pg_num]

        # Default: full page
        content_top = 0.0
        content_bottom = pg_height

        # --- Find header bottom ---
        # Look for small-font spans near the top, plus horizontal lines
        header_bottom = 0.0
        page_spans = [s for s in all_spans if s.page_num == pg_num]

        for span in sorted(page_spans, key=lambda s: s.y0):
            if span.y0 > 80:  # stop searching after 80pt from top
                break
            if span.font_size <= 9.0:
                # Header span — content starts below it
                header_bottom = max(header_bottom, span.y1)

        # Check for horizontal drawing lines (rules) near the header
        drawings = page.get_drawings()
        for d in drawings:
            for item in d.get("items", []):
                # A line item is ("l", start_point, end_point)
                if item[0] == "l":
                    p1, p2 = item[1], item[2]
                    # Horizontal line: same y (within tolerance), reasonable width
                    if abs(p1.y - p2.y) < 2 and abs(p2.x - p1.x) > 200:
                        line_y = (p1.y + p2.y) / 2
                        # If this line is near the header, it's a separator
                        if header_bottom > 0 and abs(line_y - header_bottom) < 30:
                            header_bottom = max(header_bottom, line_y + 2)
                        # If near top of page regardless
                        elif line_y < 60:
                            header_bottom = max(header_bottom, line_y + 2)

        # Also skip continuation markers ("Question N continued") at the top
        for span in sorted(page_spans, key=lambda s: s.y0):
            if span.y0 > header_bottom + 40:
                break
            if is_continuation_marker(span):
                header_bottom = max(header_bottom, span.y1 + 5)

        if header_bottom > 0:
            content_top = header_bottom

        # --- Find footer top ---
        footer_top = pg_height
        for span in sorted(page_spans, key=lambda s: -s.y0):
            if span.y0 < pg_height - 80:  # stop searching
                break
            if span.font_size <= 9.0:
                footer_top = min(footer_top, span.y0)

        # Check for horizontal lines near the footer
        for d in drawings:
            for item in d.get("items", []):
                if item[0] == "l":
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) < 2 and abs(p2.x - p1.x) > 200:
                        line_y = (p1.y + p2.y) / 2
                        if footer_top < pg_height and abs(line_y - footer_top) < 30:
                            footer_top = min(footer_top, line_y - 2)
                        elif line_y > pg_height - 60:
                            footer_top = min(footer_top, line_y - 2)

        if footer_top < pg_height:
            content_bottom = footer_top

        # Also check for "END OF QUESTIONS" or "TURN OVER" near the bottom
        for span in sorted(page_spans, key=lambda s: -s.y0):
            if span.y0 < content_bottom - 60:
                break
            text_lower = span.text.lower().strip()
            if "end of questions" in text_lower or "turn over" in text_lower:
                content_bottom = min(content_bottom, span.y0 - 2)

        zones[pg_num] = PageContentZone(
            content_top=content_top,
            content_bottom=content_bottom,
        )

    return zones


def find_question_boundaries(
    all_spans: list[SpanInfo],
    page_heights: dict[int, float],
    body_font_size: float,
    split_subparts: bool = False,
) -> list[QuestionBoundary]:
    """
    Identify where each question (and optionally sub-part) starts.

    Works at the span level so it can detect bold question numbers even when
    they share a text block with the question body (common in UK exam papers).
    """
    boundaries = []
    seen_questions = set()
    current_main_q = None
    # Track the next expected sub-part letter so we only match sequential
    # labels (a, b, c...) and don't false-positive on (x), (y) in maths.
    next_expected_subpart = "a"

    # Sort spans by page then vertical position
    sorted_spans = sorted(all_spans, key=lambda s: (s.page_num, s.line_y0, s.x0))

    for span in sorted_spans:
        text = span.text.strip()
        if not text:
            continue

        # Skip headers, footers, and continuation markers
        page_h = page_heights.get(span.page_num, 842)
        if is_header_or_footer(span, page_h):
            continue
        if is_continuation_marker(span):
            continue

        # Skip mark annotations like "[3 marks]", "[3]", "3 marks"
        # but NOT bare numbers like "1", "2" (those might be question numbers)
        if re.match(r'^\[\d+\s*(marks?)?\]$', text, re.IGNORECASE):
            continue
        if re.match(r'^\d+\s+marks?$', text, re.IGNORECASE):
            continue

        # --- Try main question patterns ---
        matched_main = False

        for i, pattern in enumerate(MAIN_Q_PATTERNS):
            m = pattern.match(text)
            if not m:
                continue

            q_num = m.group(1)
            label = f"Q{q_num}"

            # For bare-number pattern, require bold or larger-than-body font
            # This prevents matching random numbers in the text
            if i == len(MAIN_Q_PATTERNS) - 1:  # bare number pattern
                if not span.is_bold and span.font_size < body_font_size * 1.05:
                    continue

            # For the "N." / "N)" pattern, also prefer bold/larger when the
            # number is small (avoids matching list items in question text)
            if i == 2 and int(q_num) <= 2:
                if not span.is_bold and span.font_size <= body_font_size:
                    continue

            # Check it's not a duplicate (e.g., same Q in header/footer)
            if label in seen_questions:
                break

            # Sanity check: question numbers should be roughly sequential.
            # If we've seen Q3 and now see Q15, something is off.
            if seen_questions:
                max_seen = max(int(l[1:]) for l in seen_questions if l[1:].isdigit())
                if int(q_num) > max_seen + 5:
                    continue  # skip — probably not a real question number

            seen_questions.add(label)
            boundaries.append(QuestionBoundary(
                label=label,
                page_num=span.page_num,
                y_pos=span.line_y0,
                is_subpart=False,
            ))
            current_main_q = label
            next_expected_subpart = "a"  # reset for new question
            matched_main = True
            break

        # --- Try sub-part patterns ---
        if not matched_main and split_subparts and current_main_q:
            for pattern in SUBPART_PATTERNS:
                m = pattern.match(text)
                if m:
                    groups = m.groups()
                    part_letter = groups[0]

                    # Guard against false positives from maths expressions
                    # like "(x)" or "(y)". Sub-parts should appear in
                    # sequential order: (a), (b), (c)... If this letter
                    # isn't the one we expect next, skip it.
                    if len(part_letter) == 1 and part_letter.isalpha():
                        if part_letter != next_expected_subpart:
                            break  # not sequential — probably maths notation

                    if len(groups) == 2:
                        sub_label = f"{current_main_q}{groups[0]}_{groups[1]}"
                    else:
                        sub_label = f"{current_main_q}{groups[0]}"

                    if sub_label not in seen_questions:
                        seen_questions.add(sub_label)
                        boundaries.append(QuestionBoundary(
                            label=sub_label,
                            page_num=span.page_num,
                            y_pos=span.line_y0,
                            is_subpart=True,
                            parent_question=current_main_q,
                        ))
                        # Advance expected sub-part
                        if len(part_letter) == 1 and part_letter.isalpha():
                            next_expected_subpart = chr(ord(part_letter) + 1)
                    break

    return boundaries


def boundaries_to_regions(
    boundaries: list[QuestionBoundary],
    page_heights: dict[int, float],
    total_pages: int,
) -> list[QuestionRegion]:
    """Convert boundary markers into full regions (start to end)."""
    if not boundaries:
        return []

    regions = []
    sorted_bounds = sorted(boundaries, key=lambda b: (b.page_num, b.y_pos))

    for i, bound in enumerate(sorted_bounds):
        if i + 1 < len(sorted_bounds):
            next_bound = sorted_bounds[i + 1]
            end_page = next_bound.page_num
            end_y = next_bound.y_pos - 2
        else:
            # Last question extends to end of document
            end_page = total_pages - 1
            end_y = page_heights.get(end_page, 842)

        regions.append(QuestionRegion(
            label=bound.label,
            start_page=bound.page_num,
            start_y=bound.y_pos,
            end_page=end_page,
            end_y=end_y,
            is_subpart=bound.is_subpart,
            parent_question=bound.parent_question,
        ))

    return regions


# --- Rendering and Cropping ---

def render_page_to_image(page: fitz.Page, dpi: int = 200) -> Image.Image:
    """Render a PDF page to a PIL Image."""
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img


def crop_question(
    doc: fitz.Document,
    region: QuestionRegion,
    dpi: int = 200,
    padding: int = 20,
    content_zones: dict[int, PageContentZone] | None = None,
) -> Image.Image:
    """Crop a question region from the PDF, stitching pages if needed.

    When content_zones is provided, headers/footers/separator lines are
    excluded from continuation pages so that stitched multi-page questions
    contain only actual question content.
    """
    zoom = dpi / 72.0
    images = []

    for pg_num in range(region.start_page, region.end_page + 1):
        page = doc[pg_num]
        page_height = page.rect.height

        # Get content zone for this page (or fall back to full page)
        zone = content_zones.get(pg_num) if content_zones else None
        zone_top = zone.content_top if zone else 0
        zone_bottom = zone.content_bottom if zone else page_height

        # Determine vertical crop bounds for this page
        if pg_num == region.start_page and pg_num == region.end_page:
            # Single-page question: use region bounds directly
            top = region.start_y
            bottom = min(region.end_y, zone_bottom)
        elif pg_num == region.start_page:
            # First page of multi-page: start at question, end at content zone bottom
            top = region.start_y
            bottom = zone_bottom
        elif pg_num == region.end_page:
            # Last page of multi-page: start at content zone top, end at next question
            top = zone_top
            bottom = min(region.end_y, zone_bottom)
        else:
            # Middle page: use full content zone (skip header/footer)
            top = zone_top
            bottom = zone_bottom

        # Clamp values
        top = max(0, top)
        bottom = min(page_height, bottom)
        if bottom <= top:
            continue

        # Render full page then crop
        full_img = render_page_to_image(page, dpi)
        img_w, img_h = full_img.size

        # Convert PDF coords to pixel coords
        px_top = int(top * zoom)
        px_bottom = int(bottom * zoom)
        px_top = max(0, min(px_top, img_h))
        px_bottom = max(0, min(px_bottom, img_h))

        if px_bottom <= px_top:
            continue

        crop_img = full_img.crop((0, px_top, img_w, px_bottom))
        images.append(crop_img)

    if not images:
        return Image.new("RGB", (100, 100), "white")

    # Stitch vertically if multi-page
    if len(images) == 1:
        combined = images[0]
    else:
        total_h = sum(img.height for img in images)
        max_w = max(img.width for img in images)
        combined = Image.new("RGB", (max_w, total_h), "white")
        y_offset = 0
        for img in images:
            combined.paste(img, (0, y_offset))
            y_offset += img.height

    # Add padding
    if padding > 0:
        padded = Image.new(
            "RGB",
            (combined.width + 2 * padding, combined.height + 2 * padding),
            "white",
        )
        padded.paste(combined, (padding, padding))
        return padded

    return combined


def trim_whitespace(img: Image.Image, margin: int = 10) -> Image.Image:
    """Trim excessive whitespace from the edges of an image."""
    try:
        import numpy as np
    except ImportError:
        return img

    arr = np.array(img)

    # Find rows and columns that aren't all white (or nearly white)
    threshold = 250
    non_white = arr.min(axis=2) < threshold

    rows = non_white.any(axis=1)
    cols = non_white.any(axis=0)

    if not rows.any() or not cols.any():
        return img

    row_indices = rows.nonzero()[0]
    col_indices = cols.nonzero()[0]

    top = max(0, row_indices[0] - margin)
    bottom = min(img.height, row_indices[-1] + margin)
    left = max(0, col_indices[0] - margin)
    right = min(img.width, col_indices[-1] + margin)

    return img.crop((left, top, right, bottom))


def save_question_as_pdf(img: Image.Image, output_path: str):
    """Save a PIL Image as a single-page PDF."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(output_path, "PDF", resolution=150)


# --- Main Pipeline ---

def process_exam_pdf(
    pdf_path: str,
    output_dir: str,
    split_subparts: bool = False,
    dpi: int = 200,
    padding: int = 20,
    output_format: str = "both",
) -> dict:
    """
    Process a single exam PDF and extract individual questions.

    Returns a dict with:
        - questions: list of {label, file_png, file_pdf, pages}
        - warnings: list of issues encountered
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    warnings = []

    # Step 1: Extract spans from all pages
    all_spans = []
    page_heights = {}
    for pg_num in range(total_pages):
        page = doc[pg_num]
        page_heights[pg_num] = page.rect.height
        spans = extract_spans(page, pg_num)
        all_spans.extend(spans)

    # Step 2: Determine body font size
    body_font_size = compute_body_font_size(all_spans)

    # Step 3: Find question boundaries
    boundaries = find_question_boundaries(
        all_spans, page_heights, body_font_size, split_subparts
    )

    if not boundaries:
        warnings.append(
            "No question boundaries detected via text extraction. "
            "The PDF may be scanned/image-based or use non-standard numbering."
        )
        return {"questions": [], "warnings": warnings}

    # Step 4: Convert to regions
    regions = boundaries_to_regions(boundaries, page_heights, total_pages)

    # Step 4.5: Compute content zones (header/footer boundaries per page)
    content_zones = compute_content_zones(all_spans, doc, page_heights)

    # Step 5: Crop and save each question
    os.makedirs(output_dir, exist_ok=True)
    questions = []

    for region in regions:
        img = crop_question(doc, region, dpi, padding, content_zones)

        # Trim excessive whitespace
        img = trim_whitespace(img, margin=padding)

        result = {"label": region.label, "pages": f"{region.start_page+1}-{region.end_page+1}"}

        if output_format in ("png", "both"):
            png_path = os.path.join(output_dir, f"{region.label}.png")
            img.save(png_path, "PNG")
            result["file_png"] = png_path

        if output_format in ("pdf", "both"):
            pdf_path_out = os.path.join(output_dir, f"{region.label}.pdf")
            save_question_as_pdf(img, pdf_path_out)
            result["file_pdf"] = pdf_path_out

        questions.append(result)

    doc.close()
    return {"questions": questions, "warnings": warnings}


def process_folder(
    folder_path: str,
    output_base: str,
    split_subparts: bool = False,
    dpi: int = 200,
    padding: int = 20,
    output_format: str = "both",
) -> dict:
    """
    Process all PDF files in a folder.

    Creates a subfolder in output_base for each PDF, named after the PDF file.
    Returns a summary dict.
    """
    folder = Path(folder_path)
    pdf_files = sorted(folder.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDF files found in {folder_path}")
        return {"processed": 0, "results": []}

    os.makedirs(output_base, exist_ok=True)
    results = []

    for pdf_file in pdf_files:
        exam_name = pdf_file.stem
        safe_name = re.sub(r'[^\w\s\-.]', '_', exam_name).strip()
        output_dir = os.path.join(output_base, safe_name)

        print(f"\nProcessing: {pdf_file.name}")
        print(f"  Output -> {output_dir}")

        result = process_exam_pdf(
            str(pdf_file), output_dir,
            split_subparts=split_subparts,
            dpi=dpi, padding=padding,
            output_format=output_format,
        )

        result["exam_name"] = exam_name
        result["source_file"] = str(pdf_file)

        n_questions = len(result["questions"])
        print(f"  Found {n_questions} questions")
        if result["warnings"]:
            for w in result["warnings"]:
                print(f"  WARNING: {w}")

        for q in result["questions"]:
            pages_str = q["pages"]
            print(f"    {q['label']} (pages {pages_str})")

        results.append(result)

    return {"processed": len(results), "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract individual questions from exam PDFs"
    )
    parser.add_argument("input", help="PDF file or folder of PDFs")
    parser.add_argument("output", help="Output directory")
    parser.add_argument("--split-subparts", action="store_true",
                        help="Split sub-parts (a), (b) into separate files")
    parser.add_argument("--dpi", type=int, default=200,
                        help="Render DPI (default: 200)")
    parser.add_argument("--padding", type=int, default=20,
                        help="Padding pixels around crops (default: 20)")
    parser.add_argument("--format", choices=["png", "pdf", "both"],
                        default="both", dest="output_format",
                        help="Output format (default: both)")

    args = parser.parse_args()

    input_path = Path(args.input)
    if input_path.is_dir():
        summary = process_folder(
            str(input_path), args.output,
            split_subparts=args.split_subparts,
            dpi=args.dpi, padding=args.padding,
            output_format=args.output_format,
        )
        print(f"\nDone! Processed {summary['processed']} exam(s)")
    elif input_path.is_file() and input_path.suffix.lower() == ".pdf":
        result = process_exam_pdf(
            str(input_path), args.output,
            split_subparts=args.split_subparts,
            dpi=args.dpi, padding=args.padding,
            output_format=args.output_format,
        )
        print(f"\nDone! Extracted {len(result['questions'])} questions")
        if result["warnings"]:
            for w in result["warnings"]:
                print(f"WARNING: {w}")
    else:
        print(f"Error: {args.input} is not a PDF file or directory")
        sys.exit(1)