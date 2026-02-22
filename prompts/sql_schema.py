"""
SQL Schema Context

Provides the SQL Agent with full knowledge of all tables, views, functions,
and type constraints in the PostgreSQL database.
"""

SCHEMA_CONTEXT = """
Available Tables and Views:

1. v_export_policy_unified - Unified export policies
   Columns: hs_code, hs_description, chapter_number, itc_policy, policy_reference, policy_reference_text,
            is_prohibited, is_restricted, is_ste, prohibited_condition, restricted_condition, overall_status
   Note: policy_reference contains references like "Policy Condition 1", policy_reference_text has full policy text

2. prohibited_items - Items prohibited from export
   Columns: id, hs_code, description, export_policy, policy_condition
   Use this to list ALL prohibited items or search for specific prohibited items

3. restricted_items - Items with export restrictions
   Columns: id, hs_code, description, export_policy, policy_condition
   Use this to list ALL restricted items or search for specific restricted items

4. ste_items - State Trading Enterprise items
   Columns: id, hs_code, description, export_policy, authorized_entity, policy_condition
   Use this to list ALL STE items or find which entity can export specific items

5. itc_hs_policy_references - Policy references for HS codes
   Columns: hs_code, policy_reference, chapter_code, notification_no, notification_date
   Use this to find HS codes that refer to chapter policies

6. itc_chapter_policies - Chapter-wise policy definitions
   Columns: chapter_code, policy_type, policy_text, notification_no, notification_date
   Contains actual policy text for references like "Policy Condition 1"

7. itc_chapter_notes - Chapter notes and additional information
   Columns: chapter_code, note_type, sl_no, note_text, notification_no
   Types: 'main_note', 'policy_condition', 'export_licensing'

8. export_statistics - Annual export trade data
   Columns: hs_code, country_code, year_label, export_value_crore

9. monthly_export_statistics - Monthly export data for 2024
   Columns: hs_code, country_code, year, month (1-12), month_name (Jan-Dec),
            export_value_crore, prev_year_value_crore, monthly_growth_pct,
            ytd_value_crore, prev_ytd_value_crore, ytd_growth_pct,
            total_monthly_value_crore, total_ytd_value_crore
   USE THIS TABLE for any question about monthly, seasonal, or trend data in 2024
   Data: 16 HS codes × 3 countries × 12 months = 565 records

10. v_monthly_exports - Monthly exports with country names and HS descriptions (VIEW)
    Columns: hs_code, chapter (VARCHAR - use quotes e.g. chapter = '85'), hs_description, country_code, country_name,
             year, month (INTEGER 1-12), month_name (VARCHAR 'Jan'-'Dec'), export_value_crore, prev_year_value_crore,
             monthly_growth_pct, ytd_value_crore, prev_ytd_value_crore, ytd_growth_pct,
             total_monthly_value_crore, total_ytd_value_crore
    Preferred view for monthly data queries - already has country names and HS descriptions
    IMPORTANT: chapter is TEXT derived from LEFT(hs_code,2), always compare as string: chapter = '85' NOT chapter = 85

11. v_quarterly_exports - Quarterly aggregations (VIEW)
    Columns: hs_code, country_code, year, quarter (Q1-Q4), quarter_num,
             quarterly_export_crore, prev_quarterly_export_crore, quarterly_growth_pct,
             months_in_quarter
    Use for quarterly comparisons e.g. "Q1 vs Q2"

12. v_hs_codes_complete - Complete HS code information
    Columns: hs_code (VARCHAR), description, chapter_number (VARCHAR - use quotes e.g. chapter_number = '85'), code_level, overall_status
    IMPORTANT: chapter_number is VARCHAR, always compare as string: chapter_number = '85' NOT chapter_number = 85

13. countries - Country information
    Columns: country_code (AUS, UAE, GBR), country_name, region

14. mv_hs_export_summary - Aggregated export statistics
    Columns: hs_code, description, export_countries_count, total_export_value_crore, latest_year

Functions:
- get_export_feasibility(hs_code VARCHAR, country_code VARCHAR) - Check export feasibility
- search_hs_codes(search_term TEXT) - Search HS codes by description

Important:
- Country codes: 'AUS' (Australia), 'UAE' (United Arab Emirates), 'GBR' (United Kingdom)
- For annual data: year format is '2023-2024', '2024-2025' in export_statistics
- For monthly data: use monthly_export_statistics or v_monthly_exports (year=2024, month=1-12)
- Export values are always in ₹ Crore
- To get full policy details for an HS code with references, JOIN v_export_policy_unified or query itc_chapter_policies
- For "what are prohibited items" queries, use: SELECT * FROM prohibited_items
- For "what are restricted items" queries, use: SELECT * FROM restricted_items
- For "what are STE items" queries, use: SELECT * FROM ste_items
- For monthly/trend/seasonal queries, prefer v_monthly_exports (has names) or v_quarterly_exports
"""
