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


def _add_bullet(doc, text):
    p = doc.add_paragraph()
    run = p.add_run("\u00B7  " + text)
    _set_font(run)
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.space_after = Pt(4)
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

    pc = data.get("parent_context", "")
    if pc and pc not in ("", "(none)", "(none - research this)"):
        p_parent = doc.add_paragraph()
        run = p_parent.add_run(pc)
        _set_font(run, size=Pt(14), color=GRAY)

    p_div = doc.add_paragraph()
    _add_bottom_border(p_div, color="2E86C1", width="6")
    p_div.paragraph_format.space_after = Pt(12)

    _add_section_header(doc, "Client Profile")
    profile = data["client_profile"]
    labels = [
        ("What they do:", "what_they_do"),
        ("Markets served:", "markets_served"),
        ("Revenue:", "revenue"),
        ("Scale:", "scale"),
        ("Recent growth / M&A context:", "recent_growth"),
    ]
    for label, key in labels:
        _add_labeled_line(doc, label, profile.get(key, "N/A"))

    _add_section_header(doc, "Core Pain Points")
    for pain in data.get("core_pain_points", []):
        _add_bullet(doc, pain)

    _add_section_header(doc, "Highest-Impact Agentic AI Solutions")
    for sol in data.get("highest_impact_solutions", []):
        _add_bullet(doc, sol["name"] + " -- " + sol["description"])

    _add_section_header(doc, "Best Approach")
    _add_body(doc, data.get("best_approach", ""))

    _add_section_header(doc, "Company Background")
    bg = data.get("company_background", {})
    _add_body(doc, bg.get("business_model", ""))
    _add_body(doc, bg.get("founding_and_offering", ""))
    _add_body(doc, bg.get("why_now", ""))

    _add_section_header(doc, "Core Services")
    for svc in data.get("core_services", []):
        _add_bullet(doc, svc)

    _add_section_header(doc, "Revenue Drivers")
    rd = data.get("revenue_drivers", {})
    _add_body(doc, rd.get("intro", ""))
    for stream in rd.get("streams", []):
        _add_subsection_header(doc, stream["name"])
        _add_body(doc, stream["description"])
    _add_body(doc, rd.get("primary_driver_summary", ""))

    company_name = data.get("company_name", "the Company")

    _add_section_header(doc, "Specific Pain Points " + company_name + " Faces")
    for i, pp in enumerate(data.get("specific_pain_points", []), 1):
        _add_subsection_header(doc, str(i) + ". " + pp["title"])
        _add_body(doc, pp["body"])

    _add_section_header(doc, "AI Use Cases to Pitch " + company_name)
    ai = data.get("ai_use_cases", {})
    _add_body(doc, ai.get("setup", ""))
    for i, case in enumerate(ai.get("cases", []), 1):
        _add_subsection_header(doc, str(i) + ". " + case["name"])
        _add_labeled_line(doc, "The Problem:", case["problem"])
        _add_labeled_line(doc, "The Solution:", case["solution"])
        _add_labeled_line(doc, "ROI Angle:", case["roi_angle"])

    _add_section_header(doc, "Best Angle to Approach " + company_name + " for Agentic AI")
    for para in data.get("best_angle", []):
        _add_body(doc, para)

    _add_section_header(doc, "The Pitch")
    pitch = data.get("the_pitch", {})
    p = doc.add_paragraph()
    run = p.add_run(pitch.get("headline", ""))
    _set_font(run, size=Pt(11), bold=True, color=CHARCOAL)
    p.paragraph_format.space_after = Pt(6)
    _add_body(doc, pitch.get("body", ""))

    _add_section_header(doc, "Who to Target")
    for person in data.get("who_to_target", []):
        label = person["name"] + " (" + person["title"] + "):"
        _add_labeled_line(doc, label, person["rationale"])

    _add_section_header(doc, "What to Avoid")
    for item in data.get("what_to_avoid", []):
        p = doc.add_paragraph()
        bold_run = p.add_run("Don't ")
        _set_font(bold_run, bold=True)
        text_run = p.add_run(item)
        _set_font(text_run)
        p.paragraph_format.space_after = Pt(6)

    _add_section_header(doc, "Relevant AI-related Insight")
    _add_body(doc, data.get("ai_insight", ""))

    _add_section_header(doc, "Key Stakeholders")
    ks = data.get("key_stakeholders", {})
    _add_body(doc, ks.get("summary", ""))
    for leader in ks.get("leaders", []):
        _add_bullet(doc, leader["name"] + " -- " + leader["signal"])

    _add_section_header(doc, company_name + "'s Competitive Position")
    _add_body(doc, data.get("competitive_position", ""))

    safe_name = company_name.replace(" ", "_").replace("/", "-")
    filepath = os.path.join(tempfile.gettempdir(), safe_name + "_Meeting_Prep_Brief.docx")
    doc.save(filepath)
    return filepath