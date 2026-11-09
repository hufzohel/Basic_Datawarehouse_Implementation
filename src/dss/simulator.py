# src/dss/simulator.py

from typing import Dict, Any
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
        self.price_elasticity = price_elasticity

    def optimize_replenishment(
        self, 
        forecasted_demand: float, 
        unit_cost_cents: int, 
        unit_price_cents: int, 
        budget_cents: int,
        holding_cost_pct: float = 0.05
    ) -> Dict[str, Any]:
        """
        Calculates optimal replenishment order quantity under budget constraints.
        
        Algorithm: Greedy Budget-Capped Replenishment (O(1))
        
        Returns:
        --------
        Dict[str, Any] : Clean dictionary of financial metrics and unit allocations.
        """
        target_units = int(np.ceil(max(0.0, forecasted_demand)))
        
        # Calculate maximum units affordable within cash budget
        max_affordable_units = budget_cents // unit_cost_cents if unit_cost_cents > 0 else 0

        # Cap recommended order quantity at projected demand to prevent overstocking
        recommended_units = min(target_units, max_affordable_units)

        # Financial Calculations (in integer cents)
        total_purchase_cost_cents = recommended_units * unit_cost_cents
        projected_revenue_cents = recommended_units * unit_price_cents
        estimated_holding_cost_cents = int(total_purchase_cost_cents * holding_cost_pct)
        projected_gross_profit_cents = projected_revenue_cents - total_purchase_cost_cents - estimated_holding_cost_cents

        is_budget_constrained = max_affordable_units < target_units
        unmet_demand_units = max(0, target_units - recommended_units)
        
        roi_percent = (
            round((projected_gross_profit_cents / total_purchase_cost_cents) * 100.0, 2)
            if total_purchase_cost_cents > 0 else 0.0
        )

        return {
            "forecasted_demand_units": target_units,
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
        # Calculate adjusted price and unit cost
        new_price_cents = int(round(base_price_cents * (1.0 + (price_change_pct / 100.0))))
        new_cost_cents = int(round(base_cost_cents * (1.0 + (cost_change_pct / 100.0))))

        # Demand response to price shift using elasticity
        quantity_change_pct = price_change_pct * self.price_elasticity
        simulated_demand_units = max(0, int(round(base_forecast_units * (1.0 + (quantity_change_pct / 100.0)))))

        # Baseline Financials
        base_revenue_cents = int(round(base_forecast_units * base_price_cents))
        base_profit_cents = int(round(base_forecast_units * (base_price_cents - base_cost_cents)))

        # Simulated Financials
        simulated_revenue_cents = int(simulated_demand_units * new_price_cents)
        simulated_profit_cents = int(simulated_demand_units * (new_price_cents - new_cost_cents))

        profit_delta_cents = simulated_profit_cents - base_profit_cents
        profit_delta_pct = (
            round((profit_delta_cents / base_profit_cents) * 100.0, 2)
            if base_profit_cents > 0 else 0.0
        )

        return {
            "baseline": {
                "demand_units": int(base_forecast_units),
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
                "demand_delta_units": simulated_demand_units - int(base_forecast_units),
                "profit_delta_cents": profit_delta_cents,
                "profit_delta_percent": profit_delta_pct
            }
        }
