"""Central currency configuration and formatting for the POS."""

import json
from pathlib import Path

from typing import Optional
from database.db import get_database_manager


class CurrencyService:
    """Read and format monetary values using the current POS preference."""

    CODES = ("USD", "ZWL")
    SYMBOLS = {"USD": "$", "ZWL": "ZWL"}

    def __init__(self, db=None):
        self.db = db or get_database_manager()

    def current_code(self) -> str:
        row = self.db.execute_query(
            "SELECT value FROM settings WHERE key='currency' LIMIT 1"
        )
        if row and row[0]["value"] in self.CODES:
            return row[0]["value"]
        try:
            config_path = (
                Path(__file__).resolve().parent.parent / "config.json"
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            code = str(config.get("default_currency") or "ZWL").upper()
            return code if code in self.CODES else "ZWL"
        except (OSError, ValueError, TypeError):
            return "ZWL"

    def format_money(
        self, value: float, currency: Optional[str] = None
    ) -> str:
        code = (currency or self.current_code()).upper()
        return f"{self.SYMBOLS.get(code, code)} {float(value):,.2f}"
