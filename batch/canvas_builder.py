"""
Canvas builder module — creates personal daily rundown Slack canvases
with a table linking to brief PDFs in Google Drive.
"""

import os
from slack_sdk import WebClient

slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))


def _build_canvas_markdown(person_name, date_str, meetings_data):
    """
    Build the Slack canvas markdown for a person's daily rundown.

    Args:
        person_name: Name of the person
        date_str: Formatted date string (e.g., "Tuesday, April 14, 2026")
        meetings_data: List of dicts, each with:
            - title: Meeting title
            - start_time: e.g., "9:00 AM"
            - end_time: e.g., "9:30 AM"
            - meeting_link: Zoom/Teams URL or empty
            - location: Physical location or empty
            - external_attendees: List of {"name": str, "linkedin_url": str}
            - brief_link: Google Drive URL for the brief PDF (empty if none)

    Returns:
        str — Slack canvas markdown content
    """
    lines = []

    lines.append("| Meeting | Time | Location | Attendees | Notes |")
    lines.append("|---|---|---|---|---|")

    for m in meetings_data:
        title = m["title"].replace("|", "\u2014")

        time_str = m["start_time"] + " \u2013 " + m["end_time"]

        if m.get("meeting_link"):
            link = m["meeting_link"]
            if "zoom" in link.lower():
                location = "[Zoom](" + link + ")"
            elif "teams" in link.lower():
                location = "[Teams](" + link + ")"
            elif "meet.google" in link.lower():
                location = "[Google Meet](" + link + ")"
            else:
                location = "[Join](" + link + ")"
        elif m.get("location"):
            loc = m["location"]
            if loc.startswith("http"):
                location = "[Location](" + loc + ")"
            else:
                maps_url = "https://www.google.com/maps/search/" + loc.replace(" ", "+")
                location = "[" + loc[:30] + "](" + maps_url + ")"
        else:
            location = ""

        att_parts = []
        for att in m.get("external_attendees", [])[:4]:
            name = att.get("name", "Unknown")
            linkedin = att.get("linkedin_url", "")
            if linkedin:
                att_parts.append("[" + name + "](" + linkedin + ")")
            else:
                att_parts.append(name)

        total_attendees = len(m.get("external_attendees", []))
        if total_attendees > 4:
            att_parts.append("+" + str(total_attendees - 4) + " more")

        attendees = ", ".join(att_parts) if att_parts else ""

        if m.get("brief_link"):
            notes = "[Brief](" + m["brief_link"] + ")"
        else:
            notes = ""

        lines.append("| " + title + " | " + time_str + " | " + location + " | " + attendees + " | " + notes + " |")

    return "\n".join(lines)


def create_rundown_canvas(person_name, date_str, meetings_data):
    """
    Create a Slack canvas with the daily rundown for a person.

    Returns:
        dict with canvas_id and canvas_url
    """
    markdown = _build_canvas_markdown(person_name, date_str, meetings_data)

    title = "InstaBrief \u2014 " + person_name + " | " + date_str

    response = slack_client.canvases_create(
        title=title,
        document_content={"type": "markdown", "markdown": markdown},
    )

    canvas_id = response.get("canvas_id", "")

    team_id = os.environ.get("SLACK_TEAM_ID", "T03AKM3LMGX")
    canvas_url = "https://instalily.slack.com/docs/" + team_id + "/" + canvas_id

    return {
        "canvas_id": canvas_id,
        "canvas_url": canvas_url,
    }


def send_rundown_dm(channel_id, person_name, date_str, canvas_url):
    """Send a DM to a person with their daily rundown canvas link."""
    if not channel_id:
        print("No Slack DM channel configured for " + person_name + ", skipping DM")
        return

    slack_client.chat_postMessage(
        channel=channel_id,
        text=canvas_url,
        unfurl_links=True,
    )
