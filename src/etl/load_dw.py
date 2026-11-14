import argparse
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import pandas as pd
from sqlalchemy import text

from src.db import ROOT, execute_file, get_engine, sql_statements
from src.etl.staging import stage

REGIONS = {state: region for region, states in {
    'North': 'AC AP AM PA RO RR TO', 'Northeast': 'AL BA CE MA PB PE PI RN SE',
    'Central-West': 'DF GO MT MS', 'Southeast': 'ES MG RJ SP', 'South': 'PR RS SC'
}.items() for state in states.split()}


def cents(value):
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number * 100 != (number * 100).to_integral_value():
            return None
        result = int(number * 100)
        return result if result <= 10**12 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def optional_integer(value):
    if not value:
        return None
    try:
        number = Decimal(value)
        return int(number) if number.is_finite() and 0 <= number <= 2147483647 and number == number.to_integral_value() else None
    except InvalidOperation:
        return None


def unique_source(frame, key, name):
    frame = frame.drop(columns='source_row').drop_duplicates()
    if (frame[key] == '').any() or frame.duplicated(key).any():
        raise ValueError(f'{name}: empty or conflicting natural key {key}')
    return frame


def transform(frames):
    tables = {name: frame.map(lambda x: x.strip() if isinstance(x, str) else x)
              for name, frame in frames.items()}
    for name, prefix in [('customers', 'customer'), ('sellers', 'seller')]:
        tables[name][prefix + '_city'] = tables[name][prefix + '_city'].str.lower().str.replace(r'\s+', ' ', regex=True).replace('', 'unknown')
        tables[name][prefix + '_state'] = tables[name][prefix + '_state'].str.upper()
    keys = {'orders': 'order_id', 'customers': 'customer_id', 'products': 'product_id',
            'sellers': 'seller_id', 'categories': 'product_category_name'}
    dims = {name: unique_source(tables[name], key, name) for name, key in keys.items()}
    orders = dims['orders'].set_index('order_id')
    orders['purchase_date'] = pd.to_datetime(orders['order_purchase_timestamp'], errors='coerce')
    customers = dims['customers'].set_index('customer_id')
    products = dims['products'].set_index('product_id')
    sellers = dims['sellers'].set_index('seller_id')
    categories = dims['categories'].set_index('product_category_name')['product_category_name_english'].to_dict()
    items = tables['items'].copy()
    items['order_item_id'] = items['order_item_id'].map(
        lambda x: str(int(x)) if re.fullmatch(r'\d{1,10}', x) and 0 < int(x) <= 2147483647 else '')
    duplicate = items.drop(columns='source_row').duplicated()
    conflict = items.loc[~duplicate].duplicated(['order_id', 'order_item_id'], keep=False)
    bad_keys = set(map(tuple, items.loc[conflict.index[conflict], ['order_id', 'order_item_id']].values))
    clean, audit = [], []
    for row in items.to_dict('records'):
        price, freight = cents(row['price']), cents(row['freight_value'])
        disposition = 'accepted'
        order_id, item_id = row['order_id'], row['order_item_id']
        idx = row['source_row'] - 2
        order = orders.loc[order_id] if order_id in orders.index else None
        customer = customers.loc[order['customer_id']] if order is not None and order['customer_id'] in customers.index else None
        product = products.loc[row['product_id']] if row['product_id'] in products.index else None
        seller = sellers.loc[row['seller_id']] if row['seller_id'] in sellers.index else None
        purchased = order['purchase_date'] if order is not None else pd.NaT
        if not order_id or not item_id:
            disposition = 'invalid_item_key'
        elif (order_id, item_id) in bad_keys:
            disposition = 'conflicting_item'
        elif duplicate.iloc[idx]:
            disposition = 'duplicate_item'
        elif order is None:
            disposition = 'missing_order'
        elif order['order_status'].lower() != 'delivered':
            disposition = 'excluded_order_status'
        elif customer is None or product is None or seller is None:
            disposition = 'missing_dimension'
        elif not customer['customer_unique_id']:
            disposition = 'missing_customer_identity'
        elif customer['customer_state'] not in REGIONS or seller['seller_state'] not in REGIONS:
            disposition = 'invalid_state'
        elif pd.isna(purchased):
            disposition = 'invalid_purchase_date'
        elif price is None or freight is None:
            disposition = 'invalid_money'
        else:
            clean.append({
                'order_id': order_id, 'order_item_id': int(item_id), 'full_date': purchased.date(),
                'customer_unique_id': customer['customer_unique_id'],
                'customer_city': customer['customer_city'], 'customer_state': customer['customer_state'],
                'product_id': row['product_id'],
                'category_name': categories.get(product['product_category_name']) or product['product_category_name'] or 'Unknown',
                'product_weight_g': optional_integer(product['product_weight_g']),
                'product_length_cm': optional_integer(product['product_length_cm']),
                'seller_id': row['seller_id'], 'seller_city': seller['seller_city'], 'seller_state': seller['seller_state'],
                'unit_price_cents': price, 'freight_cents': freight, 'total_revenue_cents': price + freight,
            })
        audit.append({'source_row': row['source_row'], 'order_id': order_id, 'order_item_id': item_id,
                      'disposition': disposition, 'price_cents': price, 'freight_cents': freight})
    if not clean:
        raise ValueError('No valid delivered order items; warehouse was not replaced')
    return pd.DataFrame(clean), pd.DataFrame(audit)


def records(frame):
    return frame.astype(object).where(pd.notna(frame), None).to_dict('records')


def insert_rows(conn, table, rows, conflict=''):
    if not rows:
        return
    columns = list(rows[0])
    batch_size = 500 if conn.dialect.name == 'postgresql' else 50
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        values = ','.join('(' + ','.join(f':{c}_{i}' for c in columns) + ')' for i in range(len(batch)))
        parameters = {f'{c}_{i}': row[c] for i, row in enumerate(batch) for c in columns}
        conn.execute(text(f"INSERT INTO {table} ({','.join(columns)}) VALUES {values} {conflict}"), parameters)


def upsert_dimension(conn, table, frame, natural_keys, surrogate):
    columns = [c for c in frame.columns if c not in natural_keys]
    update = ','.join(f'{c}=excluded.{c}' for c in columns)
    conflict = f"ON CONFLICT ({','.join(natural_keys)}) " + ('DO UPDATE SET ' + update if update else 'DO NOTHING')
    insert_rows(conn, table, records(frame.drop_duplicates()), conflict)
    return pd.read_sql(text(f'SELECT * FROM {table}'), conn)[natural_keys + [surrogate]]


def load(conn, clean, audit):
    customers = clean[['customer_unique_id', 'customer_city', 'customer_state']].rename(columns={'customer_city': 'city', 'customer_state': 'state'}).drop_duplicates()
    customers['region'] = customers['state'].map(REGIONS)
    customer_map = upsert_dimension(conn, 'dim_customer', customers, ['customer_unique_id', 'city', 'state'], 'customer_key')
    products = clean[['product_id', 'category_name', 'product_weight_g', 'product_length_cm']].drop_duplicates()
    product_map = upsert_dimension(conn, 'dim_product', products, ['product_id'], 'product_key')
    sellers = clean[['seller_id', 'seller_city', 'seller_state']].rename(columns={'seller_city': 'city', 'seller_state': 'state'}).drop_duplicates()
    sellers['region'] = sellers['state'].map(REGIONS)
    seller_map = upsert_dimension(conn, 'dim_seller', sellers, ['seller_id'], 'seller_key')
    first = min(clean['full_date']).year
    last = max(max(clean['full_date']).year, first + 4)
    calendar = pd.date_range(f'{first}-01-01', f'{last}-12-31')
    dates = pd.DataFrame({'date_key': calendar.strftime('%Y%m%d').astype(int), 'full_date': calendar.date,
                          'year': calendar.year, 'quarter': calendar.quarter, 'month': calendar.month,
                          'month_name': calendar.month_name(), 'day_of_week': calendar.dayofweek + 1,
                          'day_name': calendar.day_name(), 'is_weekend': calendar.dayofweek >= 5})
    insert_rows(conn, 'dim_date', records(dates), 'ON CONFLICT (date_key) DO NOTHING')
    fact = clean.merge(customer_map, left_on=['customer_unique_id', 'customer_city', 'customer_state'],
                       right_on=['customer_unique_id', 'city', 'state'], validate='many_to_one')
    fact = fact.merge(product_map, on='product_id', validate='many_to_one').merge(seller_map, on='seller_id', validate='many_to_one')
    if len(fact) != len(clean):
        raise ValueError('Missing dimension mapping')
    fact['date_key'] = pd.to_datetime(fact['full_date']).dt.strftime('%Y%m%d').astype(int)
    fact['quantity'] = 1
    columns = ['order_id', 'order_item_id', 'date_key', 'customer_key', 'product_key', 'seller_key',
               'quantity', 'unit_price_cents', 'freight_cents', 'total_revenue_cents']
    conn.execute(text('DELETE FROM fact_sales'))
    insert_rows(conn, 'fact_sales', records(fact[columns]))
    conn.execute(text('DELETE FROM etl_item_audit'))
    insert_rows(conn, 'etl_item_audit', records(audit))
    clean.to_sql('clean_sales', conn, if_exists='replace', index=False, chunksize=2000)
    execute_file(conn, '04_dashboard_views.sql')


def verify(conn):
    checks = [dict(conn.execute(text(sql)).mappings().one())
              for sql in sql_statements('03_verify_dw.sql', conn.dialect.name)]
    for check in checks:
        check['violations'] = int(check['violations'])
    failures = [c for c in checks if c['violations']]
    if failures:
        raise ValueError(f'Warehouse verification failed: {failures}')
    return checks


def run_pipeline(data_dir=None, url=None):
    engine = get_engine(url)
    run_id = str(uuid4())
    now = lambda: datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        execute_file(conn, '01_schema.sql')
        conn.execute(text('INSERT INTO etl_runs(run_id,started_at,status) VALUES (:id,:at,:status)'),
                     {'id': run_id, 'at': now(), 'status': 'running'})
    try:
        with engine.begin() as conn:
            if conn.dialect.name == 'postgresql':
                conn.execute(text('SELECT pg_advisory_xact_lock(4031)'))
            frames, sources = stage(conn, data_dir or ROOT / 'data')
            clean, audit = transform(frames)
            load(conn, clean, audit)
            checks = verify(conn)
            result = {'run_id': run_id, 'fact_rows': len(clean), 'sources': sources, 'checks': checks,
                      'dispositions': {str(k): int(v) for k, v in audit.disposition.value_counts().items()}}
            conn.execute(text("UPDATE etl_runs SET status='success',finished_at=:at,summary_json=:summary WHERE run_id=:id"),
                         {'id': run_id, 'at': now(), 'summary': json.dumps(result)})
        return result
    except Exception as error:
        with engine.begin() as conn:
            conn.execute(text("UPDATE etl_runs SET status='failed',finished_at=:at,error=:error WHERE run_id=:id"),
                         {'id': run_id, 'at': now(), 'error': str(error)[:2000]})
        raise
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description='Load the Olist data warehouse')
    parser.add_argument('--data-dir', default=str(ROOT / 'data'))
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        engine = get_engine()
        try:
            with engine.connect() as conn:
                print(json.dumps(verify(conn), indent=2))
        finally:
            engine.dispose()
    else:
        print(json.dumps(run_pipeline(args.data_dir), indent=2))


if __name__ == '__main__':
    main()
