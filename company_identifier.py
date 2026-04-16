"""
Company identifier module — given a meeting's title and external attendees,
figures out which company this meeting is with so we can run the brief generator.
"""

import json
import anthropic

client = anthropic.Anthropic(timeout=120)


def identify_company_from_meeting(title, external_attendees):
    """
    Given a meeting title and list of external attendees,
    identify the company this meeting is with.

    Args:
        title: Meeting title string
        external_attendees: List of dicts with "name" and "email" keys

    Returns:
        dict with:
            "company_name": str  — best guess at company name
            "parent": str        — parent company if known, else ""
            "attendee_text": str  — formatted attendee info for brief generator
    """
    attendee_lines = []
    domains = set()
    for att in external_attendees:
        line = att["name"]
        if att.get("email"):
            line += ", " + att["email"]
            domain = att["email"].split("@")[1] if "@" in att["email"] else ""
            if domain:
                domains.add(domain)
        attendee_lines.append(line)

    attendee_text = "\n".join(attendee_lines)
    domains_text = ", ".join(domains) if domains else "unknown"

    prompt = (
        'Given this calendar meeting, identify the external company involved.\n\n'
        'Meeting title: "' + title + '"\n'
        'External attendee email domains: ' + domains_text + '\n'
        'External attendees:\n' + attendee_text + '\n\n'
        'Based on the meeting title and attendee email domains, determine:\n'
        '1. The company name (use the full official name if you can infer it from the domain or title)\n'
        '2. The parent company or PE owner if obvious from the title\n\n'
        'Return ONLY a JSON object:\n'
        '{"company_name": "Full Company Name", "parent": "Parent or empty string"}\n\n'
        'Rules:\n'
        '- If the title contains "InstaLILY x CompanyName" or "InstaLILY // CompanyName", extract CompanyName\n'
        '- If the title has a company name followed by a topic (e.g., "Radwell Calibration"), extract the company\n'
        '- Use the email domain to validate or improve your guess\n'
        '- If multiple companies are in the title, pick the external (non-InstaLILY) one\n'
        '- Return ONLY valid JSON'
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result = json.loads(text)
        result["attendee_text"] = attendee_text
        return result

    except Exception as e:
        print("Company identification failed: " + str(e))
        # Fallback: use the first external attendee's domain
        if domains:
            domain = list(domains)[0]
            company = domain.split(".")[0].capitalize()
            return {
                "company_name": company,
                "parent": "",
                "attendee_text": attendee_text,
            }
        return {
            "company_name": title.split(" - ")[0].split(" | ")[0].split(" // ")[0].strip(),
            "parent": "",
            "attendee_text": attendee_text,
        }
