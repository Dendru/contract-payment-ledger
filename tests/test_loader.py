"""Тесты загрузки и структурной проверки CSV."""

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ledger.loader import DataError, load_dataset

HEADERS = {
    "contracts.csv": ["contract_id", "contractor", "amount", "signed_at"],
    "works.csv": [
        "work_id",
        "contract_id",
        "title",
        "price",
        "status",
        "completed_at",
        "cancelled_at",
    ],
    "payments.csv": [
        "payment_id",
        "contract_id",
        "work_id",
        "purpose",
        "amount",
        "status",
        "created_at",
        "paid_at",
        "refunded_at",
    ],
}


def write_csv(path: Path, headers, rows, delimiter=","):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


def make_data(root: Path):
    write_csv(
        root / "contracts.csv",
        HEADERS["contracts.csv"],
        [["C-1", "Иван, дизайнер", "1000.00", "2026-01-01"]],
    )
    write_csv(
        root / "works.csv",
        HEADERS["works.csv"],
        [["W-1", "C-1", "Работа", "1000.00", "done", "2026-01-02", ""]],
    )
    write_csv(
        root / "payments.csv",
        HEADERS["payments.csv"],
        [
            [
                "P-1",
                "C-1",
                "",
                "Оплата",
                "1000.00",
                "paid",
                "2026-01-01",
                "2026-01-02",
                "",
            ]
        ],
    )


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_data(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def load(self):
        return load_dataset(self.root)

    def assert_error(self, fragment):
        with self.assertRaises(DataError) as ctx:
            self.load()
        text = " ".join(ctx.exception.messages)
        self.assertIn(fragment, text)

    def test_valid_data_and_quoted_comma(self):
        dataset = self.load()
        self.assertEqual(len(dataset.contracts), 1)
        self.assertEqual(dataset.contracts[0].contractor, "Иван, дизайнер")
        self.assertEqual(dataset.contracts[0].amount, 1000)
        self.assertEqual(dataset.works[0].work_id, "W-1")
        self.assertEqual(dataset.payments[0].payment_id, "P-1")

    def test_duplicate_contract_id(self):
        write_csv(
            self.root / "contracts.csv",
            HEADERS["contracts.csv"],
            [
                ["C-1", "A", "1000.00", "2026-01-01"],
                ["C-1", "B", "1000.00", "2026-01-01"],
            ],
        )
        self.assert_error("дублирующийся contract_id")

    def test_duplicate_work_id(self):
        write_csv(
            self.root / "works.csv",
            HEADERS["works.csv"],
            [
                ["W-1", "C-1", "A", "1000.00", "planned", "", ""],
                ["W-1", "C-1", "B", "1000.00", "planned", "", ""],
            ],
        )
        self.assert_error("дублирующийся work_id")

    def test_unknown_work_status(self):
        write_csv(
            self.root / "works.csv",
            HEADERS["works.csv"],
            [["W-1", "C-1", "A", "1000.00", "in_progress", "", ""]],
        )
        self.assert_error("неизвестный статус работы")

    def test_unknown_payment_status(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "",
                    "A",
                    "1000.00",
                    "cancelled",
                    "2026-01-01",
                    "",
                    "",
                ]
            ],
        )
        self.assert_error("неизвестный статус платежа")

    def test_bad_date(self):
        write_csv(
            self.root / "contracts.csv",
            HEADERS["contracts.csv"],
            [["C-1", "A", "1000.00", "2026-13-01"]],
        )
        self.assert_error("должно быть датой YYYY-MM-DD")

    def test_bad_amount(self):
        write_csv(
            self.root / "contracts.csv",
            HEADERS["contracts.csv"],
            [["C-1", "A", "1000.123", "2026-01-01"]],
        )
        self.assert_error("не более чем с 2 знаками")

    def test_negative_amount(self):
        write_csv(
            self.root / "contracts.csv",
            HEADERS["contracts.csv"],
            [["C-1", "A", "-1.00", "2026-01-01"]],
        )
        self.assert_error("не может быть отрицательным")

    def test_missing_contract_reference(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-X",
                    "",
                    "A",
                    "1000.00",
                    "paid",
                    "2026-01-01",
                    "2026-01-02",
                    "",
                ]
            ],
        )
        self.assert_error("несуществующий договор")

    def test_missing_work_reference(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "W-X",
                    "A",
                    "1000.00",
                    "paid",
                    "2026-01-01",
                    "2026-01-02",
                    "",
                ]
            ],
        )
        self.assert_error("несуществующую работу")

    def test_work_from_other_contract(self):
        write_csv(
            self.root / "contracts.csv",
            HEADERS["contracts.csv"],
            [
                ["C-1", "A", "1000.00", "2026-01-01"],
                ["C-2", "B", "1000.00", "2026-01-01"],
            ],
        )
        write_csv(
            self.root / "works.csv",
            HEADERS["works.csv"],
            [
                ["W-1", "C-1", "A", "1000.00", "planned", "", ""],
                ["W-2", "C-2", "B", "1000.00", "planned", "", ""],
            ],
        )
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "W-2",
                    "A",
                    "1000.00",
                    "paid",
                    "2026-01-01",
                    "2026-01-02",
                    "",
                ]
            ],
        )
        self.assert_error("относится к договору")

    def test_missing_column(self):
        write_csv(
            self.root / "contracts.csv",
            ["contract_id", "contractor", "amount"],
            [["C-1", "A", "1000.00"]],
        )
        self.assert_error("отсутствуют обязательные колонки")

    def test_missing_file(self):
        (self.root / "contracts.csv").unlink()
        self.assert_error("Файл не найден")

    def test_paid_without_paid_at(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "",
                    "A",
                    "1000.00",
                    "paid",
                    "2026-01-01",
                    "",
                    "",
                ]
            ],
        )
        self.assert_error("поле paid_at обязательно")

    def test_refunded_without_refunded_at(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "",
                    "A",
                    "1000.00",
                    "refunded",
                    "2026-01-01",
                    "2026-01-02",
                    "",
                ]
            ],
        )
        self.assert_error("поле refunded_at обязательно")

    def test_refunded_without_paid_at(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "",
                    "A",
                    "1000.00",
                    "refunded",
                    "2026-01-01",
                    "",
                    "2026-01-02",
                ]
            ],
        )
        self.assert_error("поле paid_at обязательно")

    def test_paid_at_before_created_at(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "",
                    "A",
                    "1000.00",
                    "paid",
                    "2026-01-05",
                    "2026-01-04",
                    "",
                ]
            ],
        )
        self.assert_error("раньше created_at")

    def test_refunded_at_before_paid_at(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "",
                    "A",
                    "1000.00",
                    "refunded",
                    "2026-01-01",
                    "2026-01-05",
                    "2026-01-04",
                ]
            ],
        )
        self.assert_error("раньше paid_at")

    def test_queued_with_paid_at(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "",
                    "A",
                    "1000.00",
                    "queued",
                    "2026-01-01",
                    "2026-01-02",
                    "",
                ]
            ],
        )
        self.assert_error("для статуса queued поле paid_at должно быть пустым")

    def test_same_day_payment_is_valid(self):
        write_csv(
            self.root / "payments.csv",
            HEADERS["payments.csv"],
            [
                [
                    "P-1",
                    "C-1",
                    "",
                    "A",
                    "1000.00",
                    "paid",
                    "2026-01-02",
                    "2026-01-02",
                    "",
                ]
            ],
        )
        dataset = self.load()
        self.assertEqual(len(dataset.payments), 1)
        self.assertEqual(dataset.payments[0].paid_at, date(2026, 1, 2))


if __name__ == "__main__":
    unittest.main()
