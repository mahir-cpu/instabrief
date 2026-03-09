import os
import re
import time
import threading
from dotenv import load_dotenv
load_dotenv()

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from company_search import search_companies
from calendar_search import search_calendar_for_company
from brief_generator import generate_brief
from docx_builder import build_docx

app = App(token=os.environ["SLACK_BOT_TOKEN"])

pending = {}


def _attendee_prompt(text):
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Let's go"},
                        "value": "go",
                        "action_id": "lets_go",
                    }
                ]
            }
        ],
        "text": text,
    }


@app.command("/brief")
def handle_brief(ack, command, client, logger):
    ack()
    query = command["text"].strip()
    channel = command["channel_id"]
    user = command["user_id"]

    if not query:
        client.chat_postMessage(
            channel=channel,
            text="Usage: `/brief <company name>`\nExample: `/brief eShipping`"
        )
        return

    client.chat_postMessage(channel=channel, text=":mag: Searching for *" + query + "*...")

    try:
        matches = search_companies(query)
    except Exception as e:
        logger.error("Search failed: " + str(e))
        client.chat_postMessage(channel=channel, text=":x: Search failed. Try again.")
        return

    if not matches:
        client.chat_postMessage(
            channel=channel,
            text="No companies found matching *" + query + "*. Try a more specific name."
        )
        return

    pending[channel] = {"matches": matches, "user_id": user, "step": "company"}

    if len(matches) == 1:
        _handle_company_selected(channel, matches[0], client, logger)
        return

    buttons = []
    for i, m in enumerate(matches[:5]):
        label = m["name"][:70]
        if m.get("parent"):
            label += " (" + m["parent"][:25] + ")"
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": label[:75]},
            "value": str(i),
            "action_id": "pick_" + str(i),
        })

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "I found " + str(len(matches)) + " possible matches for *" + query + "*.\nWhich company did you mean?"}
        },
        {"type": "actions", "elements": buttons},
    ]
    client.chat_postMessage(channel=channel, blocks=blocks, text="Which company?")


def _handle_company_selected(channel, company, client, logger):
    state = pending.get(channel, {})
    state["company"] = company
    state["step"] = "calendar"
    pending[channel] = state

    client.chat_postMessage(
        channel=channel,
        text=":calendar: Checking calendar for upcoming meetings with *" + company["name"] + "*..."
    )

    try:
        cal_matches = search_calendar_for_company(company["name"])
    except Exception as e:
        logger.error("Calendar search failed: " + str(e))
        cal_matches = []

    if not cal_matches:
        state["step"] = "attendees"
        state["external_attendees"] = []
        msg = _attendee_prompt("No upcoming meetings found for *" + company["name"] + "*.\n\nPaste attendee info (names, titles, LinkedIn URLs -- one per line), or click *Let's go*.")
        client.chat_postMessage(channel=channel, **msg)
        return

    state["cal_matches"] = cal_matches

    buttons = []
    for i, ev in enumerate(cal_matches[:5]):
        label = ev["title"][:40] + " - " + ev["time"]
        if ev["attendee_count"] > 0:
            label += " (" + str(ev["attendee_count"]) + " external)"
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": label[:75]},
            "value": str(i),
            "action_id": "event_" + str(i),
        })

    buttons.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "None of these"},
        "value": "none",
        "action_id": "event_none",
    })

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":calendar: I found these upcoming meetings that might be with *" + company["name"] + "*:"}
        },
        {"type": "actions", "elements": buttons},
    ]
    client.chat_postMessage(channel=channel, blocks=blocks, text="Which meeting?")


@app.action(re.compile(r"pick_\d"))
def handle_company_pick(ack, action, body, client, logger):
    ack()
    channel = body["channel"]["id"]
    idx = int(action["value"])

    state = pending.get(channel)
    if not state:
        client.chat_postMessage(channel=channel, text=":warning: Session expired. Run `/brief` again.")
        return

    company = state["matches"][idx]
    _handle_company_selected(channel, company, client, logger)


@app.action(re.compile(r"event_\d"))
def handle_event_pick(ack, action, body, client, logger):
    ack()
    channel = body["channel"]["id"]
    idx = int(action["value"])

    state = pending.get(channel)
    if not state:
        client.chat_postMessage(channel=channel, text=":warning: Session expired. Run `/brief` again.")
        return

    event = state["cal_matches"][idx]
    state["external_attendees"] = event["external_attendees"]

    # Go straight to generation
    _start_generation(channel, state, "", client, logger)


@app.action("event_none")
def handle_event_none(ack, body, client, logger):
    ack()
    channel = body["channel"]["id"]

    state = pending.get(channel)
    if not state:
        client.chat_postMessage(channel=channel, text=":warning: Session expired. Run `/brief` again.")
        return

    state["external_attendees"] = []
    state["step"] = "attendees"
    msg = _attendee_prompt("No problem. Paste attendee info (names, titles, LinkedIn URLs -- one per line), or click *Let's go*.")
    client.chat_postMessage(channel=channel, **msg)


@app.action("lets_go")
def handle_lets_go(ack, body, client, logger):
    ack()
    channel = body["channel"]["id"]

    state = pending.get(channel)
    if not state:
        client.chat_postMessage(channel=channel, text=":warning: Session expired. Run `/brief` again.")
        return

    _start_generation(channel, state, "", client, logger)


@app.message("")
def handle_message(message, client, logger):
    channel = message["channel"]
    text = message.get("text", "").strip()
    user = message.get("user", "")

    state = pending.get(channel)
    if not state:
        return
    if state.get("user_id") and state["user_id"] != user:
        return

    step = state.get("step")

    if step == "attendees":
        if text.lower() == "skip" or text.lower() == "go":
            _start_generation(channel, state, "", client, logger)
        else:
            state["external_attendees"] = []
            _start_generation(channel, state, text, client, logger)


def _start_generation(channel, state, extra_attendee_info, client, logger):
    company = state["company"]
    external_attendees = state.get("external_attendees", [])

    pending.pop(channel, None)

    attendee_text = ""
    if external_attendees:
        lines = []
        for a in external_attendees:
            lines.append(a["name"] + ", " + a["email"])
        attendee_text = "\n".join(lines)
    if extra_attendee_info:
        if attendee_text:
            attendee_text += "\n" + extra_attendee_info
        else:
            attendee_text = extra_attendee_info

    client.chat_postMessage(
        channel=channel,
        text=":white_check_mark: Generating brief for *" + company["name"] + "*...\nThis takes 3-4 minutes. I'll send the doc when it's ready."
    )

    def do_work():
        try:
            time.sleep(60)

            brief_data = generate_brief(
                company_name=company["name"],
                parent_context=company.get("parent", ""),
                attendees=attendee_text,
            )

            filepath = build_docx(brief_data)

            client.files_upload_v2(
                channel=channel,
                file=filepath,
                title=company["name"] + " - InstaBrief",
                initial_comment=":page_facing_up: Here's the meeting prep brief for *" + company["name"] + "*.",
            )

            os.remove(filepath)

        except Exception as e:
            logger.error("Brief generation failed: " + str(e))
            client.chat_postMessage(
                channel=channel,
                text=":x: Something went wrong generating the brief for *" + company["name"] + "*.\nError: `" + str(e)[:200] + "`\nPlease try again."
            )

    thread = threading.Thread(target=do_work)
    thread.start()


if __name__ == "__main__":
    print("InstaBrief starting...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()