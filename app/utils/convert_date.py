from datetime import datetime, date

def normalize_to_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"Invalid date string format: {value}. Expected 'YYYY-MM-DD'.")
    raise TypeError(f"Unsupported date type: {type(value)}")
