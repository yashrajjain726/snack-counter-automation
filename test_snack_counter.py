import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from snack_counter import FakeChat, FakeHR, RuleError, SnackCounter


class SnackCounterTests(unittest.TestCase):
    def setUp(self):
        self.now = {
            "Oslo": datetime(2026, 11, 27, 10, tzinfo=timezone(timedelta(hours=1))),
            "Bengaluru": datetime(2026, 11, 27, 14, 30,
                                  tzinfo=timezone(timedelta(hours=5, minutes=30))),
        }
        self.chat = FakeChat()
        self.hr = FakeHR()
        self.counter = SnackCounter(self.chat, self.hr, self.now.__getitem__)
        self.counter.set_ready("Oslo", "alice")
        self.counter.set_ready("Oslo", "bo")
        self.counter.set_ready("Bengaluru", "chandra")

    def purchase(self, office, amount, currency):
        key = self.counter.report_empty(office)
        employee = self.counter.refills[key].buyer
        self.counter.accept(key, employee)
        self.counter.authorize_checkout(key, employee, amount, currency)
        self.counter.complete(key, employee, b"simulated receipt")
        return key

    def test_duplicate_empty_reports_and_concurrent_accepts(self):
        with ThreadPoolExecutor(2) as pool:
            first, second = pool.map(self.counter.report_empty, ["Oslo", "Oslo"])
        self.assertEqual(first, second)

        def try_accept(employee):
            try:
                self.counter.accept(first, employee)
            except RuleError:
                return False
            return True

        with ThreadPoolExecutor(3) as pool:
            self.assertEqual(sum(pool.map(try_accept, ["alice", "alice", "bo"])), 1)
        self.assertEqual(self.counter.refills[first].buyer, "alice")

    def test_expired_accepted_assignment_hands_off(self):
        key = self.counter.report_empty("Oslo")
        self.counter.accept(key, "alice")
        self.now["Oslo"] += timedelta(hours=24)
        self.counter.tick()
        with self.assertRaises(RuleError):
            self.counter.authorize_checkout(key, "alice", 30_000, "NOK")
        self.counter.accept(key, "bo")
        self.assertEqual(self.counter.refills[key].buyer, "bo")

    def test_stalled_checkout_requires_payment_resolution(self):
        key = self.counter.report_empty("Oslo")
        self.counter.accept(key, "alice")
        self.counter.authorize_checkout(key, "alice", 30_000, "NOK")
        self.now["Oslo"] += timedelta(hours=25)
        self.counter.tick()
        self.assertEqual(self.counter.refills[key].buyer, "alice")
        self.assertIn("Confirm payment status", self.chat.messages[-1][1])
        self.counter.release_unpaid_checkout(key)
        self.assertEqual(self.counter.refills[key].buyer, "bo")
        with self.assertRaises(RuleError):
            self.counter.complete(key, "alice", b"old receipt")

    def test_budget_limits_and_consolidated_reporting(self):
        for _ in range(5):
            self.purchase("Oslo", 120_000, "NOK")
        self.purchase("Bengaluru", 250_000, "INR")
        key = self.counter.report_empty("Oslo")
        self.assertEqual(self.counter.refills[key].status, "empty")
        report = self.counter.monthly_report("2026-11", Decimal("0.12"))
        self.assertEqual(report["offices"]["Oslo"]["spent"], 600_000)
        self.assertEqual(report["offices"]["Bengaluru"]["spent"], 250_000)
        self.assertEqual(report["total_nok_minor"], 630_000)
        self.now["Oslo"] += timedelta(days=4)
        self.counter.tick()
        self.assertEqual(self.counter.refills[key].cap, 120_000)

    def test_invalid_currency_and_partial_remaining_budget(self):
        for _ in range(4):
            self.purchase("Oslo", 120_000, "NOK")
        self.purchase("Oslo", 60_000, "NOK")
        key = self.counter.report_empty("Oslo")
        buyer = self.counter.refills[key].buyer
        self.counter.accept(key, buyer)
        for amount, currency in [(60_001, "NOK"), (50_000, "INR"), (0, "NOK")]:
            with self.assertRaises(RuleError):
                self.counter.authorize_checkout(key, buyer, amount, currency)
        self.counter.authorize_checkout(key, buyer, 60_000, "NOK")

    def test_prefers_volunteer_with_fewer_pending_claims_and_accepts_visitors(self):
        key = self.purchase("Oslo", 45_000, "NOK")
        self.assertEqual(self.counter.refills[key].buyer, "alice")
        self.counter.set_ready("Oslo", "bo", False)
        self.counter.set_ready("Oslo", "chandra")
        next_key = self.counter.report_empty("Oslo")
        self.assertEqual(self.counter.refills[next_key].buyer, "chandra")

    def test_hr_retry_after_lost_response_and_paid_status(self):
        class LoseFirstResponse(FakeHR):
            def submit(self, request_id, claim):
                existed = request_id in self.claims
                claim_id = super().submit(request_id, claim)
                if not existed:
                    raise TimeoutError("Response lost after HR accepted claim")
                return claim_id

        self.hr = self.counter.hr = LoseFirstResponse()
        key = self.purchase("Bengaluru", 85_000, "INR")
        with self.assertRaises(TimeoutError):
            self.counter.sync_hr(key)
        self.counter.complete(key, "chandra", b"simulated receipt")
        self.assertEqual(self.counter.sync_hr(key), "submitted")
        self.assertEqual(len(self.hr.claims), 1)
        self.assertEqual(self.hr.claims[key].currency, "INR")
        self.assertEqual(self.hr.claims[key].employee_id, "chandra")
        self.hr.approve(key)
        self.assertEqual(self.counter.sync_hr(key), "approved")
        self.hr.pay(key)
        self.assertEqual(self.counter.sync_hr(key), "reimbursed")


if __name__ == "__main__":
    unittest.main()

