import os
import tempfile
from datetime import date
from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


NAVY = RGBColor(0x1B, 0x2A, 0x4A)
ACCENT = RGBColor(0x2E, 0x86, 0xC1)
CHARCOAL = RGBColor(0x2D, 0x2D, 0x2D)
BODY_COLOR = RGBColor(0x33, 0x33, 0x33)
GRAY = RGBColor(0x66, 0x66, 0x66)


def _set_font(run, name="Calibri", size=Pt(10.5), color=BODY_COLOR, bold=False):
    run.font.name = name
    run.font.size = size
    run.font.color.rgb = color
    run.bold = bold


def _add_bottom_border(paragraph, color="2E86C1", width="4"):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), width)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _add_section_header(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    _set_font(run, size=Pt(16), color=NAVY, bold=True)
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    _add_bottom_border(p)


def _add_subsection_header(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    _set_font(run, size=Pt(13), color=CHARCOAL, bold=True)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)


def _add_body(doc, text, justify=True):
    p = doc.add_paragraph()
    run = p.add_run(text)
    _set_font(run)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.15
    if justify:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


def _add_body_italic(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    _set_font(run, color=GRAY)
    run.italic = True
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.15


def _add_bullet(doc, text):
    p = doc.add_paragraph()
    run = p.add_run("\u00B7  " + text)
    _set_font(run)
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.15


def _add_bold_bullet(doc, title, description):
    p = doc.add_paragraph()
    bold_run = p.add_run("\u00B7  " + title + ": ")
    _set_font(bold_run, bold=True)
    desc_run = p.add_run(description)
    _set_font(desc_run)
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.15


def _add_sub_bullet(doc, label, text):
    p = doc.add_paragraph()
    bold_run = p.add_run("\u00B7  " + label + " ")
    _set_font(bold_run, bold=True)
    text_run = p.add_run(text)
    _set_font(text_run)
    p.paragraph_format.left_indent = Inches(0.5)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.15


def _add_labeled_line(doc, label, text):
    p = doc.add_paragraph()
    label_run = p.add_run(label + " ")
    _set_font(label_run, bold=True)
    text_run = p.add_run(text)
    _set_font(text_run)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.15


def build_docx(data):
    doc = Document()

    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2)
    section.right_margin = Cm(2)

    p_date = doc.add_paragraph()
    p_date.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p_date.add_run("Prepared for InstaBrief  |  " + date.today().strftime("%B %d, %Y"))
    _set_font(run, size=Pt(10), color=GRAY)
    run.italic = True

    p_title = doc.add_paragraph()
    run = p_title.add_run(data["company_name"])
    _set_font(run, size=Pt(28), color=NAVY, bold=True)

    p_div = doc.add_paragraph()
    _add_bottom_border(p_div, color="2E86C1", width="6")
    p_div.paragraph_format.space_after = Pt(6)

    ctx = data.get("company_context", "")
    if ctx:
        _add_body_italic(doc, ctx)

    attendees = data.get("meeting_attendees", [])
    if attendees:
        _add_section_header(doc, "Meeting Attendees")
        for person in attendees:
            p = doc.add_paragraph()
            run = p.add_run(person.get("name", ""))
            _set_font(run, size=Pt(12), color=NAVY, bold=True)
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(2)

            if person.get("current_position"):
                _add_sub_bullet(doc, "Current Position:", person["current_position"])
            if person.get("education"):
                _add_sub_bullet(doc, "Education:", person["education"])
            if person.get("career_history"):
                _add_sub_bullet(doc, "Career History:", person["career_history"])
            if person.get("awards"):
                _add_sub_bullet(doc, "Awards:", person["awards"])

    _add_section_header(doc, "Client Profile")
    profile = data.get("client_profile", {})
    for label, key in [
        ("What they do:", "what_they_do"),
        ("Markets served:", "markets_served"),
        ("Revenue:", "revenue"),
        ("Scale:", "scale"),
        ("Recent growth / M&A context:", "recent_growth"),
    ]:
        _add_labeled_line(doc, label, profile.get(key, "N/A"))

    _add_section_header(doc, "Core Pain Points")
    for pp in data.get("core_pain_points", []):
        _add_bold_bullet(doc, pp["title"], pp["description"])

    _add_section_header(doc, "Highest-Impact Agentic AI Solutions")
    for i, sol in enumerate(data.get("highest_impact_solutions", []), 1):
        _add_subsection_header(doc, str(i) + ". " + sol["name"])
        _add_body(doc, sol["description"])

    _add_section_header(doc, "Best Approach")
    ba = data.get("best_approach", "")
    if isinstance(ba, list):
        for para in ba:
            _add_body(doc, para)
    else:
        _add_body(doc, ba)

    _add_section_header(doc, "Core Services")
    for svc in data.get("core_services", []):
        _add_bullet(doc, svc)

    _add_section_header(doc, "Relevant AI-Related Insight")
    ai = data.get("ai_insight", "")
    if isinstance(ai, list):
        for para in ai:
            _add_body(doc, para)
    else:
        _add_body(doc, ai)

    safe_name = data.get("company_name", "Brief").replace(" ", "_").replace("/", "-")
    filepath = os.path.join(tempfile.gettempdir(), safe_name + "_InstaBrief.docx")
    doc.save(filepath)
    return filepath