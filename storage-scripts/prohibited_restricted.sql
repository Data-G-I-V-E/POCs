-- =====================================================
-- Export Items Database Schema
-- Database: PPL-AI
-- =====================================================

-- Drop existing tables if they exist
DROP TABLE IF EXISTS prohibited_items CASCADE;
DROP TABLE IF EXISTS restricted_items CASCADE;

-- Create prohibited_items table
CREATE TABLE prohibited_items (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(20) NOT NULL UNIQUE,
    description TEXT NOT NULL,
    export_policy VARCHAR(50) NOT NULL,
    policy_condition TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create restricted_items table
CREATE TABLE restricted_items (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(20) NOT NULL UNIQUE,
    description TEXT NOT NULL,
    export_policy VARCHAR(50) NOT NULL,
    policy_condition TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for faster searching
CREATE INDEX idx_prohibited_hs_code ON prohibited_items(hs_code);
CREATE INDEX idx_prohibited_description ON prohibited_items USING gin(to_tsvector('english', description));
CREATE INDEX idx_restricted_hs_code ON restricted_items(hs_code);
CREATE INDEX idx_restricted_description ON restricted_items USING gin(to_tsvector('english', description));

-- Create a unified search function
CREATE OR REPLACE FUNCTION search_export_items(search_term TEXT)
RETURNS TABLE (
    item_type VARCHAR,
    hs_code VARCHAR,
    description TEXT,
    export_policy VARCHAR,
    policy_condition TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        'Prohibited'::VARCHAR as item_type,
        p.hs_code,
        p.description,
        p.export_policy,
        p.policy_condition
    FROM prohibited_items p
    WHERE p.hs_code ILIKE '%' || search_term || '%'
       OR p.description ILIKE '%' || search_term || '%'
    
    UNION ALL
    
    SELECT 
        'Restricted'::VARCHAR as item_type,
        r.hs_code,
        r.description,
        r.export_policy,
        r.policy_condition
    FROM restricted_items r
    WHERE r.hs_code ILIKE '%' || search_term || '%'
       OR r.description ILIKE '%' || search_term || '%'
    ORDER BY item_type, hs_code;
END;
$$ LANGUAGE plpgsql;

-- Create function to get item by exact HS code
CREATE OR REPLACE FUNCTION get_item_by_hs_code(code VARCHAR)
RETURNS TABLE (
    item_type VARCHAR,
    hs_code VARCHAR,
    description TEXT,
    export_policy VARCHAR,
    policy_condition TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        'Prohibited'::VARCHAR as item_type,
        p.hs_code,
        p.description,
        p.export_policy,
        p.policy_condition
    FROM prohibited_items p
    WHERE p.hs_code = code
    
    UNION ALL
    
    SELECT 
        'Restricted'::VARCHAR as item_type,
        r.hs_code,
        r.description,
        r.export_policy,
        r.policy_condition
    FROM restricted_items r
    WHERE r.hs_code = code;
END;
$$ LANGUAGE plpgsql;

-- Create view for combined items
CREATE OR REPLACE VIEW all_export_items AS
SELECT 
    'Prohibited' as item_type,
    hs_code,
    description,
    export_policy,
    policy_condition,
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
    created_at,
    updated_at
FROM restricted_items

ORDER BY hs_code;

-- Grant permissions (adjust as needed)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON prohibited_items TO your_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON restricted_items TO your_user;
-- GRANT USAGE, SELECT ON SEQUENCE prohibited_items_id_seq TO your_user;
-- GRANT USAGE, SELECT ON SEQUENCE restricted_items_id_seq TO your_user;

COMMENT ON TABLE prohibited_items IS 'Items that are prohibited from export under ITC(HS) 2017 Schedule 2';
COMMENT ON TABLE restricted_items IS 'Items that have restrictions on export under ITC(HS) 2017 Schedule 2';
COMMENT ON FUNCTION search_export_items IS 'Search for items by HS code or description across both prohibited and restricted items';
COMMENT ON FUNCTION get_item_by_hs_code IS 'Get exact match for an HS code from either table';
COMMENT ON VIEW all_export_items IS 'Combined view of all prohibited and restricted export items';

-- Success message
SELECT 'Schema created successfully!' as status;