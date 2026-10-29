from pathlib import Path
import numpy as np
import pandas as pd


def generate(path, days=240, products=12, end=None):
    rng = np.random.default_rng(42)
    end = pd.Timestamp(end) if end else pd.Timestamp.now().normalize()-pd.Timedelta(days=1)
    records = []
    for p in range(products):
        base = 25 + 5*p
        for i, date in enumerate(pd.date_range(end=end, periods=days)):
            units = max(0, round(base + 0.06*i + 10*np.sin(2*np.pi*date.dayofweek/7) + rng.normal(0, 3)))
            records.append((date.strftime('%Y-%m-%d'), f'SKU-{p+1:03}', units))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records, columns=['date', 'product_id', 'units']).to_csv(path, index=False)
