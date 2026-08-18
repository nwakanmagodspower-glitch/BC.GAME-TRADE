from __future__ import annotations

from app.core.database import SessionLocal
from app.services.paper_validation import PaperValidationService


def main() -> None:
    with SessionLocal() as db:
        report = PaperValidationService(db).build_report()

    print('BC.GAME TRADE — M11 PAPER PRODUCTION VALIDATION')
    print(f'Total scans: {report.total_scans}')
    print(f'Directional signals: {report.directional_signals}')
    print(f'No trade: {report.no_trade}')
    print(f'Waiting: {report.waiting} | Active: {report.active} | Cancelled: {report.cancelled}')
    print(f'Settled: {report.settled} | Wins: {report.wins} | Losses: {report.losses} | Ties: {report.ties}')
    print(f'Average entry timing delay: {report.avg_entry_delay_seconds}')
    print(f'Max entry timing delay: {report.max_entry_delay_seconds}')
    print(f'Missing entry prices: {report.missing_entry_prices}')
    print(f'Missing expiry prices: {report.missing_expiry_prices}')
    print(f'Strategy versions: {", ".join(report.strategy_versions) or "none"}')
    print(f'Passable: {report.passable}')
    if report.blockers:
        print('Blockers:')
        for blocker in report.blockers:
            print(f'- {blocker}')


if __name__ == '__main__':
    main()
