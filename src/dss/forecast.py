import hashlib
import pandas as pd
import numpy as np
import xgboost as xgb
from sqlalchemy import bindparam, text

from src.db import database_url, get_engine

class XGBoostForecaster:
    """
    XGBoost Time-Series Forecasting Engine for DSS with Quality Gate Checks.
    """
    FEATURE_COLUMNS = [
        'day_of_week', 'day_of_month', 'month', 'is_weekend',
        'lag_1', 'lag_7', 'lag_14', 'lag_28',
        'rolling_mean_7', 'rolling_mean_28', 'rolling_std_7'
    ]

    OBJECTIVES = {'squared': 'reg:squarederror', 'absolute': 'reg:absoluteerror'}

    def __init__(self, db_uri: str = None, loss: str = 'squared'):
        if loss not in self.OBJECTIVES:
            raise ValueError('Hàm mất mát phải là squared hoặc absolute.')
        self.db_uri = db_uri or database_url()
        self.loss = loss
        self.df = None
        self.model = None
        self.scope = {}

    def load_data(self, start_date=None, cutoff=None, categories=(), regions=(), states=(), sellers=()) -> pd.DataFrame:
        """Read daily sales within the selected history and warehouse scope."""
        query = """
            SELECT 
                d.full_date,
                SUM(f.quantity) AS quantity,
                SUM(f.total_revenue_cents) AS total_revenue_cents
            FROM fact_sales f
            JOIN dim_date d ON f.date_key = d.date_key
            JOIN dim_customer c ON f.customer_key = c.customer_key
            JOIN dim_product p ON f.product_key = p.product_key
            JOIN dim_seller s ON f.seller_key = s.seller_key
            WHERE d.full_date >= :start_date AND d.full_date <= :cutoff
            {filters}
            GROUP BY d.full_date
            ORDER BY d.full_date ASC;
        """
        
        self.model = None
        self.df = None
        self.scope = {}
        engine = get_engine(self.db_uri)
        params, clauses, bindings = {}, [], []
        selections = {'categories': categories, 'regions': regions, 'states': states, 'sellers': sellers}
        for name, column in [('categories', 'p.category_name'), ('regions', 'c.region'),
                             ('states', 'c.state'), ('sellers', 's.seller_id')]:
            values = sorted(set(selections[name]))
            if values:
                params[name] = values
                clauses.append(f'AND {column} IN :{name}')
                bindings.append(bindparam(name, expanding=True))
        try:
            with engine.connect() as conn:
                bounds = conn.execute(text('SELECT MIN(d.full_date), MAX(d.full_date) FROM fact_sales f JOIN dim_date d ON d.date_key=f.date_key')).one()
                if bounds[0] is None:
                    raise ValueError('Kho dữ liệu chưa có giao dịch.')
                start = pd.Timestamp(start_date or bounds[0]).normalize()
                end = pd.Timestamp(cutoff or bounds[1]).normalize()
                if start > end or end > pd.Timestamp(bounds[1]):
                    raise ValueError('Ngày chốt phải nằm trong lịch sử dữ liệu và không trước ngày bắt đầu.')
                params.update(start_date=start.date(), cutoff=end.date())
                statement = text(query.format(filters=' '.join(clauses))).bindparams(*bindings)
                raw_df = pd.read_sql(statement, conn, params=params)
        finally:
            engine.dispose()
        self.df = self._prepare_continuous_series(raw_df, start, end)
        self.scope = {'start_date': start.date().isoformat(), 'cutoff': end.date().isoformat(),
                      **{name: sorted(set(values)) for name, values in selections.items()}}
        return self.df

    def _prepare_continuous_series(self, df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
        """Fills missing calendar dates with 0 for uninterrupted sequence."""
        data = df.copy()
        if data.empty:
            raise ValueError('Không có giao dịch trong phạm vi lịch sử đã chọn.')
        data['full_date'] = pd.to_datetime(data['full_date'])
        if data['full_date'].isna().any():
            raise ValueError('Ngày giao dịch không hợp lệ.')
        data['full_date'] = data['full_date'].dt.normalize()
        for column in data.columns.difference(['full_date']):
            data[column] = pd.to_numeric(data[column], errors='raise').astype(float)
            if not np.isfinite(data[column]).all() or (data[column] < 0).any():
                raise ValueError('Chuỗi lịch sử phải gồm các giá trị hữu hạn và không âm.')
        data = data.groupby('full_date', as_index=False).sum()
        
        full_range = pd.date_range(
            start=start if start is not None else data['full_date'].min(),
            end=end if end is not None else data['full_date'].max(),
            freq='D'
        )
        
        return (
            data.set_index('full_date')
            .reindex(full_range, fill_value=0)
            .rename_axis('full_date')
            .reset_index()
        )

    def _create_features(self, df: pd.DataFrame, target_col: str = 'quantity') -> pd.DataFrame:
        """Engineers calendar, lag, and rolling window features."""
        data = df.copy()
        data[target_col] = pd.to_numeric(data[target_col], errors='raise').astype(float)
        data['day_of_week'] = data['full_date'].dt.dayofweek
        data['day_of_month'] = data['full_date'].dt.day
        data['month'] = data['full_date'].dt.month
        data['is_weekend'] = data['day_of_week'].isin([5, 6]).astype(int)

        # Lags
        data['lag_1'] = data[target_col].shift(1)
        data['lag_7'] = data[target_col].shift(7)
        data['lag_14'] = data[target_col].shift(14)
        data['lag_28'] = data[target_col].shift(28)

        # Rolling statistics
        data['rolling_mean_7'] = data[target_col].shift(1).rolling(7).mean()
        data['rolling_mean_28'] = data[target_col].shift(1).rolling(28).mean()
        data['rolling_std_7'] = data[target_col].shift(1).rolling(7).std()

        return data

    def evaluate_quality_gate(self, wape: float, active_days: int, test_volume=None,
                              baseline_wape=None) -> dict:
        reasons, warnings = [], []
        if active_days < 14:
            reasons.append(f'Chỉ có {active_days} ngày bán trong 90 ngày cuối tập train; cần ít nhất 14.')
        if not np.isfinite(wape) or wape > 50.0:
            reasons.append('WAPE không xác định hoặc vượt ngưỡng 50%.')
        if test_volume is not None and test_volume < 30:
            reasons.append('Tập kiểm tra có ít hơn 30 sản phẩm.')
        if np.isfinite(wape) and wape > 30:
            warnings.append('WAPE trên 30%; kế hoạch cần được xem xét thận trọng.')
        if baseline_wape is not None and np.isfinite(baseline_wape) and wape > baseline_wape:
            warnings.append('XGBoost có sai số cao hơn baseline lặp lại chu kỳ 7 ngày.')
        return {'passed_quality_gate': not reasons,
                'status': 'REJECTED' if reasons else ('CAUTION' if warnings else 'APPROVED'),
                'reasons': reasons, 'warnings': warnings}

    @staticmethod
    def score(actual, predicted):
        actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
        if not len(actual) or len(actual) != len(predicted) or not np.isfinite(predicted).all():
            raise ValueError('Kết quả dự báo hoặc tập kiểm tra không hợp lệ.')
        error = actual - predicted
        volume = float(actual.sum())
        return {'MAE': float(np.mean(np.abs(error))), 'RMSE': float(np.sqrt(np.mean(error ** 2))),
                'WAPE_percent': float(np.abs(error).sum() / volume * 100) if volume else float('nan'),
                'bias_percent': float(-error.sum() / volume * 100) if volume else float('nan')}

    @staticmethod
    def series_fingerprint(data):
        rows = data[['full_date', 'quantity']].copy()
        rows['full_date'] = pd.to_datetime(rows['full_date']).dt.strftime('%Y-%m-%d')
        rows['quantity'] = rows['quantity'].astype(float)
        return hashlib.sha256(rows.to_csv(index=False, float_format='%.10f').encode()).hexdigest()

    def _fit(self, history, target_col):
        features = self._create_features(history, target_col).dropna(subset=self.FEATURE_COLUMNS + [target_col])
        if len(features) < 28:
            raise ValueError('Cần ít nhất 56 ngày lịch sử trước tập kiểm tra.')
        model = xgb.XGBRegressor(n_estimators=100, learning_rate=0.05, max_depth=4,
                                random_state=42, n_jobs=2, objective=self.OBJECTIVES[self.loss])
        model.fit(features[self.FEATURE_COLUMNS], features[target_col])
        return model

    def recursive_predict(self, model, history, horizon, target_col='quantity'):
        if not isinstance(horizon, int) or isinstance(horizon, bool) or not 1 <= horizon <= 90:
            raise ValueError('Kỳ dự báo phải từ 1 đến 90 ngày.')
        if len(history) < 28:
            raise ValueError('Không đủ lịch sử để tạo đặc trưng lag.')
        rolling = history[['full_date', target_col]].copy().reset_index(drop=True)
        output = []
        for _ in range(horizon):
            day = rolling['full_date'].iloc[-1] + pd.Timedelta(days=1)
            rolling = pd.concat([rolling, pd.DataFrame({'full_date': [day], target_col: [np.nan]})], ignore_index=True)
            features = self._create_features(rolling, target_col).tail(1)[self.FEATURE_COLUMNS]
            prediction = float(model.predict(features)[0])
            if not np.isfinite(prediction):
                raise ValueError('Mô hình trả về dự báo không hữu hạn.')
            prediction = max(0.0, prediction)
            rolling.loc[len(rolling) - 1, target_col] = prediction
            output.append({'full_date': day, 'predicted': prediction})
        return pd.DataFrame(output)

    def rolling_backtest(self, history, horizon=30, max_windows=3):
        """Evaluate disjoint windows ending before the final holdout."""
        if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 90:
            raise ValueError('Kỳ kiểm tra phải từ 1 đến 90 ngày.')
        if isinstance(max_windows, bool) or not isinstance(max_windows, int) or not 1 <= max_windows <= 12:
            raise ValueError('Số cửa sổ kiểm tra phải từ 1 đến 12.')
        data = self._prepare_continuous_series(history)
        count = min(max_windows, max(0, (len(data) - 56) // horizon))
        rows = []
        actual_all, predicted_all, baseline_all = [], [], []
        for offset in range(count - 1, -1, -1):
            stop = len(data) - offset * horizon
            train = data.iloc[:stop - horizon].copy()
            test = data.iloc[stop - horizon:stop].copy()
            model = self._fit(train, 'quantity')
            predicted = self.recursive_predict(model, train, horizon).predicted.to_numpy()
            baseline = np.resize(train.quantity.tail(7).to_numpy(), horizon)
            score = self.score(test.quantity, predicted)
            reference = self.score(test.quantity, baseline)
            active_days = int((train.quantity.tail(90) > 0).sum())
            gate = self.evaluate_quality_gate(score['WAPE_percent'], active_days,
                                               float(test.quantity.sum()), reference['WAPE_percent'])
            rows.append({'train_end': train.full_date.iloc[-1].date().isoformat(),
                         'test_start': test.full_date.iloc[0].date().isoformat(),
                         'test_end': test.full_date.iloc[-1].date().isoformat(),
                         'test_days': horizon, 'test_volume': float(test.quantity.sum()),
                         'wape_percent': score['WAPE_percent'], 'baseline_wape_percent': reference['WAPE_percent'],
                         'mae': score['MAE'], 'bias_percent': score['bias_percent'], 'quality': gate['status']})
            actual_all.extend(test.quantity.to_numpy())
            predicted_all.extend(predicted)
            baseline_all.extend(baseline)
        return {'windows': rows, 'window_count': count, 'requested_windows': max_windows,
                'metrics': self.score(actual_all, predicted_all) if count else None,
                'baseline_metrics': self.score(actual_all, baseline_all) if count else None,
                'rejected_windows': sum(row['quality'] == 'REJECTED' for row in rows),
                'wins_over_baseline': sum(row['wape_percent'] < row['baseline_wape_percent'] for row in rows)}

    def train_and_evaluate(self, target_col: str = 'quantity', test_days: int = 30,
                           validation_windows: int = 3) -> dict:
        self.model = None
        if self.df is None:
            raise ValueError('Chưa nạp dữ liệu. Gọi load_data() trước.')
        if isinstance(test_days, bool) or not isinstance(test_days, int) or not 1 <= test_days <= 90:
            raise ValueError('Số ngày kiểm tra phải từ 1 đến 90.')
        if target_col != 'quantity':
            raise ValueError('Kế hoạch bổ sung hàng sử dụng dự báo quantity.')
        history = self._prepare_continuous_series(self.df)
        if len(history) < 56 + test_days:
            raise ValueError(f'Cần ít nhất {56 + test_days} ngày lịch sử cho kỳ {test_days} ngày.')
        train_df, test_df = history.iloc[:-test_days].copy(), history.iloc[-test_days:].copy()
        validation = self.rolling_backtest(train_df, test_days, validation_windows)
        evaluation_model = self._fit(train_df, target_col)
        evaluation = self.recursive_predict(evaluation_model, train_df, test_days, target_col)
        evaluation['actual'] = test_df[target_col].to_numpy()
        evaluation['baseline'] = np.resize(train_df[target_col].tail(7).to_numpy(), test_days)
        metrics = self.score(evaluation.actual, evaluation.predicted)
        baseline_metrics = self.score(evaluation.actual, evaluation.baseline)
        active_days = int((train_df[target_col].tail(90) > 0).sum())
        metrics.update(active_sales_days=active_days, test_days=test_days,
                       test_volume=float(evaluation.actual.sum()))
        gate = self.evaluate_quality_gate(metrics['WAPE_percent'], active_days,
                                          metrics['test_volume'], baseline_metrics['WAPE_percent'])
        stability_warnings = []
        if validation['window_count'] < validation_windows:
            stability_warnings.append(f"Chỉ đủ lịch sử cho {validation['window_count']}/{validation_windows} cửa sổ đánh giá trước kỳ cuối.")
        if validation['rejected_windows']:
            stability_warnings.append(f"{validation['rejected_windows']}/{validation['window_count']} cửa sổ trước kỳ cuối không đạt ngưỡng chất lượng.")
        if validation['metrics'] and validation['baseline_metrics']:
            past_wape = validation['metrics']['WAPE_percent']
            past_baseline = validation['baseline_metrics']['WAPE_percent']
            if np.isfinite(past_wape) and np.isfinite(past_baseline) and past_wape > past_baseline:
                stability_warnings.append('WAPE gộp trên các cửa sổ trước kỳ cuối cao hơn baseline.')
        gate['warnings'].extend(stability_warnings)
        if stability_warnings and gate['status'] == 'APPROVED':
            gate['status'] = 'CAUTION'
        # Refit only after the holdout predictions and metrics have been fixed.
        self.model = self._fit(history, target_col)
        self.df = history
        return {'model': self.model, 'evaluation_model': evaluation_model, 'metrics': metrics,
                'validation': validation, 'loss': self.loss,
                'baseline_metrics': baseline_metrics, 'quality_gate': gate, 'evaluation': evaluation,
                'test_start': test_df.full_date.iloc[0].date().isoformat(),
                'trained_through': history.full_date.iloc[-1].date().isoformat(),
                'series_sha256': self.series_fingerprint(history), 'scope': self.scope}

    def forecast(self, horizon=30):
        if self.model is None or self.df is None:
            raise ValueError('Chưa có mô hình đã huấn luyện cho phạm vi hiện tại.')
        return self.recursive_predict(self.model, self.df, horizon)
