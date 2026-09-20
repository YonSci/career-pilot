from io import BytesIO
from pathlib import Path
from html import escape
import json
import re
from zipfile import ZipFile, ZIP_DEFLATED
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader


def extract_text(data: bytes, name: str):
    suffix = Path(name).suffix.lower()
    if suffix in (".txt", ".md"):
        text = data.decode("utf-8-sig")
    elif suffix == ".docx":
        with ZipFile(BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > 30_000_000:
                raise ValueError("The expanded document is too large.")
        doc = Document(BytesIO(data))
        text = "\n".join(
            [p.text for p in doc.paragraphs]
            + [" | ".join(c.text for c in r.cells) for t in doc.tables for r in t.rows]
        )
    elif suffix == ".pdf":
        reader = PdfReader(BytesIO(data))
        if len(reader.pages) > 40:
            raise ValueError("Please use a CV with fewer than 40 pages.")
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
    else:
        raise ValueError("Upload DOCX, text PDF, TXT, or Markdown.")
    if len(text.strip()) < 40:
        raise ValueError(
            "No usable text found. For scanned PDFs, run OCR first or paste the CV text."
        )
    if len(text) > 100000:
        raise ValueError("CV text exceeds 100,000 characters.")
    return text


def docx_bytes(title, paragraphs, author):
    doc = Document()
    doc.core_properties.author = author or "Applicant"
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.7)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.paragraph_format.space_after = Pt(8)
    doc.add_heading(title, 0)
    for text in paragraphs:
        doc.add_paragraph(text)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def pdf_bytes(title, paragraphs):
    out = BytesIO()
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title), styles["Title"]), Spacer(1, 12)]
    for text in paragraphs:
        story.extend(
            [
                Paragraph(escape(text).replace("\n", "<br/>"), styles["BodyText"]),
                Spacer(1, 8),
            ]
        )
    SimpleDocTemplate(
        out, pagesize=A4, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45
    ).build(story)
    return out.getvalue()


def package_zip(package, author):
    output = BytesIO()
    docs = [("CV", package["cv"]), ("Cover_letter", package["cover_letter"])]
    docs += [
        (f"Additional_{i + 1}", d)
        for i, d in enumerate(package.get("additional_documents", []))
    ]
    if package.get("answers"):
        docs.append(
            (
                "Screening_answers",
                {
                    "title": "Screening answers",
                    "paragraphs": [
                        {"text": a["question"] + "\n" + a["answer"]}
                        for a in package["answers"]
                    ],
                },
            )
        )
    with ZipFile(output, "w", ZIP_DEFLATED) as z:
        for name, doc in docs:
            paragraphs = [p["text"] for p in doc["paragraphs"]]
            z.writestr(name + ".docx", docx_bytes(doc["title"], paragraphs, author))
            z.writestr(name + ".pdf", pdf_bytes(doc["title"], paragraphs))
        checklist = (
            "REVIEW BEFORE SUBMISSION\n\n"
            + "\n".join("- " + t for t in package.get("checklist", []))
            + "\n\nMISSING INFORMATION\n"
            + "\n".join("- " + t for t in package.get("missing_information", []))
        )
        z.writestr("Checklist.txt", checklist)
        z.writestr(
            "Evidence_and_draft.json", json.dumps(package, ensure_ascii=False, indent=2)
        )
    return output.getvalue()
