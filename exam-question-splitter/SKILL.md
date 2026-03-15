---
name: exam-question-splitter
description: >
  Extract individual questions from exam PDFs as cropped images and PDFs.
  Takes a folder of maths, physics, or other exam papers and produces a subfolder
  per exam with each question saved as a separate PNG and PDF file. Handles
  multi-page questions that span across page breaks. Supports configurable
  sub-part splitting. Use this skill whenever the user mentions splitting exam
  papers, extracting exam questions, cropping questions from PDFs, creating
  question banks from past papers, or organising exam content — even if they
  don't explicitly say "exam-question-splitter".
---

# Exam Question Splitter

Split exam PDFs into individual question images and PDFs. Each question is
detected, cropped (including across page boundaries), and saved as its own file.

## When to use this skill

Any time a user wants to break exam papers into individual questions — for
revision, question banks, worksheets, tutoring materials, or just easier
navigation. Primarily designed for UK-style papers (AQA, Edexcel, OCR, WJEC)
but works with any structured exam format that uses numbered questions.

## Overview of the approach

The bundled script (`scripts/extract_questions.py`) handles the heavy lifting:

1. **Text extraction** — Uses PyMuPDF to pull text blocks with position and font
   metadata from every page.
2. **Question boundary detection** — Identifies where each question starts by
   matching patterns like "Question 1", "Q1", "1.", "(a)", etc., cross-checked
   against font size and weight to avoid false positives (e.g., "1" appearing
   inside an answer line).
3. **Multi-page awareness** — If Question 3 starts on page 2 and Question 4
   starts on page 4, the script captures all of pages 2–3 for Question 3.
4. **Cropping and stitching** — Renders pages at configurable DPI, crops the
   relevant vertical slice, and stitches multi-page questions into a single
   tall image.
5. **Output** — Saves each question as both PNG and PDF (configurable), with
   trimmed whitespace and consistent padding.

## Step-by-step workflow

### 1. Install dependencies

```bash
pip install pymupdf Pillow numpy --break-system-packages -q
```

### 2. Identify the input folder

Ask the user (or check the conversation) for the folder containing exam PDFs.
The script processes every `.pdf` file in the folder. If the user provides a
single PDF instead of a folder, the script handles that too.

### 3. Decide on sub-part splitting

Ask the user whether sub-parts like (a), (b), (c) should be:
- **Kept together** with the parent question (default) — produces `Q1.png`
- **Split into separate files** — produces `Q1a.png`, `Q1b.png`, etc.

Use `--split-subparts` flag to enable splitting.

### 4. Run the extraction script

```bash
python /path/to/skill/scripts/extract_questions.py \
  "/path/to/exam/folder" \
  "/path/to/output/folder" \
  --dpi 200 \
  --padding 20 \
  --format both
```

Add `--split-subparts` if the user requested it.

The script creates one subfolder per exam PDF, named after the file. Inside
each subfolder you'll find `Q1.png`, `Q1.pdf`, `Q2.png`, `Q2.pdf`, etc.

### 5. Verify the results

After running the script, check the output to make sure it looks right:

- **Spot-check a few images** — Open 2–3 PNGs to confirm questions are
  correctly cropped (not cut off mid-equation or including content from the
  next question).
- **Check the count** — Compare the number of extracted questions against what
  you'd expect from the paper. If the script found 8 questions but the exam has
  12, something was missed.
- **Look at multi-page questions** — These are the trickiest. Verify that
  questions spanning pages include all their content.

### 6. Handle failures gracefully

The script returns warnings when it can't detect question boundaries. This
typically happens with:

- **Scanned/image-based PDFs** — Text extraction returns nothing. In this case,
  fall back to a vision-based approach: render each page as an image, then use
  your vision capabilities to identify question boundaries visually. The
  `render_page_to_image()` function in the script can help with rendering.
- **Non-standard numbering** — Some exams use unusual formats like "Part A
  Question 1" or section-based numbering. You may need to adjust the regex
  patterns or manually identify boundaries.
- **Very dense papers** — Papers where questions aren't clearly separated by
  whitespace can confuse boundary detection. Adding visual inspection helps.

When the automated approach fails, explain to the user what happened and offer
to try a vision-assisted fallback — render pages as images, inspect them
yourself to identify question positions, then crop accordingly.

## Command reference

```
python extract_questions.py <input> <output> [options]

Arguments:
  input               PDF file or folder of PDFs
  output              Output directory (created automatically)

Options:
  --split-subparts    Split (a), (b), (c) sub-parts into separate files
  --dpi N             Render resolution, default 200 (150 for speed, 300 for print)
  --padding N         Pixels of white padding around each crop, default 20
  --format FMT        Output format: png, pdf, or both (default: both)
```

## Output structure

```
output_folder/
├── AQA_Maths_Paper1_2024/
│   ├── Q1.png
│   ├── Q1.pdf
│   ├── Q2.png
│   ├── Q2.pdf
│   ├── Q3.png
│   ├── Q3.pdf
│   └── ...
├── Edexcel_Physics_Paper2_2023/
│   ├── Q1.png
│   ├── Q1.pdf
│   └── ...
└── ...
```

With `--split-subparts`:
```
AQA_Maths_Paper1_2024/
├── Q1.png / Q1.pdf
├── Q2a.png / Q2a.pdf
├── Q2b.png / Q2b.pdf
├── Q3.png / Q3.pdf
└── ...
```

## Tips for best results

- **DPI trade-off**: 200 DPI is a good balance. Use 150 for quick previews or
  large batches, 300 if the output needs to be print-quality.
- **Padding**: 20px default keeps questions visually clean. Set to 0 if you
  want tight crops (e.g., for embedding in documents).
- **Scanned papers**: If the PDF is a scan, install `pytesseract` and
  `pdf2image` for OCR-based detection as a fallback, or use the vision approach
  described above.
- **Mark schemes**: The script works on mark schemes too, but mark scheme
  formatting varies more wildly. Expect to need manual corrections.