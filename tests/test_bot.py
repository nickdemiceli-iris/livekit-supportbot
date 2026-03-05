import unittest

from simple_loans_bot import SimpleLoansSupportBot


class SupportBotTests(unittest.TestCase):
    def test_opening_disclosure_is_present(self):
        bot = SimpleLoansSupportBot()
        response = bot.respond("Hi")
        self.assertIn("virtual support assistant", response.lower())

    def test_status_flow_requests_identifier(self):
        bot = SimpleLoansSupportBot()
        first = bot.respond("What is my loan status?")
        self.assertIn("account identifier", first.lower())

        second = bot.respond("APP-123456")
        self.assertIn("same-day funding is never promised", second.lower())

    def test_payment_policy_mentions_no_prepayment_penalty(self):
        bot = SimpleLoansSupportBot()
        response = bot.respond("Can I pay early?")
        self.assertIn("no prepayment penalty", response.lower())

    def test_escalation_on_supervisor_request(self):
        bot = SimpleLoansSupportBot()
        response = bot.respond("I want a supervisor")
        self.assertIn("escalating", response.lower())

    def test_followup_channel_and_time_flow(self):
        bot = SimpleLoansSupportBot(seed=1)
        _ = bot.respond("What are your loan terms?")
        no_help = bot.respond("no")
        self.assertIn("which contact channel", no_help.lower())
        ask_time = bot.respond("phone")
        self.assertIn("what time works best", ask_time.lower())
        done = bot.respond("tomorrow morning")
        self.assertIn("human specialist", done.lower())


if __name__ == "__main__":
    unittest.main()
