"""Weekly demand forecasting and reorder policy for purchased parts.

The package reads the warehouse's gold tables and the landed ERP extracts through dfm.store, builds the
feature frame (dfm.features), trains and selects the forecast model (dfm.training), sets the weekly
reorder points (dfm.policy) and governs promotion through the model registry (dfm.registry).
"""

__version__ = "0.1.0"
