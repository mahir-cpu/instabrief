---
name: generate-brief
description: >
  Generate an InstaBrief meeting prep brief for any company. Use this skill whenever
  the user says /brief, "brief me on", "prep me for a meeting with", "research this company",
  "generate a brief", or mentions any company name in the context of meeting preparation,
  sales research, or deal prep. Also trigger when the user asks to look up a company's
  background, pain points, AI posture, or competitive landscape for a sales meeting.
  Even casual requests like "what do we know about [company]" or "pull up info on [company]"
  should trigger this skill if the context suggests meeting prep or sales research.
---

# Generate Brief

Create a polished meeting prep brief for any company — the exact same output as InstaBrief's
Slack `/brief` command. This skill runs the production InstaBrief Python pipeline directly.

## Prerequisites

The InstaBrief codebase must be available locally with:
- Python virtual environment with dependencies installed
- `.env` file containing `ANTHROPIC_API_KEY` and `FATHOM_API_KEY`

The codebase location is the workspace folder (the user's selected folder in Cowork).
If the workspace folder IS the InstaBrief directory, use it directly. Otherwise, look
for an `InstaBrief` subdirectory.

## Flow

### Step 1: Extract the Company Name

Parse the company name from the user's message. Examples:
- `/brief eShipping` → company = "eShipping"
- `"brief me on Acme Corp"` → company = "Acme Corp"
- `"research SunSource for my meeting"` → company = "SunSource"

### Step 2: Search and Disambiguate

Run the company search script:

```bash
cd <INSTABRIEF_ROOT> && source venv/bin/activate && python -c "
import json, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from company_search import search_companies
matches = search_companies('<COMPANY_NAME>')
print(json.dumps(matches, indent=2))
"
```

This calls Claude Sonnet with web search to find up to 5 possible matches, each with
`name`, `parent`, and `description`.

- If **1 match**: confirm with the user and proceed.
- If **multiple matches**: present them to the user and ask which one. Use the AskUserQuestion
  tool to let them pick.
- If **0 matches**: tell the user no results were found, suggest trying a different name.

### Step 3: Ask About Attendees

Ask the user if they have meeting attendees to include. Accept names and email addresses
in the format `Name, email@domain.com` (one per line).

Attendee emails are important — they let the system search Fathom by domain for past meetings.

If the user says "skip" or "no", proceed without attendees.

### Step 4: Search Email Context (BEFORE running the pipeline)

Search Gmail for relevant email threads BEFORE running the brief pipeline. The email
summary will be passed into the pipeline so it can inform relationship history, next steps,
objections, and best approach directly in the DOCX output.

**Search strategy** — run these searches (up to 3 in parallel):

1. **By attendee emails**: For each attendee email provided, search:
   `from:<email> OR to:<email> newer_than:6m`
   Limit to 5 threads per attendee.

2. **By company domain**: Extract the domain from attendee emails (e.g., `acme.com` from
   `john@acme.com`). Search:
   `from:@<domain> OR to:@<domain> newer_than:6m`
   Limit to 10 threads.

3. **By company name in subject**: Search:
   `subject:(<COMPANY_NAME>) newer_than:6m`
   Limit to 5 threads.

If no attendee emails were provided, skip search #1 and try to infer the domain from the
company name for search #2 (e.g., "eShipping" → `eshipping.com`). If unsure, just run #3.

**Processing the results:**

- For each unique thread found, use `get_thread` to read the full content (use FULL_CONTENT format).
- Deduplicate threads that appear in multiple searches.
- Write a plain-text summary to a temporary file (e.g., `/tmp/email_context.txt`) with these
  categories. Only include categories that have meaningful content:
  - **Recent discussions**: What topics have been discussed over email recently?
  - **Open items**: Any unanswered questions, pending deliverables, or follow-ups mentioned?
  - **Tone & relationship signals**: Are they responsive? Enthusiastic? Pushing back on anything?
  - **Key people**: Who from their side is most active in email? Any new stakeholders?
  - **Pricing/commercial signals**: Any pricing discussions, budget mentions, or commercial terms?
  - **Objections/pushback**: Any concerns, hesitations, or resistance expressed in emails?
- Keep the summary concise — 3-5 bullet points per category.

If Gmail search returns no results or fails, proceed without email context — it's supplemental.

### Step 5: Generate the Brief

Run the full pipeline using `scripts/run_brief.py`. If email context was found in Step 4,
pass it via `--email-context-file`:

```bash
cd <INSTABRIEF_ROOT> && source venv/bin/activate && python skills/generate-brief/scripts/run_brief.py \
  --company "<COMPANY_NAME>" \
  --company-index <INDEX_IF_DISAMBIGUATION> \
  --attendees "<ATTENDEE_TEXT>" \
  --output-dir "<WORKSPACE_OUTPUT_DIR>" \
  --email-context-file "/tmp/email_context.txt"
```

If no email context was found, omit the `--email-context-file` flag.

This script runs the exact production pipeline:
1. **Company search** (`company_search.py`) — Claude Sonnet + web search for disambiguation
2. **Fathom search** (`fathom_search.py`) — searches past meeting transcripts by domain/title
3. **Brief generation** (`brief_generator.py`) — Claude Opus + web search + adaptive thinking
   with the full research prompt (why now, primary sources, LinkedIn signals, non-obvious pain,
   competitive benchmarking, AI posture, attendee research)
4. **Relationship context** (`fathom_search.py`) — if past meetings OR email context found,
   analyzes transcripts and emails for relationship history, stated pain points, objections,
   next steps. Email context adds a "Key Points from Email" row to relationship history and
   enriches next steps, objections, and what they're looking for.
5. **DOCX builder** (`docx_builder.py`) — formatted document with tables, attendee profiles,
   and either warm or cold brief layout

Steps 2-3 and step 4 run in parallel for speed. Email context (from Step 4) is passed into
both the brief generation and relationship context analysis.

The script prints a JSON result to stdout:
```json
{
  "company_name": "Company Name",
  "docx_path": "/path/to/Company_Name_InstaBrief.docx",
  "is_warm": true,
  "fathom_count": 3
}
```

If disambiguation is needed (multiple matches), it returns:
```json
{
  "needs_disambiguation": true,
  "matches": [{"name": "...", "parent": "...", "description": "..."}]
}
```
In that case, ask the user to pick and re-run with `--company-index`.

**Important**: This step takes 2-5 minutes because it does extensive web research via
Claude Opus. Set a generous timeout (at least 600 seconds) on the bash command.

### Step 6: Present the Brief

Once the DOCX is generated:
1. Copy it to the workspace output folder if not already there
2. Provide a download link to the user
3. Give a brief summary:
   - Company name and context (one sentence)
   - Whether it's a **warm brief** (has relationship history from past Fathom meetings)
     or a **cold brief** (research only)
   - How many past meetings were found (if warm)
4. If email context was found (Step 4), mention that email intelligence has been
   integrated into the brief's relationship history, next steps, objections, and
   best approach sections. The email insights are baked into the DOCX — no separate
   section needed.

## Brief Types

- **Cold brief**: Research only. Sections: Attendees → Client Profile → Core Pain Points →
  Highest-Impact Solutions → Best Approach → AI Insight
- **Warm brief**: Has past meeting data from Fathom. Sections: Attendees → Relationship History →
  Stated Pain Points → What They're Looking For → Next Steps → Key Objections →
  Client Profile → Best Approach → AI Insight

## Error Handling

- If Opus is overloaded (529), the script retries up to 4 times with exponential backoff
- If rate limited, it waits 60 seconds and retries
- If Fathom search fails, the brief falls back to cold (research only)
- If the entire pipeline fails, show the error to the user and suggest trying again

## Notes

- The research prompt positions InstaBrief as part of InstaLILY (Instalily), which builds
  agentic AI solutions for enterprises
- The brief JSON always has exactly 4 `core_pain_points` and 5 `highest_impact_solutions` (3 proven + 2 new)
- The DOCX uses navy/accent blue branding with Calibri font
