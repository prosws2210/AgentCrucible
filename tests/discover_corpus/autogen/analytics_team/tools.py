import os
import smtplib
import sqlite3
from email.message import EmailMessage
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

WAREHOUSE_DB = os.getenv("WAREHOUSE_DB", "warehouse.sqlite3")
CHART_DIR = Path(os.getenv("CHART_DIR", "charts"))
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.sendgrid.net")


async def run_sql_query(sql: str) -> str:
    """Run a read-only SELECT query against the analytics warehouse and return rows as CSV."""
    if not sql.lstrip().lower().startswith("select"):
        return "Only SELECT statements are allowed."
    conn = sqlite3.connect(f"file:{WAREHOUSE_DB}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        header = ",".join(d[0] for d in cur.description)
        rows = "\n".join(",".join(map(str, r)) for r in cur.fetchmany(200))
    finally:
        conn.close()
    return f"{header}\n{rows}"


async def save_chart(title: str, labels: list[str], values: list[float]) -> str:
    """Render a bar chart and save it as PNG. Returns the file path."""
    CHART_DIR.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, values)
    ax.set_title(title)
    path = CHART_DIR / f"{title.lower().replace(' ', '_')}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return str(path)


async def send_email(to: str, subject: str, body: str, attachment_path: str | None = None) -> str:
    """Email a report to a stakeholder, optionally attaching a chart."""
    msg = EmailMessage()
    msg["From"] = "analytics-bot@acme.example"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment_path:
        data = Path(attachment_path).read_bytes()
        msg.add_attachment(data, maintype="image", subtype="png", filename=Path(attachment_path).name)
    with smtplib.SMTP(SMTP_HOST, 587) as smtp:
        smtp.starttls()
        smtp.login("apikey", os.environ["SENDGRID_API_KEY"])
        smtp.send_message(msg)
    return f"sent to {to}"
