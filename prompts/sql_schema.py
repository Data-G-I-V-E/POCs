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

8. export_statistics - Annual export trade data (last year, country-wise)
   Columns: hs_code, country_code, year_label, export_value_crore
   ⚠ COVERAGE: Contains data for ONLY the same 16 HS codes as monthly_export_statistics.
     There is NO chapter-level or aggregate data here. Do NOT use as a fallback for
     unlisted HS codes — it will return 0 rows.

9. monthly_export_statistics - Monthly export data for 2024
   Columns: hs_code, country_code, year, month (1-12), month_name (Jan-Dec),
            export_value_crore, prev_year_value_crore, monthly_growth_pct,
            ytd_value_crore, prev_ytd_value_crore, ytd_growth_pct,
            total_monthly_value_crore, total_ytd_value_crore
   ⚠ COVERAGE: Contains data for ONLY these 16 HS codes (6-digit):
       070310, 070700, 070960  (Chapter 7)
       080310, 080410, 080450  (Chapter 8)
       610910, 610342, 610442  (Chapter 61)
       620342, 620462, 620520  (Chapter 62)
       850440, 851310, 851762  (Chapter 85)
       902610                  (Chapter 90)
   For ANY other HS code, return a "no data" message — do NOT query this table.

10. v_monthly_exports - Monthly exports with country names and HS descriptions (VIEW)
    Columns: hs_code, chapter (VARCHAR - use quotes e.g. chapter = '85'), hs_description, country_code, country_name,
             year, month (INTEGER 1-12), month_name (VARCHAR 'Jan'-'Dec'), export_value_crore, prev_year_value_crore,
             monthly_growth_pct, ytd_value_crore, prev_ytd_value_crore, ytd_growth_pct,
             total_monthly_value_crore, total_ytd_value_crore
    Preferred view for monthly data queries - already has country names and HS descriptions
    IMPORTANT: chapter is TEXT derived from LEFT(hs_code,2), always compare as string: chapter = '85' NOT chapter = 85
    ⚠ COVERAGE: Same 16 HS codes only — see monthly_export_statistics above.

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

15. hs_master_8_digit - Master HS code classification table (12,056 eight-digit Indian HS codes)
    Columns: hs_code (VARCHAR), chapter (INTEGER), heading (VARCHAR 4-digit), subheading (VARCHAR 6-digit),
             description (TEXT), code_level (INTEGER: 3=tariff line/8-digit, 2=subheading/6-digit, 1=heading/4-digit),
             parent_code (VARCHAR), source_chapter (VARCHAR)
    Use for: finding HS codes for a product description, listing all codes in a chapter,
             checking what chapter/heading a code belongs to, browsing the full HS code tree
    Indexes: GIN full-text on description (use plainto_tsquery), trigram on description (use word_similarity)
    Example: SELECT hs_code, description FROM hs_master_8_digit
             WHERE to_tsvector('english', description) @@ plainto_tsquery('english', 'cotton shirts')

16. itc_hs_products - ITC HS codes with Indian export policy classification (2,006 codes, Chapters 7,8,61,62,85,90)
    Columns: hs_code (VARCHAR), chapter_code (VARCHAR), description (TEXT),
             export_policy (VARCHAR: 'Free'/'Restricted'/'Prohibited'/'STE'/'CITES'),
             parent_hs_code (VARCHAR), level (VARCHAR), notification_no, notification_date
    Use for: checking the export policy status of specific HS codes in ITC chapters,
             finding all restricted or free items in a particular chapter,
             cross-referencing HS codes with their ITC export classifications
    Note: For full policy text and conditions use v_export_policy_unified; itc_hs_products has the raw ITC classification

Functions:
- get_export_feasibility(hs_code VARCHAR, country_code VARCHAR) - Check export feasibility
- search_hs_codes(search_term TEXT) - Search HS codes by description

Important:
- Country codes: 'AUS' (Australia), 'UAE' (United Arab Emirates), 'GBR' (United Kingdom)
- TRADE DATA COVERAGE: Only these 16 HS codes (6-digit) have ANY trade data:
    070310 070700 070960 | 080310 080410 080450 | 610910 610342 610442
    620342 620462 620520 | 850440 851310 851762 | 902610
  Both export_statistics AND monthly_export_statistics share this same limited set.
  There is NO chapter-level aggregate data and NO data for any other HS code.
- HS CODE PREFIX MATCHING: If the user provides an 8-digit code, truncate to 6 digits.
  If LEFT(code, 6) is in the 16-code list → query using that 6-digit code.
  If LEFT(code, 6) is NOT in the list → return a "no data available" SQL message.
- For annual data: use export_statistics (year_label format: '2023-2024', '2024-2025')
- For monthly/trend data: use monthly_export_statistics or v_monthly_exports (year=2024, month=1-12)
- Export values are always in ₹ Crore
- To get full policy details for an HS code with references, JOIN v_export_policy_unified or query itc_chapter_policies
- For "what are prohibited items" queries, use: SELECT * FROM prohibited_items
- For "what are restricted items" queries, use: SELECT * FROM restricted_items
- For "what are STE items" queries, use: SELECT * FROM ste_items
- For monthly/trend/seasonal queries, prefer v_monthly_exports (has names) or v_quarterly_exports
- For finding HS codes by product name, use hs_master_8_digit with plainto_tsquery or ILIKE on description
- For ITC export policy status of a known HS code, use itc_hs_products.export_policy or v_export_policy_unified
"""
