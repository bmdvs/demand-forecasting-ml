-- The installed base behind each service part on a product's bill, by month: the
-- age-weighted fielded units of every product whose bill (as of the month) carries the
-- part, times the part's quantity per unit, through subassemblies. A successor part takes
-- over its predecessor's parents from the switch, because from then the bills name it.
-- Service parts are parts with service orders that a product's bill carries in some month.
-- Grain: canonical item x month.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_item_installed_base
COMMENT 'Installed base behind each service part by month'
AS
with ib as (
    select * from silver.int_product_installed_base
),
bom as (
    select * from silver.int_bom_resolved
),
direct as (
    select i.month, i.product_number, b.component as canonical_item_number, b.qty_per as qty_per_unit
    from ib i
    join bom b on b.parent = i.product_number and b.component_type = 'purchased'
              and i.month >= b.valid_from and i.month < b.valid_to
),
via_sub as (
    select i.month, i.product_number, s.component as canonical_item_number, p.qty_per * s.qty_per as qty_per_unit
    from ib i
    join bom p on p.parent = i.product_number and p.component_type = 'subassembly'
              and i.month >= p.valid_from and i.month < p.valid_to
    join bom s on s.parent = p.component and s.component_type = 'purchased'
              and i.month >= s.valid_from and i.month < s.valid_to
),
carried as (
    select month, product_number, canonical_item_number, sum(qty_per_unit) as qty_per_unit
    from (select * from direct union all select * from via_sub) u
    group by 1, 2, 3
),
service_parts as (
    select distinct coalesce(x.canonical_item_number, s.item_number) as canonical_item_number
    from silver.stg_erp__service_orders s
    left join silver.int_item_crosswalk x on x.item_number = s.item_number
)
select
    c.canonical_item_number,
    c.month,
    count(distinct c.product_number)                          as n_parent_products,
    sum(c.qty_per_unit * i.units_fielded)                     as units_carried,
    sum(c.qty_per_unit * i.age_weighted_base)                 as age_weighted_base,
    sum(c.qty_per_unit * i.age_weighted_base_est)             as age_weighted_base_est
from carried c
join ib i on i.product_number = c.product_number and i.month = c.month
where c.canonical_item_number in (select canonical_item_number from service_parts)
group by 1, 2;
