import json
from unittest.mock import patch

from django.test import SimpleTestCase

from gateway.catalog import AGENT_CATALOG
from gateway.review_text import ReviewDisplay, readable_review, review_record
from gateway.team_runtime import run_team, specialist_review

REVIEW = {
    "request": "Review an additional order for strawberry concentrate",
    "decision": "Do not place or modify an order",
    "verified_evidence": {"pricing": "USD 4.80 per kg", "quoted_quantity": "800 kg", "record_id": "DEMO-PR-101"},
    "not_verified": ["Available inventory", "Budget availability"],
    "recommendation": "Confirm the draft quotation before committing an order.",
    "next_required_inputs": ["Requested order quantity", "Delivery date"],
}


class ReviewTextTests(SimpleTestCase):
    def test_json_review_becomes_readable_text_without_losing_evidence(self):
        raw = json.dumps(REVIEW)
        rendered = readable_review(raw)
        self.assertIn("## Verified Evidence", rendered)
        self.assertIn("- **Pricing:** USD 4.80 per kg", rendered)
        self.assertIn("800 kg", rendered)
        self.assertIn("DEMO-PR-101", rendered)
        self.assertIn("- Available inventory", rendered)
        self.assertNotIn('"verified_evidence"', rendered)
        self.assertEqual(review_record(raw), REVIEW)

    def test_partial_json_never_leaks_into_streamed_chat(self):
        display = ReviewDisplay()
        raw = json.dumps(REVIEW)
        for part in [raw[:1], raw[1:17], raw[17:80], raw[80:]]:
            self.assertEqual(display.feed(part), "")
        self.assertEqual(display.finish(), readable_review(raw))
        self.assertEqual(display.record, REVIEW)

    def test_normal_prose_keeps_immediate_streaming(self):
        display = ReviewDisplay()
        self.assertEqual(display.feed("The quotation "), "The quotation ")
        self.assertEqual(display.feed("is draft."), "is draft.")
        self.assertEqual(display.finish(), "")
        self.assertEqual(display.text, "The quotation is draft.")

    def test_fenced_json_is_formatted_and_plain_markdown_is_preserved(self):
        raw = json.dumps(REVIEW)
        self.assertEqual(readable_review("```json\n" + raw + "\n```"), readable_review(raw))
        text = "## Review\n\nThe quotation is draft."
        self.assertEqual(readable_review(text), text)

    def test_specialist_chat_is_readable_and_artifact_retains_original_record(self):
        with patch("gateway.team_runtime.chat_completion", return_value={"role": "assistant", "content": json.dumps(REVIEW)}):
            events = list(specialist_review("Procurement Specialist", "Review quotation", {"request": "Review strawberry", "prior_artifacts": []}, []))
        text = "".join(event["delta"] for event in events if event["type"] == "subagent_message_delta")
        self.assertEqual(text, readable_review(json.dumps(REVIEW)))
        self.assertEqual(events[-1]["artifact"]["record"], REVIEW)

    def test_team_synthesis_formats_json_without_exposing_fragments(self):
        team = next(team for team in AGENT_CATALOG if team["agent_id"] == "fb-procurement-team")
        finding = {"subagent": "Procurement Specialist", "finding": "Quotation is draft.", "tool_calls": []}
        raw = json.dumps(REVIEW)
        with patch("gateway.team_runtime.select_specialists", return_value=[{"agent": "Procurement Specialist", "goal": "Review"}]), patch("gateway.team_runtime.specialist_review", return_value=iter([{"type": "subagent_completed", "artifact": finding}])), patch("gateway.team_runtime.chat_text_stream", return_value=iter([raw[:3], raw[3:50], raw[50:]])):
            events = list(run_team(team, {"request": "Review strawberry", "purpose": "Review quotation"}))
        deltas = [event["delta"] for event in events if event["type"] == "team_message_delta"]
        self.assertEqual(deltas, [readable_review(raw)])
        self.assertEqual(events[-1]["artifact"]["record"], REVIEW)
