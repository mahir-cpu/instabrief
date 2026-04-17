"""
One-time script to generate a Google Drive OAuth token.
Reuses the same oauth_creds.json from Calendar setup.

Run: python get_drive_token.py
It will open a browser, you sign in, and it saves drive_token.json.
Then copy the contents into Railway's GOOGLE_DRIVE_TOKEN_JSON env var.
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

flow = InstalledAppFlow.from_client_secrets_file("oauth_creds.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("drive_token.json", "w") as f:
    f.write(creds.to_json())

print("\nDone! drive_token.json created.")
print("\nNow copy this entire JSON string into Railway as GOOGLE_DRIVE_TOKEN_JSON:\n")
print(creds.to_json())
