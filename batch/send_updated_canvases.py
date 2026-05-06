"""
One-off: send Mahir-owned canvases to each person via InstaBrief bot DM.

Usage:
    python batch/send_updated_canvases.py
"""

import os
from dotenv import load_dotenv
load_dotenv()

from slack_sdk import WebClient

slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))

CANVASES = [
    {"user_id": "U04Q17ZN6KA", "label": "Sumo",   "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0B1TCGQMC6"},
    {"user_id": "U09ER8M51SB", "label": "Raghav",  "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0B1Z2APTRA"},
    {"user_id": "U0ANJUSLRQW", "label": "Jacob",   "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0B1S2CUMFF"},
    {"user_id": "U0AJ6PAJ4J2", "label": "Austen",  "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0B28AWSA9F"},
    {"user_id": "U0910396AQ3", "label": "Vir",     "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0B1P2ZHWNP"},
    {"user_id": "U08RSHZK822", "label": "Rohan",   "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0B2PNA0E4Q"},
    {"user_id": "U05CCR5S0TY", "label": "Iris",    "canvas_url": "https://instalily.slack.com/docs/T03AKM3LMGX/F0B1Z2B6A76"},
]

for c in CANVASES:
    try:
        dm = slack_client.conversations_open(users=[c["user_id"]])
        dm_channel = dm["channel"]["id"]
        slack_client.chat_postMessage(
            channel=dm_channel,
            text=c["canvas_url"],
            unfurl_links=True,
        )
        print("Sent to " + c["label"])
    except Exception as e:
        print("Failed " + c["label"] + ": " + str(e))
