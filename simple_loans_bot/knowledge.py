"""Knowledge base and policy snippets for the Simple Loans bot."""

from __future__ import annotations

FAQ_ANSWERS = {
    "auto_equity_loan": (
        "An auto equity loan (also called a car title or car equity loan) lets you "
        "borrow using your vehicle equity as collateral."
    ),
    "what_makes_simple_loans_different": (
        "Simple Loans is a direct lender, so there are no middlemen. "
        "We focus on getting customers the most money possible, quickly, "
        "while keeping the process simple."
    ),
    "credit_check": "No credit report is run.",
    "job_requirement": (
        "Employment is not required. You do need a reliable source of income "
        "to support repayment (for example disability, retirement, unemployment, "
        "or other qualifying income)."
    ),
    "process_time": "The application process can take as little as 30 minutes.",
    "funding_methods": (
        "Funds can be sent by debit card, Zelle, PayPal, MoneyGram, wire, or ACH."
    ),
    "max_loan_amount": "Simple Loans can offer up to $25,000.",
    "fully_online": (
        "Yes. You can apply, be approved, and funded without visiting an office."
    ),
}

LOAN_STATUS_AND_DISBURSEMENT = (
    "Standard disbursement is same day to one business day after final approval "
    "and required documents are complete. Timing can be delayed by bank holidays, "
    "incorrect bank details, or pending fraud-review checks. Same-day funding is "
    "never promised."
)

PAYMENT_POLICY = (
    "Monthly payments are due on the date in the customer agreement. If the due "
    "date falls on a bank holiday, processing moves to the next business day. "
    "There is no prepayment penalty. Partial payments may reduce principal, but "
    "do not automatically change the next due date unless servicing confirms a "
    "modified schedule."
)

LATE_AND_HARDSHIP_POLICY = (
    "If you expect to pay late, contact support before the due date whenever "
    "possible. Hardship review may be available case-by-case."
)

VDC_POLICY = (
    "Voluntary Debt Cancellation (VDC/DCA) is an optional, fee-based add-on. "
    "It may cancel all or part of a debt for qualifying hardship events "
    "(such as total loss/theft of collateral, death, or disability). It is "
    "not insurance and is not state-regulated. If active, VDC charges are included "
    "in the disclosed payment estimate. Enrollment and eligibility can be reviewed "
    "through support escalation."
)

VEHICLE_AND_TITLE_POLICY = (
    "Required documents typically include a valid government ID, vehicle title "
    "information, and proof of address. If title ownership is not free and clear, "
    "the application may still be reviewed, but lienholder details are required. "
    "A virtual vehicle inspection is often required before final disbursement."
)

LOAN_TERMS = (
    "Key terms: $25 application fee if the loan is accepted, APRs from 18% to 35%, "
    "flexible 12-month repayment schedule, no prepayment penalty, doc stamp tax of "
    "$0.35 per $100 borrowed, and a $77.25 registration government fee. "
    "Lienholder and Florida doc stamp fees are included in the loan."
)

ESCALATION_KEYWORDS = {
    "fraud",
    "identity theft",
    "stolen identity",
    "legal",
    "lawyer",
    "attorney",
    "sue",
    "lawsuit",
    "supervisor",
    "human specialist",
    "real person",
    "manager",
}

STATUS_IDENTIFIER_KEYWORDS = {
    "account id",
    "account identifier",
    "application id",
    "loan id",
    "reference number",
}
