"""Тесты бизнес-правил и контрольных значений."""

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledger.engine import build_report
from ledger.loader import load_dataset
from ledger.models import (
    Contract,
    Dataset,
    Payment,
    WORK_ACCEPTED,
    WORK_CANCELLED,
    WORK_NOT_ACCEPTED,
    Work,
)

ROOT = Path(__file__).resolve().parents[1]
D = Decimal


def contract(cid="C-1", amount="1000.00", signed=date(2026, 1, 1)):
    return Contract(cid, "Подрядчик", D(amount), signed)


def work(
    wid,
    price,
    status="planned",
    completed=None,
    cancelled=None,
    cid="C-1",
):
    return Work(wid, cid, f"Работа {wid}", D(price), status, completed, cancelled)


def payment(
    pid,
    amount,
    work_id=None,
    status="paid",
    created=date(2026, 1, 1),
    paid=date(2026, 1, 2),
    refunded=None,
    cid="C-1",
):
    return Payment(
        pid,
        cid,
        work_id,
        "Назначение",
        D(amount),
        status,
        created,
        paid,
        refunded,
    )


def make_report(contracts, works, payments, as_of=date(2026, 1, 3)):
    return build_report(Dataset(contracts, works, payments), as_of)


def contract_map(reports):
    return {r.contract.contract_id: r for r in reports}


def work_map(reports):
    return {r.work.work_id: r for r in reports}


def payment_map(reports):
    return {r.payment.payment_id: r for r in reports}


class ActualDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(ROOT / "data")
        cls.report = build_report(cls.dataset, date(2026, 11, 10))
        cls.contracts = contract_map(cls.report.contracts)
        cls.works = work_map(cls.report.works)
        cls.payments = payment_map(cls.report.payments)

    def c(self, cid):
        return self.contracts[cid]

    def w(self, wid):
        return self.works[wid]

    def p(self, pid):
        return self.payments[pid]

    def test_contract_control_totals(self):
        d1 = self.c("D-1")
        d2 = self.c("D-2")
        self.assertEqual(d1.paid_total, D("315000.00"))
        self.assertEqual(d1.remaining, D("185000.00"))
        self.assertEqual(d1.cancelled_total, D("100000.00"))
        self.assertEqual(d1.active_works_total, D("500000.00"))
        self.assertEqual(d1.queued, D("150000.00"))
        self.assertEqual(d1.remaining_after_queued, D("35000.00"))
        self.assertEqual(d1.paid_direct, D("15000.00"))
        self.assertEqual(d1.paid_general, D("300000.00"))
        self.assertEqual(d1.paid_active_applied, D("315000.00"))
        self.assertEqual(d1.work_overpayment, D("0.00"))
        self.assertEqual(d1.unallocated, D("0.00"))
        self.assertEqual(d1.overpayment, D("0.00"))

        self.assertEqual(d2.paid_total, D("75000.00"))
        self.assertEqual(d2.remaining, D("15000.00"))
        self.assertEqual(d2.future, D("20000.00"))
        self.assertEqual(d2.paid_active_applied, D("75000.00"))
        self.assertEqual(d2.work_overpayment, D("0.00"))
        self.assertEqual(d2.overpayment, D("0.00"))

        for c in self.report.contracts:
            self.assertEqual(
                c.paid_total,
                c.paid_active_applied + c.work_overpayment + c.unallocated,
            )
            self.assertEqual(c.overpayment, c.work_overpayment + c.unallocated)

        total_paid = sum((c.paid_total for c in self.report.contracts), D("0.00"))
        total_remaining = sum((c.remaining for c in self.report.contracts), D("0.00"))
        self.assertEqual(total_paid, D("390000.00"))
        self.assertEqual(total_remaining, D("200000.00"))

    def test_payment_buckets(self):
        self.assertEqual(self.p("P-1").bucket, "paid")
        self.assertEqual(self.p("P-2").bucket, "refunded")
        self.assertEqual(self.p("P-2").net_paid, D("0.00"))
        self.assertEqual(self.p("P-3").bucket, "paid")
        self.assertEqual(self.p("P-4").bucket, "queued")
        self.assertEqual(self.p("P-4").net_paid, D("0.00"))
        self.assertEqual(self.p("P-5").bucket, "paid")
        self.assertEqual(self.p("P-6").bucket, "paid")
        self.assertEqual(self.p("P-7").bucket, "paid")
        self.assertEqual(self.p("P-8").bucket, "future")
        self.assertEqual(self.p("P-8").net_paid, D("0.00"))

    def test_work_allocation(self):
        self.assertEqual(self.w("W-11").paid_total, D("100000.00"))
        self.assertEqual(self.w("W-12").paid_total, D("100000.00"))
        self.assertEqual(self.w("W-13").state, WORK_CANCELLED)
        self.assertEqual(self.w("W-13").paid_total, D("0.00"))
        self.assertEqual(self.w("W-13").remaining, D("0.00"))
        self.assertEqual(self.w("W-14").paid_direct, D("15000.00"))
        self.assertEqual(self.w("W-14").paid_general, D("85000.00"))
        self.assertEqual(self.w("W-14").paid_total, D("100000.00"))
        self.assertEqual(self.w("W-14").remaining, D("0.00"))
        self.assertEqual(self.w("W-15").paid_total, D("15000.00"))
        self.assertEqual(self.w("W-15").remaining, D("85000.00"))
        self.assertEqual(self.w("W-16").paid_total, D("0.00"))
        self.assertEqual(self.w("W-16").remaining, D("100000.00"))
        self.assertEqual(self.w("W-21").paid_total, D("20000.00"))
        self.assertEqual(self.w("W-22").paid_total, D("30000.00"))
        self.assertEqual(self.w("W-23").paid_total, D("25000.00"))
        self.assertEqual(self.w("W-23").remaining, D("15000.00"))

    def test_w23_not_accepted_on_report_date(self):
        self.assertEqual(self.w("W-23").state, WORK_NOT_ACCEPTED)
        self.assertEqual(self.w("W-23").work.completed_at, date(2026, 11, 11))

    def test_w23_accepted_next_day(self):
        report = build_report(self.dataset, date(2026, 11, 11))
        w23 = work_map(report.works)["W-23"]
        d2 = contract_map(report.contracts)["D-2"]
        self.assertEqual(w23.state, WORK_ACCEPTED)
        self.assertEqual(w23.paid_total, D("25000.00"))
        self.assertEqual(w23.remaining, D("15000.00"))
        self.assertEqual(d2.paid_total, D("75000.00"))
        self.assertEqual(d2.remaining, D("15000.00"))

    def test_p8_after_date_causes_overpayment(self):
        report = build_report(self.dataset, date(2026, 11, 12))
        d2 = contract_map(report.contracts)["D-2"]
        w23 = work_map(report.works)["W-23"]
        self.assertEqual(d2.paid_total, D("95000.00"))
        self.assertEqual(d2.remaining, D("0.00"))
        self.assertEqual(d2.overpayment, D("5000.00"))
        self.assertEqual(d2.unallocated, D("5000.00"))
        self.assertEqual(w23.paid_total, D("40000.00"))
        self.assertEqual(w23.remaining, D("0.00"))

    def test_warnings_for_conflicts(self):
        codes = {w.code for w in self.report.warnings}
        self.assertIn("WORK_DONE_AFTER_REPORT", codes)
        self.assertIn("PAYMENT_REFUNDED", codes)
        self.assertIn("PAYMENT_QUEUED", codes)
        self.assertIn("PAYMENT_AFTER_REPORT", codes)
        self.assertIn("CONTRACT_CANCELLED_SCOPE", codes)
        self.assertIn("CONTRACT_FUTURE_OVERPAY", codes)
        self.assertNotIn("INTERNAL_ALLOCATION_MISMATCH", codes)
        self.assertNotIn("WORK_OVERPAID", codes)
        self.assertNotIn("CONTRACT_WORK_OVERPAYMENT", codes)
        self.assertNotIn("CONTRACT_UNALLOCATED", codes)
        self.assertNotIn("CONTRACT_OVERPAID", codes)

    def test_all_payments_classified_exactly_once(self):
        total = sum((p.payment.amount for p in self.report.payments), D("0.00"))
        net = sum((p.net_paid for p in self.report.payments), D("0.00"))
        refunded = sum(
            (
                p.payment.amount
                for p in self.report.payments
                if p.bucket == "refunded"
            ),
            D("0.00"),
        )
        queued = sum(
            (
                p.payment.amount
                for p in self.report.payments
                if p.bucket == "queued"
            ),
            D("0.00"),
        )
        future = sum(
            (
                p.payment.amount
                for p in self.report.payments
                if p.bucket == "future"
            ),
            D("0.00"),
        )
        self.assertEqual(total, D("610000.00"))
        self.assertEqual(net + refunded + queued + future, total)


class SyntheticRuleTests(unittest.TestCase):
    def test_partial_payment(self):
        report = make_report(
            [contract(amount="1000.00")],
            [
                work("W-1", "600.00", "done", completed=date(2026, 1, 1)),
                work("W-2", "400.00"),
            ],
            [payment("P-1", "500.00")],
        )
        w1 = work_map(report.works)["W-1"]
        w2 = work_map(report.works)["W-2"]
        c = report.contracts[0]
        self.assertEqual(w1.paid_total, D("500.00"))
        self.assertEqual(w1.remaining, D("100.00"))
        self.assertEqual(w2.paid_total, D("0.00"))
        self.assertEqual(w2.remaining, D("400.00"))
        self.assertEqual(c.paid_total, D("500.00"))
        self.assertEqual(c.remaining, D("500.00"))

    def test_fifo_accepted_work_before_planned(self):
        report = make_report(
            [contract(amount="200.00")],
            [
                work("W-1", "100.00"),
                work("W-2", "100.00", "done", completed=date(2026, 1, 1)),
            ],
            [payment("P-1", "100.00")],
        )
        w1 = work_map(report.works)["W-1"]
        w2 = work_map(report.works)["W-2"]
        self.assertEqual(w2.paid_total, D("100.00"))
        self.assertEqual(w1.paid_total, D("0.00"))

    def test_fifo_spills_to_next_work(self):
        report = make_report(
            [contract(amount="300.00")],
            [
                work("W-1", "100.00", "done", completed=date(2026, 1, 1)),
                work("W-2", "100.00", "done", completed=date(2026, 1, 2)),
                work("W-3", "100.00"),
            ],
            [payment("P-1", "150.00")],
        )
        works = work_map(report.works)
        self.assertEqual(works["W-1"].paid_total, D("100.00"))
        self.assertEqual(works["W-2"].paid_total, D("50.00"))
        self.assertEqual(works["W-3"].paid_total, D("0.00"))

    def test_direct_payment_applied_first(self):
        report = make_report(
            [contract(amount="200.00")],
            [
                work("W-1", "100.00", "done", completed=date(2026, 1, 1)),
                work("W-2", "100.00"),
            ],
            [
                payment("P-1", "40.00", work_id="W-1", paid=date(2026, 1, 1)),
                payment("P-2", "100.00", paid=date(2026, 1, 2)),
            ],
        )
        w1 = work_map(report.works)["W-1"]
        w2 = work_map(report.works)["W-2"]
        c = report.contracts[0]
        self.assertEqual(w1.paid_direct, D("40.00"))
        self.assertEqual(w1.paid_general, D("60.00"))
        self.assertEqual(w1.paid_total, D("100.00"))
        self.assertEqual(w2.paid_total, D("40.00"))
        self.assertEqual(w2.remaining, D("60.00"))
        self.assertEqual(c.paid_total, D("140.00"))
        self.assertEqual(
            c.paid_total, sum((w.paid_total for w in report.works), D("0.00"))
        )

    def test_direct_overpayment_and_work_overpaid_warning(self):
        report = make_report(
            [contract(amount="200.00")],
            [
                work("W-1", "100.00", "done", completed=date(2026, 1, 1)),
                work("W-2", "100.00"),
            ],
            [
                payment("P-1", "150.00", work_id="W-1", paid=date(2026, 1, 1)),
                payment("P-2", "50.00"),
            ],
        )
        w1 = work_map(report.works)["W-1"]
        w2 = work_map(report.works)["W-2"]
        c = report.contracts[0]
        self.assertEqual(w1.paid_total, D("150.00"))
        self.assertEqual(w1.paid_applied, D("100.00"))
        self.assertEqual(w1.overpayment, D("50.00"))
        self.assertEqual(w2.paid_total, D("50.00"))
        self.assertEqual(w2.paid_applied, D("50.00"))
        self.assertEqual(w2.remaining, D("50.00"))
        self.assertEqual(c.paid_total, D("200.00"))
        # Переплата по W-1 не закрывает долг по W-2.
        self.assertEqual(c.remaining, D("50.00"))
        self.assertEqual(c.work_overpayment, D("50.00"))
        self.assertEqual(c.overpayment, D("50.00"))
        self.assertIn("WORK_OVERPAID", {w.code for w in report.warnings})

    def test_direct_overpayment_is_visible_next_to_other_work_debt(self):
        report = make_report(
            [contract(amount="200.00")],
            [
                work("W-1", "100.00", "done", completed=date(2026, 1, 1)),
                work("W-2", "100.00"),
            ],
            [payment("P-1", "120.00", work_id="W-1", paid=date(2026, 1, 1))],
        )
        w1 = work_map(report.works)["W-1"]
        w2 = work_map(report.works)["W-2"]
        c = report.contracts[0]
        self.assertEqual(w1.paid_direct, D("120.00"))
        self.assertEqual(w1.paid_applied, D("100.00"))
        self.assertEqual(w1.overpayment, D("20.00"))
        self.assertEqual(w2.paid_total, D("0.00"))
        self.assertEqual(w2.remaining, D("100.00"))
        self.assertEqual(c.paid_total, D("120.00"))
        self.assertEqual(c.paid_active_applied, D("100.00"))
        self.assertEqual(c.remaining, D("100.00"))
        self.assertEqual(c.work_overpayment, D("20.00"))
        self.assertEqual(c.unallocated, D("0.00"))
        self.assertEqual(c.overpayment, D("20.00"))
        self.assertEqual(
            c.paid_total,
            c.paid_active_applied + c.work_overpayment + c.unallocated,
        )
        self.assertIn("WORK_OVERPAID", {w.code for w in report.warnings})
        self.assertIn(
            "CONTRACT_WORK_OVERPAYMENT", {w.code for w in report.warnings}
        )

    def test_general_payment_exceeding_all_works_is_unallocated(self):
        report = make_report(
            [contract(amount="200.00")],
            [
                work("W-1", "100.00", "done", completed=date(2026, 1, 1)),
                work("W-2", "100.00", "done", completed=date(2026, 1, 2)),
            ],
            [payment("P-1", "250.00", paid=date(2026, 1, 1))],
        )
        works = work_map(report.works)
        c = report.contracts[0]
        self.assertEqual(works["W-1"].paid_applied, D("100.00"))
        self.assertEqual(works["W-2"].paid_applied, D("100.00"))
        self.assertEqual(works["W-1"].remaining, D("0.00"))
        self.assertEqual(works["W-2"].remaining, D("0.00"))
        self.assertEqual(c.paid_total, D("250.00"))
        self.assertEqual(c.paid_active_applied, D("200.00"))
        self.assertEqual(c.remaining, D("0.00"))
        self.assertEqual(c.work_overpayment, D("0.00"))
        self.assertEqual(c.unallocated, D("50.00"))
        self.assertEqual(c.overpayment, D("50.00"))
        self.assertEqual(
            c.paid_total,
            c.paid_active_applied + c.work_overpayment + c.unallocated,
        )
        self.assertIn("CONTRACT_UNALLOCATED", {w.code for w in report.warnings})

    def test_direct_payment_on_cancelled_work_does_not_offset_other_work(self):
        report = make_report(
            [contract(amount="300.00")],
            [
                work(
                    "W-1",
                    "100.00",
                    status="cancelled",
                    cancelled=date(2026, 1, 1),
                ),
                work("W-2", "100.00", "done", completed=date(2026, 1, 2)),
                work("W-3", "100.00"),
            ],
            [
                payment("P-1", "40.00", work_id="W-1", paid=date(2026, 1, 1)),
                payment("P-2", "100.00", paid=date(2026, 1, 2)),
            ],
        )
        works = work_map(report.works)
        c = report.contracts[0]
        self.assertEqual(works["W-1"].state, WORK_CANCELLED)
        self.assertEqual(works["W-1"].paid_applied, D("0.00"))
        self.assertEqual(works["W-1"].overpayment, D("40.00"))
        self.assertEqual(works["W-2"].paid_applied, D("100.00"))
        self.assertEqual(c.paid_total, D("140.00"))
        self.assertEqual(c.paid_active_applied, D("100.00"))
        self.assertEqual(c.paid_cancelled, D("40.00"))
        self.assertEqual(c.remaining, D("100.00"))
        self.assertEqual(c.work_overpayment, D("40.00"))
        self.assertEqual(c.unallocated, D("0.00"))
        self.assertEqual(c.overpayment, D("40.00"))
        self.assertEqual(
            c.paid_total,
            c.paid_active_applied + c.work_overpayment + c.unallocated,
        )
        self.assertIn(
            "DIRECT_PAYMENT_ON_CANCELLED", {w.code for w in report.warnings}
        )

    def test_overpayment_is_not_counted_twice_in_contract_totals(self):
        report = make_report(
            [contract(amount="300.00")],
            [
                work("W-1", "100.00", "done", completed=date(2026, 1, 1)),
                work("W-2", "100.00", "done", completed=date(2026, 1, 2)),
                work("W-3", "100.00"),
            ],
            [
                payment("P-1", "150.00", work_id="W-1", paid=date(2026, 1, 1)),
                payment("P-2", "250.00", paid=date(2026, 1, 2)),
            ],
        )
        c = report.contracts[0]
        works_paid = sum((w.paid_total for w in report.works), D("0.00"))
        self.assertEqual(c.paid_total, D("400.00"))
        self.assertEqual(works_paid, D("350.00"))
        self.assertEqual(c.unallocated, D("50.00"))
        self.assertEqual(c.work_overpayment, D("50.00"))
        self.assertEqual(c.overpayment, D("100.00"))
        self.assertEqual(c.paid_active_applied, D("300.00"))
        self.assertEqual(
            c.paid_total,
            c.paid_active_applied + c.work_overpayment + c.unallocated,
        )
        self.assertEqual(c.paid_total, works_paid + c.unallocated)
        # Переплата и нераспределённый остаток — разные суммы, не суммируются дважды.
        self.assertEqual(c.overpayment, c.work_overpayment + c.unallocated)

    def test_forecast_overpayment_includes_current_overpayment(self):
        report = make_report(
            [contract(amount="100.00")],
            [work("W-1", "100.00", "done", completed=date(2026, 1, 1))],
            [
                payment("P-1", "120.00", work_id="W-1", paid=date(2026, 1, 1)),
                payment("P-2", "20.00", paid=date(2026, 1, 10)),
            ],
            as_of=date(2026, 1, 5),
        )
        c = report.contracts[0]
        self.assertEqual(c.overpayment, D("20.00"))
        self.assertEqual(c.remaining, D("0.00"))
        self.assertEqual(c.future, D("20.00"))
        self.assertEqual(c.all_excess, D("20.00"))
        # Прогноз не теряет уже существующую переплату.
        self.assertEqual(c.overpayment_after_all, D("40.00"))
        self.assertEqual(c.overpayment_after_queued, D("20.00"))

    def test_refund_before_and_after_report_date(self):
        dataset = Dataset(
            [contract(amount="100.00")],
            [work("W-1", "100.00", "done", completed=date(2026, 1, 1))],
            [
                payment(
                    "P-1",
                    "100.00",
                    status="refunded",
                    paid=date(2026, 1, 1),
                    refunded=date(2026, 1, 5),
                )
            ],
        )
        before = build_report(dataset, date(2026, 1, 4))
        after = build_report(dataset, date(2026, 1, 5))
        self.assertEqual(before.contracts[0].paid_total, D("100.00"))
        self.assertEqual(before.contracts[0].remaining, D("0.00"))
        self.assertEqual(after.contracts[0].paid_total, D("0.00"))
        self.assertEqual(after.contracts[0].remaining, D("100.00"))
        self.assertIn(
            "REFUND_AFTER_REPORT", {w.code for w in before.warnings}
        )

    def test_queued_is_not_paid(self):
        report = make_report(
            [contract(amount="100.00")],
            [work("W-1", "100.00")],
            [
                payment(
                    "P-1",
                    "100.00",
                    status="queued",
                    paid=None,
                )
            ],
        )
        c = report.contracts[0]
        self.assertEqual(c.paid_total, D("0.00"))
        self.assertEqual(c.queued, D("100.00"))
        self.assertEqual(c.remaining, D("100.00"))
        self.assertIn("PAYMENT_QUEUED", {w.code for w in report.warnings})

    def test_queued_created_after_report_date_is_future(self):
        report = make_report(
            [contract(amount="100.00")],
            [work("W-1", "100.00")],
            [
                payment(
                    "P-1",
                    "100.00",
                    status="queued",
                    created=date(2026, 1, 10),
                    paid=None,
                )
            ],
        )
        c = report.contracts[0]
        self.assertEqual(c.paid_total, D("0.00"))
        self.assertEqual(c.queued, D("0.00"))
        self.assertEqual(c.future, D("100.00"))

    def test_payment_after_report_date_is_future(self):
        dataset = Dataset(
            [contract(amount="100.00")],
            [work("W-1", "100.00")],
            [payment("P-1", "100.00", paid=date(2026, 1, 10))],
        )
        before = build_report(dataset, date(2026, 1, 5))
        on_date = build_report(dataset, date(2026, 1, 10))
        self.assertEqual(before.contracts[0].paid_total, D("0.00"))
        self.assertEqual(before.contracts[0].future, D("100.00"))
        self.assertEqual(before.contracts[0].remaining, D("100.00"))
        self.assertEqual(on_date.contracts[0].paid_total, D("100.00"))
        self.assertEqual(on_date.contracts[0].remaining, D("0.00"))

    def test_cancelled_work_is_skipped_before_date_and_future_cancel_is_active(self):
        dataset = Dataset(
            [contract(amount="200.00")],
            [
                work(
                    "W-1",
                    "100.00",
                    status="cancelled",
                    cancelled=date(2026, 1, 2),
                ),
                work("W-2", "100.00"),
            ],
            [payment("P-1", "100.00", paid=date(2026, 1, 1))],
        )
        before = build_report(dataset, date(2026, 1, 1))
        after = build_report(dataset, date(2026, 1, 2))
        before_works = work_map(before.works)
        after_works = work_map(after.works)
        self.assertEqual(before_works["W-1"].paid_total, D("100.00"))
        self.assertEqual(before_works["W-2"].paid_total, D("0.00"))
        self.assertEqual(after_works["W-1"].state, WORK_CANCELLED)
        self.assertEqual(after_works["W-1"].paid_total, D("0.00"))
        self.assertEqual(after_works["W-2"].paid_total, D("100.00"))
        self.assertEqual(after.contracts[0].cancelled_total, D("100.00"))
        self.assertEqual(after.contracts[0].remaining, D("0.00"))

    def test_contract_works_mismatch_is_reported_not_scaled(self):
        report = make_report(
            [contract(amount="1000.00")],
            [work("W-1", "900.00", "done", completed=date(2026, 1, 1))],
            [payment("P-1", "500.00")],
        )
        c = report.contracts[0]
        self.assertEqual(c.works_total, D("900.00"))
        self.assertEqual(c.active_works_total, D("900.00"))
        self.assertEqual(c.paid_total, D("500.00"))
        self.assertEqual(c.remaining, D("400.00"))
        self.assertEqual(c.remaining_contract_amount, D("500.00"))
        self.assertEqual(c.works_sum_diff, D("100.00"))
        self.assertIn(
            "CONTRACT_WORKS_MISMATCH", {w.code for w in report.warnings}
        )

    def test_decimal_precision(self):
        report = make_report(
            [contract(amount="1.00")],
            [work("W-1", "0.30", "done", completed=date(2026, 1, 1))],
            [
                payment("P-1", "0.10"),
                payment("P-2", "0.20"),
            ],
        )
        w1 = work_map(report.works)["W-1"]
        self.assertEqual(str(w1.paid_total), "0.30")
        self.assertEqual(str(report.contracts[0].remaining), "0.00")

    def test_date_boundary_inclusive_for_work_and_payment(self):
        report = make_report(
            [contract(amount="100.00")],
            [
                work(
                    "W-1",
                    "100.00",
                    "done",
                    completed=date(2026, 1, 10),
                )
            ],
            [payment("P-1", "100.00", paid=date(2026, 1, 10))],
            as_of=date(2026, 1, 10),
        )
        w1 = work_map(report.works)["W-1"]
        self.assertEqual(w1.state, WORK_ACCEPTED)
        self.assertEqual(w1.paid_total, D("100.00"))
        self.assertEqual(report.contracts[0].remaining, D("0.00"))

    def test_direct_payment_on_cancelled_work(self):
        report = make_report(
            [contract(amount="100.00")],
            [
                work(
                    "W-1",
                    "100.00",
                    status="cancelled",
                    cancelled=date(2026, 1, 1),
                )
            ],
            [payment("P-1", "40.00", work_id="W-1")],
        )
        w1 = work_map(report.works)["W-1"]
        c = report.contracts[0]
        self.assertEqual(w1.state, WORK_CANCELLED)
        self.assertEqual(w1.paid_total, D("40.00"))
        self.assertEqual(w1.remaining, D("0.00"))
        self.assertEqual(w1.overpayment, D("40.00"))
        self.assertEqual(c.paid_total, D("40.00"))
        self.assertEqual(c.paid_active_applied, D("0.00"))
        self.assertEqual(c.paid_cancelled, D("40.00"))
        self.assertEqual(c.active_works_total, D("0.00"))
        self.assertEqual(c.remaining, D("0.00"))
        self.assertEqual(c.overpayment, D("40.00"))
        self.assertIn(
            "DIRECT_PAYMENT_ON_CANCELLED", {w.code for w in report.warnings}
        )

    def test_no_double_count_invariant(self):
        report = make_report(
            [contract(amount="300.00")],
            [
                work("W-1", "100.00", "done", completed=date(2026, 1, 1)),
                work("W-2", "100.00", "done", completed=date(2026, 1, 2)),
                work("W-3", "100.00"),
            ],
            [
                payment("P-1", "80.00", work_id="W-1", paid=date(2026, 1, 1)),
                payment("P-2", "250.00", paid=date(2026, 1, 2)),
            ],
        )
        c = report.contracts[0]
        work_paid = sum((w.paid_total for w in report.works), D("0.00"))
        self.assertEqual(c.paid_total, work_paid + c.unallocated)
        self.assertEqual(c.paid_total, D("330.00"))
        self.assertEqual(c.unallocated, D("30.00"))
        self.assertEqual(c.overpayment, D("30.00"))


if __name__ == "__main__":
    unittest.main()
