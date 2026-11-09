```
# Data Warehouse &amp; Decision Support System (CO4031 Project)

## 📁 Project Structure

```text
.
├── data/       # Raw and sample datasets
├── sql/        # Database DDL, schemas, and analytical views
└── src/        # Python application logic
    ├── etl/    # Data extraction, cleansing, and warehouse loading
    └── dss/    # Decision support models and simulation logic

```

---

## 🛠️ Folder Responsibilities

### 1\. `data/`

* **Purpose:** Serves as the storage directory for raw input files.
* **Responsibilities:**
  * Holds initial source files (e.g., `.csv`, `.json` datasets).
  * Stores sample data packages required for project submission and evaluation.

### 2\. `sql/`

* **Purpose:** Contains all SQL scripts for managing the PostgreSQL Data Warehouse.
* **Responsibilities:**
  * **Schema Definition:** Holds DDL statements (`01_schema.sql`) for creating Fact and Dimension tables in the Star Schema.
  * **OLAP Views:** Stores pre-aggregated analytical views (`02_olap_views.sql`) to enable fast slicing, dicing, and drill-down queries.
  * **Validation:** Contains verification queries to ensure zero data leakage during ETL.

### 3\. `src/`

* **Purpose:** Contains all execution logic, modularized into two distinct sub-packages:

#### 🔄 `src/etl/` (Extract, Transform, Load)

* Handles loading raw CSVs into temporary database staging tables.
* Performs data cleansing (handling NULLs, standardizing formats, and removing duplicates).
* Maps natural keys to surrogate keys and populates the `dim_*` and `fact_*` tables.

#### 🧠 `src/dss/` (Decision Support System)

* **Analytical Modeling:** Implements predictive models (e.g., historical sales forecasting).
* **Simulation Engine:** Houses the "What-If" scenario logic (e.g., calculating the impact of price or supply chain changes on overall profit margins).

---

## 🤝 Data Contract & Star Schema Specification

To allow parallel development, all members agree to adhere to the following table structures, column names, and data types:

### 1. Fact Table: `fact_sales` (Grain: 1 Line Item per Order)
* **Primary Key:** `sales_key` (INT, Auto-increment / Identity)
* **Foreign Keys:** 
  * `date_key` (INT) ➔ `dim_date.date_key`
  * `customer_key` (INT) ➔ `dim_customer.customer_key`
  * `product_key` (INT) ➔ `dim_product.product_key`
  * `seller_key` (INT) ➔ `dim_seller.seller_key`
* **Natural Identifiers:** `order_id` (VARCHAR), `order_item_id` (INT)
* **Measures / Metrics:**
  * `quantity` (INT) — Default: 1
  * `unit_price_cents` (INT) — Stored in integer cents to avoid floating-point errors
  * `freight_cents` (INT) — Shipping cost in integer cents
  * `total_revenue_cents` (INT) — Calculated: `(unit_price_cents * quantity) + freight_cents`

---

### 2. Dimension Tables

#### `dim_date`
* `date_key` (INT, PK) — Format: `YYYYMMDD` (e.g., 20261108)
* `full_date` (DATE) — `YYYY-MM-DD`
* `year` (INT), `quarter` (INT), `month` (INT), `month_name` (VARCHAR)
* `day_of_week` (INT), `day_name` (VARCHAR), `is_weekend` (BOOLEAN)

#### `dim_product`
* `product_key` (INT, PK, Auto-increment)
* `product_id` (VARCHAR) — Natural source key
* `category_name` (VARCHAR) — Standardized category name
* `product_weight_g` (INT), `product_length_cm` (INT)

#### `dim_customer`
* `customer_key` (INT, PK, Auto-increment)
* `customer_unique_id` (VARCHAR) — Natural source key
* `city` (VARCHAR), `state` (VARCHAR), `region` (VARCHAR)

#### `dim_seller`
* `seller_key` (INT, PK, Auto-increment)
* `seller_id` (VARCHAR) — Natural source key
* `city` (VARCHAR), `state` (VARCHAR), `region` (VARCHAR)
```
---
