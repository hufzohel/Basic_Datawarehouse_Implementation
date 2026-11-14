# Kho dữ liệu bán hàng và hệ hỗ trợ quyết định Olist

CO4031 — Kho dữ liệu và Hệ hỗ trợ quyết định

## 1. Bài toán và phạm vi

Project xây dựng kho dữ liệu từ giao dịch thương mại điện tử Olist để phân tích bán hàng và hỗ trợ lập kế hoạch bổ sung hàng. Người sử dụng chọn ngành hàng, địa bàn, người bán và khoảng thời gian; hệ thống tổng hợp kết quả, dự báo lượng sản phẩm bán và tính lượng cần mua theo tồn kho, giá vốn và ngân sách giả định.

Các câu hỏi chính:

- Giá trị hàng, phí vận chuyển, số đơn, số sản phẩm và số khách trong một giai đoạn là bao nhiêu?
- Ngành hàng, địa bàn và người bán nào đóng góp nhiều nhất?
- Kết quả thay đổi thế nào khi đi từ năm xuống quý, tháng hoặc từ vùng xuống bang, thành phố?
- Lượng sản phẩm bán trong 30, 60 hoặc 90 ngày tiếp theo được dự báo ra sao? Mô hình có tốt hơn cách lặp lại tuần gần nhất không?
- Với tồn kho, hàng đang về, dự phòng và ngân sách đã nhập, cần bổ sung bao nhiêu sản phẩm?

Nguồn là Brazilian E-Commerce Public Dataset by Olist, gồm giao dịch tại Brazil giai đoạn 2016–2018. Fact chỉ chứa đơn có trạng thái `delivered`, phân tích theo ngày đặt hàng. Trạng thái này được quan sát ở snapshot nguồn cuối cùng, không phải trạng thái đã biết tại ngày đặt đơn. DSS vì vậy dự báo lượng bán của các đơn cuối cùng đã giao trong dữ liệu, chưa đại diện đầy đủ cho nhu cầu thị trường hoặc nhu cầu bị mất do hết hàng.

## 2. Kiến trúc hệ thống

```text
CSV → Staging → Làm sạch và audit → Star schema → View và truy vấn SQL
                                                   ├─ OLAP → Dashboard
                                                   └─ Chuỗi ngày → XGBoost
                                                        → Đánh giá → Dự báo
                                                        → Kế hoạch bổ sung hàng
```

PostgreSQL là cơ sở dữ liệu mục tiêu; SQLite dùng để chạy cục bộ. SQLAlchemy quản lý kết nối và transaction. pandas xử lý ETL, định dạng bảng và tạo đặc trưng chuỗi thời gian. Streamlit và Altair cung cấp giao diện và biểu đồ. XGBoost thực hiện hồi quy lượng sản phẩm bán theo ngày.

| Thành phần | File chính |
|---|---|
| Schema, đối soát và view | `sql/01_schema.sql`, `sql/03_verify_dw.sql`, `sql/04_dashboard_views.sql` |
| Staging và nạp kho | `src/etl/staging.py`, `src/etl/load_dw.py` |
| Kết nối và truy vấn phân tích | `src/db.py`, `src/analytics.py` |
| Dashboard | `app.py`, `src/ui.py`, `src/dss_ui.py` |
| Dự báo và mô phỏng | `src/dss/forecast.py`, `src/dss/simulator.py` |
| Huấn luyện và tái tạo đánh giá | `src/dss/train.py`, `src/dss/test.py` |

## 3. Nguồn dữ liệu và thiết kế đa chiều

### 3.1. Dữ liệu sử dụng

| File CSV | Vai trò |
|---|---|
| `olist_orders_dataset.csv` | Mã đơn, khách đặt đơn, trạng thái và ngày đặt |
| `olist_order_items_dataset.csv` | Dòng hàng, sản phẩm, người bán, giá hàng và phí vận chuyển |
| `olist_customers_dataset.csv` | Định danh khách và địa chỉ của đơn |
| `olist_products_dataset.csv` | Ngành hàng và thuộc tính sản phẩm |
| `olist_sellers_dataset.csv` | Người bán và địa chỉ |
| `product_category_name_translation.csv` | Dịch tên ngành từ tiếng Bồ Đào Nha sang tiếng Anh |

Geolocation, payments và reviews không được pipeline sử dụng. Payments và reviews có thể có nhiều dòng trên một đơn; nối trực tiếp vào fact dòng hàng có thể nhân số lượng và tổng tiền.

### 3.2. Star schema

Grain của `fact_sales` là một dòng hàng, xác định bởi `(order_id, order_item_id)`. Mỗi dòng nguồn biểu diễn một sản phẩm nên `quantity = 1`. `sales_key` là khóa thay thế; cặp định danh tự nhiên có ràng buộc `UNIQUE`.

| Bảng | Khóa và nội dung |
|---|---|
| `dim_date` | `date_key` dạng YYYYMMDD; ngày, năm, quý, tháng, thứ, cuối tuần |
| `dim_customer` | `customer_key`; `customer_unique_id`, thành phố, bang, vùng |
| `dim_product` | `product_key`; mã sản phẩm, ngành, khối lượng, chiều dài |
| `dim_seller` | `seller_key`; mã người bán, thành phố, bang, vùng |
| `fact_sales` | Bốn khóa ngoại; mã đơn, mã dòng hàng, số lượng và tiền theo cent |

Một `customer_unique_id` có thể xuất hiện ở nhiều địa chỉ. `dim_customer` giữ từng tổ hợp định danh, thành phố và bang để fact gắn đúng địa chỉ của đơn. Số khách tính bằng `COUNT(DISTINCT customer_unique_id)`, không đếm số khóa thay thế. Sản phẩm và người bán cập nhật theo snapshot nguồn; hệ thống không lưu lịch sử thuộc tính kiểu SCD Type 2.

Dimension ngày được sinh liên tục, tối thiểu 5 năm từ năm đầu dữ liệu hợp lệ. Fact có chỉ mục trên bốn khóa ngoại. Các ràng buộc gồm khóa chính, khóa ngoại, `UNIQUE`, `NOT NULL` và `CHECK` cho số lượng, tiền và công thức tổng tiền.

### 3.3. Chỉ tiêu phân tích

- Giá trị hàng = `unit_price_cents × quantity`.
- Phí vận chuyển = `freight_cents`.
- Tổng gồm phí = `total_revenue_cents = unit_price_cents × quantity + freight_cents`.
- Số đơn = `COUNT(DISTINCT order_id)`.
- Số khách = `COUNT(DISTINCT customer_unique_id)`.

Tiền lưu bằng số nguyên cent, 100 cent = 1 BRL. Giao diện đổi sang BRL; các cột xuất có hậu tố `_cents` giữ đơn vị cent. Tiền và số lượng có thể cộng theo chiều phân tích. Số đơn và số khách phải tính lại tại mỗi cấp vì một đơn có thể chứa nhiều ngành, một khách có thể mua nhiều kỳ hoặc tại nhiều địa chỉ.

`total_revenue_cents` là tên theo data contract, biểu diễn giá trị giao dịch gồm phí vận chuyển. Đây không phải lợi nhuận hay doanh thu thuần sau hoàn tiền. Dữ liệu không cung cấp giá vốn và tồn kho thực tế.

## 4. Quy trình ETL

### 4.1. Đọc nguồn và làm sạch

CSV được đọc dưới dạng chuỗi để giữ định danh và định dạng tiền gốc. Staging lưu các cột nguồn cùng `source_row` để truy lại dòng CSV. `etl_runs` ghi tên file, số dòng, SHA256, trạng thái và kết quả nạp.

Các quy tắc làm sạch:

1. Bỏ khoảng trắng thừa; chuẩn hóa bang sang chữ hoa, tên thành phố sang chữ thường và gom khoảng trắng.
2. Dùng bản dịch tiếng Anh của ngành khi có. Nếu thiếu bản dịch, giữ mã ngành nguồn; nếu thiếu cả ngành, gán `Unknown`. Nhãn hiển thị bổ sung nằm ở giao diện, không thay mã lọc hoặc dữ liệu gốc.
3. Chuẩn hóa mã dòng hàng thành số nguyên, nên `01` và `1` cùng một định danh. Dòng trùng hoàn toàn giữ một bản; cùng khóa nhưng khác nội dung bị loại cả nhóm và ghi audit.
4. Dừng lần nạp nếu orders hoặc dimension có cùng khóa tự nhiên nhưng nội dung mâu thuẫn, tránh phép nối nhiều-nhiều ngoài dự kiến.
5. Phân tích tiền bằng `Decimal`; loại số âm, giá trị không hữu hạn hoặc số có phần lẻ nhỏ hơn một cent. Không tự làm tròn tiền nguồn.
6. Loại dòng thiếu tham chiếu, định danh, ngày đặt hàng hoặc bang hợp lệ. Đơn chưa giao được ghi lý do `excluded_order_status`.
7. Để `NULL` cho thuộc tính kích thước sản phẩm thiếu hoặc sai định dạng.

`etl_item_audit` lưu kết quả xử lý từng dòng hàng nguồn. Nhóm `Unknown` và mã ngành thiếu bản dịch vẫn được giữ để tránh loại giao dịch hợp lệ chỉ vì thiếu mô tả.

### 4.2. Nạp kho và tính nhất quán

ETL cập nhật dimension theo khóa tự nhiên, giữ khóa thay thế ổn định rồi thay snapshot fact. Staging, `clean_sales`, audit, fact, view và trạng thái thành công được xuất bản trong cùng transaction. Đối soát thất bại hoặc lỗi giữa quy trình làm rollback, giữ kho trước đó. Thông tin lần chạy thất bại được ghi riêng vào `etl_runs`.

PostgreSQL dùng advisory lock để ngăn hai tiến trình ETL cùng xuất bản. SQLite bật khóa ngoại và dùng transaction tường minh cho cả DDL. Khi tạo lại view, PostgreSQL dùng `CREATE OR REPLACE VIEW`; SQLite dùng `DROP VIEW IF EXISTS` rồi `CREATE VIEW`, tránh giữ định nghĩa cũ.

Full refresh phù hợp với quy mô hiện tại. Chạy lại cùng nguồn không nhân số dòng và tổng tiền. Fact biến mất khỏi nguồn không còn trong snapshot mới; dimension cũ có thể còn nhưng không đóng góp vào phân tích nếu không được fact tham chiếu.

### 4.3. Đối soát kho

Có 11 phép kiểm tra phải trả về `violations = 0` trước khi hoàn tất nạp: số dòng fact, giá trị và tham chiếu dimension từng dòng, trùng khóa, số dòng staging/audit, số dòng accepted, giá trị hàng, phí vận chuyển, công thức tổng tiền và các nhóm đối soát view ngày/ngành/địa lý. View được so với fact cả số lượng, tiền, số đơn và khách DISTINCT. Đối soát từng dòng giúp phát hiện sai lệch mà phép cộng tổng có thể bỏ sót.

## 5. OLAP và dashboard

### 5.1. Tổng hợp bằng SQL

`vw_sales_detail` nối fact với bốn dimension. Các view `vw_daily_sales`, `vw_category_month` và `vw_geography_sales` cung cấp mức tổng hợp cố định và được đối soát trong ETL. Dashboard truy vấn `vw_sales_detail` với bộ lọc tham số hóa, tổng hợp trực tiếp bằng SQL để giữ đúng số đếm DISTINCT cho mọi phạm vi.

Các truy vấn dùng `GROUP BY` cho KPI theo chiều, chuỗi thời gian và dữ liệu pivot. PostgreSQL dùng `GROUP BY ROLLUP` cùng `GROUPING()` để phân biệt dòng chi tiết, tổng phụ và tổng toàn bộ. SQLite tạo các cấp tương đương bằng `UNION ALL`. Ví dụ phân cấp địa lý:

```sql
SELECT region, state, city,
       SUM(merchandise_cents) AS merchandise_cents,
       COUNT(DISTINCT order_id) AS orders,
       COUNT(DISTINCT customer_unique_id) AS customers,
       3 - GROUPING(region) - GROUPING(state) - GROUPING(city) AS grouping_depth
FROM vw_sales_detail
WHERE full_date >= :start AND full_date <= :end
GROUP BY ROLLUP (region, state, city);
```

pandas xoay kết quả đã tổng hợp thành bảng pivot, bổ sung kỳ trống và định dạng hiển thị. Dashboard không tải toàn bộ dòng hàng chỉ để tính KPI hoặc huấn luyện dự báo.

### 5.2. Chức năng giao diện

| Tab | Nội dung |
|---|---|
| Tổng quan | Sáu KPI, chuỗi thời gian, ngành hàng và bang đóng góp lớn |
| Phân tích đa chiều | Drill-down/roll-up thời gian, địa lý; phân tích sản phẩm, người bán; pivot ngành × bang |
| Dự báo & kế hoạch | Chọn ngày chốt, kỳ dự báo, xem đánh giá và mô phỏng bổ sung hàng |
| Chi tiết giao dịch | Tìm mã đơn, phân trang dòng hàng, tải toàn bộ kết quả đã lọc |
| Kho dữ liệu | Nguồn, số dòng, lý do loại và đối soát lần ETL |

Bộ lọc ngày, ngành, vùng, bang và người bán kết hợp theo AND; nhiều giá trị trong cùng bộ lọc kết hợp theo OR. Không chọn giá trị nghĩa là lấy toàn bộ. Bộ lọc bang phụ thuộc vùng đang chọn. Chuỗi thời gian thêm giá trị 0 ở kỳ không có giao dịch trong khoảng yêu cầu; phạm vi không có dữ liệu được thông báo trên giao diện.

### 5.3. Phân trang, tìm kiếm và cache

Tab Chi tiết truy vấn tối đa 1.000 dòng bằng `LIMIT/OFFSET`, sắp xếp theo `(order_id, order_item_id)`. Đổi phạm vi hoặc chuỗi tìm kiếm đưa về trang đầu. Tìm mã đơn dùng `LOWER(...) LIKE ... ESCAPE '!'`, truyền giá trị qua tham số và escape `%`, `_`, `!` để tìm đúng ký tự người dùng nhập.

Xuất CSV có hai bước: chuẩn bị toàn bộ kết quả đang lọc rồi tải file. Chỉ thao tác này mới đọc toàn bộ chi tiết phù hợp. File không bị giới hạn bởi trang đang xem.

Cache có TTL 300 giây và gắn với `run_id` của ETL thành công. Cache tổng hợp tối đa 48 mục; cache trang chi tiết tối đa 16 mục; cache file xuất tối đa 2 mục. DSS có cache dự báo riêng. Nút làm mới xóa cache và kết quả dự báo cũ. Giới hạn số mục giúp giảm bộ nhớ, nhưng kích thước CSV toàn bộ vẫn phụ thuộc lượng dữ liệu xuất.

## 6. Dự báo lượng sản phẩm bán

### 6.1. Chuỗi đầu vào và mô hình

SQL tổng hợp số lượng theo ngày sau khi áp dụng bộ lọc. DSS chỉ dùng lịch sử từ ngày bắt đầu tới ngày chốt, điền 0 cho ngày không có giao dịch. Ngày chốt mặc định trên giao diện là cuối tháng đầy đủ gần nhất trong khoảng đã chọn; với toàn bộ dữ liệu là 31/07/2018. Quy tắc này tránh dùng trực tiếp tháng cuối chưa đủ ngày, nhưng không chứng minh các ngày trước đó đều không thiếu dữ liệu nguồn.

Biến mục tiêu là số sản phẩm theo ngày. Mô hình có 11 đặc trưng:

- Lịch: thứ, ngày trong tháng, tháng, cờ cuối tuần.
- Lag: lượng bán trước 1, 7, 14 và 28 ngày.
- Thống kê trượt: trung bình 7 ngày, trung bình 28 ngày, độ lệch chuẩn 7 ngày.

Thống kê trượt được dịch một ngày trước khi tính, chỉ dùng quá khứ. XGBoost có 100 cây, `learning_rate = 0.05`, `max_depth = 4`, `random_state = 42`, `n_jobs = 2`. Mặc định dùng `reg:squarederror`; tùy chọn `absolute` dùng `reg:absoluteerror`. Chưa có bộ chọn hàm mất mát tự động.

Dự báo nhiều bước thực hiện đệ quy: dự báo ngày tiếp theo, đưa giá trị đó vào lịch sử để tính lag cho bước sau. Giá trị âm được chặn về 0. Trong kỳ kiểm tra, mô hình không dùng lượng bán thực tế của các ngày đang dự báo. Cách này có thể tích lũy sai số khi kỳ dự báo dài.

### 6.2. Đánh giá theo thời gian

Với kỳ H ngày, quy trình gồm:

1. Giữ riêng H ngày cuối lịch sử làm kỳ kiểm tra cuối.
2. Trên phần lịch sử trước kỳ cuối, lấy tối đa 3 cửa sổ kiểm tra H ngày không chồng nhau. Mỗi cửa sổ huấn luyện bằng toàn bộ dữ liệu trước nó; cần tối thiểu 56 ngày lịch sử để tạo đặc trưng và huấn luyện.
3. Dự báo đệ quy cho từng cửa sổ, so với baseline lặp lại 7 ngày cuối tập train.
4. Huấn luyện bằng lịch sử trước kỳ cuối, dự báo kỳ cuối và cố định các chỉ số đánh giá.
5. Sau đánh giá, huấn luyện lại trên toàn bộ lịch sử tới ngày chốt để dự báo H ngày tương lai.

Dashboard dùng tối đa 3 cửa sổ trước kỳ cuối. CLI cho chọn từ 1 đến 12; nếu thiếu lịch sử, số cửa sổ thực tế giảm và hệ thống cảnh báo.

Với lượng thực tế `y_t` và dự báo `ŷ_t`:

```text
MAE  = Σ|y_t − ŷ_t| / n
RMSE = sqrt(Σ(y_t − ŷ_t)² / n)
WAPE = 100 × Σ|y_t − ŷ_t| / Σy_t
Bias = 100 × Σ(ŷ_t − y_t) / Σy_t
```

WAPE và bias không xác định nếu tổng lượng thực tế bằng 0. WAPE gộp tính từ tổng sai số tuyệt đối và tổng lượng thực tế của tất cả cửa sổ, không phải trung bình WAPE từng cửa sổ. Bias dương biểu thị dự báo cao hơn thực tế.

Chọn đặc trưng hoặc hàm mất mát phải dựa trên các cửa sổ trước kỳ cuối. Nếu xem kết quả kỳ cuối rồi đổi cấu hình để cải thiện con số đó, kỳ cuối không còn là phép đánh giá độc lập cho lựa chọn mới. Các kỳ trong bảng kết quả đã được xem khi phát triển; chúng mô tả hiệu năng lịch sử, không được coi là tập kiểm tra chưa từng sử dụng để ra quyết định.

### 6.3. Cổng chất lượng

| Trạng thái | Điều kiện và cách xử lý |
|---|---|
| `REJECTED` | WAPE kỳ cuối không hữu hạn hoặc > 50%; hoặc kỳ cuối có < 30 sản phẩm; hoặc 90 ngày cuối tập train có < 14 ngày bán. Chặn lập kế hoạch. |
| `CAUTION` | Không bị chặn nhưng WAPE kỳ cuối > 30% hoặc kém baseline; hoặc thiếu cửa sổ trước kỳ cuối, có cửa sổ trước bị chặn, hay WAPE gộp trước kỳ cuối kém baseline. Cho xem kế hoạch kèm cảnh báo. |
| `APPROVED` | Không có điều kiện chặn hoặc cảnh báo ở trên. |

Các ngưỡng là quy tắc minh họa, chưa hiệu chỉnh theo chi phí thiếu hàng, tồn kho hoặc mức dịch vụ. `APPROVED` không bảo đảm kế hoạch đem lại lợi nhuận. Cửa sổ trước bị chặn chỉ bổ sung cảnh báo về độ ổn định; không tự biến kỳ cuối đạt ngưỡng thành `REJECTED`.

### 6.4. Lưu model và tái tạo kết quả

Dashboard huấn luyện khi bấm tính, không cần file model có sẵn. CLI lưu hai model: model holdout chỉ học trước kỳ cuối và model refit dùng toàn bộ lịch sử. Metadata lưu phạm vi lọc, ngày chốt, hàm mất mát, kỳ dự báo, các chỉ số, đánh giá nhiều cửa sổ và SHA256 chuỗi dữ liệu.

`src.dss.test` kiểm tra cặp model, metadata và dấu vân tay dữ liệu trước khi tái tạo kỳ holdout đã lưu. Lệnh này không tạo một tập kiểm tra mới và không thay thế bộ kiểm thử hồi quy cho ETL hoặc dashboard.

## 7. Mô phỏng kế hoạch bổ sung hàng

Gọi D là tổng nhu cầu dự báo, S là tồn kho, I là hàng đang về, B là dự phòng, C là giá vốn một sản phẩm và M là ngân sách:

```text
Nhu cầu làm tròn = ceil(D)
Lượng cần mua   = max(0, ceil(D) + B − S − I)
Lượng đủ tiền   = floor(M / C)
Lượng đề xuất   = min(lượng cần mua, lượng đủ tiền)
```

Tiền được quy đổi sang cent trước khi tính ngân sách. Kế hoạch trả lượng mua bằng 0 khi dự báo bị chặn hoặc giá bán không bù được giá vốn và tỷ lệ lưu kho giả định. Đây là quy tắc bổ sung cho một nhóm hàng tổng hợp, chưa phải bài toán tối ưu phân bổ ngân sách giữa các SKU.

Giá bán tham khảo bằng tiền hàng chia số lượng trong 90 ngày tới ngày chốt, không gồm phí vận chuyển. Giá vốn mặc định bằng 65% giá bán tham khảo để khởi tạo mô phỏng; người dùng có thể đổi. Tồn kho, hàng về, dự phòng, giá vốn, tỷ lệ lưu kho và ngân sách đều là giả định, không được suy ra từ dữ liệu Olist.

Thu giả định chỉ tính trên sản phẩm mua mới dự kiến bán được sau khi sử dụng tồn kho và hàng đang về. Chi mua tính trên toàn bộ lượng đề xuất; chi lưu kho ước tính bằng chi mua nhân tỷ lệ đã nhập. Chênh lệch thu − chi không phải lợi nhuận thực tế của doanh nghiệp, chưa phản ánh đầy đủ thuế, hoàn tiền, chi phí vận hành hoặc giá trị hàng tồn cuối kỳ.

Mô phỏng giá dùng quan hệ độ co giãn tuyến tính để tạo kịch bản nhu cầu. Hệ số độ co giãn do người dùng giả định, chưa được ước lượng nhân quả từ dữ liệu. Kết quả chỉ dùng so sánh giả định, không kết luận được mức giá hoặc mức giảm giá tối ưu.

## 8. Kết quả và kiểm chứng

### 8.1. Kho dữ liệu và truy vấn

| Chỉ tiêu | Kết quả |
|---|---:|
| Dòng order_items nguồn | 112.650 |
| Dòng fact được chấp nhận | 110.197 |
| Dòng loại do trạng thái đơn | 2.453 |
| Đơn đã giao | 96.478 |
| Khách hàng duy nhất | 93.358 |
| Giá trị hàng | 13.221.498,11 BRL |
| Phí vận chuyển | 2.198.275,64 BRL |
| Tổng gồm vận chuyển | 15.419.773,75 BRL |

Cả SQLite và PostgreSQL đạt 11/11 phép đối soát, không có vi phạm. Đối chiếu hai backend gồm KPI, roll-up thời gian/địa lý, phân trang, tìm mã đơn và chuỗi ngày dùng cho DSS. Năm phạm vi đã chạy:

| Phạm vi | Dòng hàng |
|---|---:|
| Toàn bộ, 15/09/2016–29/08/2018 | 110.197 |
| health_beauty, bang SP, toàn bộ thời gian | 4.125 |
| Southeast, 15/05/2018–21/07/2018 | 10.329 |
| Người bán `48436dade18ac8b2bce089ec2a041202`, toàn bộ thời gian | 147 |
| Ngành không tồn tại | 0 |

Phân trang được kiểm tra ở trang đầu, trang tiếp theo, trang cuối và offset sau kết quả. Với toàn bộ dữ liệu, trang đầu có 1.000 dòng, trang cuối có 197 dòng. Tìm kiếm kiểm tra chữ hoa/thường, một phần mã đơn và các ký tự `%`, `_`, `!`; chúng không làm mở rộng phạm vi ngoài nội dung tìm kiếm.

Chuỗi DSS từ truy vấn ngày của dashboard khớp truy vấn trực tiếp trong `XGBoostForecaster.load_data` sau khi điền ngày trống. Tổng lượng và tiền theo ngày khớp KPI cùng phạm vi. Các kết quả này xác nhận những trường hợp đã chạy, không bao phủ mọi tổ hợp bộ lọc hoặc truy cập đồng thời.

### 8.2. Đánh giá mô hình

Các kết quả sau dùng H = 30 ngày, 3 cửa sổ trước kỳ cuối, lịch sử từ 15/09/2016 và cùng cấu hình cây đã mô tả. WAPE tính theo %. Mỗi cặp số lần lượt là XGBoost / baseline.

| Phạm vi / ngày chốt | Hàm mất mát | WAPE kỳ cuối | WAPE gộp 3 cửa sổ trước | Trạng thái |
|---|---|---:|---:|---|
| Toàn bộ / 31/07/2018 | Bình phương | 25,95 / 24,62 | 21,54 / 27,60 | CAUTION |
| Toàn bộ / 31/07/2018 | Tuyệt đối | 23,81 / 24,62 | 23,20 / 27,60 | APPROVED |
| health_beauty / 31/07/2018 | Bình phương | 28,67 / 35,00 | 40,74 / 50,42 | CAUTION |
| health_beauty / 31/07/2018 | Tuyệt đối | 48,20 / 35,00 | 39,28 / 50,42 | CAUTION |
| Toàn bộ / 31/12/2017 | Bình phương | 284,07 / 112,50 | 29,44 / 29,43 | REJECTED |
| Toàn bộ / 31/12/2017 | Tuyệt đối | 56,27 / 112,50 | 29,22 / 29,43 | REJECTED |

Với ngày chốt 31/07/2018, kỳ cuối là 02–31/07/2018. Với ngày chốt 31/12/2017, kỳ cuối là 02–31/12/2017. Đây là kỳ đánh giá nằm trong lịch sử; dự báo tương lai bắt đầu sau ngày chốt và dùng model refit. Các con số được tái tạo trên SQLite với XGBoost 3.4.1; thay phiên bản thư viện có thể làm kết quả khác đôi chút.

Ở cấu hình mặc định, XGBoost tốt hơn baseline trên các cửa sổ trước nhưng kém hơn ở kỳ cuối. Hàm tuyệt đối cải thiện kỳ cuối toàn bộ dữ liệu, song làm kết quả ngành health_beauty kém đi; không có cơ sở chọn một hàm chỉ vì nó thắng ở một kỳ đã xem. Hai cấu hình tháng 12/2017 đều bị chặn. Trường hợp này cho thấy mô hình chưa ổn định trước các biến động lớn; project chưa triển khai đặc trưng ngày lễ hoặc xử lý ngoại lai được chọn bằng đánh giá thời gian.

## 9. Giới hạn và hướng phát triển

- Dữ liệu thuộc một nền tảng và giai đoạn lịch sử; chọn đơn cuối cùng đã giao tạo thiên lệch so với nhu cầu tại thời điểm đặt hàng.
- Không có lịch sử tồn kho, giá vốn, hoàn tiền hoặc thay đổi thuộc tính đầy đủ. Kế hoạch tài chính dùng giả định và chưa phân bổ theo SKU.
- Dự báo chịu ảnh hưởng của dữ liệu thưa, đỉnh bán bất thường và thay đổi xu hướng. Chưa có khoảng dự báo được hiệu chỉnh hoặc kiểm chứng độ bao phủ; không diễn giải kết quả thành P90.
- Mô hình và cổng chất lượng chưa hiệu chỉnh theo chi phí kinh doanh. Cần một kỳ mới chưa dùng khi điều chỉnh cấu hình để đo hiệu năng độc lập.
- ETL còn phần tra cứu từng dòng. Full refresh phù hợp với quy mô hiện tại; dữ liệu lớn hơn cần đo hiệu năng trước khi chuyển sang xử lý vector, nạp tăng dần hoặc materialized view.
- Phân trang OFFSET phải bỏ qua các dòng trước trang đích; khi dữ liệu tăng có thể chuyển sang phân trang theo khóa. Xuất toàn bộ CSV vẫn cần bộ nhớ theo kích thước kết quả.
- Chưa kiểm tra trên máy thành viên khác, Docker trên Linux/macOS hoặc tải nhiều người dùng đồng thời.
- Repo không giữ bộ kiểm thử hồi quy tự động cho toàn hệ thống. Đối soát ETL và lệnh tái tạo holdout vẫn có sẵn; các phép đối chiếu chạy riêng không tự phát hiện lỗi sau mỗi lần sửa code.

## 10. Chạy và tái tạo kết quả

Từ thư mục gốc project, tạo môi trường và chạy SQLite bằng PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.etl.load_dw
.\.venv\Scripts\python.exe -m src.etl.load_dw --verify
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Database mặc định ở `data/warehouse.db`. Nếu terminal đã đặt DATABASE_URL, xóa bằng `Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue` trước khi chạy SQLite. Với PostgreSQL, khởi động Docker Desktop rồi chạy:

```powershell
docker compose up -d --wait
$env:DATABASE_URL = 'postgresql+psycopg2://olist:olist_local@127.0.0.1:5434/olist_dw'
.\.venv\Scripts\python.exe -m src.etl.load_dw
.\.venv\Scripts\python.exe -m src.etl.load_dw --verify
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Tái tạo cấu hình dự báo mặc định và kiểm tra model đã lưu:

```powershell
.\.venv\Scripts\python.exe -m src.dss.train --cutoff 2018-07-31 --horizon 30 --loss squared --validation-windows 3
.\.venv\Scripts\python.exe -m src.dss.test
```

Thêm `--category health_beauty` để chạy theo ngành; đổi `--cutoff 2017-12-31` hoặc `--loss absolute` để tái tạo các cấu hình còn lại. Train hỗ trợ thêm `--start-date`, `--region`, `--state`, `--seller` và `--model`. Bộ lọc dùng mã gốc; có thể lặp một tùy chọn để chọn nhiều giá trị. Nếu dùng đường dẫn model riêng, truyền cùng `--model` khi test. Chi tiết tham số và cách xuất CSV nằm trong README.

## Tài liệu tham khảo

1. Olist, [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), giấy phép CC BY-NC-SA 4.0.
2. R. Kimball và M. Ross, *The Data Warehouse Toolkit*, 3rd edition, Wiley, 2013.
3. W. H. Inmon, *Building the Data Warehouse*, 4th edition, Wiley, 2005.
