import argparse
import json
from pathlib import Path

import pandas as pd
import xgboost as xgb

from src.dss.forecast import XGBoostForecaster
from src.dss.train import DEFAULT_MODEL, json_safe


def test_pipeline(model_path=DEFAULT_MODEL, db_uri=None):
    path = Path(model_path)
    holdout_path = path.with_suffix('.holdout.json')
    if not path.is_file() or not holdout_path.is_file():
        raise FileNotFoundError('Chưa có cặp model. Chạy python -m src.dss.train trước.')
    production = xgb.XGBRegressor()
    production.load_model(path)
    model = xgb.XGBRegressor()
    model.load_model(holdout_path)
    try:
        main_meta = json.loads(production.get_booster().attr('dss_metadata'))
        metadata = json.loads(model.get_booster().attr('dss_metadata'))
    except (TypeError, ValueError):
        raise ValueError('Model thiếu thông tin phạm vi và kỳ kiểm tra; cần train lại.') from None
    if metadata.get('purpose') != 'holdout' or metadata.get('artifact_id') != main_meta.get('artifact_id'):
        raise ValueError('Hai model không thuộc cùng một lần huấn luyện.')
    forecaster = XGBoostForecaster(db_uri=db_uri, loss=metadata.get('loss', 'squared'))
    df = forecaster.load_data(**metadata['scope'])
    if forecaster.series_fingerprint(df) != metadata['series_sha256']:
        raise ValueError('Dữ liệu đã thay đổi so với model đã lưu; cần train lại.')
    start = pd.Timestamp(metadata['test_start'])
    if pd.Timestamp(metadata['trained_through']) >= start:
        raise ValueError('Model kiểm tra đã được huấn luyện chồng lên kỳ đánh giá.')
    history = df[df.full_date < start]
    test = df[df.full_date >= start]
    if len(test) != metadata['horizon']:
        raise ValueError('Tập kiểm tra không đủ kỳ đã lưu.')
    results = forecaster.recursive_predict(model, history, len(test))
    results['actual'] = test.quantity.to_numpy()
    metrics = forecaster.score(results.actual, results.predicted)
    print(json.dumps(json_safe(metrics), indent=2, allow_nan=False))
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Reproduce the saved chronological holdout evaluation')
    parser.add_argument('--model', default=str(DEFAULT_MODEL))
    args = parser.parse_args()
    test_pipeline(args.model)
