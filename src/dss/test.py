# src/dss/test.py

import numpy as np
import pandas as pd
import xgboost as xgb
from src.dss.forecasting import XGBoostForecaster

def test_pipeline(model_path: str = "src/dss/models/xgboost_sales.json", 
                  db_uri: str = "postgresql://user:password@localhost:5432/olist_dw"):
    """
    Loads saved XGBoost model binary and evaluates performance on test period.
    """
    print(f"🔍 Loading trained model from: {model_path}")
    model = xgb.XGBRegressor()
    model.load_model(model_path)
    
    print("📥 Fetching latest data from Data Warehouse...")
    forecaster = XGBoostForecaster(db_uri=db_uri)
    df = forecaster.load_data()
    
    # Feature engineering for evaluation
    df_feat = forecaster._create_features(df, target_col='quantity').dropna()
    
    feature_cols = [
        'day_of_week', 'day_of_month', 'month', 'is_weekend',
        'lag_1', 'lag_7', 'lag_14', 'lag_28',
        'rolling_mean_7', 'rolling_mean_28', 'rolling_std_7'
    ]
    
    # Holdout test set (last 30 days)
    test_df = df_feat.tail(30)
    X_test = test_df[feature_cols]
    y_true = test_df['quantity'].values
    
    # Predict
    preds = np.maximum(0, model.predict(X_test))
    
    # Error metrics
    mae = float(np.mean(np.abs(y_true - preds)))
    rmse = float(np.sqrt(np.mean((y_true - preds) ** 2)))
    total_actual = float(np.sum(y_true))
    wape = float((np.sum(np.abs(y_true - preds)) / total_actual) * 100.0) if total_actual > 0 else np.nan
    
    print("\n📊 Out-of-Sample Test Results:")
    print(f"   • Test MAE:  {round(mae, 2)}")
    print(f"   • Test RMSE: {round(rmse, 2)}")
    print(f"   • Test WAPE: {round(wape, 2)}%")
    
    active_days = int((df['quantity'] > 0).sum())
    gate = forecaster.evaluate_quality_gate(wape=wape, active_days=active_days)
    print(f"🛡️ Quality Gate Verification: {gate['status']}")
    
    df_results = pd.DataFrame({
        'full_date': test_df['full_date'],
        'actual': y_true,
        'predicted': np.round(preds, 2)
    })
    
    print("\nSample Forecast Comparison:")
    print(df_results.head(7))
    return df_results

if __name__ == "__main__":
    test_pipeline()     