# Relationship Context Prompt

When past Fathom meetings are found, use this prompt to generate relationship context
from the transcripts. This turns a "cold" brief into a "warm" brief.

## System Setup

Use `claude-sonnet-4-5-20250929` with max_tokens=8000.

## User Message Template

```
Based on these past meeting transcripts with {company_name}:

{meetings_context}

{attendee_hint}

Generate the following as a JSON object. Number meetings starting from 1.

{
  "relationship_history": [
    {
      "meeting_label": "Meeting 1: [short description]",
      "meeting_date": "Mar 5, 2026",
      "key_highlights": [
        "Concise, declarative highlight. No filler.",
        "Concise, declarative highlight. No filler."
      ],
      "outcome": "1 sentence: what was decided, agreed, or demonstrated.",
      "next_steps_list": [
        "Owner: action item (done if completed by a later meeting)",
        "Owner: action item"
      ]
    }
  ],
  "attendee_context": {
    "Person Name": "1 sentence on how to approach them based on past calls"
  },
  "stated_pain_points": [
    {
      "pain_point": "The problem in their words",
      "who_stated": "Who brought it up",
      "meeting": "Which meeting",
      "detail": "1-2 sentences of specific context -- numbers, systems, frustrations they mentioned. These must be things THEY said, not inferred."
    }
  ],
  "what_theyre_looking_for": "One paragraph describing what this company actually wants from us based on everything said across all meetings. Not what we think they need -- what THEY said they need. What problems did they bring to us? What outcomes did they describe wanting? What did they get excited about? If they described their ideal solution, capture that vision in their language. Include any constraints they mentioned -- budget, timeline, systems it needs to work with, internal approvals needed.",
  "next_steps_detailed": [
    {
      "action": "Owner: what specifically needs to happen",
      "owner": "InstaLILY or client name",
      "context": "Which meeting and who requested it",
      "deadline": "Any timeline mentioned, or No deadline discussed"
    }
  ],
  "objections_detailed": [
    {
      "objection": "The specific concern in their words",
      "raised_by": "Who said it",
      "meeting": "Which meeting",
      "type": "Technical / Commercial / Organizational / Competitive",
      "severity": "Passing concern / Moderate pushback / Potential dealbreaker",
      "status": "Addressed / Partially addressed / Still open",
      "our_response": "How we responded, or Not yet addressed",
      "prep_needed": "If still open, what should we prepare to address it next meeting"
    }
  ],
  "best_approach_warm": "One paragraph grounded entirely in what happened in past meetings. Mirror the language THEY used to describe their problems. Lead with whichever solution or topic got the strongest positive reaction. Call out what to explicitly AVOID based on any pushback. Identify who is the champion and who is the skeptic and how to navigate that. End with what they said they need to see to move forward."
}
```

## Style Rules (include in prompt)

```
STYLE RULES:
- No filler words, no timestamps, no dialogue quotes
- Clean, declarative language. Every word earns its place.
- Focus on outcomes, clarity, and forward motion.

KEY HIGHLIGHTS RULES:
- Exactly 2 per meeting, concise, no filler
- Focus on: key insights uncovered, decisions made, alignments reached, confirmed goals or timelines, blockers removed or areas clarified
- Only things that moved the deal forward -- not generic summaries

NEXT STEPS LIST RULES (per meeting):
- 2-3 per meeting
- Each must start with the owner: 'InstaLILY: action' or 'ClientName: action' or 'PersonName: action'
- If a next step from an earlier meeting was completed by a later meeting, mark it (done)
- Clean and declarative, no hedging

NEXT STEPS DETAILED RULES:
- 3-5 items total across all meetings
- PRIORITIZE based on the most recent meeting (Meeting {N}). Most recent meeting's next steps come first and carry the most weight. Earlier meetings' next steps only if still relevant and not superseded.
- Each action must start with the owner
- If completed, mark (done) and deprioritize
- Focus on outcomes, clarity, and forward motion

OBJECTIONS RULES:
- Every meaningful objection, categorized by type
- prep_needed is critical: if an objection is still open, clearly state what we should prepare for the next meeting

- stated_pain_points: exactly 3, from their mouths, not inferred
- Return ONLY valid JSON.
```

## Building the Meetings Context

For each past meeting, format as:

```
MEETING {i} - {title} ({date}):
Summary: {summary}
Transcript:
{transcript}
```

## Attendee Hint

If attendee names are provided:
```
Key attendees to look for context on: {comma-separated names}
```

## Merging into Brief

After generating relationship context, merge these fields into the brief data:
- `relationship_history`
- `stated_pain_points`
- `what_theyre_looking_for`
- `next_steps_detailed`
- `objections_detailed`
- `best_approach_warm`
- For each attendee in `meeting_attendees`, if their name appears in `attendee_context`,
  add the value as `past_call_context` on that attendee object.
