"""
Standalone brief runner — wraps the existing InstaBrief Python modules
to generate a brief from the command line.

Usage:
    python scripts/run_brief.py --company "eShipping" [--attendees "John Doe, john@example.com"]

Outputs:
    - Prints JSON result to stdout with keys: company_name, docx_path, is_warm, fathom_count
    - The DOCX file is written to the specified output directory (or current dir)

Environment:
    Requires .env file in the InstaBrief root with ANTHROPIC_API_KEY and FATHOM_API_KEY.
    Must be run from the InstaBrief root directory (or have it on PYTHONPATH).
"""

import os
import sys
import json
import argparse
import threading

# Add InstaBrief root to path (3 levels up: scripts/ -> generate-brief/ -> skills/ -> InstaBrief/)
INSTABRIEF_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, INSTABRIEF_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(INSTABRIEF_ROOT, ".env"))

from company_search import search_companies
from fathom_search import search_fathom_for_company, generate_relationship_context
from brief_generator import generate_brief
from docx_builder import build_docx


def run(company_query, attendee_text="", output_dir=None, email_context=""):
    """
    Run the full brief generation pipeline.

    Args:
        company_query: Company name to search for
        attendee_text: Optional attendee info (name, email per line)
        output_dir: Where to save the DOCX (defaults to current dir)
        email_context: Optional summarized email threads for enrichment

    Returns:
        dict with company_name, docx_path, is_warm, fathom_count, matches
    """
    # Step 1: Search for company matches
    print("Searching for company: " + company_query + "...", file=sys.stderr)
    matches = search_companies(company_query)

    if not matches:
        return {"error": "No companies found matching '" + company_query + "'"}

    # Return matches for disambiguation if multiple
    if len(matches) > 1:
        return {
            "needs_disambiguation": True,
            "matches": matches,
        }

    # Single match — proceed
    company = matches[0]
    return generate_for_company(company, attendee_text, output_dir, email_context=email_context)


def generate_for_company(company, attendee_text="", output_dir=None, email_context=""):
    """
    Generate brief for a specific company dict (after disambiguation).

    Args:
        company: dict with name, parent, description
        attendee_text: Optional attendee info
        output_dir: Where to save the DOCX
        email_context: Optional summarized email threads for enrichment

    Returns:
        dict with company_name, docx_path, is_warm, fathom_count
    """
    company_name = company["name"]
    parent_context = company.get("parent", "")

    print("Generating brief for: " + company_name, file=sys.stderr)

    # Parse attendee emails/names from text
    attendee_emails = []
    attendee_names = []
    if attendee_text:
        for line in attendee_text.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                attendee_names.append(parts[0])
                attendee_emails.append(parts[1])
            elif len(parts) == 1 and "@" in parts[0]:
                attendee_emails.append(parts[0])
            elif len(parts) == 1:
                attendee_names.append(parts[0])

    # Step 2: Fathom search + Brief generation in parallel
    results = {
        "fathom_meetings": None,
        "relationship_context": None,
        "brief_data": None,
        "fathom_error": None,
        "brief_error": None,
    }

    def fathom_work():
        try:
            print("  Searching Fathom for past meetings...", file=sys.stderr)
            fathom_meetings = search_fathom_for_company(
                company_name,
                attendee_emails if attendee_emails else None,
            )
            if fathom_meetings:
                results["fathom_meetings"] = fathom_meetings
                print("  Found " + str(len(fathom_meetings)) + " past meeting(s)", file=sys.stderr)
            else:
                print("  No past meetings found", file=sys.stderr)

            # Generate relationship context if we have Fathom meetings OR email context
            if fathom_meetings or email_context:
                results["relationship_context"] = generate_relationship_context(
                    company_name,
                    fathom_meetings,
                    attendee_names if attendee_names else None,
                    email_context=email_context,
                )
        except Exception as e:
            results["fathom_error"] = str(e)
            print("  Fathom search failed: " + str(e), file=sys.stderr)

    def brief_work():
        try:
            print("  Generating research brief (Opus + web search)...", file=sys.stderr)
            results["brief_data"] = generate_brief(
                company_name=company_name,
                parent_context=parent_context,
                attendees=attendee_text,
                email_context=email_context,
            )
            print("  Brief generation complete", file=sys.stderr)
        except Exception as e:
            results["brief_error"] = str(e)
            print("  Brief generation failed: " + str(e), file=sys.stderr)

    t_fathom = threading.Thread(target=fathom_work)
    t_brief = threading.Thread(target=brief_work)
    t_fathom.start()
    t_brief.start()
    t_fathom.join()
    t_brief.join()

    if results["brief_data"] is None:
        return {"error": "Brief generation failed: " + (results["brief_error"] or "Unknown error")}

    brief_data = results["brief_data"]

    # Merge relationship context if available
    relationship_context = results["relationship_context"]
    fathom_count = len(results["fathom_meetings"]) if results["fathom_meetings"] else 0

    if relationship_context:
        brief_data["relationship_history"] = relationship_context.get("relationship_history", [])
        brief_data["stated_pain_points"] = relationship_context.get("stated_pain_points", [])
        brief_data["what_theyre_looking_for"] = relationship_context.get("what_theyre_looking_for", "")
        brief_data["next_steps_detailed"] = relationship_context.get("next_steps_detailed", [])
        brief_data["objections_detailed"] = relationship_context.get("objections_detailed", [])
        brief_data["best_approach_warm"] = relationship_context.get("best_approach_warm", "")
        attendee_ctx = relationship_context.get("attendee_context", {})
        for att in brief_data.get("meeting_attendees", []):
            name = att.get("name", "")
            if name in attendee_ctx:
                att["past_call_context"] = attendee_ctx[name]

    is_warm = bool(brief_data.get("stated_pain_points"))

    # Build DOCX
    print("  Building DOCX...", file=sys.stderr)
    docx_path = build_docx(brief_data)

    # Move to output dir if specified
    if output_dir:
        import shutil
        safe_name = company_name.replace(" ", "_").replace("/", "-")
        dest = os.path.join(output_dir, safe_name + "_InstaBrief.docx")
        shutil.move(docx_path, dest)
        docx_path = dest

    print("  Done: " + docx_path, file=sys.stderr)

    return {
        "company_name": company_name,
        "docx_path": docx_path,
        "is_warm": is_warm,
        "fathom_count": fathom_count,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate an InstaBrief")
    parser.add_argument("--company", required=True, help="Company name to research")
    parser.add_argument("--attendees", default="", help="Attendee info (name, email per line)")
    parser.add_argument("--output-dir", default=None, help="Directory to save DOCX")
    parser.add_argument("--company-index", type=int, default=None,
                        help="If disambiguation needed, pick this index (0-based)")
    parser.add_argument("--email-context", default="", help="Summarized email threads for enrichment")
    parser.add_argument("--email-context-file", default=None,
                        help="Path to a file containing email context (alternative to --email-context)")
    args = parser.parse_args()

    # Load email context from file if specified (useful for large summaries)
    email_ctx = args.email_context
    if args.email_context_file:
        with open(args.email_context_file, "r") as f:
            email_ctx = f.read()

    result = run(args.company, args.attendees, args.output_dir, email_context=email_ctx)

    if result.get("needs_disambiguation"):
        if args.company_index is not None:
            idx = args.company_index
            if 0 <= idx < len(result["matches"]):
                result = generate_for_company(
                    result["matches"][idx], args.attendees, args.output_dir,
                    email_context=email_ctx,
                )
            else:
                result = {"error": "Invalid index " + str(idx)}
        else:
            # Print matches and exit — caller must re-run with --company-index
            pass

    print(json.dumps(result, indent=2))
