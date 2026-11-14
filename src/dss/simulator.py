# src/dss/simulator.py

from typing import Dict, Any
from decimal import Decimal, ROUND_HALF_UP
import numpy as np

class InventorySimulator:
    """
    Decision Support Optimization & Simulation Engine for DSS.
    Pure mathematical engine that accepts parameters and returns
    structured Python dictionaries (JSON-serializable).
    """

    def __init__(self, price_elasticity: float = -1.5):
        """
        Initializes simulator with a Price Elasticity coefficient.
        Default -1.5 means a +10% price increase reduces demand by 15%.
        """
        if not np.isfinite(price_elasticity) or not -5 <= price_elasticity <= 0:
            raise ValueError('Độ co giãn phải nằm trong khoảng -5 đến 0.')
        self.price_elasticity = price_elasticity

    @staticmethod
    def _validate_number(name, value, integer=False, positive=False):
        if isinstance(value, bool) or not np.isfinite(value) or value < 0 or (positive and value == 0):
            raise ValueError(f'{name} phải là số hữu hạn, không âm' + (' và lớn hơn 0.' if positive else '.'))
        if integer and int(value) != value:
            raise ValueError(f'{name} phải là số nguyên.')

    @staticmethod
    def _round_cents(value):
        return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    def optimize_replenishment(
        self, 
        forecasted_demand: float, 
        unit_cost_cents: int, 
        unit_price_cents: int, 
        budget_cents: int,
        holding_cost_pct: float = 0.05,
        current_stock: int = 0,
        incoming_stock: int = 0,
        safety_stock: int = 0,
        quality_gate: dict = None,
    ) -> Dict[str, Any]:
        """
        Calculates budget-capped replenishment from demand and available stock.
        
        Algorithm: Greedy Budget-Capped Replenishment (O(1))
        
        Returns:
        --------
        Dict[str, Any] : Clean dictionary of financial metrics and unit allocations.
        """
        self._validate_number('Nhu cầu dự báo', forecasted_demand)
        for name, value in [('Giá vốn', unit_cost_cents), ('Giá bán', unit_price_cents),
                            ('Ngân sách', budget_cents), ('Tồn kho', current_stock),
                            ('Hàng đang về', incoming_stock), ('Dự phòng', safety_stock)]:
            self._validate_number(name, value, integer=True, positive=name == 'Giá vốn')
        self._validate_number('Tỷ lệ lưu kho', holding_cost_pct)
        if holding_cost_pct > 1:
            raise ValueError('Tỷ lệ lưu kho phải từ 0 đến 1.')
        unit_cost_cents, unit_price_cents, budget_cents = int(unit_cost_cents), int(unit_price_cents), int(budget_cents)
        current_stock, incoming_stock, safety_stock = int(current_stock), int(incoming_stock), int(safety_stock)
        demand_units = int(np.ceil(forecasted_demand))
        target_units = max(0, demand_units + int(safety_stock) - int(current_stock) - int(incoming_stock))
        reasons = []
        if quality_gate is not None and not quality_gate.get('passed_quality_gate', False):
            reasons.append('Dự báo chưa đạt điều kiện chất lượng.')
        if unit_price_cents <= unit_cost_cents * (1 + holding_cost_pct):
            reasons.append('Giá bán không bù được giá vốn và tỷ lệ lưu kho giả định.')
        
        # Calculate maximum units affordable within cash budget
        max_affordable_units = budget_cents // unit_cost_cents if unit_cost_cents > 0 else 0

        # Cap recommended order quantity at projected demand to prevent overstocking
        recommended_units = min(target_units, max_affordable_units)
        if reasons:
            recommended_units = 0

        # Financial Calculations (in integer cents)
        total_purchase_cost_cents = recommended_units * unit_cost_cents
        expected_sold_units = min(recommended_units, max(0, demand_units - current_stock - incoming_stock))
        projected_revenue_cents = expected_sold_units * unit_price_cents
        estimated_holding_cost_cents = self._round_cents(Decimal(total_purchase_cost_cents) * Decimal(str(holding_cost_pct)))
        projected_gross_profit_cents = projected_revenue_cents - total_purchase_cost_cents - estimated_holding_cost_cents

        is_budget_constrained = max_affordable_units < target_units
        unmet_demand_units = max(0, target_units - recommended_units)
        
        roi_percent = (
            round((projected_gross_profit_cents / total_purchase_cost_cents) * 100.0, 2)
            if total_purchase_cost_cents > 0 else 0.0
        )

        return {
            "forecasted_demand_units": demand_units,
            "required_order_units": target_units,
            "current_stock": int(current_stock),
            "incoming_stock": int(incoming_stock),
            "safety_stock": int(safety_stock),
            "blocked": bool(reasons),
            "reasons": reasons,
            "recommended_order_units": recommended_units,
            "budget_cents": budget_cents,
            "total_purchase_cost_cents": total_purchase_cost_cents,
            "projected_revenue_cents": projected_revenue_cents,
            "estimated_holding_cost_cents": estimated_holding_cost_cents,
            "projected_gross_profit_cents": projected_gross_profit_cents,
            "is_budget_constrained": is_budget_constrained,
            "unmet_demand_units": unmet_demand_units,
            "roi_percent": roi_percent
        }

    def run_what_if_scenario(
        self, 
        base_forecast_units: float, 
        base_price_cents: int, 
        base_cost_cents: int,
        price_change_pct: float = 0.0, 
        cost_change_pct: float = 0.0
    ) -> Dict[str, Any]:
        """
        Simulates 'What-If' sensitivity scenarios when adjusting unit prices or supplier costs.
        
        Algorithm: Price Elasticity of Demand (% Delta Q = Elasticity * % Delta P)
        
        Returns:
        --------
        Dict[str, Any] : Nested dictionary with baseline, simulated, and delta metrics.
        """
        self._validate_number('Nhu cầu gốc', base_forecast_units)
        self._validate_number('Giá bán', base_price_cents, integer=True, positive=True)
        self._validate_number('Giá vốn', base_cost_cents, integer=True, positive=True)
        for value in [price_change_pct, cost_change_pct]:
            if not np.isfinite(value) or not -99 <= value <= 100:
                raise ValueError('Mức thay đổi giá hoặc vốn phải từ -99% đến 100%.')
        base_price_cents, base_cost_cents = int(base_price_cents), int(base_cost_cents)
        new_price_cents = self._round_cents(Decimal(base_price_cents) * (1 + Decimal(str(price_change_pct)) / 100))
        new_cost_cents = self._round_cents(Decimal(base_cost_cents) * (1 + Decimal(str(cost_change_pct)) / 100))

        # Demand response to price shift using elasticity
        quantity_change_pct = price_change_pct * self.price_elasticity
        simulated_demand_units = max(0, int(round(base_forecast_units * (1.0 + (quantity_change_pct / 100.0)))))

        # Baseline Financials
        baseline_units = int(round(base_forecast_units))
        base_revenue_cents = baseline_units * base_price_cents
        base_profit_cents = baseline_units * (base_price_cents - base_cost_cents)

        # Simulated Financials
        simulated_revenue_cents = int(simulated_demand_units * new_price_cents)
        simulated_profit_cents = int(simulated_demand_units * (new_price_cents - new_cost_cents))

        profit_delta_cents = simulated_profit_cents - base_profit_cents
        profit_delta_pct = (
            round((profit_delta_cents / abs(base_profit_cents)) * 100.0, 2)
            if base_profit_cents != 0 else None
        )

        return {
            "baseline": {
                "demand_units": baseline_units,
                "price_cents": base_price_cents,
                "cost_cents": base_cost_cents,
                "revenue_cents": base_revenue_cents,
                "profit_cents": base_profit_cents
            },
            "simulated": {
                "demand_units": simulated_demand_units,
                "price_cents": new_price_cents,
                "cost_cents": new_cost_cents,
                "revenue_cents": simulated_revenue_cents,
                "profit_cents": simulated_profit_cents
            },
            "deltas": {
                "demand_delta_units": simulated_demand_units - baseline_units,
                "profit_delta_cents": profit_delta_cents,
                "profit_delta_percent": profit_delta_pct
            }
        }
