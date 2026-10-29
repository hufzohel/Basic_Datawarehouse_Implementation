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