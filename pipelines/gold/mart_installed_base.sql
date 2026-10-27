-- The installed base by product family and month: units completed in the month, units
-- fielded since the history opened, the age-weighted base, and the age-weighted base with
-- the estimated opening fleet (int_product_installed_base). Grain: product family x month.
CREATE OR REFRESH MATERIALIZED VIEW gold.mart_installed_base
COMMENT 'Installed base by product family and month'
AS
select
    product_family,
    month,
    sum(units_completed)         as units_completed,
    sum(units_fielded)           as units_fielded,
    sum(age_weighted_base)       as age_weighted_base,
    sum(age_weighted_base_est)   as age_weighted_base_est
from silver.int_product_installed_base
group by 1, 2;
