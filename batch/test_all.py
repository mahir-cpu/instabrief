"""
Test run for ALL people — pulls calendars, generates briefs,
creates canvases (no attendee column), and DMs everything to Mahir.

Usage:
    railway run python batch/test_all.py              # tomorrow
    railway run python batch/test_all.py 2026-04-23   # specific date
"""

import os
import sys
import datetime
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from batch.batch_calendar import get_all_events_for_date, PEOPLE
from batch.batch_runner import generate_meeting_brief
from batch.canvas_builder import (
    slack_client,
    _sanitize_text,
    _is_valid_url,
    send_rundown_dm,
)

# Where to send all canvases (Mahir's Slack user ID)
MAHIR_USER_ID = "U0ADQ29GE4A"


def _build_canvas_no_attendees(person_name, date_str, meetings_data):
    """Build canvas markdown WITHOUT the Attendees column."""
    lines = []
    lines.append("| Meeting | Time | Location | Notes |")
    lines.append("|---|---|---|---|")

    for m in meetings_data:
        title = _sanitize_text(m["title"])
        time_str = m["start_time"] + " \u2013 " + m["end_time"]

        # Location / meeting link
        link = m.get("meeting_link", "").strip()
        if link and _is_valid_url(link):
            clean_link = link.split("?")[0]
            if "zoom" in link.lower():
                location = "[Zoom](" + clean_link + ")"
            elif "teams" in link.lower():
                location = "[Teams](" + clean_link + ")"
            elif "meet.google" in link.lower():
                location = "[Google Meet](" + clean_link + ")"
            else:
                location = "[Join](" + clean_link + ")"
        elif m.get("location"):
            loc = m["location"]
            if _is_valid_url(loc):
                location = "[Location](" + loc.split("?")[0] + ")"
            else:
                location = _sanitize_text(loc[:30])
        else:
            location = ""

        # Notes — brief link or recurring label
        if m.get("brief_link"):
            brief_url = m["brief_link"].split("?")[0]
            if _is_valid_url(brief_url):
                notes = "[Brief](" + brief_url + ")"
            else:
                notes = ""
        elif m.get("is_recurring"):
            notes = "Recurring meeting"
        else:
            notes = ""

        lines.append("| " + title + " | " + time_str + " | " + location + " | " + notes + " |")

    markdown = "\n".join(lines)
    print("  Canvas markdown:\n" + markdown)
    return markdown


def create_canvas_no_attendees(person_name, date_str, meetings_data):
    """Create a Slack canvas without the attendee column."""
    markdown = _build_canvas_no_attendees(person_name, date_str, meetings_data)
    title = "InstaBrief \u2014 " + person_name + " | " + date_str

    response = slack_client.canvases_create(
        title=title,
        document_content={"type": "markdown", "markdown": markdown},
    )

    canvas_id = response.get("canvas_id", "")
    team_id = os.environ.get("SLACK_TEAM_ID", "T03AKM3LMGX")
    canvas_url = "https://instalily.slack.com/docs/" + team_id + "/" + canvas_id

    return {"canvas_id": canvas_id, "canvas_url": canvas_url}


def main():
    if len(sys.argv) > 1:
        target_date = datetime.date.fromisoformat(sys.argv[1])
    else:
        target_date = datetime.date.today() + datetime.timedelta(days=1)

    friendly_date = target_date.strftime("%A, %B %-d, %Y")
    date_str = target_date.strftime("%Y-%m-%d")

    print("\n" + "#" * 60)
    print("INSTABRIEF TEST — ALL PEOPLE")
    print("Date: " + friendly_date)
    print("People: " + ", ".join(PEOPLE.keys()))
    print("All canvases will DM to Mahir (" + MAHIR_USER_ID + ")")
    print("#" * 60)

    # Pull calendars
    print("\nPulling calendars...")
    calendar_data = get_all_events_for_date(target_date)
    unique_meetings = calendar_data["unique_meetings"]
    person_schedules = calendar_data["person_schedules"]

    print("Total unique external meetings: " + str(len(unique_meetings)))
    for person_name in PEOPLE:
        count = len(person_schedules.get(person_name, set()))
        print("  " + person_name + ": " + str(count) + " meetings")

    for person_name in PEOPLE:
        event_ids = person_schedules.get(person_name, set())
        person_meetings = [m for m in unique_meetings if m["event_id"] in event_ids]

        print("\n" + "=" * 60)
        print(person_name + ": " + str(len(person_meetings)) + " external meetings")
        print("=" * 60)

        if not person_meetings:
            print("  No external meetings, skipping.")
            continue

        for m in person_meetings:
            tag = "RECURRING" if m.get("is_recurring") else "NEW"
            print("  [" + tag + "] " + m["title"])

        # Generate briefs for non-recurring meetings
        meetings_needing_briefs = [m for m in person_meetings if not m.get("is_recurring", False)]
        brief_results = {}

        for meeting in meetings_needing_briefs:
            print("\n  Generating brief for: " + meeting["title"])
            result = generate_meeting_brief(meeting, date_str)
            if result:
                brief_results[meeting["event_id"]] = result
                print("  -> Brief uploaded: " + result["drive_link"])
            else:
                print("  -> Brief generation FAILED")

        print("\n  Briefs: " + str(len(brief_results)) + "/" + str(len(meetings_needing_briefs)))

        # Build canvas data (no attendees)
        canvas_meetings = []
        for meeting in person_meetings:
            brief = brief_results.get(meeting["event_id"])
            canvas_meetings.append({
                "title": meeting["title"],
                "start_time": meeting["start_time"],
                "end_time": meeting["end_time"],
                "meeting_link": meeting["meeting_link"],
                "location": meeting["location"],
                "brief_link": brief["drive_link"] if brief else "",
                "is_recurring": meeting.get("is_recurring", False),
            })

        # Create canvas & DM to Mahir
        try:
            canvas_info = create_canvas_no_attendees(person_name, friendly_date, canvas_meetings)
            print("\n  Canvas created: " + canvas_info["canvas_url"])

            send_rundown_dm(MAHIR_USER_ID, person_name, friendly_date, canvas_info["canvas_url"])
            print("  DM sent to Mahir")
        except Exception as e:
            print("  Canvas/DM failed: " + str(e))

    print("\n" + "#" * 60)
    print("TEST COMPLETE")
    print("#" * 60)


if __name__ == "__main__":
    main()
