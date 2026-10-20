import pandas as pd
from src.utils import csv_bytes


def test_csv_is_utf8_bom_and_neutralizes_formula_text():
    result = csv_bytes(pd.DataFrame({"store": ["=1+1", "SKLC3"], "volume": [10, 20]}))
    assert result.startswith(b"\xef\xbb\xbf")
    text = result.decode("utf-8-sig")
    assert "'=1+1" in text
    assert "SKLC3" in text
