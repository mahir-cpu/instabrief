import json
import time
import anthropic
from dotenv import load_dotenv
load_dotenv()

client = anthropic.Anthropic(timeout=300)

SYSTEM_PROMPT = """You are an elite sales and strategy researcher producing a meeting prep brief for InstaBrief, an agentic AI solutions company.

RESEARCH RULES:
1) Start with "why now?" -- find a current inflection (growth, M&A, new product, regulation, margin pressure, competitive threat, leadership change).
2) Business model in one sentence.
3) Revenue + scale: revenue, employee count, geo footprint. If unknown, estimate and label "Est."
4) Use primary sources: investor relations, annual reports, earnings calls, press releases, PE announcements, executive interviews, credible industry coverage, company site.
5) LinkedIn signals: what functions are growing? What roles suggest priorities?
6) Find non-obvious pain: search for the company + glassdoor, reddit, implementation, integration, complaints, support, EDI/API, ERP/CRM/TMS/WMS.
7) Competitive benchmarking: 3-6 direct competitors and what they do better/worse, especially around AI and automation.
8) AI/automation posture: tools mentioned, whether AI is internal-only vs customer-facing.
9) If meeting attendees are provided, research each person thoroughly via LinkedIn and web. Find their current role, background, education, career history, and recent activity.

STYLE RULES:
- Be concise and high-signal. Every sentence must earn its place.
- Use concrete numbers, names, and specifics. No generic filler.
- Bullet points should have a bold title followed by a colon and a description.
- Highest-Impact solutions should each have a bold name, then a paragraph describing what it does and why it matters to THIS company specifically.
- Best Approach should be ONE paragraph.
- AI Insight: Concise, direct, to the point. State what tech they run today (name platforms), what AI they lack, and why the window is open. No buildup, no transitions, no filler.

CRITICAL: Return ONLY a valid JSON object. No markdown, no preamble, no backticks.

The JSON must have EXACTLY these top-level keys:

{
  "company_name": "string",
  "company_context": "Max 3 sentences. Lead with the single most important thing about this company right now. Then ownership structure and key subsidiaries. Every word must earn its place.",
  "meeting_attendees": [
    {
      "name": "Full Name",
      "linkedin_url": "URL or empty string",
      "current_position": "Current title and company in one line.",
      "career_history": "1-2 sentences covering most relevant prior roles. Concise.",
      "education": "Degrees and schools. 1 sentence.",
      "background": "Concise: organizations, boards, volunteering, sports, interests. Only include what is publicly findable. 1 sentence max."
    }
  ],
  "client_profile": {
    "what_they_do": "One rich sentence including scale numbers, customer count, geographic reach, and key platforms.",
    "markets_served": "Comma-separated list of specific market segments",
    "revenue": "Revenue figure with year, growth trajectory.",
    "scale": "One sentence: employees, locations, key specifics.",
    "recent_growth": "One sentence: trajectory, acquisitions, competitive dynamics."
  },
  "core_pain_points": [
    {
      "title": "2-3 word bold title",
      "description": "1-2 sentences with concrete details."
    }
  ],
  "highest_impact_solutions": [
    {
      "name": "Solution Name",
      "description": "2-4 sentences: what it does, how it works, what systems it connects to, specific business outcome."
    }
  ],
  "best_approach": "One paragraph combining: the inflection point framing, how to position the solution, what language to use, what existing investments to build on, and what NOT to lead with.",
  "ai_insight": "Concise, direct, to the point. State what tech they run today (name platforms), what AI they lack, and why the window is open. Every sentence is a fact or an insight."
}

IMPORTANT COUNTS:
- meeting_attendees: include all provided attendees (0 if none)
- core_pain_points: exactly 4
- highest_impact_solutions: exactly 4
- ai_insight: 1 concise paragraph
- best_approach: 1 paragraph

Every claim should reference a specific number, system, person, or event."""


def generate_brief(company_name, parent_context="", attendees=""):
    attendee_section = ""
    if attendees:
        attendee_section = "\n\nMEETING ATTENDEES TO RESEARCH:\n" + attendees + "\n\nResearch each person. Find their LinkedIn, current role, education, career history, and any organizations/volunteering/interests."

    user_message = "Research the following company and produce the complete brief as JSON.\n\nCompany: " + company_name + "\nParent/Owner/Context: " + (parent_context or "(none - research this)") + attendee_section + "\n\nDo thorough web research. Then return the JSON object as specified. ONLY valid JSON, nothing else."

    for attempt in range(4):
        try:
            print("Opus brief generation attempt " + str(attempt + 1) + " for " + company_name + "...")
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": user_message}],
            )
            break
        except Exception as e:
            error_str = str(e).lower()
            if "overloaded" in error_str or "529" in error_str:
                wait = 30 * (attempt + 1)
                print("Opus overloaded (attempt " + str(attempt + 1) + "/4), retrying in " + str(wait) + "s...")
                time.sleep(wait)
                if attempt == 3:
                    raise
            elif "rate" in error_str and "limit" in error_str:
                wait = 60
                print("Rate limited (attempt " + str(attempt + 1) + "/4), waiting " + str(wait) + "s...")
                time.sleep(wait)
                if attempt == 3:
                    raise
            elif "500" in error_str or "internal server error" in error_str or "server_error" in error_str or "api_error" in error_str:
                wait = 30 * (attempt + 1)
                print("API server error (attempt " + str(attempt + 1) + "/4), retrying in " + str(wait) + "s...")
                time.sleep(wait)
                if attempt == 3:
                    raise
            else:
                raise

    text = ""
    for block in response.content:
        if hasattr(block, "text") and block.type == "text":
            text += block.text

    text = text.strip()
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
            return json.loads(text[start:end + 1])
        raise ValueError("Could not parse Claude response as JSON. First 500 chars: " + text[:500])