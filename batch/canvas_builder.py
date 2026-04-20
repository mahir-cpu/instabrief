"""
Canvas builder module — creates personal daily rundown Slack canvases
with a table linking to brief PDFs in Google Drive.
"""

import os
import re
from slack_sdk import WebClient

slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))


def _sanitize_text(text):
    """Remove characters that break Slack canvas markdown tables."""
    return text.replace("|", "\u2014").replace("<", "").replace(">", "").replace("[", "").replace("]", "").replace("(", "").replace(")", "")


def _is_valid_url(url):
    """Check if a URL is a valid http/https link for Slack canvas markdown."""
    if not url:
        return False
    url = url.strip()
    return url.startswith("http://") or url.startswith("https://")


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
        title = _sanitize_text(m["title"])

        time_str = m["start_time"] + " \u2013 " + m["end_time"]

        # Location / meeting link
        link = m.get("meeting_link", "").strip()
        if link and _is_valid_url(link):
            # Strip query params from meeting links too
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

        # Attendees (cap at 5)
        att_parts = []
        for att in m.get("external_attendees", [])[:5]:
            name = _sanitize_text(att.get("name", "Unknown"))
            linkedin = att.get("linkedin_url", "")
            if linkedin and _is_valid_url(linkedin):
                att_parts.append("[" + name + "](" + linkedin + ")")
            else:
                att_parts.append(name)

        total_attendees = len(m.get("external_attendees", []))
        if total_attendees > 5:
            att_parts.append("+" + str(total_attendees - 5) + " more")

        attendees = ", ".join(att_parts) if att_parts else ""

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

        lines.append("| " + title + " | " + time_str + " | " + location + " | " + attendees + " | " + notes + " |")

    markdown = "\n".join(lines)
    print("  Canvas markdown:\n" + markdown)
    return markdown


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


def send_rundown_dm(user_id_or_channel, person_name, date_str, canvas_url):
    """
    Send a DM to a person with their daily rundown canvas link.
    Accepts either a user ID (U...) or a DM channel ID (D...).
    If given a user ID, opens a DM conversation first.
    """
    if not user_id_or_channel:
        print("No Slack user/channel configured for " + person_name + ", skipping DM")
        return

    # If it's a user ID, open a DM conversation first
    if user_id_or_channel.startswith("U"):
        response = slack_client.conversations_open(users=[user_id_or_channel])
        channel_id = response["channel"]["id"]
    else:
        channel_id = user_id_or_channel

    slack_client.chat_postMessage(
        channel=channel_id,
        text=canvas_url,
        unfurl_links=True,
    )
