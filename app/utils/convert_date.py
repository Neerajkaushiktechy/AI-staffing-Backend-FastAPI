from datetime import datetime, date
import dateparser

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


def extract_date_from_text(text: str) -> str | None:
    dt = dateparser.parse(text)
    if dt:
        return dt.strftime('%Y-%m-%d')
    return None