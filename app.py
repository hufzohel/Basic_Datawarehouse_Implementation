import json
import math

import altair as alt
import pandas as pd
import streamlit as st

from src.analytics import (MEASURES, audit_summary, filter_options, sql_aggregate, sql_daily_series,
                           sql_detail, sql_detail_count, sql_metrics, sql_pivot, sql_rollup,
                           sql_time_series, warehouse_version)
from src.db import database_url
from src.dss_ui import compute_forecast, render_dss
from src.ui import REGIONS, category_label, chart_style, display_table, kpi_strip, scope_badges, style_page

st.set_page_config(page_title='Olist | Phân tích bán hàng', page_icon='🛒', layout='wide')
style_page()
for key in list(st.session_state):
    if key.startswith(('ui_', 'dss_')) and key != 'dss_compute' and not key.endswith(('_csv', '_reset_budget')):
        st.session_state[key] = st.session_state[key]


@st.cache_data(ttl=300, max_entries=3, show_spinner='Đang đọc kho dữ liệu...')
def options(url, run_id):
    return filter_options(url)


DETAIL_PAGE_SIZE = 1000


# Small aggregate results only; line-item tables use the two caches below.
@st.cache_data(ttl=300, max_entries=48, show_spinner=False)
def sales_query(url, run_id, operation, scope, *args):
    query = {'metrics': sql_metrics, 'aggregate': sql_aggregate, 'rollup': sql_rollup,
             'time_series': sql_time_series, 'pivot': sql_pivot, 'daily': sql_daily_series,
             'detail_count': sql_detail_count}[operation]
    return query(url, scope, *args)


@st.cache_data(ttl=300, max_entries=16, show_spinner=False)
def detail_page_query(url, run_id, scope, limit, offset):
    return sql_detail(url, scope, limit, offset)


@st.cache_data(ttl=300, max_entries=2, show_spinner='Đang chuẩn bị CSV...')
def detail_export_csv(url, run_id, scope):
    return sql_detail(url, scope).to_csv(index=False).encode('utf-8-sig')


def money(cents):
    return f'R$ {cents / 100:,.2f}'


def download(frame, label, filename, key, help=None):
    st.download_button(label, frame.to_csv(index=False).encode('utf-8-sig'), filename,
                       'text/csv', key=key, on_click='ignore', help=help)


def reset_filters(start, end):
    # Removing the key lets the date widget fall back to its full-range default, without the
    # "default value also set via Session State" warning that assigning it would trigger.
    st.session_state.pop('filter_dates', None)
    for key in ['filter_categories', 'filter_regions', 'filter_states', 'filter_sellers']:
        st.session_state[key] = []
    st.session_state['ui_order_search'] = ''
    st.session_state['ui_detail_page'] = 1
    st.session_state.pop('detail_export', None)
    st.session_state.pop('dss_result', None)


def refresh_data():
    options.clear()
    sales_query.clear()
    detail_page_query.clear()
    detail_export_csv.clear()
    compute_forecast.clear()
    st.session_state.pop('dss_result', None)
    st.session_state.pop('detail_export', None)


st.markdown('<div class="eyebrow">OLIST / KHO DỮ LIỆU & HỖ TRỢ QUYẾT ĐỊNH</div>', unsafe_allow_html=True)
st.title('Phân tích bán hàng')
st.caption('Đơn đã giao · Theo ngày đặt hàng · Đơn vị tiền tệ: BRL (R$)')
url = database_url()
try:
    version = warehouse_version(url)
    choices = options(url, version['run_id'])
except Exception:
    st.warning('Chưa kết nối được kho dữ liệu. Kiểm tra DATABASE_URL và nạp dữ liệu trước khi mở dashboard.')
    st.code('python -m src.etl.load_dw', language='bash')
    st.stop()
if pd.isna(choices['start']):
    st.info('Kho dữ liệu chưa có giao dịch.')
    st.stop()

with st.sidebar:
    st.markdown('<div class="brand">olist<span style="color:#6ca58d">.</span></div><div class="brand-sub">Phân tích thương mại điện tử</div>', unsafe_allow_html=True)
    st.subheader('Phạm vi phân tích')
    date_range = st.date_input('Ngày đặt hàng', (choices['start'].date(), choices['end'].date()),
                               min_value=choices['start'].date(), max_value=choices['end'].date(), key='filter_dates', format='DD/MM/YYYY')
    categories = st.multiselect('Ngành hàng', choices['categories'], key='filter_categories', format_func=category_label, placeholder='Tất cả ngành hàng')
    geography = choices['geography']
    regions = st.multiselect('Vùng khách hàng', sorted(geography.region.unique()), key='filter_regions', format_func=lambda x: REGIONS.get(x, x), placeholder='Tất cả vùng')
    state_options = geography[geography.region.isin(regions)].state.unique() if regions else geography.state.unique()
    if 'filter_states' in st.session_state:
        st.session_state.filter_states = [x for x in st.session_state.filter_states if x in state_options]
    states = st.multiselect('Bang khách hàng', sorted(state_options), key='filter_states', placeholder='Tất cả bang')
    with st.expander('Lọc theo người bán', expanded=bool(st.session_state.get('filter_sellers'))):
        sellers = st.multiselect('Người bán', choices['sellers'], key='filter_sellers', placeholder='Tất cả người bán')
    st.button('Xóa bộ lọc', on_click=reset_filters,
              args=(choices['start'].date(), choices['end'].date()), use_container_width=True)
    st.divider()
    st.button('Làm mới dữ liệu', on_click=refresh_data, use_container_width=True)
    st.caption(f"Dữ liệu Olist · {choices['start']:%m/%Y} – {choices['end']:%m/%Y}")

page = st.radio('Điều hướng', ['Tổng quan', 'Phân tích đa chiều', 'Dự báo & kế hoạch', 'Chi tiết giao dịch', 'Kho dữ liệu'],
                horizontal=True, key='dashboard_page', label_visibility='collapsed')

if page == 'Kho dữ liệu':
    summary = audit_summary(version)
    checks = pd.DataFrame(summary['checks'])
    st.subheader('Trạng thái kho dữ liệu')
    a, b, c = st.columns(3)
    a.metric('Dòng hàng trong kho', f"{summary['fact_rows']:,}")
    b.metric('Phép đối soát đạt', f"{(checks.violations == 0).sum()} / {len(checks)}")
    c.metric('Tổng vi phạm', f'{checks.violations.sum():,}')
    finished = pd.to_datetime(version['finished_at'], utc=True).tz_convert('Asia/Ho_Chi_Minh')
    st.caption(f'Lần nạp gần nhất: {finished:%H:%M · %d/%m/%Y} · Toàn bộ kho, không theo bộ lọc')
    with st.container(border=True):
        st.subheader('Nguồn dữ liệu')
        display_table(pd.DataFrame(summary['sources'])[['file', 'rows']])
    left, right = st.columns([1, 2])
    with left, st.container(border=True):
        st.subheader('Làm sạch')
        dispositions = pd.DataFrame(summary['dispositions'].items(), columns=['Kết quả', 'Số dòng'])
        dispositions['Kết quả'] = dispositions['Kết quả'].replace({'accepted': 'Đã nạp', 'excluded_order_status': 'Loại theo trạng thái đơn'})
        display_table(dispositions)
    check_labels = {'fact_row_count': 'Số dòng fact', 'line_values_and_dimensions': 'Giá trị và chiều từng dòng',
                    'duplicate_line_items': 'Dòng hàng trùng', 'source_row_accounting': 'Đối chiếu dòng nguồn',
                    'accepted_row_accounting': 'Đối chiếu dòng đã nạp', 'merchandise_cents': 'Tổng tiền hàng',
                    'freight_cents': 'Tổng phí vận chuyển', 'revenue_identity': 'Tiền hàng + vận chuyển',
                    'daily_view_groups': 'Tổng hợp theo ngày', 'category_view_groups': 'Tổng hợp ngành hàng',
                    'geography_view_groups': 'Tổng hợp địa lý'}
    with right, st.container(border=True):
        st.subheader('Đối soát khi nạp')
        checks.check_name = checks.check_name.replace(check_labels)
        display_table(checks, height=430)
    st.stop()

if len(date_range) != 2:
    st.info('Chọn đủ ngày bắt đầu và ngày kết thúc.')
    st.stop()
start, end = date_range
scope_badges([f'{start:%d/%m/%Y} – {end:%d/%m/%Y}',
              f'{len(categories)} ngành hàng' if categories else 'Tất cả ngành hàng',
              ', '.join(states) if states else (', '.join(REGIONS.get(x, x) for x in regions) if regions else 'Toàn bộ Brazil'),
              f'{len(sellers)} người bán' if sellers else 'Tất cả người bán'])
scope = {'start': str(start), 'end': str(end), 'categories': categories,
         'regions': regions, 'states': states, 'sellers': sellers}


def query(operation, *args):
    return sales_query(url, version['run_id'], operation, scope, *args)


kpi = query('metrics')
if not kpi['fact_rows']:
    st.info('Không có giao dịch trong phạm vi đã chọn. Hãy đổi thời gian hoặc bộ lọc.')
    st.stop()
KPI_ITEMS = [('Giá trị hàng', 'merchandise_cents'), ('Phí vận chuyển', 'freight_cents'),
             ('Tổng gồm vận chuyển', 'total_revenue_cents'), ('Đơn hàng', 'orders'),
             ('Sản phẩm bán', 'quantity'), ('Khách hàng', 'customers')]
DISTINCT_HELP = 'Đếm không trùng trong phạm vi đang chọn.'


def kpi_text(key, value):
    return money(value) if key.endswith('_cents') else f'{value:,}'


if page == 'Tổng quan':
    # Compare with the period of equal length just before the selected one, when the warehouse covers it fully.
    previous_end = start - pd.Timedelta(days=1)
    previous_start = previous_end - (end - start)
    previous = None
    if previous_start >= choices['start'].date():
        previous = sales_query(url, version['run_id'], 'metrics',
                               scope | {'start': str(previous_start), 'end': str(previous_end)})
    compare_help = (f'So với {previous_start:%d/%m/%Y} – {previous_end:%d/%m/%Y}.' if previous
                    else 'Không có kỳ trước cùng độ dài trong dữ liệu để so sánh.')
    for row in (KPI_ITEMS[:3], KPI_ITEMS[3:]):
        for col, (label, key) in zip(st.columns(3), row):
            delta = None
            if previous and previous[key]:
                delta = f'{100 * (kpi[key] - previous[key]) / previous[key]:+.1f}%'
            help_text = compare_help if key not in ('orders', 'customers') else f'{DISTINCT_HELP} {compare_help}'
            col.metric(label, kpi_text(key, kpi[key]), delta=delta, help=help_text)
else:
    kpi_strip([(label, kpi_text(key, kpi[key])) for label, key in KPI_ITEMS])

if page == 'Tổng quan':
    st.subheader('Diễn biến bán hàng')
    st.session_state.setdefault('ui_time_level', 'Tháng')
    time_level = st.radio('Cấp thời gian', ['Năm', 'Quý', 'Tháng', 'Ngày'], horizontal=True, key='ui_time_level')
    trend = query('time_series', time_level)
    trend['Giá trị hàng (BRL)'] = trend.merchandise_cents / 100
    chart = alt.Chart(trend).mark_area(color='#21765b', opacity=.14, line={'color': '#21765b', 'strokeWidth': 2.5}).encode(
        x=alt.X('period:O', title=None, sort=None),
        y=alt.Y('Giá trị hàng (BRL):Q', title='BRL'),
        tooltip=[alt.Tooltip('period:O', title='Kỳ'), alt.Tooltip('Giá trị hàng (BRL):Q', format=',.2f'),
                 alt.Tooltip('orders:Q', title='Đơn hàng'), alt.Tooltip('quantity:Q', title='Sản phẩm')])
    with st.container(border=True):
        st.altair_chart(chart_style(chart, 310), use_container_width=True)
    a, b, c = st.columns(3)
    a.metric('Giá trị hàng / đơn', money(kpi['merchandise_cents'] / kpi['orders']))
    b.metric('Sản phẩm / đơn', f"{kpi['quantity'] / kpi['orders']:.2f}")
    c.metric('Tỷ trọng vận chuyển', f"{100*kpi['freight_cents']/kpi['total_revenue_cents']:.1f}%" if kpi['total_revenue_cents'] else '—')
    left, right = st.columns(2)
    for container, title, column in [(left, 'Ngành hàng có giá trị cao nhất', 'category_name'),
                                      (right, 'Phân bố theo bang', 'state')]:
        with container, st.container(border=True):
            st.subheader(title)
            ranked = query('aggregate', [column]).sort_values('merchandise_cents', ascending=False).head(10)
            ranked['BRL'] = ranked.merchandise_cents / 100
            if column == 'category_name':
                ranked[column] = ranked[column].map(category_label)
            st.altair_chart(chart_style(alt.Chart(ranked).mark_bar(color='#3b8d72', cornerRadiusEnd=4, size=17).encode(
                x=alt.X('BRL:Q', title='Giá trị hàng (BRL)'),
                y=alt.Y(f'{column}:N', sort='-x', title=None, axis=alt.Axis(labelLimit=165)),
                tooltip=[alt.Tooltip(f'{column}:N', title='Ngành hàng' if column == 'category_name' else 'Bang'), alt.Tooltip('BRL:Q', format=',.2f'), alt.Tooltip('orders:Q', title='Đơn hàng'), alt.Tooltip('quantity:Q', title='Sản phẩm')]), 330), use_container_width=True)
    with st.container(border=True):
        st.subheader('Giá trị hàng theo thứ trong tuần',
                     help='Giá trị hàng trung bình mỗi ngày, theo thứ và tháng; ngày không bán được tính là 0.')
        daily = query('aggregate', ['full_date'])[['full_date', 'merchandise_cents']]
        daily['full_date'] = pd.to_datetime(daily.full_date)
        calendar = pd.DataFrame({'full_date': pd.date_range(start, end)}).merge(daily, how='left').fillna(0)
        calendar['month'] = calendar.full_date.dt.strftime('%Y-%m')
        calendar['weekday'] = calendar.full_date.dt.dayofweek.map(dict(enumerate(['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'])))
        heat = calendar.groupby(['month', 'weekday'], as_index=False).agg(
            BRL=('merchandise_cents', lambda cents: cents.mean() / 100), days=('full_date', 'size'))
        st.altair_chart(chart_style(alt.Chart(heat).mark_rect(cornerRadius=2).encode(
            x=alt.X('month:O', title=None, axis=alt.Axis(labelAngle=-90)),
            y=alt.Y('weekday:O', title=None, sort=['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']),
            color=alt.Color('BRL:Q', title='BRL/ngày', scale=alt.Scale(scheme='greens'),
                            legend=alt.Legend(orient='right', format=',.0f')),
            tooltip=[alt.Tooltip('month:O', title='Tháng'), alt.Tooltip('weekday:O', title='Thứ'),
                     alt.Tooltip('BRL:Q', title='Trung bình BRL/ngày', format=',.2f'), alt.Tooltip('days:Q', title='Số ngày')]), 230),
            use_container_width=True)
    download(trend.drop(columns='Giá trị hàng (BRL)'), 'Tải chuỗi thời gian', 'sales_timeseries.csv', 'trend_csv')

elif page == 'Phân tích đa chiều':
    st.subheader('Từ tổng hợp đến chi tiết')
    dimension = st.selectbox('Chiều phân tích', ['Địa lý', 'Sản phẩm', 'Thời gian', 'Người bán'], key='ui_dimension')
    if dimension == 'Địa lý':
        level = st.radio('Cấp địa lý', ['Vùng', 'Bang', 'Thành phố'], horizontal=True, key='ui_geo_level')
        columns = {'Vùng': ['region'], 'Bang': ['region', 'state'], 'Thành phố': ['region', 'state', 'city']}[level]
    elif dimension == 'Sản phẩm':
        level = st.radio('Cấp sản phẩm', ['Ngành hàng', 'Sản phẩm'], horizontal=True, key='ui_product_level')
        columns = ['category_name'] if level == 'Ngành hàng' else ['category_name', 'product_id']
    elif dimension == 'Thời gian':
        level = st.radio('Cấp tổng hợp', ['Năm', 'Quý', 'Tháng'], horizontal=True, key='ui_rollup_time')
        columns = {'Năm': ['year'], 'Quý': ['year', 'quarter'], 'Tháng': ['year', 'quarter', 'month']}[level]
    else:
        columns = ['seller_state', 'seller_id']
    hierarchy = {'Địa lý': ['region', 'state', 'city'], 'Thời gian': ['year', 'quarter', 'month']}.get(dimension)
    if hierarchy:
        rollup = query('rollup', hierarchy)
        grouped = rollup.loc[rollup.grouping_depth == len(columns), columns + list(MEASURES)].copy()
        for column in set(columns) & {'year', 'quarter', 'month'}:
            grouped[column] = grouped[column].astype('int64')
    else:
        grouped = query('aggregate', columns)
    grouped = grouped.sort_values('merchandise_cents', ascending=False)
    with st.container(border=True):
        display_table(grouped)
    if hierarchy:
        with st.expander('Tổng toàn bộ phạm vi'):
            display_table(rollup.loc[rollup.grouping_depth == 0].drop(columns=hierarchy + ['grouping_depth']))
    download(grouped, 'Tải bảng tổng hợp', 'sales_rollup.csv', 'rollup_csv')
    st.subheader('Pivot ngành hàng × bang')
    measures = {'Giá trị hàng (BRL)': 'merchandise_cents', 'Tổng gồm phí (BRL)': 'total_revenue_cents',
                'Sản phẩm': 'quantity', 'Đơn hàng': 'orders', 'Khách hàng': 'customers'}
    measure = measures[st.selectbox('Chỉ tiêu', list(measures), key='ui_pivot_measure')]
    matrix = query('pivot', measure)
    display_matrix = (matrix / 100 if measure.endswith('_cents') else matrix).reset_index()
    display_table(display_matrix, money_columns=list(matrix.columns) if measure.endswith('_cents') else ())
    download(matrix.reset_index(), 'Tải pivot CSV', f'sales_pivot_{measure}.csv', 'pivot_csv',
             help='Tiền trong CSV tính theo cent (100 cent = 1 BRL).')

elif page == 'Dự báo & kế hoạch':
    render_dss(query('daily'), url, version, start, end, categories, regions, states, sellers)

elif page == 'Chi tiết giao dịch':
    st.subheader('Dòng hàng đã giao')
    order = st.text_input('Tìm mã đơn hàng', placeholder='Nhập toàn bộ hoặc một phần mã đơn...', key='ui_order_search')
    detail_scope = scope | {'order_search': order.strip()}
    signature = json.dumps(detail_scope, sort_keys=True)
    if st.session_state.get('ui_detail_signature') != signature:
        st.session_state['ui_detail_signature'] = signature
        st.session_state['ui_detail_page'] = 1
    total = sales_query(url, version['run_id'], 'detail_count', detail_scope)
    pages = max(1, math.ceil(total / DETAIL_PAGE_SIZE))
    # Clamp before the widget is created so a stale page number never exceeds max_value.
    st.session_state['ui_detail_page'] = min(max(1, int(st.session_state.get('ui_detail_page', 1))), pages)
    page_number = st.columns([1, 3])[0].number_input('Trang', min_value=1, max_value=pages, step=1, key='ui_detail_page')
    first = (page_number - 1) * DETAIL_PAGE_SIZE
    rows = detail_page_query(url, version['run_id'], detail_scope, DETAIL_PAGE_SIZE, first)
    if total:
        st.caption(f'{total:,} dòng · trang {page_number:,}/{pages:,} · dòng {first + 1:,}–{first + len(rows):,}')
    display_table(rows)
    if total and st.session_state.get('detail_export') == signature:
        st.download_button('Tải chi tiết CSV', detail_export_csv(url, version['run_id'], detail_scope),
                           'sales_detail.csv', 'text/csv', key='detail_csv', on_click='ignore')
    elif total:
        st.button(f'Chuẩn bị CSV toàn bộ kết quả ({total:,} dòng)', key='detail_prepare',
                  on_click=lambda: st.session_state.update(detail_export=signature))
