from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging() -> None:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            RotatingFileHandler(
                log_dir / "wifi_guardian.log",
                maxBytes=2_000_000,
                backupCount=3,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    configure_logging()
    try:
        from PySide6.QtWidgets import QApplication
        from wifi_guardian.ui.main_window import MainWindow
    except ImportError as exc:
        print(
            "Thiếu thư viện. Hãy chạy: python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        logging.getLogger(__name__).exception("Không thể nạp thư viện")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("WiFi Guardian")
    app.setOrganizationName("WiFi Guardian")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

