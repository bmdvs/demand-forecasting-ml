{{ config(materialized="table") }}

-- The family each canonical item belongs to. Raw material carries its material family in
-- the grade on its description, as a commodity code would (A36 and A500 structural
-- steel, 304 and 316 stainless, 6061, 5052 and 6063 aluminum). Every other item's family
-- is its class and the product family whose bills draw most of it in 2025 (by required
-- quantity), or its class alone when no bill draws it. Grain: canonical item.

with items as (

    select i.canonical_item_number, coalesce(m.item_class, 'MISC') as item_class, upper(m.description) as descr
    from {{ ref('mart_item_attributes') }} i
    left join {{ ref('stg_erp__item_master') }} m on m.item_number = i.canonical_item_number

),

pf_share as (

    select canonical_item_number, product_family, sum(req_qty) as qty
    from {{ ref('int_job_requirements') }}
    where extract(year from required_date) = 2025
    group by 1, 2

),

pf_ranked as (

    select p.*,
           row_number() over (partition by canonical_item_number order by qty desc, product_family) as rk,
           sum(qty) over (partition by canonical_item_number)                                     as total
    from pf_share p

)

select
    i.canonical_item_number,
    i.item_class,
    case
        when i.item_class = 'Raw Material' and (i.descr like '%A36%' or i.descr like '%A500%') then 'Structural Steel'
        when i.item_class = 'Raw Material' and (i.descr like '%304%' or i.descr like '%316%') then 'Stainless'
        when i.item_class = 'Raw Material' and (i.descr like '%6061%' or i.descr like '%5052%' or i.descr like '%6063%') then 'Aluminum'
    end                                                                       as material_family,
    p.product_family                                                          as primary_product_family,
    case when p.total > 0 then p.qty / p.total end                            as primary_family_share,
    case
        when i.item_class = 'Raw Material' and (i.descr like '%A36%' or i.descr like '%A500%') then 'Structural Steel'
        when i.item_class = 'Raw Material' and (i.descr like '%304%' or i.descr like '%316%') then 'Stainless'
        when i.item_class = 'Raw Material' and (i.descr like '%6061%' or i.descr like '%5052%' or i.descr like '%6063%') then 'Aluminum'
        when p.product_family is not null then i.item_class || ' / ' || p.product_family
        else i.item_class
    end                                                                       as family
from items i
left join pf_ranked p on p.canonical_item_number = i.canonical_item_number and p.rk = 1
