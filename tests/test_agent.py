import unittest

from agent import SimpleLoansPolicyEngine
from prompting import UNANSWERABLE_FALLBACK


class SupportAgentTests(unittest.TestCase):
    def test_status_flow_requests_identifier(self):
        agent = SimpleLoansPolicyEngine()
        first = agent.answer("What is my loan status?")
        self.assertIn("account identifier", first.lower())

        second = agent.answer("APP-123456")
        self.assertIn("same-day funding is never promised", second.lower())

    def test_payment_policy_mentions_no_prepayment_penalty(self):
        agent = SimpleLoansPolicyEngine()
        response = agent.answer("Can I pay early?")
        self.assertIn("no prepayment penalty", response.lower())

    def test_escalation_on_supervisor_request(self):
        agent = SimpleLoansPolicyEngine()
        response = agent.answer("I want a supervisor")
        self.assertIn("escalating", response.lower())

    def test_fallback_when_question_not_in_knowledgebase(self):
        agent = SimpleLoansPolicyEngine()
        response = agent.answer("Can you explain your mortgage refinance program?")
        self.assertEqual(response, UNANSWERABLE_FALLBACK)

    def test_followup_capture_after_unresolved_response(self):
        agent = SimpleLoansPolicyEngine()
        _ = agent.answer("What are your loan terms?")
        no_help = agent.answer("no")
        self.assertIn("which contact channel", no_help.lower())
        ask_time = agent.answer("phone")
        self.assertIn("what time works best", ask_time.lower())
        done = agent.answer("tomorrow morning")
        self.assertIn("human specialist", done.lower())


if __name__ == "__main__":
    unittest.main()
