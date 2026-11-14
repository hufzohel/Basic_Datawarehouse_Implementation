from html import escape

import pandas as pd
import streamlit as st


LABELS = {
    'train_end': 'Chốt huấn luyện', 'test_start': 'Bắt đầu kiểm tra', 'test_end': 'Kết thúc kiểm tra',
    'test_days': 'Số ngày', 'test_volume': 'Lượng bán thực tế', 'wape_percent': 'WAPE XGBoost (%)',
    'baseline_wape_percent': 'WAPE baseline (%)', 'mae': 'MAE', 'bias_percent': 'Độ lệch (%)', 'quality': 'Chất lượng',
    'region': 'Vùng', 'state': 'Bang', 'city': 'Thành phố',
    'category_name': 'Ngành hàng', 'seller_state': 'Bang người bán',
    'seller_id': 'Mã người bán', 'product_id': 'Mã sản phẩm',
    'order_id': 'Mã đơn hàng', 'order_item_id': 'Dòng hàng',
    'full_date': 'Ngày', 'period': 'Kỳ', 'year': 'Năm', 'quarter': 'Quý', 'month': 'Tháng',
    'quantity': 'Sản phẩm', 'orders': 'Đơn hàng', 'customers': 'Khách hàng',
    'merchandise_BRL': 'Giá trị hàng (BRL)', 'freight_BRL': 'Vận chuyển (BRL)',
    'total_revenue_BRL': 'Tổng gồm phí (BRL)', 'unit_price_BRL': 'Đơn giá (BRL)',
    'actual': 'Thực tế', 'predicted': 'Dự báo', 'baseline': 'Baseline 7 ngày',
    'demand_units': 'Nhu cầu', 'price_BRL': 'Giá bán (BRL)', 'cost_BRL': 'Giá vốn (BRL)',
    'revenue_BRL': 'Thu giả định (BRL)', 'profit_BRL': 'Chênh lệch thu − chi (BRL)',
    'Kịch_bản': 'Kịch bản', 'file': 'Tệp nguồn', 'rows': 'Số dòng',
    'check_name': 'Phép đối soát', 'violations': 'Vi phạm',
}
COLUMN_HELP = {
    'orders': 'Đếm không trùng trong từng nhóm; không cộng số đếm giữa các nhóm.',
    'customers': 'Đếm không trùng trong từng nhóm; không cộng số đếm giữa các nhóm.',
}
REGIONS = {'Southeast': 'Đông Nam', 'South': 'Miền Nam', 'Northeast': 'Đông Bắc',
           'Central-West': 'Trung Tây', 'North': 'Miền Bắc', 'Unknown': 'Chưa xác định'}


def category_label(value):
    names = {'Unknown': 'Unknown', 'pc_gamer': 'Gaming computers',
             'portateis_cozinha_e_preparadores_de_alimentos': 'Small kitchen appliances and food processors'}
    return names.get(value, str(value).replace('_', ' ').capitalize())


def style_page():
    st.markdown('''<style>
    .stApp {background:#f5f7fb;}
    .block-container {padding-top:2.7rem;padding-bottom:3rem;max-width:1540px;}
    h1 {letter-spacing:-.045em;font-weight:750;font-size:2.35rem;}
    h2,h3 {letter-spacing:-.025em;}
    [data-testid="stSidebar"] {background:#edf2f7;border-right:1px solid #dae3ed;}
    [data-testid="stSidebar"] .block-container {padding-top:1.5rem;}
    [data-testid="stMetric"] {background:white;border:1px solid #dfe6ee;border-top:3px solid #21765b;
        border-radius:12px;padding:15px 18px;box-shadow:0 3px 12px #19304705;}
    [data-testid="stMetricValue"] {font-size:clamp(1.15rem,1.8vw,1.8rem);font-variant-numeric:tabular-nums;}
    [data-testid="stMetricLabel"] {color:#53667b;}
    [data-testid="stDataFrame"] {border-radius:10px;}
    .brand {font-size:1.65rem;font-weight:800;letter-spacing:-.06em;color:#185b48;}
    .brand-sub {font-size:.78rem;color:#607187;margin-bottom:1.5rem;}
    .eyebrow {font-size:.72rem;letter-spacing:.16em;color:#21765b;font-weight:750;}
    .scope {display:flex;gap:7px;flex-wrap:wrap;margin:8px 0 20px;}
    .scope span {background:#eaf1f7;border:1px solid #dce5ed;border-radius:20px;
        color:#41576d;padding:5px 12px;font-size:.78rem;}
    .st-key-dashboard_page {background:white;border:1px solid #dfe6ee;border-radius:12px;padding:7px;margin:6px 0;}
    .st-key-dashboard_page [role="radiogroup"] {gap:6px;}
    .st-key-dashboard_page label {padding:8px 10px;border-radius:8px;margin:0;}
    .st-key-dashboard_page label p {font-size:.82rem;}
    .st-key-dashboard_page label:has(input:checked) {background:#e2efe9;color:#185b48;font-weight:700;}
    .st-key-dashboard_page label>div:first-child {display:none;}
    [data-testid="stDownloadButton"] button {border-color:#cedbd5;color:#185b48;}
    .kpi-strip {display:flex;flex-wrap:wrap;background:white;border:1px solid #dfe6ee;border-radius:12px;
        margin:0 0 18px;overflow:hidden;}
    .kpi-strip div {flex:1 1 150px;padding:10px 16px;border-right:1px solid #edf1f5;}
    .kpi-strip div:last-child {border-right:0;}
    .kpi-strip span {display:block;font-size:.72rem;color:#607187;}
    .kpi-strip b {font-size:1rem;font-weight:650;color:#172d26;font-variant-numeric:tabular-nums;white-space:nowrap;}
    @media(max-width:700px) {.block-container{padding:2rem 1rem;} h1{font-size:1.8rem;}}
    </style>''', unsafe_allow_html=True)


def scope_badges(values):
    st.markdown('<div class="scope">' + ''.join(f'<span>{escape(str(value))}</span>' for value in values) + '</div>', unsafe_allow_html=True)


def kpi_strip(items):
    """One compact row of (label, value) pairs, used on tabs where the full KPI cards would push content down."""
    cells = ''.join(f'<div><span>{escape(label)}</span><b>{escape(value)}</b></div>' for label, value in items)
    st.markdown(f'<div class="kpi-strip">{cells}</div>', unsafe_allow_html=True)


def display_table(frame, *, money_columns=(), height=None):
    table = frame.copy()
    config = {}
    for column in list(table.columns):
        if isinstance(column, str) and column.endswith('_cents'):
            target = column.removesuffix('_cents') + '_BRL'
            table[target] = table.pop(column) / 100
    for column in table:
        label = LABELS.get(column, column)
        if column == 'category_name':
            table[column] = table[column].map(category_label)
        elif column == 'region':
            table[column] = table[column].replace(REGIONS)
        elif column == 'quality':
            table[column] = table[column].replace({'APPROVED': 'Đạt', 'CAUTION': 'Cần thận trọng', 'REJECTED': 'Không đạt'})
        if column in money_columns or str(column).endswith('_BRL') or column == 'BRL':
            config[column] = st.column_config.NumberColumn(label, format='%.2f', help='BRL (R$), làm tròn đến 2 chữ số thập phân')
            table[column] = table[column].round(2)
        elif pd.api.types.is_datetime64_any_dtype(table[column]):
            config[column] = st.column_config.DateColumn(label, format='DD/MM/YYYY')
        elif pd.api.types.is_integer_dtype(table[column]):
            config[column] = st.column_config.NumberColumn(label, format='%d', help=COLUMN_HELP.get(column))
        elif pd.api.types.is_float_dtype(table[column]):
            config[column] = st.column_config.NumberColumn(label, format='%.2f')
        else:
            config[column] = st.column_config.TextColumn(label)
    if len(table) == 0:
        st.info('Không có kết quả phù hợp.')
    kwargs = {'height': height} if height else {}
    st.dataframe(table, column_config=config, use_container_width=True, hide_index=True, **kwargs)


def chart_style(chart, height=300):
    return chart.properties(height=height).configure_view(strokeWidth=0).configure_axis(
        labelColor='#61738a', titleColor='#61738a', gridColor='#edf1f5', domain=False,
        labelFontSize=11, titleFontSize=12,
    ).configure_legend(title=None, orient='top', labelColor='#53667b')
