-- =====================================================
-- STE Items Database Schema
-- Database: PPL-AI
-- State Trading Enterprise (STE) Export Items
-- =====================================================

-- Drop existing table if it exists
DROP TABLE IF EXISTS ste_items CASCADE;

-- Create ste_items table
CREATE TABLE ste_items (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(20) NOT NULL UNIQUE,
    description TEXT NOT NULL,
    export_policy VARCHAR(50) NOT NULL,
    policy_condition TEXT,
    authorized_entity VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for faster searching
CREATE INDEX idx_ste_hs_code ON ste_items(hs_code);
CREATE INDEX idx_ste_authorized_entity ON ste_items(authorized_entity);
CREATE INDEX idx_ste_description ON ste_items USING gin(to_tsvector('english', description));

-- =====================================================
-- SEARCH FUNCTIONS
-- =====================================================

-- Function to search STE items
CREATE OR REPLACE FUNCTION search_ste_items(search_term TEXT)
RETURNS TABLE (
    hs_code VARCHAR,
    description TEXT,
    export_policy VARCHAR,
    policy_condition TEXT,
    authorized_entity VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        s.hs_code,
        s.description,
        s.export_policy,
        s.policy_condition,
        s.authorized_entity
    FROM ste_items s
    WHERE s.hs_code ILIKE '%' || search_term || '%'
       OR s.description ILIKE '%' || search_term || '%'
       OR s.authorized_entity ILIKE '%' || search_term || '%'
    ORDER BY s.hs_code;
END;
$$ LANGUAGE plpgsql;

-- Function to get items by authorized entity
CREATE OR REPLACE FUNCTION get_items_by_entity(entity_name TEXT)
RETURNS TABLE (
    hs_code VARCHAR,
    description TEXT,
    export_policy VARCHAR,
    policy_condition TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        s.hs_code,
        s.description,
        s.export_policy,
        s.policy_condition
    FROM ste_items s
    WHERE s.authorized_entity = entity_name
    ORDER BY s.hs_code;
END;
$$ LANGUAGE plpgsql;

-- Function to check if an HS code is STE controlled
CREATE OR REPLACE FUNCTION is_ste_item(code VARCHAR)
RETURNS BOOLEAN AS $$
DECLARE
    item_exists BOOLEAN;
BEGIN
    SELECT EXISTS(SELECT 1 FROM ste_items WHERE hs_code = code) INTO item_exists;
    RETURN item_exists;
END;
$$ LANGUAGE plpgsql;

-- Function to get STE item by exact HS code
CREATE OR REPLACE FUNCTION get_ste_item_by_code(code VARCHAR)
RETURNS TABLE (
    hs_code VARCHAR,
    description TEXT,
    export_policy VARCHAR,
    policy_condition TEXT,
    authorized_entity VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        s.hs_code,
        s.description,
        s.export_policy,
        s.policy_condition,
        s.authorized_entity
    FROM ste_items s
    WHERE s.hs_code = code;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- UNIFIED VIEWS (if other tables exist)
-- =====================================================

-- Drop and recreate unified view combining all export policy items
DROP VIEW IF EXISTS all_export_policy_items CASCADE;

CREATE OR REPLACE VIEW all_export_policy_items AS
SELECT 
    'Prohibited' as item_type,
    hs_code,
    description,
    export_policy,
    policy_condition,
    NULL::VARCHAR as authorized_entity,
    created_at,
    updated_at
FROM prohibited_items

UNION ALL

SELECT 
    'Restricted' as item_type,
    hs_code,
    description,
    export_policy,
    policy_condition,
    NULL::VARCHAR as authorized_entity,
    created_at,
    updated_at
FROM restricted_items

UNION ALL

SELECT 
    'STE' as item_type,
    hs_code,
    description,
    export_policy,
    policy_condition,
    authorized_entity,
    created_at,
    updated_at
FROM ste_items

ORDER BY hs_code;

-- =====================================================
-- COMPREHENSIVE SEARCH FUNCTION
-- =====================================================

-- Function to search across ALL export policy items (prohibited, restricted, and STE)
CREATE OR REPLACE FUNCTION search_all_export_items(search_term TEXT)
RETURNS TABLE (
    item_type VARCHAR,
    hs_code VARCHAR,
    description TEXT,
    export_policy VARCHAR,
    policy_condition TEXT,
    authorized_entity VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.item_type,
        a.hs_code,
        a.description,
        a.export_policy,
        a.policy_condition,
        a.authorized_entity
    FROM all_export_policy_items a
    WHERE a.hs_code ILIKE '%' || search_term || '%'
       OR a.description ILIKE '%' || search_term || '%'
       OR a.authorized_entity ILIKE '%' || search_term || '%'
    ORDER BY a.item_type, a.hs_code;
END;
$$ LANGUAGE plpgsql;

-- Function to get export policy for any HS code
CREATE OR REPLACE FUNCTION get_export_policy(code VARCHAR)
RETURNS TABLE (
    item_type VARCHAR,
    hs_code VARCHAR,
    description TEXT,
    export_policy VARCHAR,
    policy_condition TEXT,
    authorized_entity VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.item_type,
        a.hs_code,
        a.description,
        a.export_policy,
        a.policy_condition,
        a.authorized_entity
    FROM all_export_policy_items a
    WHERE a.hs_code = code;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- SUMMARY STATISTICS VIEW
-- =====================================================

CREATE OR REPLACE VIEW export_policy_summary AS
SELECT 
    'Prohibited' as policy_type,
    COUNT(*) as item_count,
    NULL::VARCHAR as top_entity
FROM prohibited_items

UNION ALL

SELECT 
    'Restricted' as policy_type,
    COUNT(*) as item_count,
    NULL::VARCHAR as top_entity
FROM restricted_items

UNION ALL

SELECT 
    'STE' as policy_type,
    COUNT(*) as item_count,
    (SELECT authorized_entity 
     FROM ste_items 
     WHERE authorized_entity IS NOT NULL 
     GROUP BY authorized_entity 
     ORDER BY COUNT(*) DESC 
     LIMIT 1) as top_entity
FROM ste_items;

-- =====================================================
-- COMMENTS
-- =====================================================

COMMENT ON TABLE ste_items IS 'Items that require State Trading Enterprise authorization for export under ITC(HS) 2017 Schedule 2';
COMMENT ON COLUMN ste_items.authorized_entity IS 'The State Trading Enterprise authorized to export this item (e.g., IREL, MOIL, IOCL)';
COMMENT ON FUNCTION search_ste_items IS 'Search STE items by HS code, description, or authorized entity';
COMMENT ON FUNCTION get_items_by_entity IS 'Get all STE items for a specific authorized entity';
COMMENT ON FUNCTION is_ste_item IS 'Check if an HS code requires STE authorization';
COMMENT ON FUNCTION search_all_export_items IS 'Search across all export policy items (prohibited, restricted, and STE)';
COMMENT ON FUNCTION get_export_policy IS 'Get the complete export policy for any HS code';
COMMENT ON VIEW all_export_policy_items IS 'Unified view of all export policy items including prohibited, restricted, and STE items';
COMMENT ON VIEW export_policy_summary IS 'Summary statistics of export policy items by type';

-- =====================================================
-- SEED DATA: All STE Items from ITC(HS) 2017 Schedule 2
-- =====================================================

INSERT INTO ste_items (hs_code, description, export_policy, policy_condition, authorized_entity) VALUES
('25085031', 'Sillimanite ---- Lumps', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('25085032', 'Sillimanite ---- Fines (including sand)', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('25085039', 'Sillimanite ---- Other', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('25132030', 'Natural garnet', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('26011111', '60percent Fe or more but below 62percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011112', '62percent Fe or more but below 65percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011119', '65percent Fe and above', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011121', 'Iron ore lumps (below 60percent Fe) ---- Iron ore lumps below 55percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011122', 'Iron ore lumps (below 60percent Fe) ---- Iron ore lumps 55percent Fe or more but below 58 percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011129', 'Iron ore lumps (below 60percent Fe) ---- 58 percent Fe or more but below 60 percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011131', 'Iron ore fines (62percent Fe or more) ---- 62percent Fe or more but below 65percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011139', 'Iron ore fines (62percent Fe or more) ---- 65percent Fe and above', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011141', 'Iron ore Fines (below 62percent Fe) ---- below 55percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011142', 'Iron ore Fines (below 62percent Fe) ---- 55percent Fe or more but below 58percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011143', 'Iron ore Fines (below 62percent Fe) ---- 58percent Fe or more but below 60percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011149', 'Iron ore Fines (below 62percent Fe) ---- 60percent Fe or more but below 62percent Fe', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26011150', 'Iron ore concentrates', 'STE (State Trading Enterprise)', 'Export of Iron ore concentrate prepared by benefication and/or concentration of lowgrade ore containing 40 percent or less of iron produced by Kudremukh Iron Ore Company Limited can be exported by STE- Kudremukh Iron Ore Company Limited, Bangalore.', 'Kudremukh Iron Ore Company Limited'),
('26011190', 'Others', 'STE (State Trading Enterprise)', 'Subject to Policy Condition 1 of the Chapter.', NULL),
('26020020', 'Manganese ore (44percent or more but below 46percent)', 'STE (State Trading Enterprise)', 'Export is allowed through Manganese Ore India Limited (MOIL) only.', 'MOIL'),
('26020030', 'Manganese ore (40percent or more but below 44percent)', 'STE (State Trading Enterprise)', 'Export is allowed through Manganese Ore India Limited (MOIL) only.', 'MOIL'),
('26020040', 'Manganese ore (35percent or more but below 40percent)', 'STE (State Trading Enterprise)', 'Export is allowed through Manganese Ore India Limited (MOIL) only.', 'MOIL'),
('26020050', 'Manganese ore (30percent or more but below 35percent)', 'STE (State Trading Enterprise)', 'Export is allowed through Manganese Ore India Limited (MOIL) only.', 'MOIL'),
('26020060', 'Ferruginous (10percent or more but below 30percent)', 'STE (State Trading Enterprise)', 'Export is allowed through Manganese Ore India Limited (MOIL) only.', 'MOIL'),
('26020070', 'Manganese ore sinters, agglomerated', 'STE (State Trading Enterprise)', 'Export is allowed through Manganese Ore India Limited (MOIL) only.', 'MOIL'),
('26020090', 'Other', 'STE (State Trading Enterprise)', 'Export is allowed through Manganese Ore India Limited (MOIL) only.', 'MOIL'),
('26121000', 'Uranium ores and concentrates', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('26122000', 'Thorium ores and concentrates', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('26140010', 'Ilmenite, unprocessed', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('26140020', 'Ilmenite, upgraded (beneficiated ilmenite including ilmenite ground)', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('26140031', 'Rutile: ---- Rare earth oxides including rutile sand', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('26140039', 'Rutile: ---- Other', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('26140090', 'Other', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('26151000', 'Zirconium ores and concentrates', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Rare Earths Limited (IREL) only.', 'IREL'),
('27090010', 'PETROLEUM CRUDE', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Oil Corporation Limited (IOCL) only.', 'IOCL'),
('27090090', 'OTHER', 'STE (State Trading Enterprise)', 'Export is allowed through Indian Oil Corporation Limited (IOCL) only.', 'IOCL')
ON CONFLICT (hs_code) DO UPDATE SET
    description = EXCLUDED.description,
    export_policy = EXCLUDED.export_policy,
    policy_condition = EXCLUDED.policy_condition,
    authorized_entity = EXCLUDED.authorized_entity,
    updated_at = CURRENT_TIMESTAMP;

-- Success message
SELECT 'STE Items schema created successfully!' as status;
SELECT 'Tables created: ste_items' as tables;
SELECT 'Functions created: search_ste_items, get_items_by_entity, is_ste_item, search_all_export_items, get_export_policy' as functions;
SELECT 'Views created: all_export_policy_items, export_policy_summary' as views;