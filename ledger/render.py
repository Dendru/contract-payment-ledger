"""Вывод отчёта в CSV и консоль."""

import csv
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List

from .models import (
    PAYMENT_FUTURE,
    PAYMENT_PAID,
    PAYMENT_QUEUED,
    PAYMENT_REFUNDED,
    Report,
    WORK_ACCEPTED,
    WORK_CANCELLED,
    WORK_NOT_ACCEPTED,
    ZERO,
)

STATE_LABELS = {
    WORK_ACCEPTED: "принята",
    WORK_CANCELLED: "отменена",
    WORK_NOT_ACCEPTED: "не принята",
}

BUCKET_LABELS = {
    PAYMENT_PAID: "выплачен",
    PAYMENT_REFUNDED: "возвращён",
    PAYMENT_QUEUED: "в очереди",
    PAYMENT_FUTURE: "после даты",
}


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _grouped(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _date(value) -> str:
    return value.isoformat() if value is not None else ""


def _write_csv(path: Path, headers: List[str], rows: Iterable[List[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


def write_reports(report: Report, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    contract_headers = [
        "Договор",
        "Подрядчик",
        "Сумма договора",
        "Сумма работ",
        "Отменено",
        "Действующие работы",
        "Договор минус действующие",
        "Выплачено",
        "Прямые",
        "Общие",
        "Зачтено в действующие",
        "Остаток по действующим",
        "Остаток по договору",
        "Переплата по работам",
        "Нераспределённые платежи",
        "Переплата",
        "В очереди",
        "Остаток после очереди",
        "Переплата после очереди",
        "После даты",
        "Остаток после всех",
        "Переплата после всех",
        "Расхождение сумм",
        "Комментарий",
    ]
    contract_rows = []
    total_amount = ZERO
    total_works = ZERO
    total_cancelled = ZERO
    total_active = ZERO
    total_contract_active_diff = ZERO
    total_paid = ZERO
    total_direct = ZERO
    total_general = ZERO
    total_applied_active = ZERO
    total_remaining = ZERO
    total_remaining_contract = ZERO
    total_work_overpayment = ZERO
    total_unallocated = ZERO
    total_overpayment = ZERO
    total_queued = ZERO
    total_after_queued = ZERO
    total_overpayment_after_queued = ZERO
    total_future = ZERO
    total_after_all = ZERO
    total_overpayment_after_all = ZERO
    total_works_diff = ZERO

    for c in report.contracts:
        contract_rows.append(
            [
                c.contract.contract_id,
                c.contract.contractor,
                _money(c.contract.amount),
                _money(c.works_total),
                _money(c.cancelled_total),
                _money(c.active_works_total),
                _money(c.contract.amount - c.active_works_total),
                _money(c.paid_total),
                _money(c.paid_direct),
                _money(c.paid_general),
                _money(c.paid_active_applied),
                _money(c.remaining),
                _money(c.remaining_contract_amount),
                _money(c.work_overpayment),
                _money(c.unallocated),
                _money(c.overpayment),
                _money(c.queued),
                _money(c.remaining_after_queued),
                _money(c.overpayment_after_queued),
                _money(c.future),
                _money(c.remaining_after_all),
                _money(c.overpayment_after_all),
                _money(c.works_sum_diff),
                c.comment,
            ]
        )
        total_amount += c.contract.amount
        total_works += c.works_total
        total_cancelled += c.cancelled_total
        total_active += c.active_works_total
        total_contract_active_diff += c.contract.amount - c.active_works_total
        total_paid += c.paid_total
        total_direct += c.paid_direct
        total_general += c.paid_general
        total_applied_active += c.paid_active_applied
        total_remaining += c.remaining
        total_remaining_contract += c.remaining_contract_amount
        total_work_overpayment += c.work_overpayment
        total_unallocated += c.unallocated
        total_overpayment += c.overpayment
        total_queued += c.queued
        total_after_queued += c.remaining_after_queued
        total_overpayment_after_queued += c.overpayment_after_queued
        total_future += c.future
        total_after_all += c.remaining_after_all
        total_overpayment_after_all += c.overpayment_after_all
        total_works_diff += c.works_sum_diff

    contract_rows.append(
        [
            "ИТОГО",
            "",
            _money(total_amount),
            _money(total_works),
            _money(total_cancelled),
            _money(total_active),
            _money(total_contract_active_diff),
            _money(total_paid),
            _money(total_direct),
            _money(total_general),
            _money(total_applied_active),
            _money(total_remaining),
            _money(total_remaining_contract),
            _money(total_work_overpayment),
            _money(total_unallocated),
            _money(total_overpayment),
            _money(total_queued),
            _money(total_after_queued),
            _money(total_overpayment_after_queued),
            _money(total_future),
            _money(total_after_all),
            _money(total_overpayment_after_all),
            _money(total_works_diff),
            "",
        ]
    )
    _write_csv(out_dir / "contracts.csv", contract_headers, contract_rows)

    work_headers = [
        "Договор",
        "Работа",
        "Название",
        "Цена",
        "Статус",
        "Состояние на дату",
        "Принята",
        "Отменена",
        "Прямые",
        "Из общих",
        "Выплачено всего",
        "Зачтено в счёт цены",
        "Осталось оплатить",
        "Переплата",
        "Комментарий",
    ]
    work_rows = []
    for w in report.works:
        work_rows.append(
            [
                w.work.contract_id,
                w.work.work_id,
                w.work.title,
                _money(w.work.price),
                w.work.status,
                STATE_LABELS.get(w.state, w.state),
                _date(w.work.completed_at),
                _date(w.work.cancelled_at),
                _money(w.paid_direct),
                _money(w.paid_general),
                _money(w.paid_total),
                _money(w.paid_applied),
                _money(w.remaining),
                _money(w.overpayment),
                w.comment,
            ]
        )
    _write_csv(out_dir / "works.csv", work_headers, work_rows)

    payment_headers = [
        "Платёж",
        "Договор",
        "Работа",
        "Назначение",
        "Сумма",
        "Статус",
        "Создан",
        "Оплачен",
        "Возвращён",
        "Категория на дату",
        "Net paid",
        "Распределено",
        "Комментарий",
    ]
    payment_rows = []
    for p in report.payments:
        payment_rows.append(
            [
                p.payment.payment_id,
                p.payment.contract_id,
                p.payment.work_id or "",
                p.payment.purpose,
                _money(p.payment.amount),
                p.payment.status,
                _date(p.payment.created_at),
                _date(p.payment.paid_at),
                _date(p.payment.refunded_at),
                BUCKET_LABELS.get(p.bucket, p.bucket),
                _money(p.net_paid),
                _money(p.allocated),
                p.comment,
            ]
        )
    _write_csv(out_dir / "payments.csv", payment_headers, payment_rows)

    allocation_headers = ["Платёж", "Договор", "Работа", "Сумма", "Тип"]
    allocation_rows = [
        [
            a.payment_id,
            a.contract_id,
            a.work_id,
            _money(a.amount),
            "прямой" if a.kind == "direct" else "общий",
        ]
        for a in report.allocations
    ]
    _write_csv(out_dir / "allocations.csv", allocation_headers, allocation_rows)

    warning_headers = ["Уровень", "Код", "Объект", "Сообщение"]
    warning_rows = [
        [w.severity, w.code, w.entity, w.message] for w in report.warnings
    ]
    _write_csv(out_dir / "warnings.csv", warning_headers, warning_rows)


def print_summary(report: Report) -> None:
    print(f"Отчёт на {report.as_of.isoformat()}")
    print("Договоры:")

    total_paid = ZERO
    total_remaining = ZERO
    total_overpayment = ZERO
    total_work_overpayment = ZERO
    total_unallocated = ZERO
    total_queued = ZERO
    total_future = ZERO
    for c in report.contracts:
        total_paid += c.paid_total
        total_remaining += c.remaining
        total_overpayment += c.overpayment
        total_work_overpayment += c.work_overpayment
        total_unallocated += c.unallocated
        total_queued += c.queued
        total_future += c.future
        print(
            f"  {c.contract.contract_id}: выплачено {_grouped(c.paid_total)}, "
            f"остаток по действующим {_grouped(c.remaining)}, "
            f"переплата {_grouped(c.overpayment)} "
            f"(по работам {_grouped(c.work_overpayment)}, "
            f"нераспределено {_grouped(c.unallocated)}), "
            f"отменено {_grouped(c.cancelled_total)}, "
            f"в очереди {_grouped(c.queued)}, "
            f"после даты {_grouped(c.future)}"
        )

    print("Работы:")
    for w in report.works:
        print(
            f"  {w.work.work_id} ({STATE_LABELS.get(w.state, w.state)}): "
            f"цена {_grouped(w.work.price)}, выплачено {_grouped(w.paid_total)}, "
            f"зачтено {_grouped(w.paid_applied)}, "
            f"осталось {_grouped(w.remaining)}, "
            f"переплата {_grouped(w.overpayment)}"
        )

    print(
        f"Итого: выплачено {_grouped(total_paid)}, "
        f"остаток по действующим работам {_grouped(total_remaining)}, "
        f"переплата {_grouped(total_overpayment)} "
        f"(по работам {_grouped(total_work_overpayment)}, "
        f"нераспределено {_grouped(total_unallocated)}), "
        f"в очереди {_grouped(total_queued)}, "
        f"после даты {_grouped(total_future)}"
    )

    if report.warnings:
        print(f"Предупреждения ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  [{w.severity}] {w.entity}: {w.message}")
    else:
        print("Предупреждений нет.")
