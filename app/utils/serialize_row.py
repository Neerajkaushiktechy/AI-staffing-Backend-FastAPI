from decimal import Decimal
from datetime import date, datetime, time

def serialize_row(row):
    if not row:
        return None
    return {
        key: (
            str(value) if isinstance(value, (Decimal, date, datetime, time)) else value
        )
        for key, value in dict(row).items()
    }
