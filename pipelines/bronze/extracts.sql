-- Bronze: one Auto Loader streaming table per source extract, read from the landing volume as
-- delivered. Each table reads one pass folder (<source>/<table>/<pass>/), chosen by the pipeline
-- configuration value dfm.pass; changing it is a full refresh of the pipeline. Directory listing,
-- no file events. Columns and types are the extract's, as landed (infra/land_extracts.py).

CREATE OR REFRESH STREAMING TABLE bronze.erp__bill_of_materials
COMMENT 'Source extract erp/bill_of_materials as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/erp/bill_of_materials/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.erp__inventory_transactions
COMMENT 'Source extract erp/inventory_transactions as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/erp/inventory_transactions/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.erp__item_master
COMMENT 'Source extract erp/item_master as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/erp/item_master/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.erp__production_orders
COMMENT 'Source extract erp/production_orders as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/erp/production_orders/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.erp__purchase_orders
COMMENT 'Source extract erp/purchase_orders as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/erp/purchase_orders/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.erp__service_orders
COMMENT 'Source extract erp/service_orders as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/erp/service_orders/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.erp__supplier_master
COMMENT 'Source extract erp/supplier_master as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/erp/supplier_master/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.purchasing__buyer_spreadsheet
COMMENT 'Source extract purchasing/buyer_spreadsheet as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/purchasing/buyer_spreadsheet/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__bom_change_log
COMMENT 'Source extract remediation/bom_change_log as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/bom_change_log/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__chronic_adjustment_list
COMMENT 'Source extract remediation/chronic_adjustment_list as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/chronic_adjustment_list/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__config_change_log
COMMENT 'Source extract remediation/config_change_log as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/config_change_log/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__dead_item_dispositions
COMMENT 'Source extract remediation/dead_item_dispositions as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/dead_item_dispositions/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__duplicate_crosswalk
COMMENT 'Source extract remediation/duplicate_crosswalk as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/duplicate_crosswalk/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__free_text_attribution
COMMENT 'Source extract remediation/free_text_attribution as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/free_text_attribution/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__interview_log
COMMENT 'Source extract remediation/interview_log as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/interview_log/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__lead_time_computation
COMMENT 'Source extract remediation/lead_time_computation as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/lead_time_computation/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__open_document_closures
COMMENT 'Source extract remediation/open_document_closures as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/open_document_closures/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__parameter_recommendations
COMMENT 'Source extract remediation/parameter_recommendations as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/parameter_recommendations/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__posting_corrections
COMMENT 'Source extract remediation/posting_corrections as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/posting_corrections/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__spreadsheet_reconciliation
COMMENT 'Source extract remediation/spreadsheet_reconciliation as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/spreadsheet_reconciliation/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__supplier_crosswalk
COMMENT 'Source extract remediation/supplier_crosswalk as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/supplier_crosswalk/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.remediation__uom_conversions
COMMENT 'Source extract remediation/uom_conversions as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/remediation/uom_conversions/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.wms__cycle_counts
COMMENT 'Source extract wms/cycle_counts as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/wms/cycle_counts/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__abc_by_item
COMMENT 'Source extract truth/abc_by_item as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/abc_by_item/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__batched_receipts
COMMENT 'Source extract truth/batched_receipts as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/batched_receipts/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__duplicate_clusters
COMMENT 'Source extract truth/duplicate_clusters as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/duplicate_clusters/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__rushes
COMMENT 'Source extract truth/rushes as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/rushes/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__shortages
COMMENT 'Source extract truth/shortages as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/shortages/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__true_backflush
COMMENT 'Source extract truth/true_backflush as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/true_backflush/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__true_direct_demand
COMMENT 'Source extract truth/true_direct_demand as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/true_direct_demand/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__unrecorded_events
COMMENT 'Source extract truth/unrecorded_events as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/unrecorded_events/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__unrecorded_usage
COMMENT 'Source extract truth/unrecorded_usage as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/unrecorded_usage/${dfm.pass}', format => 'parquet');

CREATE OR REFRESH STREAMING TABLE bronze.truth__uom_mismatch_items
COMMENT 'Source extract truth/uom_mismatch_items as landed'
AS
SELECT *, _metadata.file_path AS source_file
FROM STREAM read_files('${dfm.landing_root}/truth/uom_mismatch_items/${dfm.pass}', format => 'parquet');
