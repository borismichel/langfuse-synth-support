"""The support knowledge base, and the re-index that broke it.

The seeded pool (`materialize.py`) *models* the regression statistically. This module is
the companion's **live** counterpart: a real (tiny) knowledge base and a real retrieval
function, so an SA can flip the index version in the browser and watch the same failure
happen in front of them rather than take the charts on faith.

The mechanism is deliberately honest — no magic "make it worse" multiplier:

* `kb-v1` indexes each article's **title plus its whole body**. A customer question
  usually shares most of its terms with some article, so coverage is high.
* `kb-v2` is the botched re-index: the pipeline dropped the title field, and a shifted
  chunk boundary orphaned each article's opening — the part that actually answers the
  question. Only the tail (everything past `V2_LEAD_DROPPED` tokens) made it into the
  index. Nothing errors: the search still returns its top-k, just worse ones.

Retrieval scores use the **overlap coefficient** (share of the query's terms covered by
the chunk) rather than Jaccard, so a long article is not penalised for being long and the
score stays a readable 0..1 "how much of what you asked did I find".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The shifted chunk boundary orphaned this many leading tokens of every article body —
# which is exactly where the answer usually lives.
V2_LEAD_DROPPED = 10

_STOPWORDS = frozenset(
    """a an and are as at be but by can do does for from get got has have how i if in is it
    my me not of on or our so that the their then there these they this to was we what when
    where which who why will with you your""".split()
)

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Article:
    id: str
    intent: str
    title: str
    body: str


KB: tuple[Article, ...] = (
    Article(
        "kb-101",
        "billing",
        "Refunds and duplicate charges",
        "If you were charged twice for the same order we refund the duplicate automatically "
        "within five business days. Refunds return to the original payment method. A pending "
        "authorisation is not a charge and drops off by itself.",
    ),
    Article(
        "kb-102",
        "billing",
        "Changing your plan or cancelling a subscription",
        "You can upgrade, downgrade, or cancel a subscription at any time from Settings, "
        "Billing. Downgrades take effect at the end of the current billing period and we "
        "prorate the difference on the next invoice.",
    ),
    Article(
        "kb-103",
        "billing",
        "Understanding your invoice",
        "Invoices list a base subscription line plus any metered usage for the period. VAT is "
        "applied according to the billing address on file. Historic invoices are downloadable "
        "as PDF for the last 24 months.",
    ),
    Article(
        "kb-201",
        "technical",
        "Resetting a password and recovering access",
        "Use the forgotten password link on the sign-in page to receive a reset email. The "
        "link expires after one hour. If the email never arrives check the spam folder and "
        "confirm the address matches the one on the account.",
    ),
    Article(
        "kb-202",
        "technical",
        "The app is slow or will not load",
        "Most loading problems clear after a hard refresh and a cache clear. If a page still "
        "hangs, disable browser extensions and retry, then report the request id shown on the "
        "error screen so we can trace it.",
    ),
    Article(
        "kb-203",
        "technical",
        "Two-factor authentication and recovery codes",
        "Two-factor authentication can be enabled from the security page. Store the recovery "
        "codes somewhere safe: without them, losing the authenticator device requires an "
        "identity check before we can restore access.",
    ),
    Article(
        "kb-301",
        "account",
        "Updating your email address or account details",
        "Account owners can change the primary email from the profile page. We send a "
        "confirmation to both the old and the new address, and the change applies once the "
        "new address is confirmed.",
    ),
    Article(
        "kb-302",
        "account",
        "Deleting an account and exporting your data",
        "Request deletion from the privacy page. We export your data as a downloadable "
        "archive first, then remove the account after a fourteen day grace period during "
        "which you can still cancel the request.",
    ),
    Article(
        "kb-401",
        "shipping",
        "Where is my order and how do I track it",
        "Tracking activates once the carrier scans the parcel, usually within a day of "
        "dispatch. Standard delivery takes three to five working days; a parcel is only "
        "declared lost after ten working days.",
    ),
    Article(
        "kb-402",
        "shipping",
        "Returns, exchanges and damaged parcels",
        "You can return an unused item within thirty days using the returns portal. For a "
        "damaged parcel send a photograph with the order number and we ship a replacement "
        "without waiting for the return.",
    ),
)

INDEX_VERSIONS = ("kb-v1", "kb-v2")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric terms, minus stopwords. Order-preserving."""
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def _indexed_terms(article: Article, index_version: str) -> set[str]:
    """The terms actually searchable for this article under the given index."""
    if index_version == "kb-v2":
        # The re-index dropped titles, and the shifted boundary orphaned the opening.
        return set(tokenize(article.body)[V2_LEAD_DROPPED:])
    return set(tokenize(f"{article.title} {article.body}"))


@dataclass(frozen=True)
class Hit:
    article: Article
    score: float

    @property
    def snippet(self) -> str:
        return self.article.body[:160] + ("…" if len(self.article.body) > 160 else "")


def search(query: str, *, index_version: str = "kb-v1", top_k: int = 3) -> list[Hit]:
    """Top-`top_k` articles for `query`, scored by term coverage under `index_version`.

    Ties break on article id so the same query always returns the same ordering — the
    companion is not under the determinism gate, but a demo that reshuffles between two
    identical clicks is a demo that invites the wrong question.
    """
    if index_version not in INDEX_VERSIONS:
        raise ValueError(f"unknown index version {index_version!r}; expected one of {INDEX_VERSIONS}")

    terms = set(tokenize(query))
    if not terms:
        return []

    hits = [
        Hit(article, len(terms & _indexed_terms(article, index_version)) / len(terms))
        for article in KB
    ]
    hits.sort(key=lambda h: (-h.score, h.article.id))
    return hits[:top_k]
