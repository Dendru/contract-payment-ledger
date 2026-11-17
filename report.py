"""CLI для отчёта по работам и договорам."""

import argparse
import sys
from datetime import date
from pathlib import Path

from ledger import DataError, build_report, load_dataset
from ledger.render import print_summary, write_reports


def _as_of(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"дата должна быть в формате YYYY-MM-DD, получено {value!r}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Отчёт: выплачено и осталось оплатить по работам и договорам."
    )
    parser.add_argument(
        "--data",
        default="data",
        help="папка с contracts.csv, works.csv, payments.csv (по умолчанию data)",
    )
    parser.add_argument(
        "--as-of",
        required=True,
        type=_as_of,
        help="дата отчёта, YYYY-MM-DD",
    )
    parser.add_argument(
        "--out",
        default="out",
        help="папка для CSV-файлов отчёта (по умолчанию out)",
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)

    try:
        dataset = load_dataset(Path(args.data))
        report = build_report(dataset, args.as_of)
        write_reports(report, Path(args.out))
    except DataError as exc:
        print("Ошибка входных данных:", file=sys.stderr)
        for message in exc.messages:
            print(f"  - {message}", file=sys.stderr)
        return 2
    except Exception as exc:  # понятное сообщение вместо traceback
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    print_summary(report)
    print(f"CSV записаны в: {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
