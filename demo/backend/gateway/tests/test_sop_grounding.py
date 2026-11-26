import json

from django.test import SimpleTestCase

from gateway.errors import HarnessError
from gateway.grounding import validated_sop_review


class SOPGroundingTests(SimpleTestCase):
    def test_applicable_review_preserves_requirements_and_exact_sources(self):
        value = {"sop_found": True, "context": "Verify pump dimensions and approval before purchasing.", "sources": ["maintenance.md"]}
        context, sources = validated_sop_review(json.dumps(value), "Source: maintenance.md. Inspection and approval are required.")
        self.assertEqual(context, value["context"])
        self.assertEqual(sources, ["maintenance.md"])

    def test_empty_irrelevant_or_invented_source_evidence_is_rejected(self):
        valid = {"sop_found": True, "context": "Check approval.", "sources": ["maintenance.md"]}
        cases = [(valid, ""), ({**valid, "sop_found": False}, "maintenance.md"),
                 ({**valid, "sources": ["invented-sop.md"]}, "maintenance.md"),
                 ({**valid, "sources": []}, "maintenance.md"), ({**valid, "context": ""}, "maintenance.md")]
        for value, evidence in cases:
            with self.assertRaises(HarnessError):
                validated_sop_review(json.dumps(value), evidence)

    def test_malformed_review_is_a_safe_error(self):
        with self.assertRaises(HarnessError) as caught:
            validated_sop_review("Bearer confidential-token", "maintenance.md")
        self.assertEqual(caught.exception.code, "sop_unavailable")
        self.assertNotIn("confidential-token", str(caught.exception))
