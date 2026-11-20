"""In-memory prototype. Amounts are integer minor units throughout."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from threading import RLock
from uuid import uuid4


@dataclass(frozen=True)
class Office:
    currency: str
    budget: int
    refill_cap: int
    typical_minimum: int


OFFICES = {
    "Oslo": Office("NOK", 600_000, 120_000, 30_000),
    "Bengaluru": Office("INR", 1_500_000, 300_000, 50_000),
}
LEASE = timedelta(hours=24)


class RuleError(ValueError):
    pass


@dataclass
class Refill:
    id: str
    office: str
    status: str = "empty"
    buyer: str | None = None
    deadline: datetime | None = None
    tried: set[str] = field(default_factory=set)
    month: str | None = None
    cap: int = 0
    amount: int = 0
    receipt: bytes = b""
    claim_id: str | None = None
    checkout_alerted: bool = False


class FakeChat:
    def __init__(self):
        self.messages = []

    def send(self, target, message):
        self.messages.append((target, message))


@dataclass(frozen=True)
class Claim:
    employee_id: str
    amount: int
    currency: str
    description: str
    receipt_image: bytes


class FakeHR:
    def __init__(self):
        self.claims = {}
        self.statuses = {}

    def submit(self, request_id, claim):
        existing = self.claims.setdefault(request_id, claim)
        if existing != claim:
            raise RuleError("Claim key reused with different data")
        self.statuses.setdefault(request_id, "submitted")
        return request_id

    def approve(self, claim_id):
        if self.statuses[claim_id] == "submitted":
            self.statuses[claim_id] = "approved"

    def pay(self, claim_id):
        if self.statuses[claim_id] not in {"approved", "reimbursed"}:
            raise RuleError("HR approval required")
        self.statuses[claim_id] = "reimbursed"

    def status(self, claim_id):
        return self.statuses[claim_id]


class SnackCounter:
    def __init__(self, chat, hr, office_clock):
        self.chat = chat
        self.hr = hr
        # Returns an aware datetime expressed in the requested office's local time.
        self.clock = office_clock
        self.ready = {office: set() for office in OFFICES}
        self.refills = {}
        self.active = {}
        self.lock = RLock()

    def set_ready(self, office, employee, available=True):
        """Represent the current on-site, opted-in roster, including visitors."""
        with self.lock:
            if available:
                self.ready[office].add(employee)
            else:
                self.ready[office].discard(employee)

    def report_empty(self, office):
        with self.lock:
            if office in self.active:
                return self.active[office]
            refill = Refill(uuid4().hex, office)
            self.refills[refill.id] = refill
            self.active[office] = refill.id
            self._offer(refill, self.clock(office))
            return refill.id

    def _purchases(self, office, month):
        return sum(r.amount for r in self.refills.values()
                   if r.office == office and r.month == month and r.receipt)

    def _offer(self, refill, now):
        office = refill.office
        month = now.date().isoformat()[:7]
        if month != refill.month:
            refill.tried.clear()
            refill.month = month
        policy = OFFICES[office]
        cap = min(policy.refill_cap, policy.budget - self._purchases(office, month))
        busy = {self.refills[key].buyer for key in self.active.values()}
        candidates = self.ready[office] - refill.tried - busy
        if cap < policy.typical_minimum or not candidates:
            self.chat.send(office, "Refill waiting for budget or an available volunteer")
            return

        def fairness(employee):
            bought = [r for r in self.refills.values() if r.buyer == employee and r.receipt]
            pending = sum(r.status != "reimbursed" for r in bought)
            return pending, len(bought), employee

        refill.buyer = min(candidates, key=fairness)
        refill.tried.add(refill.buyer)
        refill.month = month
        refill.cap = cap
        refill.deadline = now + LEASE
        refill.status = "offered"
        self.chat.send(refill.buyer, f"Refill {refill.id} at {office}. Cap {cap / 100:.2f} {policy.currency}.")

    def tick(self):
        with self.lock:
            for key in self.active.values():
                refill = self.refills[key]
                now = self.clock(refill.office)
                if refill.status in {"offered", "accepted"} and (
                    now >= refill.deadline or now.date().isoformat()[:7] != refill.month
                    or refill.buyer not in self.ready[refill.office]
                ):
                    self.chat.send(refill.buyer, f"Refill {key} assignment expired")
                    if now.date().isoformat()[:7] != refill.month:
                        refill.tried.clear()
                    refill.status = "empty"
                    refill.buyer = None
                    refill.cap = 0
                    refill.deadline = None
                if refill.status == "empty":
                    self._offer(refill, now)
                if refill.status == "checkout" and now >= refill.deadline and not refill.checkout_alerted:
                    self.chat.send(refill.office, f"Confirm payment status for stalled refill {key}")
                    refill.checkout_alerted = True

    def _require_lease(self, refill, employee, expected, now):
        if (refill.status != expected or refill.buyer != employee
                or now >= refill.deadline or now.date().isoformat()[:7] != refill.month
                or employee not in self.ready[refill.office]):
            raise RuleError("No current assignment for this action")

    def accept(self, refill_id, employee):
        with self.lock:
            refill = self.refills[refill_id]
            now = self.clock(refill.office)
            self._require_lease(refill, employee, "offered", now)
            refill.deadline = now + LEASE
            refill.status = "accepted"

    def authorize_checkout(self, refill_id, employee, amount, currency):
        with self.lock:
            refill = self.refills[refill_id]
            now = self.clock(refill.office)
            self._require_lease(refill, employee, "accepted", now)
            if (type(amount) is not int or not 0 < amount <= refill.cap
                    or currency != OFFICES[refill.office].currency):
                raise RuleError("Checkout must be within the cap and in office currency")
            refill.amount = amount
            refill.status = "checkout"
            refill.deadline = now + LEASE
            refill.checkout_alerted = False
            self.chat.send(employee, f"Pay now for refill {refill.id}, then upload the receipt")

    def release_unpaid_checkout(self, refill_id):
        """Office coordinator calls this only after confirming payment did not occur."""
        with self.lock:
            refill = self.refills[refill_id]
            if refill.status != "checkout":
                raise RuleError("No checkout to release")
            refill.status = "empty"
            refill.buyer = None
            refill.amount = 0
            refill.cap = 0
            refill.deadline = None
            self._offer(refill, self.clock(refill.office))

    def complete(self, refill_id, employee, receipt_image):
        """Confirm the counter was stocked and queue the receipt for HR."""
        with self.lock:
            refill = self.refills[refill_id]
            if employee != refill.buyer:
                raise RuleError("Only the checkout owner can upload the receipt")
            if refill.receipt:
                if receipt_image != refill.receipt:
                    raise RuleError("Receipt already recorded")
                return
            if refill.status != "checkout" or not isinstance(receipt_image, bytes) or not receipt_image:
                raise RuleError("Authorized checkout and receipt image required")
            refill.receipt = receipt_image
            refill.status = "claim_pending"
            del self.active[refill.office]

    def sync_hr(self, refill_id):
        with self.lock:
            refill = self.refills[refill_id]
            if refill.status == "claim_pending":
                claim = Claim(refill.buyer, refill.amount, OFFICES[refill.office].currency,
                              f"Snack counter refill in {refill.office}", refill.receipt)
                refill.claim_id = self.hr.submit(refill.id, claim)
                refill.status = "submitted"
            if refill.claim_id:
                status = self.hr.status(refill.claim_id)
                if status != refill.status:
                    self.chat.send(refill.buyer, f"Refill {refill.id} claim is {status}")
                    refill.status = status
            return refill.status

    def monthly_report(self, month, inr_to_nok):
        """Use the supplied finance rate (NOK per INR) and round once to a NOK minor unit."""
        if not isinstance(inr_to_nok, Decimal) or not inr_to_nok.is_finite() or inr_to_nok <= 0:
            raise RuleError("Expected a positive Decimal INR-to-NOK rate")
        with self.lock:
            by_office = {office: {"currency": policy.currency,
                                  "spent": self._purchases(office, month),
                                  "budget": policy.budget}
                         for office, policy in OFFICES.items()}
            total = by_office["Oslo"]["spent"] + Decimal(by_office["Bengaluru"]["spent"]) * inr_to_nok
            return {"month": month, "offices": by_office, "inr_to_nok": inr_to_nok,
                    "total_nok_minor": int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))}

