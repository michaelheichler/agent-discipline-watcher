"""Tests for the deterministic unproved-done rule."""
from __future__ import annotations

import unittest

import done_claims


class ClaimFiresTests(unittest.TestCase):
    def test_bare_all_done_fires(self):
        findings = done_claims.scan_done_claims("All done.", "msg.md")
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["family"], "clean_code")
        self.assertEqual(finding["rule"], "unproved_done_claim")
        self.assertEqual(finding["line"], 1)
        self.assertTrue(finding["action"])

    def test_is_fixed_fires(self):
        findings = done_claims.scan_done_claims("Everything is fixed now.", "msg.md")
        self.assertEqual(len(findings), 1)

    def test_all_tests_pass_claim_fires(self):
        findings = done_claims.scan_done_claims("All tests pass.", "msg.md")
        self.assertEqual(len(findings), 1)

    def test_tests_pass_claim_fires(self):
        findings = done_claims.scan_done_claims("Tests pass.", "msg.md")
        self.assertEqual(len(findings), 1)

    def test_transitive_fixed_fires(self):
        findings = done_claims.scan_done_claims("Fixed the parser.", "msg.md")
        self.assertEqual(len(findings), 1)

    def test_transitive_completed_fires(self):
        findings = done_claims.scan_done_claims("Completed the implementation.", "msg.md")
        self.assertEqual(len(findings), 1)

    def test_its_done_fires(self):
        findings = done_claims.scan_done_claims("It's done. Sending it over.", "msg.md")
        self.assertEqual(len(findings), 1)

    def test_contractions_do_not_swallow_the_claim(self):
        findings = done_claims.scan_done_claims("It's done. I'd send it now.", "msg.md")
        self.assertEqual(len(findings), 1)

    def test_claim_between_two_quoted_tokens_still_fires(self):
        findings = done_claims.scan_done_claims("'x' all done 'y'", "msg.md")
        self.assertEqual(len(findings), 1)

    def test_finding_snippet_comes_from_original_line(self):
        message = "I looked at the parser." + chr(10) + "Everything is fixed now."
        findings = done_claims.scan_done_claims(message, "msg.md")
        self.assertEqual(findings[0]["line"], 2)
        self.assertEqual(findings[0]["snippet"], "Everything is fixed now.")


class ClaimSuppressedByEvidenceTests(unittest.TestCase):
    def test_pytest_count_is_evidence(self):
        message = "Fixed the parser. 3 passed via pytest."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_exit_code_is_evidence(self):
        message = "The build is complete: exit code 0 on the full run."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_evidence_inside_fenced_output_counts(self):
        message = "Fixed." + chr(10) + "```" + chr(10) + "12 passed" + chr(10) + "```"
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_result_evidence_stands_despite_negated_mention(self):
        message = "Fixed the parser. 3 passed. I did not run the linter."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])


class MentionIsNeverEvidenceTests(unittest.TestCase):
    """Only a shown result suppresses; naming or claiming a run proves nothing."""

    def test_bare_runner_mention_fires(self):
        message = "All done. I ran pytest."
        self.assertEqual(len(done_claims.scan_done_claims(message, "msg.md")), 1)

    def test_ran_suite_mention_fires(self):
        message = "All done. I ran the full test suite after the change."
        self.assertEqual(len(done_claims.scan_done_claims(message, "msg.md")), 1)

    def test_negated_mentions_fire(self):
        phrasings = (
            "I did not run pytest.",
            "I didn't run pytest.",
            "I haven't run pytest yet.",
            "It hasn't run since the change.",
            "I never ran the suite.",
            "Ship it without running pytest.",
            "I am not running the checks.",
        )
        for phrasing in phrasings:
            message = "All done. " + phrasing
            with self.subTest(phrasing=phrasing):
                self.assertEqual(
                    len(done_claims.scan_done_claims(message, "msg.md")), 1
                )

    def test_negated_execute_mention_fires(self):
        message = "All done. I did not execute pytest."
        self.assertEqual(len(done_claims.scan_done_claims(message, "msg.md")), 1)

    def test_passed_count_suppresses(self):
        message = "All done. 238 passed."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_fenced_runner_output_suppresses(self):
        message = (
            "All done."
            + chr(10)
            + "```"
            + chr(10)
            + "tests/core_test.py ......"
            + chr(10)
            + "41 passed in 0.3s"
            + chr(10)
            + "```"
        )
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_blockquoted_evidence_does_not_count(self):
        message = "All done." + chr(10) + "> 12 passed in 0.4s"
        self.assertEqual(len(done_claims.scan_done_claims(message, "msg.md")), 1)


class QuotedTextDoesNotFireTests(unittest.TestCase):
    """The named over-firing risk: someone else's done claim is not the assistant's."""

    def test_double_quoted_user_claim_does_not_fire(self):
        message = 'The user wrote "all tests pass" in the ticket, so I rechecked.'
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_single_quoted_claim_does_not_fire(self):
        message = "The old log line 'tests are passing' predates my change."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_single_quoted_done_claim_does_not_fire(self):
        message = "The reviewer wrote 'it is done' in chat, so I rechecked."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_quoted_span_with_internal_contraction_does_not_fire(self):
        message = "The reviewer wrote 'It's done.' in chat, so I rechecked."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_boundary_possessive_quote_does_not_fire(self):
        message = "The reviewer wrote 'Chris' tests are passing.' in chat, so I rechecked."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_blockquoted_claim_does_not_fire(self):
        message = (
            "> Everything is fixed."
            + chr(10)
            + "That quote is from the report. I am still verifying."
        )
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_fenced_code_claim_does_not_fire(self):
        message = (
            "```"
            + chr(10)
            + "it is done"
            + chr(10)
            + "```"
            + chr(10)
            + "That sample is from the docs. Still checking."
        )
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_inline_code_claim_does_not_fire(self):
        message = "The fixture prints `all tests pass` but I have not rerun it."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])


class NoClaimTests(unittest.TestCase):
    def test_plain_status_passes(self):
        message = "I changed parser.py to handle empty input and added a case."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_contractions_alone_are_not_claims(self):
        message = "I'd hold off on that; it's late and the review is still open."
        self.assertEqual(done_claims.scan_done_claims(message, "msg.md"), [])

    def test_empty_message_passes(self):
        self.assertEqual(done_claims.scan_done_claims("", "msg.md"), [])
        self.assertEqual(done_claims.scan_done_claims("   " + chr(10), "msg.md"), [])


if __name__ == "__main__":
    unittest.main()
