from datetime import datetime, date
from typing import Union

def convert_to_md(date_input: Union[str, datetime, date]) -> str:
    if isinstance(date_input, (datetime, date)):
        dt = date_input
    else:
        try:
            # Try parsing ISO or YYYY-MM-DD first
            dt = datetime.fromisoformat(date_input.split("T")[0])
        except ValueError:
            try:
                # Fallback for MM-DD-YYYY
                dt = datetime.strptime(date_input, "%m-%d-%Y")
            except ValueError:
                raise ValueError(f"Unsupported date format: {date_input}")

    return f"{dt.month}/{dt.day}"
