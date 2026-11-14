import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_UP

import altair as alt
import pandas as pd
import streamlit as st

from src.dss.simulator import InventorySimulator
from src.ui import chart_style, display_table


@st.cache_data(ttl=300, max_entries=12, show_spinner='Đang huấn luyện và đánh giá XGBoost...')
def compute_forecast(history, horizon, run_id, scope, loss='squared'):
    from src.dss.forecast import XGBoostForecaster
    forecaster = XGBoostForecaster(loss=loss)
    forecaster.df = forecaster._prepare_continuous_series(history, scope['start_date'], scope['cutoff'])
    forecaster.scope = scope
    result = forecaster.train_and_evaluate(test_days=horizon)
    return {key: value for key, value in result.items() if key not in ('model', 'evaluation_model')} | {
        'forecast': forecaster.forecast(horizon), 'history': forecaster.df,
    }


def to_cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def percentage(value):
    return f'{value:.2f}%' if math.isfinite(value) else 'Không xác định'


def export_frame(frame, context):
    result = frame.copy()
    for key, value in context.items():
        result[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
    return result.to_csv(index=False).encode('utf-8-sig')


def render_dss(daily, url, version, start, end, categories, regions, states, sellers):
    """daily: SQL daily totals (quantity, merchandise_cents, total_revenue_cents) for the filtered start..end scope."""
    st.subheader('Dự báo và kế hoạch bổ sung hàng')
    end_day = pd.Timestamp(end)
    default_cutoff = end_day if end_day.is_month_end else end_day.to_period('M').start_time - pd.Timedelta(days=1)
    default_cutoff = max(pd.Timestamp(start), default_cutoff).date()
    cutoff_key = f'dss_cutoff_{start}_{end}'
    st.session_state.setdefault(cutoff_key, default_cutoff)
    loss_labels = {'squared': 'XGBoost gốc · sai số bình phương', 'absolute': 'XGBoost · sai số tuyệt đối'}
    with st.container(border=True):
        left, middle, right = st.columns([1.2, 1, 1], vertical_alignment='bottom')
        cutoff = left.date_input('Ngày chốt lịch sử', min_value=start, max_value=end, key=cutoff_key, format='DD/MM/YYYY',
                                 help='Mô hình chỉ dùng giao dịch từ ngày bắt đầu bộ lọc đến ngày này.')
        horizon = middle.selectbox('Kỳ dự báo (ngày)', [30, 60, 90], key='dss_horizon',
                                   help='Số ngày cuối lịch sử được giữ riêng để kiểm tra, cũng là số ngày dự báo tiếp theo. '
                                        'Tối đa 3 cửa sổ trước đó dùng để đánh giá độ ổn định.')
        compute = right.button('Tính dự báo', type='primary', key='dss_compute', use_container_width=True,
                               help='Huấn luyện XGBoost trên lượng bán theo ngày của phạm vi đang lọc.')
        with st.expander('Thiết lập mô hình'):
            loss = st.selectbox('Hàm mất mát', list(loss_labels), format_func=loss_labels.get, key='dss_loss',
                                help='Sai số tuyệt đối giảm ảnh hưởng của các ngày bất thường. '
                                     'Nên chọn theo kết quả các cửa sổ trước kỳ cuối, không theo kỳ cuối.')
    scope = {'start_date': str(start), 'cutoff': str(cutoff), 'categories': sorted(categories),
             'regions': sorted(regions), 'states': sorted(states), 'sellers': sorted(sellers)}
    signature = hashlib.sha256(json.dumps([url, version['run_id'], scope, horizon, loss, 'rolling-v1'], sort_keys=True).encode()).hexdigest()[:20]
    historical_rows = daily[daily.full_date <= pd.Timestamp(cutoff)].reset_index(drop=True)
    if compute:
        st.session_state.pop('dss_result', None)
        try:
            history = historical_rows[['full_date', 'quantity', 'total_revenue_cents']]
            result = compute_forecast(history, horizon, version['run_id'], scope, loss)
            st.session_state['dss_result'] = (signature, result)
        except ImportError:
            st.error('Thiếu thư viện dự báo. Chạy python -m pip install -r requirements.txt rồi mở lại ứng dụng.')
        except ValueError as error:
            st.warning(str(error))
    saved = st.session_state.get('dss_result')
    if saved is None or saved[0] != signature:
        st.info('Bấm Tính dự báo để xem kết quả cho phạm vi đang chọn.')
        return
    result = saved[1]
    metrics, gate = result['metrics'], result['quality_gate']
    demand = float(result['forecast'].predicted.sum())
    test_help = (f"Kỳ kiểm tra {metrics['test_days']} ngày, {metrics['test_volume']:,.0f} sản phẩm · "
                 f"MAE {metrics['MAE']:.2f} sản phẩm/ngày · RMSE {metrics['RMSE']:.2f}")
    status = {'APPROVED': 'Đạt ngưỡng chất lượng', 'CAUTION': 'Cần xem xét thận trọng', 'REJECTED': 'Chưa đủ điều kiện lập kế hoạch'}[gate['status']]
    messages = gate['reasons'] + gate['warnings']
    alert, icon = {'APPROVED': (st.success, ':material/check_circle:'), 'CAUTION': (st.warning, ':material/warning:'),
                   'REJECTED': (st.error, ':material/block:')}[gate['status']]
    alert(status + ('\n\n' + '\n'.join(f'- {message}' for message in messages) if messages else ''), icon=icon)
    for col, label, value, help_text in zip(
            st.columns(3), ['Sản phẩm dự báo', 'WAPE XGBoost', 'WAPE baseline 7 ngày'],
            [f'{demand:,.1f}', percentage(metrics['WAPE_percent']), percentage(result['baseline_metrics']['WAPE_percent'])],
            [f'Tổng {horizon} ngày sau ngày chốt.', test_help, 'Lặp lại lượng bán 7 ngày cuối tập huấn luyện.']):
        col.metric(label, value, help=help_text)
    history_line = result['history'].tail(90)[['full_date', 'quantity']].rename(columns={'quantity': 'Sản phẩm'})
    history_line['Chuỗi'] = 'Lịch sử'
    forecast_line = result['forecast'].rename(columns={'predicted': 'Sản phẩm'}).assign(Chuỗi='Dự báo')
    chart_data = pd.concat([history_line, forecast_line], ignore_index=True)
    # Shade the forecast period so the hand-over from history to forecast is visible at a glance.
    forecast_band = pd.DataFrame({'start': [forecast_line.full_date.min()], 'end': [forecast_line.full_date.max()]})
    band = alt.Chart(forecast_band).mark_rect(color='#c78432', opacity=.07).encode(x='start:T', x2='end:T')
    lines = alt.Chart(chart_data).mark_line(strokeWidth=2.5).encode(
        x=alt.X('full_date:T', title=None), y=alt.Y('Sản phẩm:Q', title='Sản phẩm/ngày'),
        color=alt.Color('Chuỗi:N', scale=alt.Scale(domain=['Lịch sử', 'Dự báo'], range=['#21765b', '#c78432'])),
        tooltip=[alt.Tooltip('full_date:T', title='Ngày', format='%d/%m/%Y'), 'Chuỗi:N', alt.Tooltip('Sản phẩm:Q', format=',.1f')])
    with st.container(border=True):
        st.markdown(f'**Lượng bán 90 ngày gần nhất và dự báo {horizon} ngày**')
        st.altair_chart(chart_style(band + lines, 300), use_container_width=True)
    with st.expander('Đối chiếu trên tập kiểm tra'):
        evaluation = result['evaluation'].melt(id_vars='full_date', value_vars=['actual', 'predicted', 'baseline'], var_name='Chuỗi', value_name='Sản phẩm')
        evaluation['Chuỗi'] = evaluation['Chuỗi'].replace({'actual': 'Thực tế', 'predicted': 'Dự báo', 'baseline': 'Baseline 7 ngày'})
        st.altair_chart(chart_style(alt.Chart(evaluation).mark_line().encode(x=alt.X('full_date:T', title='Ngày'), y='Sản phẩm:Q', color='Chuỗi:N', tooltip=[alt.Tooltip('full_date:T', title='Ngày', format='%d/%m/%Y'), 'Chuỗi:N', alt.Tooltip('Sản phẩm:Q', format=',.1f')])), use_container_width=True)
        display_table(result['evaluation'])
    validation = result['validation']
    with st.expander('Độ ổn định qua các cửa sổ thời gian'):
        if validation['window_count']:
            pooled_help = 'Tổng sai số tuyệt đối chia tổng lượng bán thực tế của các cửa sổ trước kỳ cuối.'
            a, b, c = st.columns(3)
            a.metric('WAPE gộp XGBoost', percentage(validation['metrics']['WAPE_percent']), help=pooled_help)
            b.metric('WAPE gộp baseline', percentage(validation['baseline_metrics']['WAPE_percent']), help=pooled_help)
            c.metric('Cửa sổ tốt hơn baseline', f"{validation['wins_over_baseline']} / {validation['window_count']}")
            validation_table = pd.DataFrame(validation['windows'])
            for column in ['train_end', 'test_start', 'test_end']:
                validation_table[column] = pd.to_datetime(validation_table[column])
            display_table(validation_table)
        else:
            st.info('Chưa đủ lịch sử cho một cửa sổ trước kỳ kiểm tra cuối.')
    context = {'history_start': str(start), 'cutoff': str(cutoff), 'horizon': horizon,
               'scope': scope, 'model': 'XGBoost', 'loss': loss, 'quality': gate['status'], 'run_id': version['run_id'],
               'wape_percent': metrics['WAPE_percent'] if math.isfinite(metrics['WAPE_percent']) else None}
    first, second, _ = st.columns([1, 1, 2])
    with first:
        st.download_button('Tải dự báo CSV', export_frame(result['forecast'], context),
                           'forecast.csv', 'text/csv', key='dss_forecast_csv', on_click='ignore', use_container_width=True)
    if validation['window_count']:
        with second:
            st.download_button('Tải đánh giá nhiều cửa sổ', export_frame(pd.DataFrame(validation['windows']), context),
                               'forecast_validation.csv', 'text/csv', key='dss_validation_csv', on_click='ignore',
                               use_container_width=True)
    if not gate['passed_quality_gate']:
        st.info('Thử mở rộng phạm vi hoặc chọn khoảng lịch sử dài hơn. Kế hoạch mua hàng bị chặn với dự báo hiện tại.')
        return

    st.subheader('Kế hoạch theo tồn kho và ngân sách',
                 help='Kế hoạch tổng hợp cho cả phạm vi, chưa chia theo SKU. Tồn kho, hàng đang về, dự phòng và giá vốn do người dùng nhập.')
    recent = historical_rows[historical_rows.full_date > pd.Timestamp(cutoff) - pd.Timedelta(days=90)]
    average_price = float(recent.merchandise_cents.sum() / recent.quantity.sum()) if recent.quantity.sum() else 0
    prefix = f'dss_{signature}_'
    defaults = {'price': round(average_price / 100, 2), 'cost': round(average_price * .65 / 100, 2),
                'budget': math.ceil(demand) * round(average_price * .65) / 100,
                'holding': 5.0, 'price_change': 0, 'cost_change': 0, 'elasticity': -1.5}
    for name, value in defaults.items():
        st.session_state.setdefault(prefix + name, value)
    inputs, outputs = st.columns([1.1, 1], gap='large')
    with inputs, st.container(border=True):
        st.markdown('**Giả định đầu vào**')
        a, b = st.columns(2)
        stock = a.number_input('Tồn kho (sản phẩm)', min_value=0, step=1, key=prefix+'stock')
        incoming = b.number_input('Hàng đang về (sản phẩm)', min_value=0, step=1, key=prefix+'incoming')
        safety = a.number_input('Dự phòng (sản phẩm)', min_value=0, step=1, key=prefix+'safety')
        holding = b.number_input('Tỷ lệ lưu kho giả định (%)', min_value=0.0, max_value=100.0, step=1.0, key=prefix+'holding',
                                 help='Chi phí lưu kho tính theo phần trăm chi phí mua.')
        price = a.number_input('Giá bán tham khảo (BRL/sản phẩm)', min_value=0.0, step=1.0, key=prefix+'price',
                               help='Mặc định: tiền hàng chia số lượng trong 90 ngày trước ngày chốt, không gồm phí vận chuyển.')
        cost = b.number_input('Giá vốn giả định (BRL/sản phẩm)', min_value=0.0, step=1.0, key=prefix+'cost',
                              help='Dữ liệu Olist không có giá vốn; mặc định lấy 65% giá bán tham khảo.')
        budget_column, button_column = st.columns([1.3, 1], vertical_alignment='bottom')
        # The button runs before the budget widget is created, so it may still set the budget value.
        if button_column.button('Đặt ngân sách đủ', key=prefix+'reset_budget', use_container_width=True,
                                help='Ngân sách = lượng cần bổ sung × giá vốn.'):
            st.session_state[prefix+'budget'] = max(0, math.ceil(demand) + safety - stock - incoming) * to_cents(cost) / 100
        budget = budget_column.number_input('Ngân sách (BRL)', min_value=0.0, step=100.0, key=prefix+'budget')
    with outputs:
        simulator = InventorySimulator()
        try:
            plan = simulator.optimize_replenishment(demand, to_cents(cost), to_cents(price), to_cents(budget),
                                                   holding / 100, stock, incoming, safety, gate)
        except ValueError as error:
            st.warning(str(error))
            return
        for message in plan['reasons']:
            st.warning(message)
        a, b = st.columns(2)
        a.metric('Cần bổ sung', f"{plan['required_order_units']:,}", help='max(0, dự báo + dự phòng − tồn kho − hàng đang về)')
        b.metric('Có thể mua', f"{plan['recommended_order_units']:,}", help='Giới hạn bởi ngân sách và giá vốn.')
        a.metric('Chi phí mua (BRL)', f"{plan['total_purchase_cost_cents']/100:,.2f}")
        b.metric('Còn thiếu', f"{plan['unmet_demand_units']:,}", help='Phần cần bổ sung chưa mua được trong ngân sách.')
        required = plan['required_order_units']
        coverage = min(1.0, plan['recommended_order_units'] / required) if required else 1.0
        st.progress(coverage, text=f'Đáp ứng {coverage:.1%} lượng cần bổ sung')
        st.markdown('**Thu chi giả định**', help='Chỉ tính thu từ phần mua mới đáp ứng nhu cầu; hàng dự phòng chưa tính là đã bán. '
                                                 'Đây không phải lợi nhuận thực tế của Olist.')
        finance = pd.DataFrame({'Chỉ tiêu': ['Thu giả định từ phần mua mới', 'Chi phí mua', 'Chi phí lưu kho giả định', 'Chênh lệch thu - chi giả định'],
                                'BRL': [plan[key]/100 for key in ['projected_revenue_cents', 'total_purchase_cost_cents', 'estimated_holding_cost_cents', 'projected_gross_profit_cents']]})
        display_table(finance)
        plan_export = pd.DataFrame([{key: value for key, value in plan.items() if key != 'reasons'}])
        st.download_button('Tải kế hoạch CSV', export_frame(plan_export, context | {'unit_price_cents': to_cents(price), 'unit_cost_cents': to_cents(cost), 'holding_cost_pct': holding / 100}),
                           'replenishment_plan.csv', 'text/csv', key='dss_plan_csv', on_click='ignore')
    with st.expander('Độ nhạy giá và giá vốn'):
        a, b, c = st.columns(3)
        price_change = a.slider('Thay đổi giá bán (%)', -20, 20, key=prefix+'price_change')
        cost_change = b.slider('Thay đổi giá vốn (%)', -20, 50, key=prefix+'cost_change')
        elasticity = c.number_input('Độ co giãn giả định', min_value=-5.0, max_value=0.0, step=.1, key=prefix+'elasticity',
                                    help='Ví dụ −1,5: giá tăng 10% thì nhu cầu giảm 15%. Đây là giả định, không ước lượng từ dữ liệu.')
        if price > 0:
            scenario = InventorySimulator(elasticity).run_what_if_scenario(demand, to_cents(price), to_cents(cost), price_change, cost_change)
            comparison = pd.DataFrame([dict(Kịch_bản='Gốc', **scenario['baseline']), dict(Kịch_bản='Thay đổi', **scenario['simulated'])])
            for column in list(comparison.columns):
                if column.endswith('_cents'):
                    comparison[column.replace('_cents', '_BRL')] = comparison.pop(column) / 100
            display_table(comparison)
