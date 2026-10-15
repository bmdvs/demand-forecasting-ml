# Machine Learning Model: Demand Forecasting 

The project began with a full [data quality audit](https://brimsystems.github.io/demand-forecasting-ml/docs/reports/data_quality_audit.html) of the shop's ERP system, which found sixteen recurring error types across eight tables and documented the remediation process. 

A **demand forecasting ML model** was then built on the cleaned records. This model makes weekly demand forecasts and reordering decisions for each of the shop's 1,300 stocked items. The ML model is detailed in the [model overview report](https://brimsystems.github.io/demand-forecasting-ml/docs/reports/model_overview.html) and summarized below.  

- **Results.** Over a six month period (Jan. to Jun. 2026), the model has been in production and used to set every reordering decision the shop made. The table below compares the model's performance to 2025 when the shop's reordering decisions were done manually. The model achieved significant improvements across production and purchasing KPIs, while also reducing the shop's inventory balance and freeing up cash tied in working capital.

<div align="center">

<b>ML-driven vs. Manual Reordering Performance on Cleaned ERP Records (1H 2026 against 2025)</b>

| | Stockout days | Jobs held for material | Rush-freight spend | Avg. inventory |
|---|---|---|---|---|
| **Manual Reordering** | −7% | −11% | −19% | −11% (139 days of usage, from 160) |
| **ML-driven Reordering** | −36% | −43% | −46% | −5% (148 days of usage, from 160) |

</div>

- **Purpose & intended use.** Every Monday, the model forecasts each stocked item's expected usage over its supplier lead time and turns this into a recommended reordering decision. This decision includes a reorder point (date) and order quantity, and is embedded in the ERP's purchasing screen. A buffer is added to each forecast based on the size of the item's forecast error and its supplier's lead-time variability. [These forecasts are intended to be used as...] 
- **Model training.** The model was trained on three years of remediated ERP history: inventory transactions, production orders and bills of materials, service orders, purchase-order receipts, and the item and supplier masters. It takes the items that booked jobs will draw as known, then forecasts the demand for the rest of the items. This forecasted demand is driven by each item's own usage history, expressed as lagging and rolling features computed up to the forecast date. For replacement part forecasted demand, item lifecycle and installed-base signals were added. A single random forest is trained across all 1,300 items on these features together with each item’s demand pattern, class, lead time and annual volume, so the model pools what it learns across items with similar histories rather than fitting each series alone. 
- **Model Evaluation.** Candidates (ridge, random forest, XGBoost) were tuned [mention Optuna] on validation and selected by rule, then scored against five simple methods a buyer could run by hand, including the order book plus the best moving average by demand pattern (47.3% WAPE). The production model reaches 42.8% overall and 36.8% on line-critical parts. The largest source of forecast inaccuracy is the shop's intermittent demand items: nearly 1/3 of all items have demand that arrives in just a few weeks a year and in quantities that vary by 35% to 60%, and no method forecasts this at low error. Regardless, the production model achieved a 9.5% relative reduction in error as compared to the baseline (42.8% WAPE vs. 47.3%) [anything more to say about why we think this is a good model score?]. Full evaluation and technical details are found in the [technical report](https://brimsystems.github.io/demand-forecasting-ml/docs/reports/technical_report.html)  
- **Production Monitoring.** Retrained monthly and refreshed weekly, with a monitor that tracks forecast error and bias by demand pattern, feature drift, supplier lead-time drift and data quality against investigate-and-retrain thresholds. [Stack sentence after the Databricks port: Lakeflow pipeline, MLflow registry with a champion alias, promotion gates.] Additional detail is found in the [monitoring report](https://bmdvs.github.io/demand-forecasting-ml/docs/reports/monitoring_report.html)


The model's reorder suggestions are embedded in the shop's existing [ERP purchasing screen](https://bmdvs.github.io/demand-forecasting-ml/docs/index.html), as shown below:

[![ERP reorder queue with embedded demand forecasts](docs/screenshots/erp_queue.png)](https://bmdvs.github.io/demand-forecasting-ml/docs/index.html)

---

## Business Context

An industrial equipment manufacturer (~$30mm revenue) produces conveyors and material-handling modules, industrial mixers and agitators, and custom enclosures and frames. It stocks about 1,300 items purchased from 40 suppliers. 

Historically, the shop's inventory reordering was done manually and ran on data that was messy and couldn't be trusted. Much of the reordering process was labor-intensive and imprecise: stock levels and lead times were stale, stock on hand was unverified, safety stock was inflated, and rush orders were relied upon to compensate for shortfalls. The result was the shop carrying excess inventory, roughly 160 days of usage, yet still logging elevated stockout events, held jobs for missing material, and rush freight spend.

---

## Deliverables

| # | Deliverable | What it is | Links |
|---|---|---|---|
| 1 | ERP reorder queue | The demand forecasting model embedded in the ERP's purchasing screen: each item's on-hand, allocated, on-order and available stock, forecast usage over its lead time, safety stock, reorder point, and suggested order quantity. | [View](https://bmdvs.github.io/demand-forecasting-ml/docs/index.html) |
| 2 | Data quality audit | Details the data quality audit, including every type of error found across the ERP's eight tables, the error remediation completed, the before-and-after results, and the process changes that will keep the ERP system clean. | [View](https://bmdvs.github.io/demand-forecasting-ml/docs/reports/data_quality_audit.html) |
| 3 | ML model overview & performance report | A high-level summary of the demand forecasting model: what it does, the data it learns from, how it sets each reorder, and the results it achieves. | [View](https://bmdvs.github.io/demand-forecasting-ml/docs/reports/model_overview.html) |
| 4 | ML technical report | The model card, training data and time-based split, model selection and performance, SHAP feature importance, how forecasts turn into reorder decisions, known limitations, and deployment. | [View](https://bmdvs.github.io/demand-forecasting-ml/docs/reports/technical_report.html) |
| 5 | MLOps monitoring report | Monthly monitoring of the live model's outcomes against retraining thresholds: forecast error and bias overall and by demand pattern, drift, data quality, and business KPIs. | [View](https://bmdvs.github.io/demand-forecasting-ml/docs/reports/monitoring_report.html) |

---

## Code

### Data pipeline: [`data_pipeline/models/`](data_pipeline/models/)

| Layer | What it is, does and contains |
|---|---|
| Staging | One model per source table (ERP, WMS and the buyers' spreadsheet). Each inputs and cleans the raw data into a consistent shape and format. |
| Data quality | One model for each of the 16 error types identified in the audit. Flags the records affected across the staging tables. |
| Intermediate | Applies the cleanup to the staged data without altering the source. Builds the shared pieces the marts are assembled from, including the item crosswalk and cleaned item master and inventory ledger. |
| Marts | The analysis-ready tables the audit and model read: cleaned demand, weekly usage, item attributes, inventory position, supplier performance, and the audit's error register. |

### Data cleaning: [`data_pipeline/models/data_quality/`](data_pipeline/models/data_quality/) and [`data_source/generate/remediation.py`](data_source/generate/remediation.py)

| File | What it does |
|---|---|
| `data_quality/dq_01` to `dq_16` | Flags the records affected by each of the sixteen errors in the audit. |
| `marts/mart_dq_error_summary.sql` | Rolls the flagged records into the audit's error register: rows affected and rows in scope for each error and ERP table. |
| `remediation.py` | Records every change made during the cleanup: dead-item dispositions, duplicate and supplier crosswalks, UOM conversions, recomputed lead times and reorder points, ledger corrections, document closures and the free-text attributions. |
| `ml/src/reliability.py` | Classes every item's on-hand balance as reliable, uncertain or unreliable, before and after remediation. |
| `ml/src/financials.py` | Measures what the errors cost and what the cleanup achieved, from the records: rush spend and shortages traced to each error, inventory write-offs and phantom on-order, and the before-and-after measures in the audit's results. |

### Demand forecasting ML model: [`ml/src/`](ml/src/)

| File | What it does |
|---|---|
| `export_marts.py` | Exports the dbt marts the model reads to parquet. |
| `baselines.py` | Simple forecasting methods (naive, seasonal naive, moving averages, exponential smoothing, Croston) to serve as baselines. |
| `features.py`, `training.py` | Feature building and evaluation of the three model candidates. |
| `demand_model.py` | The production model: builds the weekly features, tunes and selects best model, retrains it monthly,  converts forecasts into reorder points, safety buffers, and order quantities for the ERP. |
| `explain_weekly.py` | SHAP feature importance, the learning curve, feature correlations and the train, validation and test summary for the technical report. |
| `monitor_weekly.py` | Monthly monitoring against Investigate and Retrain thresholds: forecast error and bias overall and by demand pattern, target, prediction and feature drift, data quality and business KPIs. |

---

## How it works

```mermaid
flowchart LR
  subgraph SRC["Source systems"]
    ERP["ERP<br/>items, suppliers, BOMs, production,<br/>service, purchasing, inventory"]
    WMS["WMS<br/>cycle counts"]
    SS["Buyer spreadsheet"]
  end
  ERP --> STG
  WMS --> STG
  SS --> STG
  STG["dbt staging"] --> DQ["16 data-quality models<br/>one per error type"]
  DQ --> REM["Remediation records<br/>merges, corrections, deactivations"]
  REM --> INT["dbt intermediate<br/>resolved items, corrected ledger"]
  STG --> INT
  INT --> MARTS[("Cleaned marts<br/>weekly usage, item attributes,<br/>inventory, suppliers, error register")]
  MARTS --> ML["Demand model<br/>weekly forecast &rarr; reorder policy"]
  DQ --> AUD["Data quality audit"]
  ML --> QUEUE["ERP reorder queue"]
  ML --> MON["MLOps monitoring"]
```

Raw extracts from the ERP, its warehouse system, and the buyers' spreadsheet, and are then combined by a tested dbt pipeline into conformed marts. Along the way, one data-quality model per error type flags the affected records and feeds the audit's error register, and the remediation is applied through auditable merges. The cleaned marts then feed the demand forecasting model, whose weekly reorder points and order quantities are loaded into the ERP's reorder queue.

---

## Data

The datasets were generated to represent typical records from a manufacturing ERP, its warehouse system and a buyer's spreadsheet, with error types and rates constructed to reflect patterns commonly documented in these systems, so the full workflow can be demonstrated on data that is safe to share publicly. The [generators are in `data_source/generate/`](data_source/generate/).

---

## Running it locally

```bash
# 1. Environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

# 2. Generate the source data and remediate it
python3 -m data_source.generate.run_generator
python3 -m data_source.generate.validate
python3 -m data_source.generate.remediation
python3 -m data_source.generate.export_truth

# 3. Warehouse: staging, data-quality models, intermediate models and marts
cd data_pipeline && dbt build --profiles-dir . && cd ..
python3 -m ml.src.export_marts

# 4. Baselines, model selection, the weekly forecast and reorder policy, and explainability
python3 -m ml.src.baselines
python3 -m ml.src.training
python3 -m ml.src.training_3way
python3 -m ml.src.demand_model
python3 -m ml.src.explain_weekly

# 5. Replay January to June 2026 on the model's reorder schedule
python3 -m data_source.generate.run_generator
python3 -m data_source.generate.validate
python3 -m data_source.generate.remediation
python3 -m data_source.generate.export_truth
cd data_pipeline && dbt build --profiles-dir . && cd ..
python3 -m ml.src.export_marts
python3 -m ml.src.reliability
python3 -m ml.src.financials

# 6. Monitoring
python3 -m ml.src.monitor_weekly

# 7. Client-facing deliverables
python3 ml/reports/generate_data_quality_audit.py
python3 -m ml.reports.generate_reorder_queue
python3 -m ml.reports.generate_model_overview
python3 -m ml.reports.generate_technical_report
python3 -m ml.reports.generate_monitoring_report
```

The report generators write standalone HTML to [`docs/`](docs/), which GitHub Pages serves.

---

## Stack

| Layer | Tools |
|---|---|
| Integration & transformation | dbt, DuckDB |
| Data quality & remediation | dbt data-quality models, Python, pandas |
| Data generation | Python, pandas, NumPy |
| Modeling | scikit-learn (random forest, ridge regression), XGBoost, Optuna, SHAP |
| Monitoring | SciPy (Jensen-Shannon distance), pandas |
| Reporting | matplotlib, HTML/CSS |
| Delivery | Static HTML, GitHub Pages |
