from agents import Agent

from .tools import check_status, lookup_invoice, refund_payment, reset_password

billing_agent = Agent(
    name="Billing Specialist",
    handoff_description="Handles invoices, charges and refunds.",
    instructions="Look up the invoice first. Refund only when the customer was charged in error.",
    model="gpt-4.1",
    tools=[lookup_invoice, refund_payment],
)

tech_agent = Agent(
    name="Tech Support",
    handoff_description="Handles outages, login problems and password resets.",
    instructions="Check service status before troubleshooting. Reset passwords only for the account owner.",
    model="gpt-4.1-mini",
    tools=[check_status, reset_password],
)
