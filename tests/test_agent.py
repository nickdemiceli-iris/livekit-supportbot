import unittest

from agent import SimpleLoansSupportAgent


class SupportAgentTests(unittest.TestCase):
    def test_opening_disclosure_is_present(self):
        agent = SimpleLoansSupportAgent()
        response = agent.respond("Hi")
        self.assertIn("virtual support assistant", response.lower())

    def test_status_flow_requests_identifier(self):
        agent = SimpleLoansSupportAgent()
        first = agent.respond("What is my loan status?")
        self.assertIn("account identifier", first.lower())

        second = agent.respond("APP-123456")
        self.assertIn("same-day funding is never promised", second.lower())

    def test_payment_policy_mentions_no_prepayment_penalty(self):
        agent = SimpleLoansSupportAgent()
        response = agent.respond("Can I pay early?")
        self.assertIn("no prepayment penalty", response.lower())

    def test_escalation_on_supervisor_request(self):
        agent = SimpleLoansSupportAgent()
        response = agent.respond("I want a supervisor")
        self.assertIn("escalating", response.lower())

    def test_followup_channel_and_time_flow(self):
        agent = SimpleLoansSupportAgent(seed=1)
        _ = agent.respond("What are your loan terms?")
        no_help = agent.respond("no")
        self.assertIn("which contact channel", no_help.lower())
        ask_time = agent.respond("phone")
        self.assertIn("what time works best", ask_time.lower())
        done = agent.respond("tomorrow morning")
        self.assertIn("human specialist", done.lower())


if __name__ == "__main__":
    unittest.main()
