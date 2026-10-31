-- Staging for bronze.purchasing__buyer_spreadsheet: types, names and parsed fields; no rows dropped.
CREATE OR REFRESH MATERIALIZED VIEW silver.stg_purchasing__buyer_spreadsheet
COMMENT 'The purchasing tracking spreadsheet'
AS
SELECT
    item_ref,
    on_hand_note,
    -- The approximate on-hand figure the buyer keeps, parsed from the note.
    try_cast(regexp_extract(on_hand_note, '([0-9]+)', 1) as int) as on_hand_estimate,
    lead_time_note,
    reorder_note,
    preferred_supplier_note,
    cast(last_updated as date)       as last_updated
FROM bronze.purchasing__buyer_spreadsheet;
