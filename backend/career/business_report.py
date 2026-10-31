"""Print the business report (revenue, checkouts, members, employers, AI usage).

    python -m career.business_report     (on Render: Shell tab, from /app)
"""

from .db import Session
from .business import report, print_report


def main():
    with Session() as db:
        print_report(report(db))


if __name__ == "__main__":
    main()
