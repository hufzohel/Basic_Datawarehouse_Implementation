# src/dss/train.py

import os
from src.dss.forecast import XGBoostForecaster

def train_pipeline(db_uri: str = "postgresql://user:password@localhost:5432/olist_dw", 
                   model_save_path: str = "src/dss/models/xgboost_sales.json"):
    """
    Executes model training, Quality Gate check, and model serialization.
    """
    print("🚀 Initializing XGBoost Forecaster...")
    forecaster = XGBoostForecaster(db_uri=db_uri)
    
    print("📥 Loading data from Data Warehouse...")
    forecaster.load_data()
    
    print("⚙️ Training model on historical split...")
    results = forecaster.train_and_evaluate(target_col='quantity', test_days=30)
    
    metrics = results['metrics']
    gate = results['quality_gate']
    
    print("\n📊 Training Evaluation Results:")
    print(f"   • MAE:  {metrics['MAE']}")
    print(f"   • RMSE: {metrics['RMSE']}")
    print(f"   • WAPE: {metrics['WAPE_percent']}%")
    print(f"   • Active Sales Days: {metrics['active_sales_days']}")
    print(f"🛡️ Quality Gate Status: {gate['status']}")
    
    for reason in gate['reasons']:
        print(f"   - {reason}")
        
    if gate['passed_quality_gate']:
        os.makedirs(os.path.dirname(model_save_path), exist_ok=True)
        results['model'].save_model(model_save_path)
        print(f"\n✅ Model approved! Saved serialized model to: {model_save_path}")
    else:
        print("\n❌ Model failed Quality Gate. Deployment blocked.")

if __name__ == "__main__":
    train_pipeline()
