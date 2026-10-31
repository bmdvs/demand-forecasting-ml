-- Fully cleaned weekly usage, the series the model trains on: master-cleaned usage,
-- plus unrecorded usage added back over the item's own weekly shape, less the confirmed
-- keying errors and duplicate postings. Floored at zero. The parts are added with a
-- compensated (Kahan) sum in a fixed order (recorded usage, each unrecorded source, keying
-- corrections, duplicate removals), so the result is reproducible to the last digit.
-- Grain: canonical item x week.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_consumption_weekly (
  CONSTRAINT canonical_item_number_not_null EXPECT (canonical_item_number IS NOT NULL),
  CONSTRAINT consumption_not_null EXPECT (consumption IS NOT NULL)
)
COMMENT 'Fully cleaned weekly usage by canonical item'
AS
with base as (
    select canonical_item_number, week, sum(units) as consumption
    from silver.int_recorded_usage
    group by 1, 2
),
totals as (
    select canonical_item_number, sum(consumption) as total
    from base
    group by 1
),
sources as (
    select
        u.source_no,
        coalesce(x.canonical_item_number, u.item_number) as canonical_item_number,
        u.annual_unrecorded
    from silver.stg_truth__unrecorded_usage u
    left join silver.int_item_crosswalk x using (item_number)
    where u.annual_unrecorded > 0
),
add_back as (
    select
        s.source_no,
        b.canonical_item_number,
        b.week,
        s.annual_unrecorded * (cast(b.consumption as double) / greatest(1.0D, t.total)) as delta
    from sources s
    join base b using (canonical_item_number)
    join totals t using (canonical_item_number)
),
combined as (
    select canonical_item_number, week, 0 as part, 0 as source_no, '' as txn_id,
           cast(consumption as double) as delta
    from base
    union all
    select canonical_item_number, week, 1, source_no, '', delta
    from add_back
    union all
    select canonical_item_number, week, case correction when 'keying' then 2 else 3 end, 0, txn_id, delta
    from silver.int_usage_corrections
    where is_usage_posting
)
select
    canonical_item_number,
    week,
    greatest(
        aggregate(
            array_sort(collect_list(named_struct('part', part, 'source_no', source_no,
                                                 'txn_id', txn_id, 'delta', delta))),
            named_struct('s', 0.0D, 'c', 0.0D),
            (acc, x) -> named_struct(
                's', acc.s + (x.delta - acc.c),
                'c', ((acc.s + (x.delta - acc.c)) - acc.s) - (x.delta - acc.c))
        ).s,
        0) as consumption
from combined
group by 1, 2;
