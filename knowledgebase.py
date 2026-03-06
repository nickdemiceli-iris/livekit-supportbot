"""Simple Loans support knowledge base and fast local retrieval helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional


@dataclass(frozen=True)
class KnowledgeArticle:
    intent: str
    answer: str
    keywords: tuple[str, ...]


FAQ_ANSWERS = {
    "auto_equity_loan": (
        "An auto equity loan, also known as a car title loan or car equity loan, "
        "lets you borrow by using your vehicle equity as collateral."
    ),
    "what_makes_simple_loans_different": (
        "Simple Loans is a direct lender with no middlemen. We focus on getting "
        "you the most money as fast as possible while keeping the process simple."
    ),
    "credit_check": "No credit report is run.",
    "job_requirement": (
        "No, current employment is not required. You do need a source of income "
        "to support repayment, such as disability, retirement, unemployment, "
        "or another qualifying income source."
    ),
    "process_time": "The application process can take as little as 30 minutes.",
    "funding_methods": (
        "Funds can be sent by debit card, Zelle, PayPal, MoneyGram, wire, or ACH."
    ),
    "max_loan_amount": "Simple Loans can offer up to $25,000.",
    "fully_online": (
        "Yes, the full process can be completed online without going to an office."
    ),
}

LOAN_STATUS_AND_DISBURSEMENT = (
    "Standard disbursement is same day to one business day after final approval "
    "and required documents are complete. Timing can be delayed by bank holidays, "
    "incorrect bank details, or pending fraud-review checks. Same-day funding is "
    "never promised."
)

PAYMENT_POLICY = (
    "Monthly payments are due on the date listed in your agreement. If that date "
    "falls on a bank holiday, processing moves to the next business day. There is "
    "no prepayment penalty, so you can pay early without extra fees. Partial "
    "payments may reduce principal but do not automatically change the next due "
    "date unless servicing confirms a modified schedule."
)

LATE_AND_HARDSHIP_POLICY = (
    "If you expect a late payment, contact support before the due date whenever "
    "possible. Hardship review may be available case-by-case."
)

VDC_POLICY = (
    "Voluntary Debt Cancellation (VDC/DCA) is an optional fee-based add-on, not "
    "insurance, and not state-regulated. It may cancel all or part of a debt for "
    "qualifying events such as total loss or theft of collateral, death, or "
    "disability. If active, VDC charges appear in the disclosed payment estimate. "
    "Support can escalate VDC enrollment and eligibility review."
)

VEHICLE_AND_TITLE_POLICY = (
    "Required documentation typically includes a valid government ID, vehicle title "
    "information, and proof of address. If title ownership is not free and clear, "
    "the application may still be reviewed but additional lienholder details are "
    "required. A virtual vehicle inspection is often required before disbursement."
)

LOAN_TERMS = (
    "Loan terms include a $25.00 application fee if the loan is accepted, APR from "
    "18% to 35%, a flexible 12-month repayment schedule, and no prepayment penalty. "
    "Doc stamp tax is $0.35 per $100 borrowed and the registration government fee is "
    "$77.25. Lien holder fee and Florida doc stamp fees are included in your loan."
)

ESCALATION_KEYWORDS = {
    "fraud",
    "identity theft",
    "stolen identity",
    "legal threat",
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

KNOWLEDGE_ARTICLES: tuple[KnowledgeArticle, ...] = (
    KnowledgeArticle(
        intent="auto_equity_loan",
        answer=FAQ_ANSWERS["auto_equity_loan"],
        keywords=("auto equity", "car title", "title loan", "car equity", "collateral"),
    ),
    KnowledgeArticle(
        intent="what_makes_simple_loans_different",
        answer=FAQ_ANSWERS["what_makes_simple_loans_different"],
        keywords=("different", "middlemen", "direct lender", "so simple"),
    ),
    KnowledgeArticle(
        intent="credit_check",
        answer=FAQ_ANSWERS["credit_check"],
        keywords=("credit report", "credit check", "run credit"),
    ),
    KnowledgeArticle(
        intent="job_requirement",
        answer=FAQ_ANSWERS["job_requirement"],
        keywords=("job", "employed", "employment", "income source"),
    ),
    KnowledgeArticle(
        intent="process_time",
        answer=FAQ_ANSWERS["process_time"],
        keywords=("how long", "process take", "30 minutes", "approval speed"),
    ),
    KnowledgeArticle(
        intent="funding_methods",
        answer=FAQ_ANSWERS["funding_methods"],
        keywords=("zelle", "paypal", "moneygram", "wire", "ach", "debit card"),
    ),
    KnowledgeArticle(
        intent="max_loan_amount",
        answer=FAQ_ANSWERS["max_loan_amount"],
        keywords=("how much", "maximum", "max amount", "25000", "$25,000"),
    ),
    KnowledgeArticle(
        intent="fully_online",
        answer=FAQ_ANSWERS["fully_online"],
        keywords=("online", "office", "in person", "without office"),
    ),
    KnowledgeArticle(
        intent="loan_status_and_disbursement",
        answer=LOAN_STATUS_AND_DISBURSEMENT,
        keywords=("loan status", "disbursement", "funding time", "same day funding", "pending"),
    ),
    KnowledgeArticle(
        intent="payment_policy",
        answer=PAYMENT_POLICY,
        keywords=(
            "payment",
            "monthly payment",
            "due date",
            "bank holiday",
            "prepayment",
            "pay early",
            "partial payment",
        ),
    ),
    KnowledgeArticle(
        intent="late_and_hardship",
        answer=LATE_AND_HARDSHIP_POLICY,
        keywords=("late payment", "hardship", "cannot pay", "can't pay", "struggling"),
    ),
    KnowledgeArticle(
        intent="vdc_policy",
        answer=VDC_POLICY,
        keywords=("vdc", "dca", "debt cancellation", "optional protection"),
    ),
    KnowledgeArticle(
        intent="vehicle_and_title_docs",
        answer=VEHICLE_AND_TITLE_POLICY,
        keywords=("vehicle inspection", "title", "government id", "proof of address", "lienholder"),
    ),
    KnowledgeArticle(
        intent="loan_terms",
        answer=LOAN_TERMS,
        keywords=("loan terms", "loan details", "apr", "fees", "fee", "doc stamp", "registration", "12-month"),
    ),
)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def match_article(question: str) -> Optional[KnowledgeArticle]:
    """Return the best-matching knowledge article, or None when no match exists."""
    normalized = normalize_text(question)
    tokens = {token for token in re.findall(r"[a-z0-9$']+", normalized) if len(token) >= 3}
    best: Optional[KnowledgeArticle] = None
    best_score = 0.0

    for article in KNOWLEDGE_ARTICLES:
        score = 0.0
        for keyword in article.keywords:
            keyword_n = normalize_text(keyword)
            if keyword_n in normalized:
                score += 2.0
            keyword_tokens = {t for t in re.findall(r"[a-z0-9$']+", keyword_n) if len(t) >= 3}
            score += 0.9 * len(tokens.intersection(keyword_tokens))
        if score > best_score:
            best = article
            best_score = score

    return best if best_score >= 1.2 else None
