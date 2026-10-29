import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import Ridge

NUMERIC = ['dow_sin', 'dow_cos', 'month_sin', 'month_cos', 'lag1', 'lag7', 'mean7', 'mean28']


def validate(frame):
    required = {'date', 'product_id', 'units'}
    if set(frame.columns) != required:
        raise ValueError('CSV must contain exactly: date,product_id,units')
    df = frame.copy()
    if df.isna().any().any():
        raise ValueError('Null values are forbidden')
    df['date'] = pd.to_datetime(df.date, format='%Y-%m-%d', errors='raise')
    df['product_id'] = df.product_id.astype(str)
    if df.product_id.str.strip().eq('').any():
        raise ValueError('Empty product_id')
    df['units'] = pd.to_numeric(df.units, errors='raise')
    if not np.isfinite(df.units).all() or (df.units < 0).any():
        raise ValueError('Units must be finite and nonnegative')
    if df.duplicated(['date', 'product_id']).any():
        raise ValueError('Duplicate date/product_id')
    for _, group in df.groupby('product_id'):
        dates = group.date.sort_values()
        if len(dates) < 70 or not dates.diff().dropna().eq(pd.Timedelta(days=1)).all():
            raise ValueError('Each product requires >=70 consecutive daily observations, including zero-sales days')
    if df.groupby('product_id').date.max().nunique() != 1:
        raise ValueError('Products must have the same last observation date')
    if df.date.max() > pd.Timestamp.now().normalize():
        raise ValueError('Future observations are forbidden')
    return df.sort_values(['product_id', 'date']).reset_index(drop=True)


def row(product, day, history):
    return {'product_id': product, 'dow_sin': np.sin(2*np.pi*day.dayofweek/7),
            'dow_cos': np.cos(2*np.pi*day.dayofweek/7),
            'month_sin': np.sin(2*np.pi*day.month/12), 'month_cos': np.cos(2*np.pi*day.month/12),
            'lag1': history[-1], 'lag7': history[-7],
            'mean7': np.mean(history[-7:]), 'mean28': np.mean(history[-28:])}


def features(df):
    rows, targets = [], []
    for product, group in df.groupby('product_id', sort=True):
        values = group.units.tolist()
        for i in range(28, len(group)):
            rows.append(row(product, group.date.iloc[i], values[:i]))
            targets.append(values[i])
    return pd.DataFrame(rows), np.array(targets)


def fit(df):
    x, y = features(df)
    transform = ColumnTransformer([('product', OneHotEncoder(handle_unknown='ignore', sparse_output=False), ['product_id']),
                                   ('numeric', StandardScaler(), NUMERIC)])
    model = make_pipeline(transform, Ridge(alpha=10.0))
    return model.fit(x, y)


def forecast(df, horizon, model=None):
    histories = {p: g.units.tolist() for p, g in df.groupby('product_id', sort=True)}
    last = df.date.max()
    records = []
    for step in range(1, horizon+1):
        day = last + pd.Timedelta(days=step)
        products = list(histories)
        if model is None:
            predictions = [histories[p][-7] for p in products]
        else:
            predictions = model.predict(pd.DataFrame([row(p, day, histories[p]) for p in products]))
        for p, prediction in zip(products, predictions):
            prediction = max(0.0, float(prediction))
            histories[p].append(prediction)
            records.append({'date': day.strftime('%Y-%m-%d'), 'product_id': p, 'prediction': prediction})
    return pd.DataFrame(records)


def scores(actual, predicted):
    error = np.abs(np.asarray(actual) - np.asarray(predicted))
    denominator = float(np.abs(actual).sum())
    return {'mae': float(error.mean()), 'wape': float(error.sum()/denominator) if denominator else None}


def select_model(df, holdout=14):
    cutoff = df.date.max()-pd.Timedelta(days=holdout)
    train, test = df[df.date <= cutoff], df[df.date > cutoff]
    candidate = fit(train)
    results = {}
    for name, model in [('ridge', candidate), ('seasonal_naive', None)]:
        predicted = forecast(train, holdout, model)
        actual = test.assign(date=test.date.dt.strftime('%Y-%m-%d'))
        joined = actual.merge(predicted, on=['date', 'product_id'], validate='one_to_one')
        results[name] = scores(joined.units.to_numpy(), joined.prediction.to_numpy())
    winner = min(results, key=lambda name: results[name]['mae'])
    return winner, results, fit(df) if winner == 'ridge' else None
