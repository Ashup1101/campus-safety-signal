-- The real-only view of the conformed incidents: what public pages, alerts and models see by
-- default. Synthetic rows exist only for gap patching and evaluation.
select * from {{ ref('incidents') }} where source != 'synthetic'
