{# Use +schema as-is (silver, staging) instead of dbt's <target>_<schema> default. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}
