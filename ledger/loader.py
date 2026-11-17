"""Загрузка и структурная проверка CSV."""

import csv
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .models import Contract, Dataset, Payment, Work

MONEY_RE = re.compile(r"^\d+(\.\d{1,2})?$")

WORK_STATUSES = {"planned", "done", "cancelled"}
PAYMENT_STATUSES = {"paid", "queued", "refunded"}

CONTRACT_COLUMNS = ("contract_id", "contractor", "amount", "signed_at")
WORK_COLUMNS = (
    "work_id",
    "contract_id",
    "title",
    "price",
    "status",
    "completed_at",
    "cancelled_at",
)
PAYMENT_COLUMNS = (
    "payment_id",
    "contract_id",
    "work_id",
    "purpose",
    "amount",
    "status",
    "created_at",
    "paid_at",
    "refunded_at",
)


class DataError(Exception):
    """Ошибка структуры входных данных."""

    def __init__(self, messages: List[str]):
        self.messages = messages
        super().__init__("\n".join(messages))


def _parse_date(
    value: str,
    field: str,
    where: str,
    errors: List[str],
    required: bool,
) -> Optional[date]:
    if not value:
        if required:
            errors.append(f"{where}: поле {field} обязательно")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(
            f"{where}: поле {field} должно быть датой YYYY-MM-DD, получено {value!r}"
        )
        return None


def _parse_money(
    value: str, field: str, where: str, errors: List[str]
) -> Optional[Decimal]:
    if not value:
        errors.append(f"{where}: поле {field} обязательно")
        return None
    if value.startswith("-"):
        errors.append(f"{where}: поле {field} не может быть отрицательным")
        return None
    if not MONEY_RE.match(value):
        errors.append(
            f"{where}: поле {field} должно быть неотрицательным числом "
            f"не более чем с 2 знаками после точки, получено {value!r}"
        )
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        errors.append(f"{where}: не удалось разобрать сумму {value!r}")
        return None
    if amount < 0:
        errors.append(f"{where}: поле {field} не может быть отрицательным")
        return None
    return amount


def _read_rows(
    path: Path,
    required_columns: Tuple[str, ...],
    errors: List[str],
) -> List[Tuple[int, Dict[str, str]]]:
    if not path.exists():
        errors.append(f"Файл не найден: {path}")
        return []

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                errors.append(f"{path.name}: пустой файл или отсутствует строка заголовков")
                return []

            headers = [h.strip() for h in reader.fieldnames if h is not None]
            duplicates = sorted({h for h in headers if headers.count(h) > 1})
            if duplicates:
                errors.append(
                    f"{path.name}: дублирующиеся колонки: {', '.join(duplicates)}"
                )
                return []

            missing = [c for c in required_columns if c not in headers]
            if missing:
                errors.append(
                    f"{path.name}: отсутствуют обязательные колонки: {', '.join(missing)}"
                )
                return []

            rows: List[Tuple[int, Dict[str, str]]] = []
            for raw in reader:
                if None in raw:
                    errors.append(
                        f"{path.name}: строка {reader.line_num}: больше значений, "
                        "чем колонок"
                    )
                    continue
                row = {
                    str(key).strip(): (value or "").strip()
                    for key, value in raw.items()
                    if key is not None
                }
                if not any(row.values()):
                    continue
                rows.append((reader.line_num, row))
            return rows
    except UnicodeDecodeError:
        errors.append(f"{path.name}: файл должен быть в кодировке UTF-8")
        return []
    except OSError as exc:
        errors.append(f"{path.name}: не удалось прочитать файл: {exc}")
        return []


def _load_contracts(
    path: Path, errors: List[str]
) -> List[Contract]:
    rows = _read_rows(path, CONTRACT_COLUMNS, errors)
    contracts: List[Contract] = []
    seen: Set[str] = set()

    for line, row in rows:
        where = f"contracts.csv, строка {line}"
        contract_id = row.get("contract_id", "")
        contractor = row.get("contractor", "")
        if not contract_id:
            errors.append(f"{where}: поле contract_id обязательно")
            continue
        if contract_id in seen:
            errors.append(f"{where}: дублирующийся contract_id {contract_id!r}")
            continue
        if not contractor:
            errors.append(f"{where}: поле contractor обязательно")
            continue

        amount = _parse_money(row.get("amount", ""), "amount", where, errors)
        signed_at = _parse_date(
            row.get("signed_at", ""), "signed_at", where, errors, required=True
        )
        if amount is None or signed_at is None:
            continue

        seen.add(contract_id)
        contracts.append(Contract(contract_id, contractor, amount, signed_at))

    return contracts


def _load_works(path: Path, errors: List[str]) -> List[Work]:
    rows = _read_rows(path, WORK_COLUMNS, errors)
    works: List[Work] = []
    seen: Set[str] = set()

    for line, row in rows:
        where = f"works.csv, строка {line}"
        work_id = row.get("work_id", "")
        contract_id = row.get("contract_id", "")
        title = row.get("title", "")
        status = row.get("status", "")

        if not work_id:
            errors.append(f"{where}: поле work_id обязательно")
            continue
        if work_id in seen:
            errors.append(f"{where}: дублирующийся work_id {work_id!r}")
            continue
        if not contract_id:
            errors.append(f"{where}: поле contract_id обязательно")
            continue
        if not title:
            errors.append(f"{where}: поле title обязательно")
            continue
        if status not in WORK_STATUSES:
            errors.append(
                f"{where}: неизвестный статус работы {status!r}; "
                f"допустимо: {', '.join(sorted(WORK_STATUSES))}"
            )
            continue

        price = _parse_money(row.get("price", ""), "price", where, errors)
        completed_at = _parse_date(
            row.get("completed_at", ""),
            "completed_at",
            where,
            errors,
            required=(status == "done"),
        )
        cancelled_at = _parse_date(
            row.get("cancelled_at", ""),
            "cancelled_at",
            where,
            errors,
            required=(status == "cancelled"),
        )
        if price is None:
            continue
        if status == "done" and completed_at is None:
            continue
        if status == "cancelled" and cancelled_at is None:
            continue

        seen.add(work_id)
        works.append(
            Work(
                work_id,
                contract_id,
                title,
                price,
                status,
                completed_at,
                cancelled_at,
            )
        )

    return works


def _load_payments(path: Path, errors: List[str]) -> List[Payment]:
    rows = _read_rows(path, PAYMENT_COLUMNS, errors)
    payments: List[Payment] = []
    seen: Set[str] = set()

    for line, row in rows:
        where = f"payments.csv, строка {line}"
        payment_id = row.get("payment_id", "")
        contract_id = row.get("contract_id", "")
        work_id = row.get("work_id", "") or None
        purpose = row.get("purpose", "")
        status = row.get("status", "")

        if not payment_id:
            errors.append(f"{where}: поле payment_id обязательно")
            continue
        if payment_id in seen:
            errors.append(f"{where}: дублирующийся payment_id {payment_id!r}")
            continue
        if not contract_id:
            errors.append(f"{where}: поле contract_id обязательно")
            continue
        if status not in PAYMENT_STATUSES:
            errors.append(
                f"{where}: неизвестный статус платежа {status!r}; "
                f"допустимо: {', '.join(sorted(PAYMENT_STATUSES))}"
            )
            continue

        amount = _parse_money(row.get("amount", ""), "amount", where, errors)
        created_at = _parse_date(
            row.get("created_at", ""), "created_at", where, errors, required=True
        )
        paid_at = _parse_date(
            row.get("paid_at", ""),
            "paid_at",
            where,
            errors,
            required=(status in {"paid", "refunded"}),
        )
        refunded_at = _parse_date(
            row.get("refunded_at", ""),
            "refunded_at",
            where,
            errors,
            required=(status == "refunded"),
        )
        if amount is None or created_at is None:
            continue
        if status in {"paid", "refunded"} and paid_at is None:
            continue
        if status == "refunded" and refunded_at is None:
            continue

        chronology_error = False
        if paid_at is not None and paid_at < created_at:
            errors.append(
                f"{where}: paid_at {paid_at.isoformat()} раньше "
                f"created_at {created_at.isoformat()}"
            )
            chronology_error = True
        if status == "queued" and paid_at is not None:
            errors.append(
                f"{where}: для статуса queued поле paid_at должно быть пустым, "
                f"получено {paid_at.isoformat()}"
            )
            chronology_error = True
        if (
            refunded_at is not None
            and paid_at is not None
            and refunded_at < paid_at
        ):
            errors.append(
                f"{where}: refunded_at {refunded_at.isoformat()} раньше "
                f"paid_at {paid_at.isoformat()}"
            )
            chronology_error = True
        if chronology_error:
            continue

        seen.add(payment_id)
        payments.append(
            Payment(
                payment_id,
                contract_id,
                work_id,
                purpose,
                amount,
                status,
                created_at,
                paid_at,
                refunded_at,
            )
        )

    return payments


def load_dataset(data_dir: Path) -> Dataset:
    """Читает три CSV и проверяет структуру и ссылки."""

    data_dir = Path(data_dir)
    errors: List[str] = []

    contracts = _load_contracts(data_dir / "contracts.csv", errors)
    works = _load_works(data_dir / "works.csv", errors)
    payments = _load_payments(data_dir / "payments.csv", errors)

    if errors:
        raise DataError(errors)

    contract_ids = {c.contract_id for c in contracts}
    work_by_id = {w.work_id: w for w in works}

    for work in works:
        if work.contract_id not in contract_ids:
            errors.append(
                f"works.csv: работа {work.work_id} ссылается на "
                f"несуществующий договор {work.contract_id}"
            )

    for payment in payments:
        if payment.contract_id not in contract_ids:
            errors.append(
                f"payments.csv: платёж {payment.payment_id} ссылается на "
                f"несуществующий договор {payment.contract_id}"
            )
        if payment.work_id is not None:
            work = work_by_id.get(payment.work_id)
            if work is None:
                errors.append(
                    f"payments.csv: платёж {payment.payment_id} ссылается на "
                    f"несуществующую работу {payment.work_id}"
                )
            elif work.contract_id != payment.contract_id:
                errors.append(
                    f"payments.csv: платёж {payment.payment_id} относится к договору "
                    f"{payment.contract_id}, а работа {payment.work_id} — к договору "
                    f"{work.contract_id}"
                )

    if errors:
        raise DataError(errors)

    return Dataset(contracts, works, payments)
