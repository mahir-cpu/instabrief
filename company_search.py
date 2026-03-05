import json
import anthropic

client = anthropic.Anthropic()


def search_companies(query: str) -> list[dict]:
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": f"""Search the web for the company "{query}" and identify up to 5 possible matches.
For each, determine:
- The full company name
- The parent company or PE owner (if any)
- A one-sentence description (what they do, HQ, approximate size)

Return ONLY a JSON array. No markdown fences, no explanation, no preamble.
[
  {{
    "name": "Full Company Name",
    "parent": "Parent or PE owner, or empty string",
    "description": "One sentence description"
  }}
]

If the company name is completely unambiguous (only one real match), return a single-item array.
ONLY return valid JSON."""
        }],
    )

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
        results = json.loads(text)
        if isinstance(results, list):
            return results[:5]
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])[:5]
            except json.JSONDecodeError:
                pass

    return []
