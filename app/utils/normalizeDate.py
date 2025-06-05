from datetime import datetime, date
from typing import Union

def normalize_date(date_obj: Union[str, datetime, date]) -> str:
    if isinstance(date_obj, str):
        return date_obj.split("T")[0]
    return date_obj.strftime("%Y-%m-%d")
