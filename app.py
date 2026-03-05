"""CLI runner for the Simple Loans support bot."""

from simple_loans_bot import SimpleLoansSupportBot


def main() -> None:
    bot = SimpleLoansSupportBot()
    print("Simple Loans Support Chat")
    print("Type 'exit' to quit.\n")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Bot: Thanks for contacting Simple Loans support. Take care.")
            break
        if not user_input:
            print("Bot: Please send a message when you are ready.")
            continue
        print(f"Bot: {bot.respond(user_input)}")


if __name__ == "__main__":
    main()
