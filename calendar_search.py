import os
import json
import datetime
import anthropic
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
ai_client = anthropic.Anthropic()


def _get_creds():
    creds = None
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "")
    token_path = os.path.join(os.path.dirname(__file__), "token.json")

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
            creds_file = os.path.join(os.path.dirname(__file__), "oauth_creds.json")
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    return creds


def search_calendar_for_company(company_name):
    creds = _get_creds()
    service = build("calendar", "v3", credentials=creds)

    now = datetime.datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + datetime.timedelta(days=30)).isoformat() + "Z"

    calendars = [
        "sumo@instalily.ai",
        "raghav@instalily.ai",
    ]

    all_events = []
    for cal_id in calendars:
        try:
            events_result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=100,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            all_events.extend(events_result.get("items", []))
        except Exception:
            pass

    # Sort all events by start time
    all_events.sort(key=lambda e: e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")))

    if not all_events:
        return []

    event_summaries = []
    for i, event in enumerate(all_events):
        title = event.get("summary", "(no title)")
        start = event.get("start", {})
        start_str = start.get("dateTime", start.get("date", ""))
        desc = event.get("description", "")[:100]
        attendees = event.get("attendees", [])
        attendee_list = []
        for att in attendees:
            name = att.get("displayName", "")
            email = att.get("email", "")
            attendee_list.append(name + " <" + email + ">")

        summary = "Event " + str(i) + ": Title: " + title + " | Date: " + start_str
        if attendee_list:
            summary += " | Attendees: " + ", ".join(attendee_list)
        if desc:
            summary += " | Description: " + desc
        event_summaries.append(summary)

    events_text = "\n".join(event_summaries)

    response = ai_client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": "I am looking for calendar events that are meetings with the company \"" + company_name + "\".\n\nHere are my upcoming events:\n\n" + events_text + "\n\nWhich events are likely meetings with \"" + company_name + "\"? Consider the event title, attendee names, attendee email domains, and description. A match could be the company name (or part of it) in the title, an attendee with an email domain related to the company, or the company mentioned in the description. Be flexible with matching -- for example 'InstaLILY // Activera' should match 'Activera Consulting'.\n\nReturn ONLY a JSON array of matching event numbers. If no events match, return [].\nReturn ONLY the JSON array. No explanation."
        }],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        matching_indices = json.loads(text)
    except json.JSONDecodeError:
        start_pos = text.find("[")
        end_pos = text.rfind("]")
        if start_pos != -1 and end_pos != -1:
            try:
                matching_indices = json.loads(text[start_pos:end_pos + 1])
            except json.JSONDecodeError:
                return []
        else:
            return []

    if not isinstance(matching_indices, list):
        return []

    matches = []
    for idx in matching_indices:
        if not isinstance(idx, int) or idx < 0 or idx >= len(all_events):
            continue

        event = all_events[idx]
        title = event.get("summary", "(no title)")
        start = event.get("start", {})
        start_str = start.get("dateTime", start.get("date", ""))
        attendees = event.get("attendees", [])

        try:
            if "T" in start_str:
                dt = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                friendly_time = dt.strftime("%b %d, %I:%M %p")
            else:
                friendly_time = start_str
        except Exception:
            friendly_time = start_str

        external_attendees = []
        for att in attendees:
            email = att.get("email", "").lower()
            if "instalily" not in email and "resource.calendar" not in email:
                external_attendees.append({
                    "name": att.get("displayName", email.split("@")[0]),
                    "email": email,
                })

        matches.append({
            "event_id": event.get("id", ""),
            "title": title,
            "time": friendly_time,
            "attendee_count": len(external_attendees),
            "external_attendees": external_attendees,
        })

    return matches[:5]