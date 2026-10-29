import os
import sqlite3
import sys

import requests
from corelib import AgentRunner, OpenAILLM

EXPENSES_DB = os.getenv("EXPENSES_DB", "expenses.db")


def get_weather(city: str) -> dict:
    """Current weather for a city (used for travel-expense context)."""
    r = requests.get(f"https://wttr.in/{city}", params={"format": "j1"}, timeout=10)
    cur = r.json()["current_condition"][0]
    return {"temp_c": cur["temp_C"], "desc": cur["weatherDesc"][0]["value"]}


def file_expense(employee_id: str, amount: float, category: str, memo: str = "") -> dict:
    """File a new expense claim."""
    with sqlite3.connect(EXPENSES_DB) as db:
        cur = db.execute(
            "INSERT INTO expenses (employee_id, amount, category, memo, status) VALUES (?, ?, ?, ?, 'submitted')",
            (employee_id, amount, category, memo),
        )
        return {"expense_id": cur.lastrowid}


def delete_expense(expense_id: int) -> dict:
    """Delete an expense claim that has not been approved yet."""
    with sqlite3.connect(EXPENSES_DB) as db:
        cur = db.execute("DELETE FROM expenses WHERE id = ? AND status != 'approved'", (expense_id,))
        return {"deleted": cur.rowcount}


def summarize_receipt_url(url: str) -> str:
    """Download a receipt page (e.g. an e-receipt link from an email) and return its text."""
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.text[:8000]


expense_runner = AgentRunner(
    llm=OpenAILLM("gpt-4o-mini"),
    tools=[get_weather, file_expense, delete_expense, summarize_receipt_url],
    system_prompt="You help employees file and manage expense claims. Never delete without confirmation.",
)

if __name__ == "__main__":
    print(expense_runner.run(" ".join(sys.argv[1:]) or "File a $42.50 meals expense for E-117"))
