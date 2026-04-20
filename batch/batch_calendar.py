"""
Batch calendar module — pulls all events for a specific date across all calendars,
deduplicates by event ID, and filters to only external meetings.
"""

import os
import sys
import json
import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Map of person name -> calendar ID
PEOPLE = {
    "Sumo": "sumo@instalily.ai",
    "Raghav": "raghav@instalily.ai",
    "Roxie": "roxie@instalily.ai",
    "Jacob": "jacob@instalily.ai",
    "Tyler": "tyler@instalily.ai",
    "Austen": "austen@instalily.ai",
}

# Slack user IDs for each person (U... IDs, not DM channel IDs)
# The bot will open a DM conversation automatically using conversations_open
SLACK_USER_IDS = {
    "Sumo": os.environ.get("SLACK_USER_SUMO", ""),
    "Raghav": os.environ.get("SLACK_USER_RAGHAV", ""),
    "Roxie": os.environ.get("SLACK_USER_ROXIE", ""),
    "Jacob": os.environ.get("SLACK_USER_JACOB", ""),
    "Tyler": os.environ.get("SLACK_USER_TYLER", ""),
    "Austen": os.environ.get("SLACK_USER_AUSTEN", ""),
}


def _get_creds():
    creds = None
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "")
    token_path = os.path.join(os.path.dirname(__file__), "..", "token.json")

    if token_json:
        info = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    elif os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            if not token_json:
                with open(token_path, "w") as f:
                    f.write(creds.to_json())
        else:
            creds_file = os.path.join(os.path.dirname(__file__), "..", "oauth_creds.json")
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    return creds


def _is_external_meeting(event):
    """Check if a meeting has any non-instalily.ai attendees."""
    attendees = event.get("attendees", [])
    if not attendees:
        return False

    for att in attendees:
        email = att.get("email", "")
        if email and not email.endswith("@instalily.ai") and not email.endswith("@group.calendar.google.com"):
            return True

    return False


def _get_external_attendees(event):
    """Get list of external attendees from an event."""
    external = []
    for att in event.get("attendees", []):
        email = att.get("email", "")
        if email and not email.endswith("@instalily.ai") and not email.endswith("@group.calendar.google.com"):
            name = att.get("displayName", email.split("@")[0])
            external.append({"name": name, "email": email})
    return external


def _has_declined(event, calendar_email):
    """Check if the calendar owner has declined this event."""
    for att in event.get("attendees", []):
        if att.get("email", "").lower() == calendar_email.lower():
            return att.get("responseStatus") == "declined"
    return False


def _extract_meeting_link(event):
    """Extract video meeting link from event."""
    # Check conferenceData first
    conf = event.get("conferenceData", {})
    for entry_point in conf.get("entryPoints", []):
        if entry_point.get("entryPointType") == "video":
            return entry_point.get("uri", "")

    # Fall back to hangoutLink
    if event.get("hangoutLink"):
        return event["hangoutLink"]

    # Check description or location for meeting URLs
    for field in [event.get("location", ""), event.get("description", "")]:
        if field:
            for token in field.split():
                if any(p in token.lower() for p in ["zoom.us", "teams.microsoft", "meet.google"]):
                    return token.strip()

    return ""


def _parse_time(dt_dict):
    """Parse a Google Calendar dateTime or date value into a time string."""
    if "dateTime" in dt_dict:
        dt = datetime.datetime.fromisoformat(dt_dict["dateTime"])
        return dt.strftime("%-I:%M %p")
    return ""


def get_all_events_for_date(target_date):
    """
    Pull all events for a target date across all configured calendars.
    Deduplicates by event ID and filters to external-only meetings.

    Args:
        target_date: datetime.date object

    Returns:
        dict with:
            "unique_meetings": list of meeting dicts (deduplicated)
            "person_schedules": dict of person_name -> set of event IDs they're in
    """
    creds = _get_creds()
    service = build("calendar", "v3", credentials=creds)

    time_min = datetime.datetime.combine(target_date, datetime.time.min).isoformat() + "Z"
    time_max = datetime.datetime.combine(target_date, datetime.time.max).isoformat() + "Z"

    all_events = {}  # event_id -> event data
    person_schedules = {name: set() for name in PEOPLE}

    for person_name, calendar_id in PEOPLE.items():
        try:
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = events_result.get("items", [])

            for event in events:
                event_id = event.get("id", "")

                # Skip all-day events
                if "date" in event.get("start", {}) and "dateTime" not in event.get("start", {}):
                    continue

                # Skip if person declined
                if _has_declined(event, calendar_id):
                    continue

                # Skip if not external
                if not _is_external_meeting(event):
                    continue

                # Deduplicate by event ID
                if event_id not in all_events:
                    all_events[event_id] = {
                        "event_id": event_id,
                        "title": event.get("summary", "Untitled Meeting"),
                        "start_time": _parse_time(event.get("start", {})),
                        "end_time": _parse_time(event.get("end", {})),
                        "meeting_link": _extract_meeting_link(event),
                        "location": event.get("location", ""),
                        "external_attendees": _get_external_attendees(event),
                        "is_recurring": bool(event.get("recurringEventId")),
                    }

                person_schedules[person_name].add(event_id)

        except Exception as e:
            print("Error pulling calendar for " + person_name + ": " + str(e))

    return {
        "unique_meetings": list(all_events.values()),
        "person_schedules": person_schedules,
    }
