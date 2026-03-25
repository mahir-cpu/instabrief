import os
import json
import time as _time
import anthropic
import requests
from dotenv import load_dotenv
load_dotenv()

FATHOM_API_KEY = os.environ.get("FATHOM_API_KEY", "")
FATHOM_BASE_URL = "https://api.fathom.ai/external/v1"
ai_client = anthropic.Anthropic(timeout=120)


def _fathom_get(endpoint, params=None, retries=3):
    headers = {"X-Api-Key": FATHOM_API_KEY}
    for attempt in range(retries):
        resp = requests.get(FATHOM_BASE_URL + endpoint, headers=headers, params=params or {})
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)
            print("Fathom rate limit hit, waiting " + str(wait) + "s...")
            _time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def _parse_transcript(data):
    if isinstance(data, str):
        if len(data) > 6000:
            return data[:6000] + "... [truncated]"
        return data

    if isinstance(data, list):
        lines = []
        for seg in data[:200]:
            if isinstance(seg, dict):
                speaker = seg.get("speaker", {})
                if isinstance(speaker, dict):
                    name = speaker.get("display_name", "Unknown")
                else:
                    name = str(speaker)
                text = seg.get("text", "")
                ts = seg.get("timestamp", "")
                lines.append(name + " [" + ts + "]: " + text)
            else:
                lines.append(str(seg))
        transcript = "\n".join(lines)
        if len(transcript) > 6000:
            transcript = transcript[:6000] + "... [truncated]"
        return transcript

    if isinstance(data, dict):
        if "transcript" in data:
            return _parse_transcript(data["transcript"])
        return str(data)[:6000]

    return str(data)[:6000]


def _get_transcript(recording_id):
    try:
        data = _fathom_get("/recordings/" + str(recording_id) + "/transcript")
        return _parse_transcript(data)
    except Exception as e:
        print("Transcript fetch error for " + str(recording_id) + ": " + str(e))
        return ""


def _get_summary(recording_id):
    try:
        data = _fathom_get("/recordings/" + str(recording_id) + "/summary")
        if isinstance(data, dict):
            for key in ["summary", "text", "content", "body"]:
                if key in data and data[key]:
                    val = data[key]
                    if isinstance(val, str):
                        return val[:3000]
                    return str(val)[:3000]
            return str(data)[:3000]
        if isinstance(data, str):
            return data[:3000]
        return str(data)[:3000]
    except Exception as e:
        print("Summary fetch error for " + str(recording_id) + ": " + str(e))
        return ""


def search_fathom_for_company(company_name, attendee_emails=None):
    if not FATHOM_API_KEY:
        return None

    matched_meetings = []

    if attendee_emails:
        domains = list(set([
            e.split("@")[1] for e in attendee_emails
            if "@" in e and "instalily" not in e.lower()
        ]))

        for domain in domains:
            cursor = None
            for _ in range(5):
                params = {"calendar_invitees_domains[]": domain}
                if cursor:
                    params["cursor"] = cursor
                try:
                    data = _fathom_get("/meetings", params)
                except Exception:
                    break
                items = data.get("items", [])
                for m in items:
                    title = m.get("title", "") or m.get("meeting_title", "")
                    matched_meetings.append({
                        "title": title,
                        "date": m.get("created_at", "")[:10],
                        "recording_id": m.get("recording_id"),
                        "summary": "",
                        "transcript": "",
                    })
                cursor = data.get("next_cursor", "")
                if not cursor:
                    break

    if not matched_meetings:
        company_lower = company_name.lower()
        company_words = [w for w in company_lower.split() if len(w) > 2]

        cursor = None
        for _ in range(100):
            params = {}
            if cursor:
                params["cursor"] = cursor
            try:
                data = _fathom_get("/meetings", params)
            except Exception:
                break
            items = data.get("items", [])
            if not items:
                break
            for m in items:
                title = (m.get("title", "") or m.get("meeting_title", "")).lower()
                if any(word in title for word in company_words):
                    matched_meetings.append({
                        "title": m.get("title", "") or m.get("meeting_title", ""),
                        "date": m.get("created_at", "")[:10],
                        "recording_id": m.get("recording_id"),
                        "summary": "",
                        "transcript": "",
                    })
            cursor = data.get("next_cursor", "")
            if not cursor:
                break

    if not matched_meetings:
        return None

    matched_meetings.sort(key=lambda x: x.get("date", ""))

    for m in matched_meetings:
        rid = m.get("recording_id")
        if rid:
            print("Fetching transcript for: " + m.get("title", "") + " (id: " + str(rid) + ")")
            _time.sleep(2)
            m["transcript"] = _get_transcript(rid)
            print("  Transcript length: " + str(len(m["transcript"])))
            _time.sleep(2)
            m["summary"] = _get_summary(rid)
            print("  Summary length: " + str(len(m["summary"])))

    return matched_meetings


def generate_relationship_context(company_name, matched_meetings, attendee_names=None):
    if not matched_meetings:
        return None

    meetings_context = ""
    for i, m in enumerate(matched_meetings):
        meetings_context += "\n\nMEETING " + str(i + 1) + " - " + m["title"] + " (" + m["date"] + "):\n"
        if m.get("summary"):
            meetings_context += "Summary: " + str(m["summary"]) + "\n"
        if m.get("transcript"):
            meetings_context += "Transcript:\n" + str(m["transcript"]) + "\n"

    attendee_hint = ""
    if attendee_names:
        attendee_hint = "\n\nKey attendees to look for context on: " + ", ".join(attendee_names)

    response = ai_client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": "Based on these past meeting transcripts with " + company_name + ":" + meetings_context + attendee_hint + "\n\nGenerate the following as a JSON object. Number meetings starting from 1:\n\n{\n  \"relationship_history\": [\n    {\n      \"meeting_label\": \"Meeting 1: [short description]\",\n      \"meeting_date\": \"Mar 5, 2026\",\n      \"key_highlights\": [\n        \"First key highlight from this meeting -- 1 sentence, specific and actionable\",\n        \"Second key highlight from this meeting -- 1 sentence, specific and actionable\"\n      ],\n      \"outcome\": \"1 sentence: what was decided, agreed, or demonstrated.\",\n      \"next_step\": \"1 sentence: what was agreed as the next action coming out of this meeting.\"\n    }\n  ],\n  \"attendee_context\": {\n    \"Person Name\": \"1 sentence on how to approach them based on past calls\"\n  },\n  \"next_steps\": \"What they told us they need in the next call. Be specific.\",\n  \"objections\": \"Key objections or concerns raised that we should be ready for.\"\n}\n\nEach meeting MUST have exactly 2 key_highlights. Be concise but specific. Reference actual things said. Return ONLY valid JSON."
        }],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None