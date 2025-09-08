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


# def extract_date_from_text(text: str) -> str | None:
#     dt = dateparser.parse(text)
#     if dt:
#         return dt.strftime('%Y-%m-%d')
#     return None

def extract_date_from_text(text: str) -> date | None:
    # Step 1: Try strict parsing with dateparser
    dt = dateparser.parse(text, settings={"STRICT_PARSING": True})
    if dt:
        return dt.date()

    # Step 2: Try common manual formats
    formats = ["%m/%d", "%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt).date()
            # If year is missing, assume current year
            if "%Y" not in fmt:
                parsed = parsed.replace(year=datetime.now().year)
            return parsed
        except ValueError:
            continue
    return None