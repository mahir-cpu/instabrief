"""
Quick test script — runs the batch for one or more people on a specific date.

Usage (from repo root):
    python batch/test_batch.py --person Sumo --channel C08P96GDG6M
    python batch/test_batch.py --person Sumo,Raghav --channel C08P96GDG6M,C097KCDC6E6
    python batch/test_batch.py --person Austen --date 2026-04-17
    python batch/test_batch.py --all
"""

import os
import sys
import argparse
import datetime
from dotenv import load_dotenv
load_dotenv()

# Add parent directory to path so we can import shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from batch.batch_calendar import get_all_events_for_date, PEOPLE, SLACK_USER_IDS
from batch.batch_runner import generate_meeting_brief, run_batch
from batch.canvas_builder import create_rundown_canvas, send_rundown_dm


def run_single_person_test(person_name, target_date, send_to):
    """Run the batch pipeline for a single person only."""
    date_str = target_date.strftime("%Y-%m-%d")
    friendly_date = target_date.strftime("%A, %B %-d, %Y")

    print(f"\n{'#' * 60}")
    print(f"INSTABRIEF TEST RUN — {person_name}")
    print(f"Date: {friendly_date}")
    print(f"{'#' * 60}")

    if person_name not in PEOPLE:
        print(f"Unknown person: {person_name}")
        print(f"Available: {', '.join(PEOPLE.keys())}")
        return

    # Pull ALL calendars (needed for dedup) but only process this person's meetings
    print("\nPulling calendars...")
    calendar_data = get_all_events_for_date(target_date)
    unique_meetings = calendar_data["unique_meetings"]
    person_event_ids = calendar_data["person_schedules"].get(person_name, set())

    person_meetings = [m for m in unique_meetings if m["event_id"] in person_event_ids]
    print(f"Found {len(person_meetings)} external meetings for {person_name}")

    for m in person_meetings:
        is_rec = "RECURRING" if m.get("is_recurring") else "NEW"
        print(f"  [{is_rec}] {m['title']} ({len(m['external_attendees'])} external)")

    # Generate briefs for non-recurring meetings
    meetings_needing_briefs = [m for m in person_meetings if not m.get("is_recurring", False)]
    brief_results = {}

    for meeting in meetings_needing_briefs:
        result = generate_meeting_brief(meeting, date_str)
        if result:
            brief_results[meeting["event_id"]] = result

    print(f"\nGenerated {len(brief_results)}/{len(meetings_needing_briefs)} briefs")

    # Build canvas
    canvas_meetings = []
    for meeting in person_meetings:
        brief = brief_results.get(meeting["event_id"])
        canvas_meetings.append({
            "title": meeting["title"],
            "start_time": meeting["start_time"],
            "end_time": meeting["end_time"],
            "meeting_link": meeting["meeting_link"],
            "location": meeting["location"],
            "external_attendees": [
                {"name": a["name"], "linkedin_url": ""} for a in meeting["external_attendees"]
            ],
            "brief_link": brief["drive_link"] if brief else "",
        })

    if canvas_meetings:
        canvas_info = create_rundown_canvas(person_name, friendly_date, canvas_meetings)
        print(f"Canvas created: {canvas_info['canvas_url']}")

        if send_to:
            send_rundown_dm(send_to, person_name, friendly_date, canvas_info["canvas_url"])
            print(f"Sent to {send_to}")
        else:
            print("No --channel provided, canvas created but not sent")
    else:
        print("No external meetings — nothing to send.")

    print(f"\n{'#' * 60}")
    print("TEST COMPLETE")
    print(f"{'#' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test InstaBrief for one or more people")
    parser.add_argument("--person", default="Austen", help="Person name(s), comma-separated (default: Austen)")
    parser.add_argument("--channel", default=None, help="Channel/user ID(s) to send to, comma-separated")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: tomorrow)")
    parser.add_argument("--all", action="store_true", help="Run for everyone (full batch)")
    args = parser.parse_args()

    if args.date:
        target = datetime.date.fromisoformat(args.date)
    else:
        target = datetime.date.today() + datetime.timedelta(days=1)

    if args.all:
        run_batch(target)
    else:
        people = [p.strip() for p in args.person.split(",")]
        channels = [c.strip() for c in args.channel.split(",")] if args.channel else [None] * len(people)

        if len(channels) == 1 and len(people) > 1:
            channels = channels * len(people)

        for person, channel in zip(people, channels):
            run_single_person_test(person, target, channel)
