"""
Quick one-off: send existing canvases to channels via the InstaBrief bot.

Usage:
    railway run python batch/send_canvases.py
"""

import os
from dotenv import load_dotenv
load_dotenv()

from slack_sdk import WebClient

slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))

SENDS = [
    {
        "channel": "U0ACF7D0BGS",  # Roxie
        "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0AUHT4AAAF",
        "label": "Roxie",
    },
    {
        "channel": "U0ANJUSLRQW",  # Jacob
        "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0AUHU7R6H1",
        "label": "Jacob",
    },
    {
        "channel": "U0AJ6PAJ4J2",  # Austen
        "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0AUN8UKY8N",
        "label": "Austen",
    },
    {
        "channel": "U0910396AQ3",  # Vir
        "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0AUU016J9J",
        "label": "Vir",
    },
]

for s in SENDS:
    try:
        user_id = s["channel"]
        # Open a DM conversation with the user first
        dm = slack_client.conversations_open(users=[user_id])
        dm_channel = dm["channel"]["id"]

        slack_client.chat_postMessage(
            channel=dm_channel,
            text=s["canvas_url"],
            unfurl_links=True,
        )
        print("Sent " + s["label"] + " canvas to " + user_id + " (DM: " + dm_channel + ")")
    except Exception as e:
        print("Failed " + s["label"] + ": " + str(e))
