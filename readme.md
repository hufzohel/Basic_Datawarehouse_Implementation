# Kho dữ liệu bán hàng Olist

Kho dữ liệu phục vụ phân tích đơn hàng đã giao theo thời gian, ngành hàng, địa lý và người bán. DSS dự báo lượng sản phẩm bán theo ngày bằng XGBoost và lập kế hoạch bổ sung hàng theo tồn kho, giá vốn và ngân sách giả định. Backend dùng PostgreSQL; có thể chạy SQLite trên máy cá nhân. Dashboard sử dụng Streamlit.

## Chạy với SQLite

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.etl.load_dw
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Mở http://localhost:8501. Database mặc định ở `data/warehouse.db`. CSV đã có trong `data/`; có thể chỉ định thư mục khác bằng `python -m src.etl.load_dw --data-dir <folder>`.

## Chạy với PostgreSQL

Khởi động Docker Desktop. Sau khi tạo môi trường và cài thư viện như trên, chạy trong PowerShell:

```powershell
docker compose up -d --wait
$env:DATABASE_URL = 'postgresql+psycopg2://olist:olist_local@127.0.0.1:5434/olist_dw'
.\.venv\Scripts\python.exe -m src.etl.load_dw
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Đặt `DATABASE_URL` trong cùng terminal chạy ETL và ứng dụng. Xóa biến này bằng `Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue` để quay về SQLite. Cổng 5434 và tài khoản trong compose dùng cho môi trường chạy cục bộ. Các lệnh `python` bên dưới cần chạy bằng Python của môi trường đã cài thư viện.

Kiểm tra kho sau khi nạp: `python -m src.etl.load_dw --verify`. Chạy lại ETL sẽ thay snapshot fact trong một transaction; nếu có lỗi, dữ liệu cũ được giữ nguyên. `etl_runs` lưu trạng thái, dấu vân tay nguồn và kết quả đối soát; `etl_item_audit` ghi kết quả xử lý từng dòng nguồn.

## Phân tích

- Lọc ngày đặt hàng, ngành hàng, vùng, bang và người bán.
- Tổng giá trị hàng, phí vận chuyển, tổng gồm phí, số đơn, sản phẩm và khách duy nhất.
- Drill-down/roll-up theo năm, quý, tháng; vùng, bang, thành phố; ngành và sản phẩm.
- Pivot ngành hàng × bang, tìm mã đơn, xuất CSV.
- Kiểm tra nguồn và kết quả làm sạch tại tab Kho dữ liệu.

Dashboard có 5 tab: **Tổng quan**, **Phân tích đa chiều**, **Dự báo & kế hoạch**, **Chi tiết giao dịch** và **Kho dữ liệu**. Các bộ lọc áp dụng đồng thời. Các cột tiền có hậu tố `_cents` trong database và CSV dùng số nguyên cent; giao diện đổi sang BRL. Số đơn và khách tính DISTINCT tại từng phạm vi, không cộng giữa các nhóm. Chuỗi thời gian hiển thị các kỳ không có giao dịch bằng 0.

Tổng hợp chạy bằng SQL `GROUP BY`; PostgreSQL dùng thêm `ROLLUP`/`GROUPING` cho các cấp thời gian và địa lý. SQLite mô phỏng các cấp roll-up bằng `UNION ALL`. pandas chỉ định dạng kết quả, bổ sung kỳ trống và xoay bảng pivot. Tab DSS nhận chuỗi đã tổng hợp theo ngày.

Tab **Chi tiết giao dịch** truy vấn tối đa 1.000 dòng mỗi trang, theo thứ tự mã đơn và mã dòng hàng. Ô tìm kiếm tìm một phần mã đơn, không phân biệt chữ hoa/thường; `%` và `_` được coi là ký tự tìm kiếm, không phải ký tự đại diện. Đổi bộ lọc hoặc nội dung tìm kiếm đưa về trang đầu. Để xuất toàn bộ kết quả đang lọc, bấm **Chuẩn bị CSV toàn bộ kết quả**, rồi bấm **Tải chi tiết CSV**. File tải gồm toàn bộ kết quả phù hợp, không chỉ trang đang xem.

Cache có thời hạn 5 phút và gắn với phiên ETL. Kết quả tổng hợp, trang chi tiết và file CSV có cache riêng; chỉ khi chuẩn bị CSV hệ thống mới đọc toàn bộ dòng chi tiết phù hợp. Nút làm mới dữ liệu xóa cache và kết quả dự báo cũ.

## Dự báo và kế hoạch bổ sung hàng

Tab **Dự báo & kế hoạch** dùng cùng bộ lọc ngành hàng, vùng, bang và người bán của dashboard. Chọn ngày chốt lịch sử, kỳ 30/60/90 ngày rồi bấm **Tính dự báo**. Ngày chốt mặc định là cuối tháng đầy đủ gần nhất trong phạm vi đang xem. Chỉ các giao dịch từ ngày bắt đầu đến ngày chốt được dùng cho mô hình và giá bán tham khảo.

Mô hình XGBoost dùng đặc trưng lịch, lag 1/7/14/28 ngày và rolling 7/28 ngày. Với kỳ dự báo H ngày, H ngày cuối lịch sử được giữ riêng để kiểm tra. Phần lịch sử trước đó được đánh giá trên tối đa 3 cửa sổ H ngày không chồng nhau, với tập huấn luyện mở rộng dần. Mỗi cửa sổ dự báo nhiều bước bằng kết quả của bước trước, không đọc lượng bán thực tế trong cửa sổ đang kiểm tra. Baseline lặp lại 7 ngày cuối tập huấn luyện. WAPE gộp tính từ tổng sai số tuyệt đối chia tổng lượng bán của các cửa sổ, không lấy trung bình các tỷ lệ WAPE.

Sau khi cố định các kết quả MAE/RMSE/WAPE và so sánh baseline, mô hình được huấn luyện lại trên toàn bộ lịch sử tới ngày chốt để dự báo tương lai. Mặc định giữ hàm mất mát bình phương (`squared`); `absolute` là lựa chọn so sánh. Chọn cấu hình bằng các cửa sổ trước kỳ cuối, không chọn theo WAPE kỳ cuối. Nếu đã dùng kỳ cuối để điều chỉnh cấu hình thì cần một kỳ kiểm tra mới để đánh giá độc lập. Các kỳ đã xem trong báo cáo chỉ là kết quả đánh giá lịch sử.

Kế hoạch bị chặn (`REJECTED`) nếu WAPE kỳ cuối không xác định hoặc trên 50%, tập kiểm tra dưới 30 sản phẩm, hoặc 90 ngày cuối tập train có dưới 14 ngày bán. WAPE trên 30% hoặc kém baseline sẽ hiện cảnh báo (`CAUTION`). Thiếu cửa sổ đánh giá, có cửa sổ trước bị chặn hoặc WAPE gộp trước kỳ cuối kém baseline cũng tạo cảnh báo. `CAUTION` vẫn cho phép xem kế hoạch; `APPROVED` chỉ có nghĩa đạt các ngưỡng đang đặt. Các ngưỡng là quy tắc minh họa, chưa hiệu chỉnh theo chi phí kinh doanh.

Lượng cần mua = max(0, ceil(dự báo) + dự phòng − tồn kho − hàng đang về), giới hạn bởi ngân sách và giá vốn. Giá vốn, tồn kho, hàng về, dự phòng và tỷ lệ lưu kho do người dùng giả định. Giá bán tham khảo lấy tiền hàng chia số lượng trong 90 ngày tới ngày chốt (gồm ngày chốt), không gồm freight. Mô phỏng thay đổi giá giữ công thức độ co giãn tuyến tính; chưa dùng để khẳng định giá bán tối ưu. Kế hoạch tính cho toàn bộ phạm vi, chưa phân bổ theo SKU.

Dashboard huấn luyện khi người dùng yêu cầu, không cần có sẵn file model. Đổi phạm vi, ngày chốt, kỳ dự báo hoặc phiên ETL sẽ yêu cầu tính lại; đổi các tham số kế hoạch giữ ngân sách đã nhập. Nút đặt ngân sách đủ là thao tác riêng.

Có thể huấn luyện và tái tạo đánh giá bằng terminal:

```powershell
python -m src.dss.train --cutoff 2018-07-31 --horizon 30
python -m src.dss.test
```

Các tùy chọn của lệnh train:

| Tham số | Ý nghĩa |
|---|---|
| `--start-date YYYY-MM-DD`, `--cutoff YYYY-MM-DD` | Giới hạn lịch sử; nên chỉ rõ ngày chốt để tái tạo kết quả |
| `--horizon 30` | Kỳ dự báo và kiểm tra: 30, 60 hoặc 90 ngày |
| `--category health_beauty` | Lọc mã ngành hàng |
| `--region Southeast`, `--state SP` | Lọc vùng và bang khách hàng |
| `--seller <seller_id>` | Lọc người bán |
| `--loss squared` | `squared` (mặc định) hoặc `absolute` |
| `--validation-windows 3` | Số cửa sổ trước kỳ cuối, từ 1 đến 12; số thực tế phụ thuộc độ dài lịch sử |
| `--model <file.json>` | Đường dẫn lưu model |

Có thể lặp `--category`, `--region`, `--state` và `--seller` để chọn nhiều giá trị. Trong cùng một bộ lọc, các giá trị kết hợp theo OR; giữa các bộ lọc kết hợp theo AND. CLI dùng mã gốc, chẳng hạn `pc_gamer`, không dùng nhãn hiển thị.

Cả train và test dùng cùng `DATABASE_URL` với ETL. Nếu train dùng đường dẫn model riêng, truyền cùng `--model` khi test. File `xgboost_sales.json` chứa mô hình đã refit; `xgboost_sales.holdout.json` chứa mô hình chỉ học trước kỳ kiểm tra. Mỗi file lưu phạm vi, ngày chốt, hàm mất mát, kết quả đánh giá nhiều cửa sổ, chỉ số chất lượng và dấu vân tay chuỗi dữ liệu. Lệnh test dùng đúng model holdout và từ chối dữ liệu đã thay đổi. Đây là phép tái tạo kỳ kiểm tra đã lưu, không phải một tập kiểm tra mới. File model được tạo khi chạy và không đưa vào Git.

## Cấu trúc

```text
app.py                     Dashboard và tab DSS
sql/01_schema.sql          Star schema và bảng nhật ký
sql/03_verify_dw.sql       Đối soát kho dữ liệu
sql/04_dashboard_views.sql Các view dùng cho phân tích
src/db.py                  Kết nối database
src/analytics.py           Lọc, tổng hợp, pivot
src/etl/staging.py         Đọc CSV và nạp staging
src/etl/load_dw.py         Làm sạch, nạp kho và đối soát
src/dss/                   Mô hình dự báo, train/test và mô phỏng
src/dss_ui.py              Giao diện dự báo và kế hoạch
data/                      Dữ liệu nguồn
```

## Dữ liệu và cách tính

Nguồn: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), giấy phép CC BY-NC-SA 4.0. Dữ liệu giao dịch thuộc giai đoạn 2016–2018. Chỉ đơn có `order_status = delivered` được nạp vào fact; ngày phân tích là ngày đặt hàng.

ETL cần 6 file trong `data/`: `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`, `olist_customers_dataset.csv`, `olist_products_dataset.csv`, `olist_sellers_dataset.csv` và `product_category_name_translation.csv`. Geolocation, payments và reviews không được pipeline hiện tại sử dụng.

Một dòng fact tương ứng `(order_id, order_item_id)`, `quantity = 1`. Giá trị hàng bằng `unit_price_cents * quantity`; `total_revenue_cents` gồm thêm phí vận chuyển theo data contract. Không nối trực tiếp payments/reviews vào fact vì có thể làm nhân dòng hàng. Đây là giá trị giao dịch trong snapshot, chưa phản ánh hoàn tiền hoặc lợi nhuận thực tế.

Định danh khách là `customer_unique_id`. Một khách có thể có nhiều địa chỉ; `dim_customer` giữ từng tổ hợp định danh, thành phố và bang để fact gắn đúng địa chỉ của đơn. Số khách luôn đếm DISTINCT định danh, không đếm số khóa thay thế. Các thuộc tính sản phẩm và người bán cập nhật theo snapshot nguồn.

## Báo cáo

[Báo cáo kỹ thuật](docs/Report.md)

## Data contract

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
