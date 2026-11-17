"""Расчёт отчёта: состояние на дату, распределение платежей, итоги."""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from .models import (
    ZERO,
    Allocation,
    ContractReport,
    Dataset,
    PAYMENT_FUTURE,
    PAYMENT_PAID,
    PAYMENT_QUEUED,
    PAYMENT_REFUNDED,
    PaymentReport,
    Report,
    WarningItem,
    WORK_ACCEPTED,
    WORK_CANCELLED,
    WORK_NOT_ACCEPTED,
    WorkReport,
)

SEVERITY_INFO = "INFO"
SEVERITY_WARNING = "WARNING"


def _warn(
    warnings: List[WarningItem],
    severity: str,
    code: str,
    entity: str,
    message: str,
) -> None:
    warnings.append(WarningItem(severity, code, entity, message))


def _work_state(work, as_of: date, warnings: List[WarningItem]) -> str:
    if work.cancelled_at is not None and work.cancelled_at <= as_of:
        if work.status != "cancelled":
            _warn(
                warnings,
                SEVERITY_WARNING,
                "WORK_STATUS_DATE_CONFLICT",
                work.work_id,
                f"статус {work.status!r}, но cancelled_at {work.cancelled_at} "
                "не позднее даты отчёта; считаем работу отменённой",
            )
        if work.completed_at is not None and work.completed_at <= as_of:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "WORK_STATUS_DATE_CONFLICT",
                work.work_id,
                f"есть completed_at {work.completed_at} и cancelled_at "
                f"{work.cancelled_at}; считаем работу отменённой",
            )
        _warn(
            warnings,
            SEVERITY_INFO,
            "WORK_CANCELLED",
            work.work_id,
            f"отменена {work.cancelled_at}; в распределении не участвует",
        )
        return WORK_CANCELLED

    if work.completed_at is not None and work.completed_at <= as_of:
        if work.status == "cancelled":
            _warn(
                warnings,
                SEVERITY_WARNING,
                "WORK_CANCELLED_AFTER_REPORT",
                work.work_id,
                f"на дату отчёта была принята ({work.completed_at}), "
                f"отмена указана на {work.cancelled_at} — после даты",
            )
        elif work.status == "planned":
            _warn(
                warnings,
                SEVERITY_WARNING,
                "WORK_STATUS_DATE_CONFLICT",
                work.work_id,
                f"статус planned, но completed_at {work.completed_at} "
                "не позднее даты отчёта; считаем работу принятой",
            )
        return WORK_ACCEPTED

    if work.status == "done":
        _warn(
            warnings,
            SEVERITY_WARNING,
            "WORK_DONE_AFTER_REPORT",
            work.work_id,
            f"статус done, но completed_at {work.completed_at} позже даты "
            f"отчёта {as_of}; на дату отчёта работа не принята",
        )
    elif work.status == "cancelled":
        _warn(
            warnings,
            SEVERITY_WARNING,
            "WORK_CANCELLED_AFTER_REPORT",
            work.work_id,
            f"отмена указана на {work.cancelled_at}, позже даты отчёта; "
            "на дату отчёта работа действует",
        )
    elif work.completed_at is not None or work.cancelled_at is not None:
        _warn(
            warnings,
            SEVERITY_WARNING,
            "WORK_STATUS_DATE_CONFLICT",
            work.work_id,
            "статус planned, но заполнена дата completed_at/cancelled_at",
        )
    return WORK_NOT_ACCEPTED


def _payment_bucket(payment, as_of: date, warnings: List[WarningItem]) -> str:
    pid = payment.payment_id

    if payment.refunded_at is not None and payment.refunded_at <= as_of:
        if payment.status != "refunded":
            _warn(
                warnings,
                SEVERITY_WARNING,
                "PAYMENT_STATUS_CONFLICT",
                pid,
                f"статус {payment.status!r}, но возврат указан на "
                f"{payment.refunded_at}; считаем платёж возвращённым",
            )
        _warn(
            warnings,
            SEVERITY_INFO,
            "PAYMENT_REFUNDED",
            pid,
            f"возвращён {payment.refunded_at}; net paid = 0",
        )
        return PAYMENT_REFUNDED

    if payment.paid_at is not None:
        if payment.paid_at <= as_of:
            if payment.status == "refunded":
                _warn(
                    warnings,
                    SEVERITY_WARNING,
                    "REFUND_AFTER_REPORT",
                    pid,
                    f"возврат указан на {payment.refunded_at}, после даты "
                    "отчёта; на дату платёж считается выплаченным",
                )
            if payment.status == "queued":
                _warn(
                    warnings,
                    SEVERITY_WARNING,
                    "PAYMENT_STATUS_CONFLICT",
                    pid,
                    f"статус queued, но есть paid_at {payment.paid_at}; "
                    "считаем платёж выплаченным",
                )
            return PAYMENT_PAID

        if payment.status == "queued":
            _warn(
                warnings,
                SEVERITY_WARNING,
                "PAYMENT_STATUS_CONFLICT",
                pid,
                f"статус queued, но paid_at {payment.paid_at} позже даты отчёта",
            )
        _warn(
            warnings,
            SEVERITY_INFO,
            "PAYMENT_AFTER_REPORT",
            pid,
            f"оплачен {payment.paid_at}, после даты отчёта; не включён",
        )
        return PAYMENT_FUTURE

    if payment.status == "queued":
        if payment.created_at <= as_of:
            _warn(
                warnings,
                SEVERITY_INFO,
                "PAYMENT_QUEUED",
                pid,
                "в очереди; не считается выплатой",
            )
            return PAYMENT_QUEUED
        _warn(
            warnings,
            SEVERITY_INFO,
            "PAYMENT_CREATED_AFTER_REPORT",
            pid,
            f"создан {payment.created_at}, после даты отчёта; не включён",
        )
        return PAYMENT_FUTURE

    # Для paid/refunded отсутствие paid_at отсекается загрузчиком.
    _warn(
        warnings,
        SEVERITY_WARNING,
        "PAYMENT_STATUS_CONFLICT",
        pid,
        "нет paid_at, поэтому дату выплаты определить нельзя",
    )
    return PAYMENT_FUTURE


def _ordered_active_works(works, states: Dict[str, str]):
    active = [w for w in works if states[w.work_id] != WORK_CANCELLED]
    return sorted(
        active,
        key=lambda w: (
            0 if states[w.work_id] == WORK_ACCEPTED else 1,
            w.completed_at or date.max,
            w.work_id,
        ),
    )


def _payment_comment(payment, bucket: str, allocated: Decimal) -> str:
    if bucket == PAYMENT_REFUNDED:
        return "Возвращён до даты отчёта, net paid = 0."
    if bucket == PAYMENT_QUEUED:
        return "В очереди, не выплачен."
    if bucket == PAYMENT_FUTURE:
        when = payment.paid_at or payment.created_at
        return f"После даты отчёта ({when}), не включён."
    if payment.status == "refunded":
        return "Оплачен до даты; возврат после даты не учитывается."
    if allocated < payment.amount:
        return f"Распределено {allocated:.2f} из {payment.amount:.2f}."
    return "Выплачен до даты отчёта."


def _work_comment(
    work,
    state: str,
    paid: Decimal,
    overpayment: Decimal,
    as_of: date,
) -> str:
    parts: List[str] = []
    if state == WORK_CANCELLED:
        parts.append(f"Отменена {work.cancelled_at}; в распределении не участвует.")
        if paid > ZERO:
            parts.append(
                "Есть выплата по отменённой работе; требуется возврат или подтверждение."
            )
    elif state == WORK_NOT_ACCEPTED:
        parts.append(f"Не принята на {as_of}.")
        if work.completed_at is not None and work.completed_at > as_of:
            parts.append(f"Принята {work.completed_at} (после даты отчёта).")
        if paid > ZERO:
            parts.append("Аванс по непринятой работе.")
    else:
        if overpayment > ZERO:
            parts.append("Переплата по работе.")
    return " ".join(parts)


def build_report(dataset: Dataset, as_of: date) -> Report:
    warnings: List[WarningItem] = []

    contracts = sorted(dataset.contracts, key=lambda c: c.contract_id)
    works = sorted(dataset.works, key=lambda w: (w.contract_id, w.work_id))
    payments = sorted(dataset.payments, key=lambda p: p.payment_id)

    work_by_id = {w.work_id: w for w in works}
    works_by_contract = defaultdict(list)
    for work in works:
        works_by_contract[work.contract_id].append(work)

    states: Dict[str, str] = {
        work.work_id: _work_state(work, as_of, warnings) for work in works
    }

    payment_reports: List[PaymentReport] = []
    for payment in payments:
        bucket = _payment_bucket(payment, as_of, warnings)
        net_paid = payment.amount if bucket == PAYMENT_PAID else ZERO
        payment_reports.append(
            PaymentReport(payment, bucket, net_paid, ZERO, "")
        )

    work_direct: Dict[str, Decimal] = {w.work_id: ZERO for w in works}
    work_general: Dict[str, Decimal] = {w.work_id: ZERO for w in works}
    general_pools = defaultdict(list)
    allocations: List[Allocation] = []

    for report in payment_reports:
        if report.bucket != PAYMENT_PAID:
            continue
        payment = report.payment
        if payment.work_id is not None:
            work_direct[payment.work_id] += payment.amount
            allocations.append(
                Allocation(
                    payment.payment_id,
                    payment.contract_id,
                    payment.work_id,
                    payment.amount,
                    "direct",
                )
            )
            if states[payment.work_id] == WORK_CANCELLED:
                _warn(
                    warnings,
                    SEVERITY_WARNING,
                    "DIRECT_PAYMENT_ON_CANCELLED",
                    payment.payment_id,
                    f"прямой платёж по отменённой работе {payment.work_id}; "
                    "показан как выплата, требуется возврат или подтверждение",
                )
        else:
            general_pools[payment.contract_id].append(report)

    unallocated: Dict[str, Decimal] = {c.contract_id: ZERO for c in contracts}

    for contract in contracts:
        cid = contract.contract_id
        pool = sorted(
            general_pools[cid],
            key=lambda r: (r.payment.paid_at or date.max, r.payment.payment_id),
        )
        remaining_by_payment = {
            report.payment.payment_id: report.payment.amount for report in pool
        }
        pointer = 0

        for work in _ordered_active_works(works_by_contract[cid], states):
            capacity = max(work.price - work_direct[work.work_id], ZERO)
            while capacity > ZERO and pointer < len(pool):
                report = pool[pointer]
                pid = report.payment.payment_id
                available = remaining_by_payment[pid]
                if available <= ZERO:
                    pointer += 1
                    continue

                take = min(capacity, available)
                if take > ZERO:
                    work_general[work.work_id] += take
                    allocations.append(
                        Allocation(
                            pid,
                            cid,
                            work.work_id,
                            take,
                            "general",
                        )
                    )
                    remaining_by_payment[pid] -= take
                    capacity -= take

                if remaining_by_payment[pid] == ZERO:
                    pointer += 1
                else:
                    break

        unallocated[cid] = sum(remaining_by_payment.values(), ZERO)

    allocated_by_payment: Dict[str, Decimal] = defaultdict(lambda: ZERO)
    for allocation in allocations:
        allocated_by_payment[allocation.payment_id] += allocation.amount
    for report in payment_reports:
        report.allocated = allocated_by_payment[report.payment.payment_id]
        report.comment = _payment_comment(
            report.payment, report.bucket, report.allocated
        )

    work_reports: List[WorkReport] = []
    for work in works:
        state = states[work.work_id]
        direct = work_direct[work.work_id]
        general = work_general[work.work_id]
        paid = direct + general

        if state == WORK_CANCELLED:
            applied = ZERO
            remaining = ZERO
            overpayment = paid
        else:
            applied = min(paid, work.price)
            remaining = work.price - applied
            overpayment = paid - applied

        comment = _work_comment(work, state, paid, overpayment, as_of)

        if overpayment > ZERO and state != WORK_CANCELLED:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "WORK_OVERPAID",
                work.work_id,
                f"выплачено {paid:.2f} при цене {work.price:.2f}; "
                f"переплата {overpayment:.2f}",
            )
        if state == WORK_NOT_ACCEPTED and paid > ZERO:
            _warn(
                warnings,
                SEVERITY_INFO,
                "WORK_ADVANCE",
                work.work_id,
                f"аванс {paid:.2f} по непринятой работе",
            )

        work_reports.append(
            WorkReport(
                work,
                state,
                direct,
                general,
                paid,
                applied,
                remaining,
                overpayment,
                comment,
            )
        )

    contract_reports: List[ContractReport] = []
    for contract in contracts:
        cid = contract.contract_id
        contract_works = works_by_contract[cid]
        contract_works_reports = [
            r for r in work_reports if r.work.contract_id == cid
        ]

        works_total = sum((w.price for w in contract_works), ZERO)
        cancelled_total = sum(
            (
                r.work.price
                for r in contract_works_reports
                if r.state == WORK_CANCELLED
            ),
            ZERO,
        )
        active_total = works_total - cancelled_total
        paid_total = sum(
            (r.net_paid for r in payment_reports if r.payment.contract_id == cid),
            ZERO,
        )
        paid_direct = sum(
            (
                a.amount
                for a in allocations
                if a.contract_id == cid and a.kind == "direct"
            ),
            ZERO,
        )
        contract_unallocated = unallocated[cid]
        # «Общие» — только распределённые по работам общие платежи.
        # Нераспределённый остаток показывается отдельной колонкой.
        paid_general = paid_total - paid_direct - contract_unallocated
        paid_active_applied = sum(
            (
                r.paid_applied
                for r in contract_works_reports
                if r.state != WORK_CANCELLED
            ),
            ZERO,
        )
        paid_cancelled = sum(
            (
                r.paid_total
                for r in contract_works_reports
                if r.state == WORK_CANCELLED
            ),
            ZERO,
        )
        work_overpayment = sum(
            (r.overpayment for r in contract_works_reports), ZERO
        )

        remaining = max(active_total - paid_active_applied, ZERO)
        overpayment = work_overpayment + contract_unallocated
        remaining_contract_amount = max(contract.amount - paid_total, ZERO)

        queued = sum(
            (
                r.payment.amount
                for r in payment_reports
                if r.payment.contract_id == cid and r.bucket == PAYMENT_QUEUED
            ),
            ZERO,
        )
        future = sum(
            (
                r.payment.amount
                for r in payment_reports
                if r.payment.contract_id == cid and r.bucket == PAYMENT_FUTURE
            ),
            ZERO,
        )
        remaining_after_queued = max(remaining - queued, ZERO)
        queued_excess = max(queued - remaining, ZERO)
        overpayment_after_queued = overpayment + queued_excess
        remaining_after_all = max(remaining - queued - future, ZERO)
        all_excess = max(queued + future - remaining, ZERO)
        overpayment_after_all = overpayment + all_excess

        works_sum_diff = contract.amount - works_total
        cancel_scope_diff = (contract.amount - cancelled_total) - active_total

        comment_parts: List[str] = []
        if cancelled_total > ZERO:
            comment_parts.append(
                f"Отменено {cancelled_total:.2f}; действующие работы "
                f"{active_total:.2f}; сумма договора не уменьшена."
            )
        if works_sum_diff != ZERO:
            comment_parts.append(
                f"Сумма работ отличается от договора на {works_sum_diff:.2f}."
            )
        if queued > ZERO:
            comment_parts.append(f"В очереди {queued:.2f}.")
        if future > ZERO:
            comment_parts.append(f"После даты отчёта {future:.2f}.")
        comment = " ".join(comment_parts)

        if works_sum_diff != ZERO:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "CONTRACT_WORKS_MISMATCH",
                cid,
                f"сумма договора {contract.amount:.2f}, сумма работ "
                f"{works_total:.2f}, разница {works_sum_diff:.2f}",
            )
        if cancelled_total > ZERO:
            _warn(
                warnings,
                SEVERITY_INFO,
                "CONTRACT_CANCELLED_SCOPE",
                cid,
                f"отменено {cancelled_total:.2f}; действующие работы "
                f"{active_total:.2f}; договор {contract.amount:.2f}. "
                "Уменьшение договорной суммы требует подтверждения.",
            )
        if cancel_scope_diff != ZERO:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "CONTRACT_CANCEL_SCOPE_MISMATCH",
                cid,
                f"сумма договора минус отменённые работы = "
                f"{contract.amount - cancelled_total:.2f}, а действующие "
                f"работы = {active_total:.2f}; разница {cancel_scope_diff:.2f}",
            )
        if contract_unallocated > ZERO:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "CONTRACT_UNALLOCATED",
                cid,
                f"нераспределённые платежи по договору {contract_unallocated:.2f}; "
                "показаны отдельно и не уменьшают остаток по работам",
            )
        if work_overpayment > ZERO:
            cancelled_part = (
                f" (в том числе по отменённым {paid_cancelled:.2f})"
                if paid_cancelled > ZERO
                else ""
            )
            _warn(
                warnings,
                SEVERITY_WARNING,
                "CONTRACT_WORK_OVERPAYMENT",
                cid,
                f"переплата по работам {work_overpayment:.2f}{cancelled_part}; "
                "она не уменьшает остаток по другим работам",
            )
        if overpayment > ZERO:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "CONTRACT_OVERPAID",
                cid,
                f"переплата по договору {overpayment:.2f}: "
                f"по работам {work_overpayment:.2f}, "
                f"нераспределённые платежи {contract_unallocated:.2f}",
            )
        if queued > ZERO:
            _warn(
                warnings,
                SEVERITY_INFO,
                "CONTRACT_QUEUED",
                cid,
                f"в очереди {queued:.2f}; после неё останется "
                f"{remaining_after_queued:.2f}",
            )
        if queued_excess > ZERO:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "CONTRACT_QUEUED_OVERPAY",
                cid,
                f"очередь {queued:.2f} больше остатка {remaining:.2f} "
                f"на {queued_excess:.2f}; итоговая переплата после очереди "
                f"{overpayment_after_queued:.2f}",
            )
        if future > ZERO:
            _warn(
                warnings,
                SEVERITY_INFO,
                "CONTRACT_FUTURE",
                cid,
                f"платежи после даты отчёта {future:.2f}; после них останется "
                f"{remaining_after_all:.2f}",
            )
        if all_excess > ZERO:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "CONTRACT_FUTURE_OVERPAY",
                cid,
                f"очередь и платежи после даты ({queued + future:.2f}) "
                f"больше остатка {remaining:.2f} на {all_excess:.2f}; "
                f"итоговая переплата после всех {overpayment_after_all:.2f}",
            )
        if not contract_works:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "CONTRACT_NO_WORKS",
                cid,
                "у договора нет работ",
            )

        internal_sum = (
            paid_active_applied + work_overpayment + contract_unallocated
        )
        if paid_total != internal_sum:
            _warn(
                warnings,
                SEVERITY_WARNING,
                "INTERNAL_ALLOCATION_MISMATCH",
                cid,
                f"выплачено {paid_total:.2f}, а сумма зачтённого "
                f"({paid_active_applied:.2f}), переплаты по работам "
                f"({work_overpayment:.2f}) и нераспределённого остатка "
                f"({contract_unallocated:.2f}) равна {internal_sum:.2f}",
            )

        contract_reports.append(
            ContractReport(
                contract,
                works_total,
                cancelled_total,
                active_total,
                paid_total,
                paid_active_applied,
                paid_cancelled,
                paid_direct,
                paid_general,
                contract_unallocated,
                work_overpayment,
                remaining,
                overpayment,
                remaining_contract_amount,
                queued,
                future,
                remaining_after_queued,
                queued_excess,
                overpayment_after_queued,
                remaining_after_all,
                all_excess,
                overpayment_after_all,
                works_sum_diff,
                cancel_scope_diff,
                comment,
            )
        )

    allocations.sort(key=lambda a: (a.payment_id, a.work_id, a.kind))
    warnings.sort(key=lambda w: (0 if w.severity == SEVERITY_WARNING else 1, w.entity, w.code, w.message))

    return Report(
        as_of,
        contract_reports,
        work_reports,
        payment_reports,
        allocations,
        warnings,
    )
