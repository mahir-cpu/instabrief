"""
Google Drive upload module — uploads brief files to a shared Drive folder
and returns shareable links.
"""

import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]

# The shared folder ID where briefs are stored
# Structure: BRIEFS_FOLDER / YYYY-MM-DD / individual brief files
BRIEFS_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_BRIEFS_FOLDER_ID", "")


def _get_drive_creds():
    """Get Google Drive credentials (separate from Calendar creds)."""
    creds = None
    token_json = os.environ.get("GOOGLE_DRIVE_TOKEN_JSON", "")
    token_path = os.path.join(os.path.dirname(__file__), "..", "drive_token.json")

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
            creds_file = os.path.join(os.path.dirname(__file__), "..", "drive_oauth_creds.json")
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    return creds


def _get_or_create_date_folder(service, date_str):
    """
    Get or create a subfolder named YYYY-MM-DD inside the briefs folder.
    Returns the folder ID.
    """
    if not BRIEFS_FOLDER_ID:
        raise ValueError("GOOGLE_DRIVE_BRIEFS_FOLDER_ID environment variable not set")

    # Check if folder already exists
    query = (
        "name = '" + date_str + "' "
        "and mimeType = 'application/vnd.google-apps.folder' "
        "and '" + BRIEFS_FOLDER_ID + "' in parents "
        "and trashed = false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    # Create the folder
    folder_metadata = {
        "name": date_str,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [BRIEFS_FOLDER_ID],
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder["id"]


def upload_brief_to_drive(filepath, company_name, date_str, mime_type="application/pdf"):
    """
    Upload a brief file to Google Drive.

    Args:
        filepath: Local path to the file
        company_name: Company name (used in the filename)
        date_str: Date string YYYY-MM-DD (used for folder organization)
        mime_type: MIME type of the file

    Returns:
        dict with:
            "file_id": str — Drive file ID
            "web_view_link": str — shareable link to view the file
            "web_content_link": str — direct download link
    """
    creds = _get_drive_creds()
    service = build("drive", "v3", credentials=creds)

    # Get or create the date folder
    folder_id = _get_or_create_date_folder(service, date_str)

    # Clean up filename
    safe_name = company_name.replace("/", "-").replace("\\", "-")
    filename = safe_name + "_InstaBrief"
    if filepath.endswith(".pdf"):
        filename += ".pdf"
    elif filepath.endswith(".docx"):
        filename += ".docx"
    else:
        filename += os.path.splitext(filepath)[1]

    # Upload
    file_metadata = {
        "name": filename,
        "parents": [folder_id],
    }
    media = MediaFileUpload(filepath, mimetype=mime_type, resumable=True)
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink, webContentLink",
    ).execute()

    # Make the file viewable by anyone with the link
    service.permissions().create(
        fileId=file["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    return {
        "file_id": file["id"],
        "web_view_link": file.get("webViewLink", ""),
        "web_content_link": file.get("webContentLink", ""),
    }
