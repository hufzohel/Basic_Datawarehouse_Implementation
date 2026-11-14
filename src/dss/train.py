import argparse
import json
import math
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from src.db import ROOT
from src.dss.forecast import XGBoostForecaster

DEFAULT_MODEL = ROOT / 'src' / 'dss' / 'models' / 'xgboost_sales.json'


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def train_pipeline(db_uri=None, model_save_path=DEFAULT_MODEL, cutoff=None, test_days=30,
                   start_date=None, categories=(), regions=(), states=(), sellers=(), loss='squared', validation_windows=3):
    forecaster = XGBoostForecaster(db_uri=db_uri, loss=loss)
    forecaster.load_data(start_date, cutoff, categories, regions, states, sellers)
    results = forecaster.train_and_evaluate(test_days=test_days, validation_windows=validation_windows)
    metadata = {key: results[key] for key in ['metrics', 'baseline_metrics', 'quality_gate',
                'test_start', 'trained_through', 'series_sha256', 'scope', 'loss', 'validation']}
    metadata = json_safe(dict(metadata, artifact_id=str(uuid4()), horizon=test_days, version=2,
                              validation_windows=validation_windows))
    path = Path(model_save_path)
    if path.suffix != '.json':
        raise ValueError('Model phải được lưu trong file .json.')
    path.parent.mkdir(parents=True, exist_ok=True)
    for model, target, purpose in [(results['evaluation_model'], path.with_suffix('.holdout.json'), 'holdout'),
                                   (results['model'], path, 'forecast')]:
        saved_metadata = dict(metadata, purpose=purpose)
        if purpose == 'holdout':
            saved_metadata['trained_through'] = (date.fromisoformat(metadata['test_start']) - timedelta(days=1)).isoformat()
        model.get_booster().set_attr(dss_metadata=json.dumps(saved_metadata, allow_nan=False))
        temporary = target.with_suffix('.tmp.json')
        try:
            model.save_model(temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    print(json.dumps(metadata, ensure_ascii=True, indent=2, allow_nan=False))
    return results


def main():
    parser = argparse.ArgumentParser(description='Train and evaluate the Olist XGBoost model')
    parser.add_argument('--cutoff')
    parser.add_argument('--start-date')
    parser.add_argument('--horizon', type=int, default=30, choices=[30, 60, 90])
    parser.add_argument('--category', action='append', default=[])
    parser.add_argument('--region', action='append', default=[])
    parser.add_argument('--state', action='append', default=[])
    parser.add_argument('--seller', action='append', default=[])
    parser.add_argument('--loss', choices=['squared', 'absolute'], default='squared')
    parser.add_argument('--validation-windows', type=int, choices=range(1, 13), default=3)
    parser.add_argument('--model', default=str(DEFAULT_MODEL))
    args = parser.parse_args()
    train_pipeline(model_save_path=args.model, cutoff=args.cutoff, test_days=args.horizon,
                   start_date=args.start_date, categories=args.category, regions=args.region,
                   states=args.state, sellers=args.seller, loss=args.loss,
                   validation_windows=args.validation_windows)


if __name__ == '__main__':
    main()
