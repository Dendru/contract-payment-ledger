"""Модели данных и структур отчёта."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

ZERO = Decimal("0.00")

# Состояния работы на дату отчёта.
WORK_ACCEPTED = "accepted"
WORK_CANCELLED = "cancelled"
WORK_NOT_ACCEPTED = "not_accepted"

# Категории платежа на дату отчёта.
PAYMENT_PAID = "paid"
PAYMENT_REFUNDED = "refunded"
PAYMENT_QUEUED = "queued"
PAYMENT_FUTURE = "future"


@dataclass(frozen=True)
class Contract:
    contract_id: str
    contractor: str
    amount: Decimal
    signed_at: date


@dataclass(frozen=True)
class Work:
    work_id: str
    contract_id: str
    title: str
    price: Decimal
    status: str
    completed_at: Optional[date]
    cancelled_at: Optional[date]


@dataclass(frozen=True)
class Payment:
    payment_id: str
    contract_id: str
    work_id: Optional[str]
    purpose: str
    amount: Decimal
    status: str
    created_at: date
    paid_at: Optional[date]
    refunded_at: Optional[date]


@dataclass(frozen=True)
class Dataset:
    contracts: List[Contract]
    works: List[Work]
    payments: List[Payment]


@dataclass(frozen=True)
class WarningItem:
    severity: str
    code: str
    entity: str
    message: str


@dataclass(frozen=True)
class Allocation:
    payment_id: str
    contract_id: str
    work_id: str
    amount: Decimal
    kind: str  # direct | general


@dataclass
class WorkReport:
    work: Work
    state: str
    paid_direct: Decimal
    paid_general: Decimal
    paid_total: Decimal
    # Зачтено в счёт цены работы; не может превышать цену.
    paid_applied: Decimal
    remaining: Decimal
    # Сумма сверх цены (для отменённой работы — вся выплата).
    overpayment: Decimal
    comment: str


@dataclass
class ContractReport:
    contract: Contract
    works_total: Decimal
    cancelled_total: Decimal
    active_works_total: Decimal
    paid_total: Decimal
    # Выплаты, зачтённые в цену действующих работ (без превышения).
    paid_active_applied: Decimal
    # Выплаты по отменённым работам: целиком переплата/к возврату.
    paid_cancelled: Decimal
    paid_direct: Decimal
    paid_general: Decimal
    # Нераспределённый остаток общих платежей.
    unallocated: Decimal
    # Переплата по работам (действующим и отменённым).
    work_overpayment: Decimal
    remaining: Decimal
    # Итоговая переплата по договору = переплата по работам + нераспределённое.
    overpayment: Decimal
    remaining_contract_amount: Decimal
    queued: Decimal
    future: Decimal
    remaining_after_queued: Decimal
    # Превышение очереди над остатком (не итоговая переплата).
    queued_excess: Decimal
    # Итоговая переплата, если очередь состоится.
    overpayment_after_queued: Decimal
    remaining_after_all: Decimal
    # Превышение очереди и будущих платежей над остатком.
    all_excess: Decimal
    # Итоговая переплата, если состоятся очередь и платежи после даты.
    overpayment_after_all: Decimal
    works_sum_diff: Decimal
    cancel_scope_diff: Decimal
    comment: str


@dataclass
class PaymentReport:
    payment: Payment
    bucket: str
    net_paid: Decimal
    allocated: Decimal
    comment: str


@dataclass
class Report:
    as_of: date
    contracts: List[ContractReport]
    works: List[WorkReport]
    payments: List[PaymentReport]
    allocations: List[Allocation]
    warnings: List[WarningItem]
