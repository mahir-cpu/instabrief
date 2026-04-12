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


def _fathom_get(endpoint, params=None, retries=5):
    headers = {"X-Api-Key": FATHOM_API_KEY}
    for attempt in range(retries):
        resp = requests.get(FATHOM_BASE_URL + endpoint, headers=headers, params=params or {})
        if resp.status_code == 429:
            wait = 20 * (attempt + 1)
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


def _claude_filter_meetings(company_name, matched_meetings):
    if len(matched_meetings) <= 1:
        return matched_meetings

    titles_list = ""
    for i, m in enumerate(matched_meetings):
        titles_list += str(i) + ": " + m["title"] + " (" + m["date"] + ")\n"

    try:
        filter_response = ai_client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": "Which of these meetings are specifically about " + company_name + "? A meeting is relevant ONLY if it is a meeting WITH " + company_name + " or directly about " + company_name + ". Meetings that happen to have a " + company_name + " employee attending but are about a different company are NOT relevant. Return ONLY a JSON array of index numbers.\n\n" + titles_list
            }],
        )
        filter_text = filter_response.content[0].text.strip()
        if filter_text.startswith("```"):
            filter_text = filter_text.split("\n", 1)[1] if "\n" in filter_text else filter_text[3:]
        if filter_text.endswith("```"):
            filter_text = filter_text[:-3]
        indices = json.loads(filter_text.strip())
        if isinstance(indices, list) and len(indices) > 0:
            filtered = [matched_meetings[i] for i in indices if i < len(matched_meetings)]
            print("Claude filtered " + str(len(matched_meetings)) + " meetings down to " + str(len(filtered)) + " relevant ones")
            return filtered
        else:
            print("Claude found no relevant meetings")
            return []
    except Exception as e:
        print("Claude filter failed, keeping all: " + str(e))
        return matched_meetings


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

    if matched_meetings:
        matched_meetings = _claude_filter_meetings(company_name, matched_meetings)

    if not matched_meetings:
        company_lower = company_name.lower()
        skip_words = {"inc", "inc.", "llc", "ltd", "ltd.", "corp", "corp.", "co", "co.", "group", "the", "company", "limited", "solutions", "consulting"}
        company_words = [w for w in company_lower.split() if len(w) > 2 and w not in skip_words]

        if not company_words:
            company_words = [company_lower.split()[0]] if company_lower.split() else []

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
                if all(word in title for word in company_words):
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

        if matched_meetings:
            matched_meetings = _claude_filter_meetings(company_name, matched_meetings)

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

    most_recent = str(len(matched_meetings))

    attendee_hint = ""
    if attendee_names:
        attendee_hint = "\n\nKey attendees to look for context on: " + ", ".join(attendee_names)

    response = ai_client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": "Based on these past meeting transcripts with " + company_name + ":" + meetings_context + attendee_hint + "\n\nGenerate the following as a JSON object. Number meetings starting from 1.\n\n{\n  \"relationship_history\": [\n    {\n      \"meeting_label\": \"Meeting 1: [short description]\",\n      \"meeting_date\": \"Mar 5, 2026\",\n      \"key_highlights\": [\n        \"Concise, declarative highlight. No filler.\",\n        \"Concise, declarative highlight. No filler.\"\n      ],\n      \"outcome\": \"1 sentence: what was decided, agreed, or demonstrated.\",\n      \"next_steps_list\": [\n        \"Owner: action item (done if completed by a later meeting)\",\n        \"Owner: action item\"\n      ]\n    }\n  ],\n  \"attendee_context\": {\n    \"Person Name\": \"1 sentence on how to approach them based on past calls\"\n  },\n  \"stated_pain_points\": [\n    {\n      \"pain_point\": \"The problem in their words\",\n      \"who_stated\": \"Who brought it up\",\n      \"meeting\": \"Which meeting\",\n      \"detail\": \"1-2 sentences of specific context -- numbers, systems, frustrations they mentioned. These must be things THEY said, not inferred.\"\n    }\n  ],\n  \"what_theyre_looking_for\": \"One paragraph describing what this company actually wants from us based on everything said across all meetings. Not what we think they need -- what THEY said they need. What problems did they bring to us? What outcomes did they describe wanting? What did they get excited about? If they described their ideal solution, capture that vision in their language. Include any constraints they mentioned -- budget, timeline, systems it needs to work with, internal approvals needed.\",\n  \"next_steps_detailed\": [\n    {\n      \"action\": \"Owner: what specifically needs to happen\",\n      \"owner\": \"InstaLILY or client name\",\n      \"context\": \"Which meeting and who requested it\",\n      \"deadline\": \"Any timeline mentioned, or No deadline discussed\"\n    }\n  ],\n  \"objections_detailed\": [\n    {\n      \"objection\": \"The specific concern in their words\",\n      \"raised_by\": \"Who said it\",\n      \"meeting\": \"Which meeting\",\n      \"type\": \"Technical / Commercial / Organizational / Competitive\",\n      \"severity\": \"Passing concern / Moderate pushback / Potential dealbreaker\",\n      \"status\": \"Addressed / Partially addressed / Still open\",\n      \"our_response\": \"How we responded, or Not yet addressed\",\n      \"prep_needed\": \"If still open, what should we prepare to address it next meeting\"\n    }\n  ],\n  \"best_approach_warm\": \"One paragraph grounded entirely in what happened in past meetings. Mirror the language THEY used to describe their problems. Lead with whichever solution or topic got the strongest positive reaction. Call out what to explicitly AVOID based on any pushback. Identify who is the champion and who is the skeptic and how to navigate that. End with what they said they need to see to move forward.\"\n}\n\nSTYLE RULES:\n- No filler words, no timestamps, no dialogue quotes\n- Clean, declarative language. Every word earns its place.\n- Focus on outcomes, clarity, and forward motion.\n\nKEY HIGHLIGHTS RULES:\n- Exactly 2 per meeting, concise, no filler\n- Focus on: key insights uncovered, decisions made, alignments reached, confirmed goals or timelines, blockers removed or areas clarified\n- Only things that moved the deal forward -- not generic summaries\n\nNEXT STEPS LIST RULES (per meeting):\n- 2-3 per meeting\n- Each must start with the owner: 'InstaLILY: action' or 'ClientName: action' or 'PersonName: action'\n- If a next step from an earlier meeting was completed by a later meeting, mark it (done)\n- Clean and declarative, no hedging\n\nNEXT STEPS DETAILED RULES:\n- 3-5 items total across all meetings\n- PRIORITIZE based on the most recent meeting (Meeting " + most_recent + "). Most recent meeting's next steps come first and carry the most weight. Earlier meetings' next steps only if still relevant and not superseded.\n- Each action must start with the owner\n- If completed, mark (done) and deprioritize\n- Focus on outcomes, clarity, and forward motion\n\nOBJECTIONS RULES:\n- Every meaningful objection, categorized by type\n- prep_needed is critical: if an objection is still open, clearly state what we should prepare for the next meeting\n\n- stated_pain_points: exactly 3, from their mouths, not inferred\n- Return ONLY valid JSON."
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