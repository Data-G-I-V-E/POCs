"""
Database Unification and Migration Script

Creates unified views and helpful SQL functions to work across
the fragmented database tables.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import config
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from config import Config


UNIFICATION_SQL = """
-- =====================================================
-- DATABASE UNIFICATION VIEWS AND FUNCTIONS
-- Run this after all tables are created
-- =====================================================

-- Drop existing views if they exist
DROP VIEW IF EXISTS v_export_policy_unified CASCADE;
DROP VIEW IF EXISTS v_hs_codes_complete CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_hs_export_summary CASCADE;
DROP FUNCTION IF EXISTS get_export_feasibility CASCADE;

-- =====================================================
-- 1. UNIFIED EXPORT POLICY VIEW
-- Combines all export policies for any HS code
-- Includes codes from both hs_codes and itc_hs_products tables
-- =====================================================

CREATE OR REPLACE VIEW v_export_policy_unified AS
WITH all_codes AS (
    -- Get all unique HS codes from both tables
    SELECT DISTINCT hs_code, description, chapter_number, code_level
    FROM hs_codes
    UNION
    SELECT DISTINCT hs_code, description, chapter_code as chapter_number, level as code_level
    FROM itc_hs_products
)
SELECT 
    ac.hs_code,
    ac.description AS hs_description,
    ac.chapter_number,
    ac.code_level,
    
    -- ITC Policy
    itc.export_policy AS itc_policy,
    itc.notification_no AS itc_notification,
    itc.notification_date AS itc_date,
    
    -- Policy References (e.g., "Policy Condition 1")
    pr.policy_reference,
    cp.policy_text AS policy_reference_text,
    
    -- Prohibited Status
    pi.export_policy AS prohibited_policy,
    pi.policy_condition AS prohibited_condition,
    CASE WHEN pi.hs_code IS NOT NULL THEN TRUE ELSE FALSE END AS is_prohibited,
    
    -- Restricted Status
    ri.export_policy AS restricted_policy,
    ri.policy_condition AS restricted_condition,
    CASE WHEN ri.hs_code IS NOT NULL THEN TRUE ELSE FALSE END AS is_restricted,
    
    -- STE Status
    ste.export_policy AS ste_policy,
    ste.authorized_entity AS ste_entity,
    CASE WHEN ste.hs_code IS NOT NULL THEN TRUE ELSE FALSE END AS is_ste,
    
    -- Overall Status
    CASE 
        WHEN pi.hs_code IS NOT NULL THEN 'PROHIBITED'
        WHEN ri.hs_code IS NOT NULL THEN 'RESTRICTED'
        WHEN ste.hs_code IS NOT NULL THEN 'STE_ONLY'
        WHEN pr.policy_reference IS NOT NULL THEN 'CONDITIONAL'
        WHEN itc.export_policy = 'Free' THEN 'FREE'
        ELSE 'CHECK_POLICY'
    END AS overall_status

FROM all_codes ac
LEFT JOIN itc_hs_products itc ON ac.hs_code = itc.hs_code
LEFT JOIN itc_hs_policy_references pr ON ac.hs_code = pr.hs_code
LEFT JOIN itc_chapter_policies cp ON pr.chapter_code = cp.chapter_code 
    AND pr.policy_reference = cp.policy_type
LEFT JOIN prohibited_items pi ON ac.hs_code = pi.hs_code
LEFT JOIN restricted_items ri ON ac.hs_code = ri.hs_code
LEFT JOIN ste_items ste ON ac.hs_code = ste.hs_code;

COMMENT ON VIEW v_export_policy_unified IS 'Unified view of all export policies for HS codes';

-- =====================================================
-- 2. COMPLETE HS CODE INFO VIEW
-- HS code with all related information
-- =====================================================

CREATE OR REPLACE VIEW v_hs_codes_complete AS
SELECT 
    hc.*,
    ch.title AS chapter_title,
    ch.notes AS chapter_notes,
    ep.overall_status,
    ep.is_prohibited,
    ep.is_restricted,
    ep.is_ste,
    ep.ste_entity,
    ep.prohibited_condition,
    ep.restricted_condition
FROM hs_codes hc
LEFT JOIN chapters ch ON hc.chapter_number = ch.chapter_number
LEFT JOIN v_export_policy_unified ep ON hc.hs_code = ep.hs_code;

COMMENT ON VIEW v_hs_codes_complete IS 'Complete HS code information with export policies';

-- =====================================================
-- 3. HS CODE EXPORT SUMMARY (MATERIALIZED)
-- Aggregated export statistics per HS code
-- =====================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hs_export_summary AS
SELECT 
    es.hs_code,
    hc.description,
    COUNT(DISTINCT es.country_code) AS export_countries_count,
    COUNT(DISTINCT es.year_label) AS years_with_data,
    SUM(es.export_value_crore) AS total_export_value_crore,
    AVG(es.export_value_crore) AS avg_export_value_crore,
    MAX(es.export_value_crore) AS max_export_value_crore,
    MAX(es.year_label) AS latest_year,
    array_agg(DISTINCT es.country_code) AS export_countries
FROM export_statistics es
JOIN hs_codes hc ON es.hs_code = hc.hs_code
GROUP BY es.hs_code, hc.description;

CREATE INDEX idx_mv_hs_export_summary_hscode ON mv_hs_export_summary(hs_code);

COMMENT ON MATERIALIZED VIEW mv_hs_export_summary IS 'Aggregated export statistics per HS code - refresh periodically';

-- Refresh function
CREATE OR REPLACE FUNCTION refresh_export_summary()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_hs_export_summary;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 4. EXPORT FEASIBILITY CHECK FUNCTION
-- Comprehensive export check for HS code + country
-- =====================================================

CREATE OR REPLACE FUNCTION get_export_feasibility(
    p_hs_code VARCHAR(10),
    p_country_code VARCHAR(10)
)
RETURNS TABLE (
    hs_code VARCHAR(10),
    description TEXT,
    can_export BOOLEAN,
    overall_status TEXT,
    issues TEXT[],
    warnings TEXT[],
    requirements TEXT[],
    has_trade_data BOOLEAN,
    recent_export_value DECIMAL
) AS $$
BEGIN
    RETURN QUERY
    WITH policy_check AS (
        SELECT 
            ep.hs_code,
            ep.hs_description,
            ep.overall_status,
            ep.is_prohibited,
            ep.is_restricted,
            ep.is_ste,
            ep.ste_entity,
            ep.prohibited_condition,
            ep.restricted_condition
        FROM v_export_policy_unified ep
        WHERE ep.hs_code = p_hs_code
    ),
    trade_check AS (
        SELECT 
            es.hs_code,
            bool_or(es.country_code = p_country_code) AS has_data,
            MAX(CASE WHEN es.country_code = p_country_code 
                THEN es.export_value_crore ELSE 0 END) AS recent_value
        FROM export_statistics es
        WHERE es.hs_code = p_hs_code
        GROUP BY es.hs_code
    )
    SELECT 
        pc.hs_code,
        pc.hs_description,
        NOT pc.is_prohibited AS can_export,
        pc.overall_status,
        
        -- Issues array
        ARRAY_REMOVE(ARRAY[
            CASE WHEN pc.is_prohibited THEN 
                'PROHIBITED: ' || COALESCE(pc.prohibited_condition, 'Export not allowed')
            END
        ], NULL) AS issues,
        
        -- Warnings array
        ARRAY_REMOVE(ARRAY[
            CASE WHEN pc.is_restricted THEN 
                'RESTRICTED: ' || COALESCE(pc.restricted_condition, 'Special conditions apply')
            END
        ], NULL) AS warnings,
        
        -- Requirements array
        ARRAY_REMOVE(ARRAY[
            CASE WHEN pc.is_ste THEN 
                'STE Required: Export through ' || COALESCE(pc.ste_entity, 'designated entity')
            END,
            CASE WHEN pc.is_restricted THEN 
                'License/Permit may be required'
            END
        ], NULL) AS requirements,
        
        -- Trade data
        COALESCE(tc.has_data, FALSE) AS has_trade_data,
        COALESCE(tc.recent_value, 0) AS recent_export_value
        
    FROM policy_check pc
    LEFT JOIN trade_check tc ON pc.hs_code = tc.hs_code;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_export_feasibility IS 'Comprehensive export feasibility check for HS code to country';

-- =====================================================
-- 5. SEARCH FUNCTIONS
-- =====================================================

-- Search HS codes by description
CREATE OR REPLACE FUNCTION search_hs_codes(search_term TEXT, limit_rows INT DEFAULT 20)
RETURNS TABLE (
    hs_code VARCHAR(10),
    description TEXT,
    chapter_number VARCHAR(10),
    overall_status TEXT,
    relevance REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        v.hs_code,
        v.description,
        v.chapter_number,
        v.overall_status,
        ts_rank(to_tsvector('english', v.description), plainto_tsquery('english', search_term)) AS relevance
    FROM v_hs_codes_complete v
    WHERE to_tsvector('english', v.description) @@ plainto_tsquery('english', search_term)
    ORDER BY relevance DESC
    LIMIT limit_rows;
END;
$$ LANGUAGE plpgsql;

-- Get all export policies for a chapter
CREATE OR REPLACE FUNCTION get_chapter_export_policies(p_chapter VARCHAR(10))
RETURNS TABLE (
    hs_code VARCHAR(10),
    description TEXT,
    overall_status TEXT,
    policy_details JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ep.hs_code,
        ep.hs_description,
        ep.overall_status,
        jsonb_build_object(
            'itc_policy', ep.itc_policy,
            'is_prohibited', ep.is_prohibited,
            'is_restricted', ep.is_restricted,
            'is_ste', ep.is_ste,
            'ste_entity', ep.ste_entity,
            'prohibited_condition', ep.prohibited_condition,
            'restricted_condition', ep.restricted_condition
        ) AS policy_details
    FROM v_export_policy_unified ep
    WHERE ep.chapter_number = p_chapter
    ORDER BY ep.hs_code;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 6. HELPFUL INDEXES (if not already created)
-- =====================================================

-- Create indexes on views' underlying tables if missing
CREATE INDEX IF NOT EXISTS idx_itc_hs_products_hs_code ON itc_hs_products(hs_code);
CREATE INDEX IF NOT EXISTS idx_prohibited_items_hs_code ON prohibited_items(hs_code);
CREATE INDEX IF NOT EXISTS idx_restricted_items_hs_code ON restricted_items(hs_code);
CREATE INDEX IF NOT EXISTS idx_ste_items_hs_code ON ste_items(hs_code);

-- =====================================================
-- COMPLETION MESSAGE
-- =====================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '════════════════════════════════════════════════════════════════════';
    RAISE NOTICE 'DATABASE UNIFICATION COMPLETE!';
    RAISE NOTICE '════════════════════════════════════════════════════════════════════';
    RAISE NOTICE '';
    RAISE NOTICE 'Created Views:';
    RAISE NOTICE '  ✓ v_export_policy_unified    - All export policies in one view';
    RAISE NOTICE '  ✓ v_hs_codes_complete         - Complete HS code information';
    RAISE NOTICE '  ✓ mv_hs_export_summary        - Export statistics summary';
    RAISE NOTICE '';
    RAISE NOTICE 'Created Functions:';
    RAISE NOTICE '  ✓ get_export_feasibility()    - Check if export is feasible';
    RAISE NOTICE '  ✓ search_hs_codes()           - Search by description';
    RAISE NOTICE '  ✓ get_chapter_export_policies() - Get all policies for chapter';
    RAISE NOTICE '  ✓ refresh_export_summary()    - Refresh materialized view';
    RAISE NOTICE '';
    RAISE NOTICE 'Example Queries:';
    RAISE NOTICE '  -- Check export feasibility';
    RAISE NOTICE '  SELECT * FROM get_export_feasibility(''070310'', ''AUS'');';
    RAISE NOTICE '';
    RAISE NOTICE '  -- Search for products';
    RAISE NOTICE '  SELECT * FROM search_hs_codes(''onion'');';
    RAISE NOTICE '';
    RAISE NOTICE '  -- Get all policies for chapter';
    RAISE NOTICE '  SELECT * FROM get_chapter_export_policies(''07'');';
    RAISE NOTICE '';
    RAISE NOTICE '  -- View unified policy';
    RAISE NOTICE '  SELECT * FROM v_export_policy_unified WHERE hs_code = ''070310'';';
    RAISE NOTICE '';
    RAISE NOTICE '════════════════════════════════════════════════════════════════════';
END $$;
"""


def run_unification(verbose: bool = True):
    """Run database unification script"""
    if verbose:
        print("="*70)
        print("DATABASE UNIFICATION SCRIPT")
        print("="*70)
        print(f"\nConnecting to database: {Config.DB_CONFIG['database']}")
    
    try:
        conn = psycopg2.connect(**Config.DB_CONFIG)
        cursor = conn.cursor()
        
        if verbose:
            print("✓ Connected successfully\n")
            print("Running unification SQL...")
        
        # Execute the SQL
        cursor.execute(UNIFICATION_SQL)
        conn.commit()
        
        if verbose:
            print("\n✓ Unification complete!")
            print("\nYou can now use:")
            print("  - v_export_policy_unified")
            print("  - v_hs_codes_complete")
            print("  - get_export_feasibility(hs_code, country)")
            print("  - search_hs_codes(term)")
        
        cursor.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error during unification: {e}")
        return False


if __name__ == "__main__":
    run_unification(verbose=True)
