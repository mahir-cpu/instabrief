"""
Batch runner — nightly orchestrator that generates briefs for all meetings
the next day and sends personal rundown canvases to each person.

Usage:
    python batch/batch_runner.py                  # runs for tomorrow
    python batch/batch_runner.py 2026-04-17       # runs for a specific date

Flow:
    1. Pull all calendars for the target date
    2. Deduplicate meetings, filter to external-only
    3. For each unique NON-RECURRING meeting:
       a. Identify the company from title/attendees
       b. Generate the brief (company research + Fathom transcripts)
       c. Build the DOCX, convert to PDF
       d. Upload PDF to Google Drive
    4. For each person:
       a. Build their rundown canvas (table with links to Drive PDFs)
       b. DM them the canvas link
"""

import os
import sys
import json
import time
import datetime
import threading
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
load_dotenv()

# Add parent directory to path so we can import shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from batch.batch_calendar import get_all_events_for_date, PEOPLE, SLACK_USER_IDS
from company_identifier import identify_company_from_meeting
from brief_generator import generate_brief
from fathom_search import search_fathom_for_company, generate_relationship_context
from docx_builder import build_docx
from batch.drive_upload import upload_brief_to_drive
from batch.canvas_builder import create_rundown_canvas, send_rundown_dm


# Maximum number of briefs to generate concurrently
MAX_PARALLEL_BRIEFS = 4


# ---------------------------------------------------------------------------
# PDF conversion
# ---------------------------------------------------------------------------

def convert_docx_to_pdf(docx_path):
    """
    Convert a DOCX file to PDF using LibreOffice.
    Returns the path to the PDF file.

    Falls back to uploading the DOCX directly if LibreOffice isn't available.
    """
    try:
        output_dir = os.path.dirname(docx_path)
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", output_dir, docx_path],
            check=True,
            timeout=60,
            capture_output=True,
        )
        pdf_path = docx_path.rsplit(".", 1)[0] + ".pdf"
        if os.path.exists(pdf_path):
            return pdf_path
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print("LibreOffice PDF conversion failed: " + str(e))

    # Fallback: return the DOCX path (will upload as DOCX instead)
    print("Falling back to DOCX upload (no PDF conversion available)")
    return docx_path


# ---------------------------------------------------------------------------
# Brief generation for a single meeting
# ---------------------------------------------------------------------------

def generate_meeting_brief(meeting, date_str):
    """
    Generate a complete brief for a single meeting.

    Args:
        meeting: Meeting dict from batch_calendar
        date_str: YYYY-MM-DD string

    Returns:
        dict with:
            - company_name: str
            - drive_link: str (Google Drive URL to the brief)
            - event_id: str
        or None if generation failed
    """
    title = meeting["title"]
    external_attendees = meeting["external_attendees"][:5]  # Cap at 5 attendees for briefs
    event_id = meeting["event_id"]

    print("\n" + "=" * 60)
    print("GENERATING BRIEF: " + title)
    print("External attendees: " + str(len(external_attendees)))
    print("=" * 60)

    # Step 1: Identify the company
    company_info = identify_company_from_meeting(title, external_attendees)
    company_name = company_info["company_name"]
    parent_context = company_info.get("parent", "")
    attendee_text = company_info.get("attendee_text", "")

    print("Identified company: " + company_name)

    # Step 2: Generate brief + search Fathom in parallel (same as app.py)
    results = {
        "fathom_meetings": None,
        "relationship_context": None,
        "brief_data": None,
        "fathom_error": None,
        "brief_error": None,
    }

    attendee_emails = [a["email"] for a in external_attendees] if external_attendees else None
    attendee_names = [a["name"] for a in external_attendees] if external_attendees else None

    def fathom_work():
        try:
            print("  Searching Fathom for " + company_name + "...")
            fathom_meetings = search_fathom_for_company(company_name, attendee_emails)
            if fathom_meetings:
                results["fathom_meetings"] = fathom_meetings
                results["relationship_context"] = generate_relationship_context(
                    company_name, fathom_meetings, attendee_names,
                )
                print("  Found " + str(len(fathom_meetings)) + " past meeting(s)")
            else:
                print("  No past meetings found")
        except Exception as e:
            results["fathom_error"] = str(e)
            print("  Fathom search failed: " + str(e))

    def brief_work():
        try:
            print("  Generating research brief for " + company_name + "...")
            results["brief_data"] = generate_brief(
                company_name=company_name,
                parent_context=parent_context,
                attendees=attendee_text,
            )
            print("  Brief generation complete")
        except Exception as e:
            results["brief_error"] = str(e)
            print("  Brief generation failed: " + str(e))

    t_fathom = threading.Thread(target=fathom_work)
    t_brief = threading.Thread(target=brief_work)
    t_fathom.start()
    t_brief.start()
    t_fathom.join()
    t_brief.join()

    if results["brief_data"] is None:
        print("FAILED: Could not generate brief for " + title)
        return None

    brief_data = results["brief_data"]

    # Merge relationship context (same logic as app.py)
    relationship_context = results["relationship_context"]
    if relationship_context:
        brief_data["relationship_history"] = relationship_context.get("relationship_history", [])
        brief_data["stated_pain_points"] = relationship_context.get("stated_pain_points", [])
        brief_data["what_theyre_looking_for"] = relationship_context.get("what_theyre_looking_for", "")
        brief_data["next_steps_detailed"] = relationship_context.get("next_steps_detailed", [])
        brief_data["objections_detailed"] = relationship_context.get("objections_detailed", [])
        brief_data["best_approach_warm"] = relationship_context.get("best_approach_warm", "")
        attendee_ctx = relationship_context.get("attendee_context", {})
        for att in brief_data.get("meeting_attendees", []):
            name = att.get("name", "")
            if name in attendee_ctx:
                att["past_call_context"] = attendee_ctx[name]

    # Step 3: Build DOCX
    print("  Building DOCX...")
    docx_path = build_docx(brief_data)

    # Step 4: Convert to PDF
    print("  Converting to PDF...")
    file_path = convert_docx_to_pdf(docx_path)
    is_pdf = file_path.endswith(".pdf")

    # Step 5: Upload to Google Drive
    print("  Uploading to Google Drive...")
    try:
        mime_type = "application/pdf" if is_pdf else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        drive_result = upload_brief_to_drive(file_path, company_name, date_str, mime_type)
        drive_link = drive_result["web_view_link"]
        print("  Uploaded: " + drive_link)
    except Exception as e:
        print("  Drive upload failed: " + str(e))
        drive_link = ""

    # Cleanup temp files
    try:
        os.remove(docx_path)
        if is_pdf and file_path != docx_path:
            os.remove(file_path)
    except OSError:
        pass

    return {
        "company_name": company_name,
        "drive_link": drive_link,
        "event_id": meeting["event_id"],
    }


# ---------------------------------------------------------------------------
# Main batch orchestrator
# ---------------------------------------------------------------------------

def run_batch(target_date=None):
    """
    Run the full nightly batch for a target date.

    Args:
        target_date: datetime.date object. Defaults to tomorrow.
    """
    if target_date is None:
        target_date = datetime.date.today() + datetime.timedelta(days=1)

    date_str = target_date.strftime("%Y-%m-%d")
    friendly_date = target_date.strftime("%A, %B %-d, %Y")

    print("\n" + "#" * 60)
    print("INSTABRIEF BATCH RUN")
    print("Date: " + friendly_date)
    print("Started: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("#" * 60)

    # Step 1: Pull all calendars
    print("\n[1/4] Pulling calendars...")
    calendar_data = get_all_events_for_date(target_date)
    unique_meetings = calendar_data["unique_meetings"]
    person_schedules = calendar_data["person_schedules"]

    print("Found " + str(len(unique_meetings)) + " unique external meetings")
    for person, event_ids in person_schedules.items():
        if event_ids:
            print("  " + person + ": " + str(len(event_ids)) + " meetings")

    if not unique_meetings:
        print("No external meetings found. Nothing to do.")
        return

    # Step 2: Generate briefs for eligible meetings (parallel)
    print("\n[2/4] Generating briefs...")
    brief_results = {}  # event_id -> brief result dict

    # Count meetings per external domain to detect high-frequency companies
    domain_counts = {}
    for m in unique_meetings:
        for att in m.get("external_attendees", []):
            domain = att["email"].split("@")[1] if "@" in att["email"] else ""
            if domain:
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

    high_freq_domains = {d for d, c in domain_counts.items() if c > 10}
    if high_freq_domains:
        print("  High-frequency domains (>10 meetings, skipping briefs): " + ", ".join(high_freq_domains))

    # Personal/generic email domains — no useful company to research
    PERSONAL_DOMAINS = {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
        "icloud.com", "me.com", "mac.com", "live.com", "msn.com",
        "protonmail.com", "proton.me", "ymail.com", "mail.com",
    }

    def _is_interview(title):
        return "interview" in title.lower()

    def _is_high_freq_company(meeting):
        for att in meeting.get("external_attendees", []):
            domain = att["email"].split("@")[1] if "@" in att["email"] else ""
            if domain in high_freq_domains:
                return True
        return False

    def _is_personal_email_only(meeting):
        """Skip if ALL external attendees are from personal email domains."""
        external = meeting.get("external_attendees", [])
        if not external:
            return True
        for att in external:
            domain = att["email"].split("@")[1] if "@" in att["email"] else ""
            if domain and domain.lower() not in PERSONAL_DOMAINS:
                return False
        return True

    # Filter: non-recurring, not an interview, not a high-frequency company, not personal email only
    meetings_needing_briefs = [
        m for m in unique_meetings
        if not m.get("is_recurring", False)
        and not _is_interview(m["title"])
        and not _is_high_freq_company(m)
        and not _is_personal_email_only(m)
    ]
    skipped_interviews = [m for m in unique_meetings if _is_interview(m["title"])]
    skipped_high_freq = [m for m in unique_meetings if not m.get("is_recurring", False) and _is_high_freq_company(m)]
    skipped_personal = [m for m in unique_meetings if not m.get("is_recurring", False) and _is_personal_email_only(m)]
    recurring_meetings = [m for m in unique_meetings if m.get("is_recurring", False)]

    print("  Will generate briefs: " + str(len(meetings_needing_briefs)))
    print("  Recurring (no briefs): " + str(len(recurring_meetings)))
    print("  Interviews (no briefs): " + str(len(skipped_interviews)))
    print("  High-frequency company (no briefs): " + str(len(skipped_high_freq)))
    print("  Personal email only (no briefs): " + str(len(skipped_personal)))

    if meetings_needing_briefs:
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_BRIEFS) as executor:
            future_to_meeting = {
                executor.submit(generate_meeting_brief, meeting, date_str): meeting
                for meeting in meetings_needing_briefs
            }

            for future in as_completed(future_to_meeting):
                meeting = future_to_meeting[future]
                try:
                    result = future.result()
                    if result:
                        brief_results[meeting["event_id"]] = result
                    else:
                        print("Skipping meeting (brief generation failed): " + meeting["title"])
                except Exception as e:
                    print("Brief generation raised exception for " + meeting["title"] + ": " + str(e))

    print("\nGenerated " + str(len(brief_results)) + "/" + str(len(meetings_needing_briefs)) + " briefs")

    # Step 3: Build personal rundown canvases
    print("\n[3/4] Building personal rundown canvases...")
    canvas_results = {}  # person -> canvas info

    for person_name, event_ids in person_schedules.items():
        # Include ALL external meetings (recurring + non-recurring) in the canvas
        # but only link briefs for non-recurring ones that succeeded
        person_meetings = []
        for meeting in unique_meetings:
            if meeting["event_id"] in event_ids:
                brief = brief_results.get(meeting["event_id"])
                person_meetings.append({
                    "title": meeting["title"],
                    "start_time": meeting["start_time"],
                    "end_time": meeting["end_time"],
                    "meeting_link": meeting["meeting_link"],
                    "location": meeting["location"],
                    "external_attendees": [
                        {"name": a["name"], "linkedin_url": ""}
                        for a in meeting["external_attendees"]
                    ],
                    "brief_link": brief["drive_link"] if brief else "",
                    "is_recurring": meeting.get("is_recurring", False),
                })

        if not person_meetings:
            print("  " + person_name + ": no external meetings, skipping canvas")
            continue

        print("  " + person_name + ": " + str(len(person_meetings)) + " meetings")

        try:
            canvas_info = create_rundown_canvas(person_name, friendly_date, person_meetings)
            canvas_results[person_name] = canvas_info
            print("    Canvas created: " + canvas_info["canvas_url"])
        except Exception as e:
            print("    Canvas creation failed: " + str(e))

    # Step 4: DM canvases — currently sending ALL to Mahir for review
    # TODO: Switch back to individual DMs once testing is complete
    mahir_user_id = "U0ADQ29GE4A"
    print("\n[4/4] Sending all canvases to Mahir for review...")
    for person_name, canvas_info in canvas_results.items():
        try:
            send_rundown_dm(mahir_user_id, person_name, friendly_date, canvas_info["canvas_url"])
            print("  " + person_name + "'s canvas sent to Mahir")
        except Exception as e:
            print("  DM to Mahir failed for " + person_name + "'s canvas: " + str(e))

    # Summary
    print("\n" + "#" * 60)
    print("BATCH COMPLETE")
    print("Total external meetings: " + str(len(unique_meetings)))
    print("Briefs generated: " + str(len(brief_results)) + " (non-recurring only)")
    print("Canvases created: " + str(len(canvas_results)))
    print("DMs sent to Mahir: " + str(len(canvas_results)))
    print("Finished: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("#" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = datetime.date.fromisoformat(sys.argv[1])
    else:
        target = datetime.date.today() + datetime.timedelta(days=1)

    run_batch(target)
