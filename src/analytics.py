import json

import pandas as pd
from sqlalchemy import bindparam, text

from src.db import get_engine


DIMENSIONS = {'region', 'state', 'city', 'category_name', 'product_id',
              'seller_state', 'seller_id', 'year', 'quarter', 'month', 'full_date'}
MEASURES = {
    'merchandise_cents': 'COALESCE(SUM(merchandise_cents), 0)',
    'freight_cents': 'COALESCE(SUM(freight_cents), 0)',
    'total_revenue_cents': 'COALESCE(SUM(total_revenue_cents), 0)',
    'quantity': 'COALESCE(SUM(quantity), 0)',
    'orders': 'COUNT(DISTINCT order_id)',
    'customers': 'COUNT(DISTINCT customer_unique_id)',
}
MEASURE_SQL = ', '.join(f'{expression} AS {name}' for name, expression in MEASURES.items())


def scope_where(scope):
    params = {'start': pd.Timestamp(scope['start']).date(), 'end': pd.Timestamp(scope['end']).date()}
    clauses, bindings = ['full_date >= :start', 'full_date <= :end'], []
    for name, column in [('categories', 'category_name'), ('regions', 'region'),
                         ('states', 'state'), ('sellers', 'seller_id')]:
        values = sorted(set(scope.get(name, ())))
        if values:
            params[name] = values
            clauses.append(f'{column} IN :{name}')
            bindings.append(bindparam(name, expanding=True))
    search = str(scope.get('order_search') or '').strip().lower()
    if search:
        # Substring search on order_id; '!' escapes LIKE wildcards typed by the user.
        params['order_search'] = '%' + ''.join('!' + ch if ch in '!%_' else ch for ch in search) + '%'
        clauses.append("LOWER(order_id) LIKE :order_search ESCAPE '!'")
    return ' AND '.join(clauses), params, bindings


def query_frame(url, sql, scope, extra_params=None):
    where, params, bindings = scope_where(scope)
    statement = text(sql.format(where=where)).bindparams(*bindings)
    engine = get_engine(url)
    try:
        with engine.connect() as conn:
            result = pd.read_sql(statement, conn, params=params | (extra_params or {}))
        for column in MEASURES.keys() & set(result.columns):
            result[column] = result[column].astype('int64')
        return result
    finally:
        engine.dispose()


def filter_options(url):
    engine = get_engine(url)
    try:
        with engine.connect() as conn:
            bounds = conn.execute(text('SELECT MIN(full_date), MAX(full_date) FROM vw_sales_detail')).one()
            result = {'start': pd.Timestamp(bounds[0]), 'end': pd.Timestamp(bounds[1])}
            for name, column in [('categories', 'category_name'), ('sellers', 'seller_id')]:
                result[name] = list(conn.execute(text(f'SELECT DISTINCT {column} FROM vw_sales_detail ORDER BY {column}')).scalars())
            result['geography'] = pd.read_sql(text('SELECT DISTINCT region, state FROM vw_sales_detail ORDER BY region, state'), conn)
            return result
    finally:
        engine.dispose()


def sql_metrics(url, scope):
    result = query_frame(url, f'SELECT {MEASURE_SQL}, COUNT(*) AS fact_rows FROM vw_sales_detail WHERE {{where}}', scope)
    return {key: int(value) for key, value in result.iloc[0].items()}


def sql_aggregate(url, scope, columns):
    if not columns or not set(columns) <= DIMENSIONS or len(set(columns)) != len(columns):
        raise ValueError('Chiều phân tích không hợp lệ.')
    dimensions = ', '.join(columns)
    return query_frame(url, f'SELECT {dimensions}, {MEASURE_SQL} FROM vw_sales_detail '
                       f'WHERE {{where}} GROUP BY {dimensions} ORDER BY {dimensions}', scope)


def sql_rollup(url, scope, columns):
    if not columns or not set(columns) <= DIMENSIONS or len(set(columns)) != len(columns):
        raise ValueError('Cấp tổng hợp không hợp lệ.')
    engine = get_engine(url)
    try:
        dialect = engine.dialect.name
    finally:
        engine.dispose()
    dimensions = ', '.join(columns)
    if dialect == 'postgresql':
        depth = f"{len(columns)} - " + ' - '.join(f'GROUPING({column})' for column in columns)
        sql = (f'SELECT {dimensions}, {MEASURE_SQL}, {depth} AS grouping_depth '
               f'FROM vw_sales_detail WHERE {{where}} GROUP BY ROLLUP ({dimensions})')
    else:
        levels = []
        for depth in range(len(columns) + 1):
            selected = ', '.join(column if i < depth else f'NULL AS {column}' for i, column in enumerate(columns))
            group = ' GROUP BY ' + ', '.join(columns[:depth]) if depth else ''
            levels.append(f'SELECT {selected}, {MEASURE_SQL}, {depth} AS grouping_depth '
                          f'FROM scoped{group}')
        source_columns = dimensions + ', merchandise_cents, freight_cents, total_revenue_cents, quantity, order_id, customer_unique_id'
        sql = f'WITH scoped AS (SELECT {source_columns} FROM vw_sales_detail WHERE {{where}}) ' + ' UNION ALL '.join(levels)
    return query_frame(url, sql, scope)


def sql_time_series(url, scope, level):
    freq = {'Ngày': 'D', 'Tháng': 'M', 'Quý': 'Q', 'Năm': 'Y'}[level]
    columns = {'Ngày': ['full_date'], 'Tháng': ['year', 'month'], 'Quý': ['year', 'quarter'], 'Năm': ['year']}[level]
    result = sql_aggregate(url, scope, columns)
    if level == 'Ngày':
        periods = pd.to_datetime(result.full_date).dt.to_period(freq)
    elif level == 'Quý':
        periods = pd.PeriodIndex(result.year.astype(str) + 'Q' + result.quarter.astype(str), freq=freq)
    elif level == 'Tháng':
        periods = pd.PeriodIndex(result.year.astype(str) + '-' + result.month.astype(str).str.zfill(2), freq=freq)
    else:
        periods = pd.PeriodIndex(result.year.astype(str), freq=freq)
    result = result[list(MEASURES)].set_axis(pd.PeriodIndex(periods, freq=freq))
    calendar = pd.period_range(scope['start'], scope['end'], freq=freq)
    result = result.reindex(calendar, fill_value=0).rename_axis('period').reset_index()
    result['period'] = result.period.astype(str)
    return result


def sql_pivot(url, scope, measure):
    if measure not in MEASURES:
        raise ValueError('Chỉ tiêu không hợp lệ.')
    grouped = sql_aggregate(url, scope, ['category_name', 'state'])
    return grouped.pivot(index='category_name', columns='state', values=measure).fillna(0).astype('int64')


DETAIL_COLUMNS = ['order_id', 'order_item_id', 'full_date', 'category_name', 'product_id', 'seller_id',
                  'city', 'state', 'quantity', 'unit_price_cents', 'freight_cents', 'total_revenue_cents']


def sql_detail_count(url, scope):
    return int(query_frame(url, 'SELECT COUNT(*) AS fact_rows FROM vw_sales_detail WHERE {where}', scope).iloc[0, 0])


def sql_detail(url, scope, limit=None, offset=0):
    """Line items in scope, ordered by the natural key; one page when limit is given."""
    sql = f"SELECT {', '.join(DETAIL_COLUMNS)} FROM vw_sales_detail WHERE {{where}} ORDER BY order_id, order_item_id"
    extra = {}
    if limit is not None:
        if limit < 1 or offset < 0:
            raise ValueError('Phân trang không hợp lệ.')
        sql += ' LIMIT :limit OFFSET :offset'
        extra = {'limit': int(limit), 'offset': int(offset)}
    frame = query_frame(url, sql, scope, extra)
    frame['full_date'] = pd.to_datetime(frame['full_date'])
    # An empty result comes back as object columns; keep numeric types for display and CSV.
    for column in ['order_item_id', 'quantity', 'unit_price_cents', 'freight_cents', 'total_revenue_cents']:
        frame[column] = frame[column].astype('int64')
    return frame


def sql_daily_series(url, scope):
    """Daily quantity and money totals for the DSS; only days with sales are returned."""
    frame = query_frame(url, 'SELECT full_date, COALESCE(SUM(quantity), 0) AS quantity, '
                             'COALESCE(SUM(merchandise_cents), 0) AS merchandise_cents, '
                             'COALESCE(SUM(total_revenue_cents), 0) AS total_revenue_cents '
                             'FROM vw_sales_detail WHERE {where} GROUP BY full_date ORDER BY full_date', scope)
    frame['full_date'] = pd.to_datetime(frame['full_date'])
    return frame


def warehouse_version(url):
    engine = get_engine(url)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT run_id, finished_at, summary_json FROM etl_runs WHERE status='success' ORDER BY finished_at DESC LIMIT 1")).mappings().first()
            if row is None:
                raise ValueError('Kho dữ liệu chưa có lần nạp thành công.')
            return dict(row)
    finally:
        engine.dispose()


def audit_summary(version):
    return json.loads(version['summary_json'])
