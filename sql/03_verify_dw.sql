SELECT 'fact_row_count' AS check_name,
       ABS((SELECT COUNT(*) FROM clean_sales)-(SELECT COUNT(*) FROM fact_sales)) AS violations;
SELECT 'line_values_and_dimensions' AS check_name, COUNT(*) AS violations
FROM clean_sales x
LEFT JOIN fact_sales f ON f.order_id=x.order_id AND f.order_item_id=x.order_item_id
LEFT JOIN dim_date d ON d.date_key=f.date_key
LEFT JOIN dim_customer c ON c.customer_key=f.customer_key
LEFT JOIN dim_product p ON p.product_key=f.product_key
LEFT JOIN dim_seller s ON s.seller_key=f.seller_key
WHERE f.sales_key IS NULL OR d.date_key IS NULL OR c.customer_key IS NULL
   OR p.product_key IS NULL OR s.seller_key IS NULL OR f.quantity<>1
   OR d.full_date<>x.full_date OR c.customer_unique_id<>x.customer_unique_id
   OR c.city<>x.customer_city OR c.state<>x.customer_state
   OR p.product_id<>x.product_id OR s.seller_id<>x.seller_id
   OR f.unit_price_cents<>x.unit_price_cents OR f.freight_cents<>x.freight_cents
   OR f.total_revenue_cents<>x.total_revenue_cents;
SELECT 'duplicate_line_items' AS check_name, COUNT(*) AS violations FROM (
 SELECT order_id, order_item_id FROM fact_sales GROUP BY order_id, order_item_id HAVING COUNT(*)>1
) duplicates;
SELECT 'source_row_accounting' AS check_name,
 ABS((SELECT COUNT(*) FROM staging_items)-(SELECT COUNT(*) FROM etl_item_audit)) AS violations;
SELECT 'accepted_row_accounting' AS check_name,
 ABS((SELECT COUNT(*) FROM etl_item_audit WHERE disposition='accepted')-(SELECT COUNT(*) FROM fact_sales)) AS violations;
SELECT 'merchandise_cents' AS check_name,
 ABS(COALESCE((SELECT SUM(price_cents) FROM etl_item_audit WHERE disposition='accepted'),0)
     -COALESCE((SELECT SUM(unit_price_cents * quantity) FROM fact_sales),0)) AS violations;
SELECT 'freight_cents' AS check_name,
 ABS(COALESCE((SELECT SUM(freight_cents) FROM etl_item_audit WHERE disposition='accepted'),0)
     -COALESCE((SELECT SUM(freight_cents) FROM fact_sales),0)) AS violations;
SELECT 'revenue_identity' AS check_name, COUNT(*) AS violations FROM fact_sales
WHERE total_revenue_cents<>unit_price_cents*quantity+freight_cents;
WITH expected AS (
 SELECT d.full_date, SUM(f.quantity) AS quantity, SUM(f.total_revenue_cents) AS total_revenue_cents,
        COUNT(DISTINCT f.order_id) AS orders, COUNT(DISTINCT c.customer_unique_id) AS customers
 FROM fact_sales f JOIN dim_date d ON d.date_key=f.date_key
 JOIN dim_customer c ON c.customer_key=f.customer_key GROUP BY d.full_date
)
SELECT 'daily_view_groups' AS check_name,
 (SELECT COUNT(*) FROM expected e LEFT JOIN vw_daily_sales v ON v.full_date=e.full_date
  WHERE v.full_date IS NULL OR v.quantity IS NULL OR v.quantity<>e.quantity
     OR v.total_revenue_cents IS NULL OR v.total_revenue_cents<>e.total_revenue_cents
     OR v.orders IS NULL OR v.orders<>e.orders OR v.customers IS NULL OR v.customers<>e.customers)
 + (SELECT COUNT(*) FROM vw_daily_sales v LEFT JOIN expected e ON e.full_date=v.full_date WHERE e.full_date IS NULL) AS violations;
WITH expected AS (
 SELECT d.year, d.month, p.category_name, SUM(f.quantity) AS quantity,
        SUM(f.total_revenue_cents) AS total_revenue_cents, COUNT(DISTINCT f.order_id) AS orders,
        COUNT(DISTINCT c.customer_unique_id) AS customers
 FROM fact_sales f JOIN dim_date d ON d.date_key=f.date_key
 JOIN dim_product p ON p.product_key=f.product_key JOIN dim_customer c ON c.customer_key=f.customer_key
 GROUP BY d.year, d.month, p.category_name
)
SELECT 'category_view_groups' AS check_name,
 (SELECT COUNT(*) FROM expected e LEFT JOIN vw_category_month v
  ON v.year=e.year AND v.month=e.month AND v.category_name=e.category_name
  WHERE v.year IS NULL OR v.quantity IS NULL OR v.quantity<>e.quantity
     OR v.total_revenue_cents IS NULL OR v.total_revenue_cents<>e.total_revenue_cents
     OR v.orders IS NULL OR v.orders<>e.orders OR v.customers IS NULL OR v.customers<>e.customers)
 + (SELECT COUNT(*) FROM vw_category_month v LEFT JOIN expected e
    ON v.year=e.year AND v.month=e.month AND v.category_name=e.category_name WHERE e.year IS NULL) AS violations;
WITH expected AS (
 SELECT c.region, c.state, c.city, SUM(f.quantity) AS quantity,
        SUM(f.total_revenue_cents) AS total_revenue_cents, COUNT(DISTINCT f.order_id) AS orders,
        COUNT(DISTINCT c.customer_unique_id) AS customers
 FROM fact_sales f JOIN dim_customer c ON c.customer_key=f.customer_key GROUP BY c.region,c.state,c.city
)
SELECT 'geography_view_groups' AS check_name,
 (SELECT COUNT(*) FROM expected e LEFT JOIN vw_geography_sales v
  ON v.region=e.region AND v.state=e.state AND v.city=e.city
  WHERE v.region IS NULL OR v.quantity IS NULL OR v.quantity<>e.quantity
     OR v.total_revenue_cents IS NULL OR v.total_revenue_cents<>e.total_revenue_cents
     OR v.orders IS NULL OR v.orders<>e.orders OR v.customers IS NULL OR v.customers<>e.customers)
 + (SELECT COUNT(*) FROM vw_geography_sales v LEFT JOIN expected e
    ON v.region=e.region AND v.state=e.state AND v.city=e.city WHERE e.region IS NULL) AS violations;
