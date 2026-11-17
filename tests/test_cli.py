"""Интеграционные тесты CLI."""

import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, data=None, out=None):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, str(ROOT / "report.py")]
    if data is not None:
        command += ["--data", str(data)]
    command += ["--as-of", "2026-11-10"]
    if out is not None:
        command += ["--out", str(out)]
    command += list(args)
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def read_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


class CliTests(unittest.TestCase):
    def test_baseline_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            result = run_cli(data=ROOT / "data", out=out)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("выплачено 390 000.00", result.stdout)
            self.assertIn("W-23", result.stdout)

            contracts = {
                row["Договор"]: row for row in read_rows(out / "contracts.csv")
            }
            self.assertEqual(contracts["D-1"]["Выплачено"], "315000.00")
            self.assertEqual(
                contracts["D-1"]["Остаток по действующим"], "185000.00"
            )
            self.assertEqual(contracts["D-1"]["В очереди"], "150000.00")
            self.assertEqual(contracts["D-1"]["Переплата по работам"], "0.00")
            self.assertEqual(
                contracts["D-1"]["Нераспределённые платежи"], "0.00"
            )
            self.assertEqual(contracts["D-1"]["Переплата"], "0.00")
            self.assertEqual(contracts["D-2"]["Выплачено"], "75000.00")
            self.assertEqual(
                contracts["D-2"]["Остаток по действующим"], "15000.00"
            )
            self.assertEqual(contracts["D-2"]["После даты"], "20000.00")
            self.assertEqual(contracts["ИТОГО"]["Выплачено"], "390000.00")
            self.assertEqual(
                contracts["ИТОГО"]["Остаток по действующим"], "200000.00"
            )

            works = {
                row["Работа"]: row for row in read_rows(out / "works.csv")
            }
            self.assertEqual(works["W-14"]["Прямые"], "15000.00")
            self.assertEqual(works["W-14"]["Из общих"], "85000.00")
            self.assertEqual(works["W-14"]["Зачтено в счёт цены"], "100000.00")
            self.assertEqual(works["W-23"]["Состояние на дату"], "не принята")
            self.assertEqual(works["W-23"]["Осталось оплатить"], "15000.00")

            payments = {
                row["Платёж"]: row for row in read_rows(out / "payments.csv")
            }
            self.assertEqual(payments["P-2"]["Категория на дату"], "возвращён")
            self.assertEqual(payments["P-4"]["Категория на дату"], "в очереди")
            self.assertEqual(payments["P-8"]["Категория на дату"], "после даты")
            self.assertEqual(payments["P-8"]["Net paid"], "0.00")

            self.assertTrue((out / "allocations.csv").exists())
            warnings = read_rows(out / "warnings.csv")
            self.assertTrue(
                any(row["Код"] == "WORK_DONE_AFTER_REPORT" for row in warnings)
            )

    def test_direct_overpayment_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            write_csv(
                data / "contracts.csv",
                ["contract_id", "contractor", "amount", "signed_at"],
                [["C-1", "Подрядчик", "200.00", "2026-01-01"]],
            )
            write_csv(
                data / "works.csv",
                [
                    "work_id",
                    "contract_id",
                    "title",
                    "price",
                    "status",
                    "completed_at",
                    "cancelled_at",
                ],
                [
                    ["W-1", "C-1", "Первая", "100.00", "done", "2026-01-02", ""],
                    ["W-2", "C-1", "Вторая", "100.00", "planned", "", ""],
                ],
            )
            write_csv(
                data / "payments.csv",
                [
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
                [
                    [
                        "P-1",
                        "C-1",
                        "W-1",
                        "Прямой платёж",
                        "120.00",
                        "paid",
                        "2026-01-01",
                        "2026-01-02",
                        "",
                    ]
                ],
            )

            out = Path(tmp) / "out"
            result = run_cli(data=data, out=out)
            self.assertEqual(result.returncode, 0, result.stderr)

            contracts = {
                row["Договор"]: row for row in read_rows(out / "contracts.csv")
            }
            c = contracts["C-1"]
            self.assertEqual(c["Выплачено"], "120.00")
            self.assertEqual(c["Зачтено в действующие"], "100.00")
            self.assertEqual(c["Остаток по действующим"], "100.00")
            self.assertEqual(c["Переплата по работам"], "20.00")
            self.assertEqual(c["Нераспределённые платежи"], "0.00")
            self.assertEqual(c["Переплата"], "20.00")

            works = {
                row["Работа"]: row for row in read_rows(out / "works.csv")
            }
            self.assertEqual(works["W-1"]["Выплачено всего"], "120.00")
            self.assertEqual(works["W-1"]["Зачтено в счёт цены"], "100.00")
            self.assertEqual(works["W-1"]["Осталось оплатить"], "0.00")
            self.assertEqual(works["W-1"]["Переплата"], "20.00")
            self.assertEqual(works["W-2"]["Осталось оплатить"], "100.00")

    def test_repeat_run_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            out1 = Path(tmp) / "out1"
            out2 = Path(tmp) / "out2"
            first = run_cli(data=ROOT / "data", out=out1)
            second = run_cli(data=ROOT / "data", out=out2)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            for name in (
                "contracts.csv",
                "works.csv",
                "payments.csv",
                "allocations.csv",
                "warnings.csv",
            ):
                self.assertEqual(
                    (out1 / name).read_bytes(),
                    (out2 / name).read_bytes(),
                    name,
                )

    def test_structural_error_has_no_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_data = Path(tmp) / "data"
            shutil.copytree(ROOT / "data", bad_data)
            with (bad_data / "works.csv").open("a", encoding="utf-8") as handle:
                handle.write("W-11,D-1,Дубль,100000.00,planned,,\n")
            out = Path(tmp) / "out"
            result = run_cli(data=bad_data, out=out)
            self.assertEqual(result.returncode, 2)
            self.assertIn("Ошибка входных данных", result.stderr)
            self.assertIn("дублирующийся work_id", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_bad_date_has_no_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "report.py"),
                    "--data",
                    str(ROOT / "data"),
                    "--as-of",
                    "2026-13-01",
                    "--out",
                    str(Path(tmp) / "out"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("дата должна быть", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_missing_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(
                data=Path(tmp) / "missing",
                out=Path(tmp) / "out",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Файл не найден", result.stderr)


if __name__ == "__main__":
    unittest.main()
