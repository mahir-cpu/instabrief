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
from fathom_search import search_fathom_for_company, generate_relationship_context
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
        text=":white_check_mark: Generating brief for *" + company["name"] + "*...\nThis takes a couple minutes. I'll send the doc when it's ready."
    )

    def do_work():
        try:
            # Run Fathom search and Opus brief generation in parallel
            attendee_emails = [a["email"] for a in external_attendees] if external_attendees else None
            attendee_names = [a["name"] for a in external_attendees] if external_attendees else None

            # Shared results from threads
            results = {
                "fathom_meetings": None,
                "relationship_context": None,
                "brief_data": None,
                "fathom_error": None,
                "brief_error": None,
            }

            # ── Thread 1: Fathom search + relationship context (Sonnet) ──
            def fathom_work():
                try:
                    client.chat_postMessage(
                        channel=channel,
                        text=":film_projector: Searching past meeting transcripts..."
                    )
                    fathom_meetings = search_fathom_for_company(company["name"], attendee_emails)
                    print("FATHOM RESULT:", fathom_meetings is not None, "count:",
                          len(fathom_meetings) if fathom_meetings else 0)

                    if fathom_meetings:
                        results["fathom_meetings"] = fathom_meetings
                        relationship_context = generate_relationship_context(
                            company["name"],
                            fathom_meetings,
                            attendee_names,
                        )
                        results["relationship_context"] = relationship_context
                        print("RELATIONSHIP CONTEXT:", relationship_context is not None)
                        client.chat_postMessage(
                            channel=channel,
                            text=":white_check_mark: Found " + str(len(fathom_meetings)) + " past meeting(s). Including context in brief."
                        )
                    else:
                        client.chat_postMessage(
                            channel=channel,
                            text=":information_source: No past meeting transcripts found."
                        )
                except Exception as e:
                    results["fathom_error"] = str(e)
                    print("Fathom thread error: " + str(e))
                    client.chat_postMessage(
                        channel=channel,
                        text=":information_source: Could not search past transcripts."
                    )

            # ── Thread 2: Opus brief generation ──
            def brief_work():
                try:
                    client.chat_postMessage(
                        channel=channel,
                        text=":brain: Researching company with AI (this is the slow part)..."
                    )
                    brief_data = generate_brief(
                        company_name=company["name"],
                        parent_context=company.get("parent", ""),
                        attendees=attendee_text,
                    )
                    results["brief_data"] = brief_data
                    print("BRIEF GENERATION: complete")
                except Exception as e:
                    results["brief_error"] = str(e)
                    print("Brief thread error: " + str(e))

            # Start both threads
            t_fathom = threading.Thread(target=fathom_work)
            t_brief = threading.Thread(target=brief_work)
            t_fathom.start()
            t_brief.start()

            # Wait for both to finish
            t_fathom.join()
            t_brief.join()

            # Check for brief generation failure
            if results["brief_data"] is None:
                raise Exception("Brief generation failed: " + (results["brief_error"] or "Unknown error"))

            brief_data = results["brief_data"]

            # Inject relationship context into brief data
            relationship_context = results["relationship_context"]
            if relationship_context:
                brief_data["relationship_history"] = relationship_context.get("relationship_history", [])
                brief_data["next_steps"] = relationship_context.get("next_steps", "")
                brief_data["objections"] = relationship_context.get("objections", "")
                # Add per-attendee context
                attendee_ctx = relationship_context.get("attendee_context", {})
                for att in brief_data.get("meeting_attendees", []):
                    name = att.get("name", "")
                    if name in attendee_ctx:
                        att["past_call_context"] = attendee_ctx[name]

            print("BRIEF HAS RELATIONSHIP HISTORY:", "relationship_history" in brief_data,
                  len(brief_data.get("relationship_history", [])))

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