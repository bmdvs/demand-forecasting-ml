{% test unique_combination(model, columns) %}

-- Fails on every combination of the grain columns that appears more than once.
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1

{% endtest %}
