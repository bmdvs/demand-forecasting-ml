-- The audit's error register: for each of the 16 errors and the ERP table it lives in,
-- the rows flagged and the rows in scope. Grain: one row per error per ERP table.

with live as (

    select count(*) as n from {{ ref('int_items_resolved') }} where not is_dead

),

ledger as (

    select count(*) as n from {{ ref('stg_erp__inventory_transactions') }}

),

po as (

    select count(*) as n from {{ ref('stg_erp__purchase_orders') }}

)

select 1 as error_no, 'Dead records never deactivated' as error, 'Item master' as erp_table,
       (select count(*) from {{ ref('dq_01_dead_records') }}) as rows_flagged,
       (select count(*) from {{ ref('stg_erp__item_master') }}) as rows_in_scope
union all select 2, 'Stale lead times', 'Item master (live items)',
       (select count(*) from {{ ref('dq_02_stale_lead_times') }}), (select n from live)
union all select 3, 'Stale reorder points', 'Item master (live items)',
       (select count(*) from {{ ref('dq_03_stale_reorder_points') }}), (select n from live)
union all select 4, 'Duplicate item records', 'Item master (live items)',
       (select count(*) from {{ ref('dq_04_duplicate_items') }}), (select n from live)
union all select 5, 'UOM mismatch', 'Item master (live items)',
       (select count(distinct item_id) from {{ ref('dq_05_uom_mismatch') }}), (select n from live)
union all select 6, 'Missing and placeholder fields', 'Item master (live items)',
       (select count(*) from {{ ref('dq_06_missing_fields') }}), (select n from live)
union all select 7, 'BOM omissions', 'Bill of materials',
       (select count(*) from {{ ref('dq_07_bom_omissions') }}),
       (select count(*) from {{ ref('stg_erp__bill_of_materials') }})
           + (select count(*) from {{ ref('dq_07_bom_omissions') }})
union all select 8, 'Supplier fragmentation', 'Supplier master',
       (select count(*) from {{ ref('dq_08_supplier_fragmentation') }}),
       (select count(*) from {{ ref('stg_erp__supplier_master') }})
union all select 9, 'Unrecorded consumption', 'Inventory ledger',
       (select count(*) from {{ ref('dq_09_unrecorded_consumption') }}), (select n from ledger)
union all select 10, 'Wrong references', 'Inventory ledger',
       (select count(*) from {{ ref('dq_10_wrong_references') }}), (select n from ledger)
union all select 11, 'Quantity and unit errors', 'Inventory ledger',
       (select count(*) from {{ ref('dq_11_quantity_errors') }}), (select n from ledger)
union all select 12, 'Duplicate postings', 'Inventory ledger',
       (select count(*) from {{ ref('dq_12_duplicate_postings') }} where is_confirmed), (select n from ledger)
union all select 13, 'Adjustments as a catch-all', 'Inventory ledger (adjustments)',
       (select count(*) from {{ ref('dq_13_catch_all_adjustments') }}),
       (select count(*) from {{ ref('stg_erp__inventory_transactions') }} where txn_type = 'ADJUST')
union all select 14, 'Free-text purchases', 'Purchase orders',
       (select count(*) from {{ ref('dq_14_free_text_purchases') }}), (select n from po)
union all select 15, 'Batched and backdated postings', 'Purchase orders',
       (select count(*) from {{ ref('dq_15_batched_postings') }}), (select n from po)
union all select 16, 'Open documents never closed', 'Purchase orders',
       (select count(*) from {{ ref('dq_16_open_documents') }} where document_type = 'PO'), (select n from po)
union all select 16, 'Open documents never closed', 'Production orders',
       (select count(*) from {{ ref('dq_16_open_documents') }} where document_type = 'JOB'),
       (select count(*) from {{ ref('stg_erp__production_orders') }})
