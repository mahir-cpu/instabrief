import os
import re
import threading
from dotenv import load_dotenv
load_dotenv()

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from company_search import search_companies
from brief_generator import generate_brief
from docx_builder import build_docx

app = App(token=os.environ["SLACK_BOT_TOKEN"])

pending = {}


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

    client.chat_postMessage(channel=channel, text=f":mag: Searching for *{query}*...")

    try:
        matches = search_companies(query)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        client.chat_postMessage(channel=channel, text=":x: Search failed. Try again.")
        return

    if not matches:
        client.chat_postMessage(
            channel=channel,
            text=f"No companies found matching *{query}*. Try a more specific name."
        )
        return

    if len(matches) == 1:
        pending[channel] = {"matches": matches, "user_id": user}
        _generate_and_send(channel, 0, client, logger)
        return

    pending[channel] = {"matches": matches, "user_id": user}

    buttons = []
    for i, m in enumerate(matches[:5]):
        label = m["name"][:70]
        if m.get("parent"):
            label += f" ({m['parent'][:25]})"
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": label[:75]},
            "value": str(i),
            "action_id": f"pick_{i}",
        })

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"I found {len(matches)} possible matches for *{query}*.\nWhich company did you mean?"}
        },
        {"type": "actions", "elements": buttons},
    ]
    client.chat_postMessage(channel=channel, blocks=blocks, text="Which company?")


@app.action(re.compile(r"pick_\d"))
def handle_pick(ack, action, body, client, logger):
    ack()
    channel = body["channel"]["id"]
    idx = int(action["value"])
    _generate_and_send(channel, idx, client, logger)


def _generate_and_send(channel, idx, client, logger):
    state = pending.pop(channel, None)
    if not state:
        client.chat_postMessage(channel=channel, text=":warning: Session expired. Run `/brief` again.")
        return

    company = state["matches"][idx]

    client.chat_postMessage(
        channel=channel,
        text=f":white_check_mark: Generating brief for *{company['name']}*...\nThis takes 3-4 minutes. I'll send the doc when it's ready."
    )

    def do_work():
        try:
            brief_data = generate_brief(
                company_name=company["name"],
                parent_context=company.get("parent", ""),
            )

            filepath = build_docx(brief_data)

            client.files_upload_v2(
                channel=channel,
                file=filepath,
                title=f"{company['name']} - Meeting Prep Brief",
                initial_comment=f":page_facing_up: Here's the meeting prep brief for *{company['name']}*.",
            )

            os.remove(filepath)

        except Exception as e:
            logger.error(f"Brief generation failed: {e}")
            client.chat_postMessage(
                channel=channel,
                text=f":x: Something went wrong generating the brief for *{company['name']}*.\nError: `{str(e)[:200]}`\nPlease try again."
            )

    thread = threading.Thread(target=do_work)
    thread.start()


if __name__ == "__main__":
    print("InstaBrief starting...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
