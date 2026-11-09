# src/dss/forecasting.py

import pandas as pd
import numpy as np
from datetime import timedelta
import xgboost as xgb
from sqlalchemy import create_engine

class XGBoostForecaster:
    """
    XGBoost Time-Series Forecasting Engine for DSS with Quality Gate Checks.
    """
    def __init__(self, db_uri: str = "postgresql://user:password@localhost:5432/olist_dw"):
        self.db_uri = db_uri
        self.df = None

    def load_data(self) -> pd.DataFrame:
        """
        Executes query against Data Contract tables (fact_sales & dim_date).
        Replace connection string when Member 1 finishes DB setup.
        """
        query = """
            SELECT 
                d.full_date,
                SUM(f.quantity) AS quantity,
                SUM(f.total_revenue_cents) AS total_revenue_cents
            FROM fact_sales f
            JOIN dim_date d ON f.date_key = d.date_key
            GROUP BY d.full_date
            ORDER BY d.full_date ASC;
        """
        
        engine = create_engine(self.db_uri)
        raw_df = pd.read_sql(query, engine)
        
        self.df = self._prepare_continuous_series(raw_df)
        return self.df

    def _prepare_continuous_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fills missing calendar dates with 0 for uninterrupted sequence."""
        data = df.copy()
        data['full_date'] = pd.to_datetime(data['full_date'])
        
        full_range = pd.date_range(
            start=data['full_date'].min(),
            end=data['full_date'].max(),
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
        data['day_of_week'] = data['full_date'].dt.dayofweek
        data['day_of_month'] = data['full_date'].dt.day
        data['month'] = data['full_date'].dt.month
        data['is_weekend'] = data['day_of_week'].isin().astype(int)

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

    def evaluate_quality_gate(self, wape: float, active_days: int) -> dict:
        """
        Evaluates safety thresholds before allowing downstream replenishment recommendations:
        1. WAPE <= 50% (Error threshold)
        2. Active Sales Days >= 14 (Data density threshold)
        """
        reasons = []
        is_reliable = True

        if active_days < 14:
            is_reliable = False
            reasons.append(f"Insufficient active sales history ({active_days} days < 14 days minimum).")

        if np.isnan(wape) or wape > 50.0:
            is_reliable = False
            reasons.append(f"Forecast error too high (WAPE: {wape:.2f}% > 50.0% threshold).")

        return {
            'passed_quality_gate': is_reliable,
            'status': "APPROVED" if is_reliable else "REJECTED",
            'reasons': reasons if reasons else ["Model metrics within safe parameters."]
        }

    def train_and_evaluate(self, target_col: str = 'quantity', test_days: int = 30) -> dict:
        """
        Splits data chronologically, fits XGBoost regressor, computes metrics,
        and runs Quality Gate verification.
        """
        if self.df is None:
            raise ValueError("Data not loaded. Call load_data() first.")

        # Count active sales days in historical dataset
        active_days = int((self.df[target_col] > 0).sum())

        df_feat = self._create_features(self.df, target_col=target_col).dropna()

        feature_cols = [
            'day_of_week', 'day_of_month', 'month', 'is_weekend',
            'lag_1', 'lag_7', 'lag_14', 'lag_28',
            'rolling_mean_7', 'rolling_mean_28', 'rolling_std_7'
        ]

        # Chronological train/test split
        cutoff_date = df_feat['full_date'].max() - timedelta(days=test_days)
        train_df = df_feat[df_feat['full_date'] <= cutoff_date]
        test_df = df_feat[df_feat['full_date'] > cutoff_date]

        X_train, y_train = train_df[feature_cols], train_df[target_col]
        X_test, y_test = test_df[feature_cols], test_df[target_col]

        # Train XGBoost
        model = xgb.XGBRegressor(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=4,
            random_state=42
        )
        model.fit(X_train, y_train)

        # Predict & Evaluate
        preds = np.maximum(0, model.predict(X_test))
        y_true = y_test.values

        mae = float(np.mean(np.abs(y_true - preds)))
        rmse = float(np.sqrt(np.mean((y_true - preds) ** 2)))
        total_actual = float(np.sum(y_true))
        wape = float((np.sum(np.abs(y_true - preds)) / total_actual) * 100.0) if total_actual > 0 else np.nan

        # Run Quality Gate Verification
        quality_gate = self.evaluate_quality_gate(wape=wape, active_days=active_days)

        return {
            'model': model,
            'metrics': {
                'MAE': round(mae, 2),
                'RMSE': round(rmse, 2),
                'WAPE_percent': round(wape, 2),
                'active_sales_days': active_days
            },
            'quality_gate': quality_gate
        }
