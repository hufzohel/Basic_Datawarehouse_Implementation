CREATE OR REPLACE VIEW vw_sales_detail AS
SELECT f.sales_key, f.order_id, f.order_item_id, d.full_date, d.year, d.quarter,
       d.month, d.day_of_week, d.day_name, d.is_weekend,
       c.customer_unique_id, c.city, c.state, c.region,
       p.product_id, p.category_name, s.seller_id, s.state AS seller_state,
       f.quantity, f.unit_price_cents, f.freight_cents, f.total_revenue_cents,
       f.unit_price_cents * f.quantity AS merchandise_cents
FROM fact_sales f
JOIN dim_date d ON d.date_key=f.date_key
JOIN dim_customer c ON c.customer_key=f.customer_key
JOIN dim_product p ON p.product_key=f.product_key
JOIN dim_seller s ON s.seller_key=f.seller_key;
CREATE OR REPLACE VIEW vw_daily_sales AS
SELECT full_date, SUM(quantity) AS quantity,
       SUM(merchandise_cents) AS merchandise_cents,
       SUM(freight_cents) AS freight_cents,
       SUM(total_revenue_cents) AS total_revenue_cents,
       COUNT(DISTINCT order_id) AS orders,
       COUNT(DISTINCT customer_unique_id) AS customers
FROM vw_sales_detail GROUP BY full_date;
CREATE OR REPLACE VIEW vw_category_month AS
SELECT year, month, category_name, SUM(quantity) AS quantity,
       SUM(merchandise_cents) AS merchandise_cents,
       SUM(total_revenue_cents) AS total_revenue_cents,
       COUNT(DISTINCT order_id) AS orders,
       COUNT(DISTINCT customer_unique_id) AS customers
FROM vw_sales_detail GROUP BY year, month, category_name;
CREATE OR REPLACE VIEW vw_geography_sales AS
SELECT region, state, city, SUM(quantity) AS quantity,
       SUM(merchandise_cents) AS merchandise_cents,
       SUM(total_revenue_cents) AS total_revenue_cents,
       COUNT(DISTINCT order_id) AS orders,
       COUNT(DISTINCT customer_unique_id) AS customers
FROM vw_sales_detail GROUP BY region, state, city;
