import hashlib
from pathlib import Path

import pandas as pd

SOURCES = {
    'orders': ('olist_orders_dataset.csv', ['order_id', 'customer_id', 'order_status', 'order_purchase_timestamp']),
    'items': ('olist_order_items_dataset.csv', ['order_id', 'order_item_id', 'product_id', 'seller_id', 'price', 'freight_value']),
    'customers': ('olist_customers_dataset.csv', ['customer_id', 'customer_unique_id', 'customer_city', 'customer_state']),
    'products': ('olist_products_dataset.csv', ['product_id', 'product_category_name', 'product_weight_g', 'product_length_cm']),
    'sellers': ('olist_sellers_dataset.csv', ['seller_id', 'seller_city', 'seller_state']),
    'categories': ('product_category_name_translation.csv', ['product_category_name', 'product_category_name_english']),
}


def stage(conn, data_dir):
    frames, manifest = {}, []
    for name, (filename, required) in SOURCES.items():
        path = Path(data_dir) / filename
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        missing = set(required) - set(frame.columns)
        if missing:
            raise ValueError(f'{filename}: missing columns {sorted(missing)}')
        frame.insert(0, 'source_row', range(2, len(frame) + 2))
        frame.to_sql('staging_' + name, conn, if_exists='replace', index=False, chunksize=2000)
        frames[name] = frame
        manifest.append({'file': filename, 'rows': len(frame),
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return frames, manifest
