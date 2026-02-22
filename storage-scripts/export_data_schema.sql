-- =====================================================
-- HS CODES EXPORT DATA - DATABASE SCHEMA
-- =====================================================

-- This extends the existing hs_codes database with export statistics

-- =====================================================
-- CREATE NEW TABLES FOR EXPORT DATA
-- =====================================================

-- Countries/Destination table
CREATE TABLE IF NOT EXISTS countries (
    country_code VARCHAR(10) PRIMARY KEY,
    country_name VARCHAR(100) NOT NULL,
    region VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Financial years table
CREATE TABLE IF NOT EXISTS financial_years (
    year_id SERIAL PRIMARY KEY,
    year_label VARCHAR(20) UNIQUE NOT NULL,  -- e.g., '2023-2024', '2024-2025'
    start_year INTEGER,
    end_year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Export statistics table (main data table)
CREATE TABLE IF NOT EXISTS export_statistics (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) NOT NULL REFERENCES hs_codes(hs_code),
    country_code VARCHAR(10) NOT NULL REFERENCES countries(country_code),
    year_label VARCHAR(20) NOT NULL REFERENCES financial_years(year_label),
    export_value_crore DECIMAL(15, 2),  -- Value in ₹ Crore
    serial_number INTEGER,  -- S.No. from source
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hs_code, country_code, year_label)  -- Prevent duplicates
);

-- Growth statistics table (denormalized for performance)
CREATE TABLE IF NOT EXISTS export_growth (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) NOT NULL REFERENCES hs_codes(hs_code),
    country_code VARCHAR(10) NOT NULL REFERENCES countries(country_code),
    from_year VARCHAR(20) NOT NULL,
    to_year VARCHAR(20) NOT NULL,
    growth_percentage DECIMAL(10, 2),
    from_value DECIMAL(15, 2),
    to_value DECIMAL(15, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hs_code, country_code, from_year, to_year)
);

-- Country total exports table (aggregated totals per country)
CREATE TABLE IF NOT EXISTS country_total_exports (
    id SERIAL PRIMARY KEY,
    country_code VARCHAR(10) NOT NULL REFERENCES countries(country_code),
    year_label VARCHAR(20) NOT NULL REFERENCES financial_years(year_label),
    total_export_value_crore DECIMAL(15, 2),  -- Total value in ₹ Crore
    growth_percentage DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(country_code, year_label)  -- One total per country per year
);

-- Metadata table to track data imports
CREATE TABLE IF NOT EXISTS import_metadata (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10),
    country_code VARCHAR(10),
    source_file VARCHAR(255),
    import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    record_count INTEGER,
    status VARCHAR(50)
);

-- =====================================================
-- CREATE INDEXES
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_export_stats_hs_code ON export_statistics(hs_code);
CREATE INDEX IF NOT EXISTS idx_export_stats_country ON export_statistics(country_code);
CREATE INDEX IF NOT EXISTS idx_export_stats_year ON export_statistics(year_label);
CREATE INDEX IF NOT EXISTS idx_export_stats_composite ON export_statistics(hs_code, country_code, year_label);

CREATE INDEX IF NOT EXISTS idx_export_growth_hs_code ON export_growth(hs_code);
CREATE INDEX IF NOT EXISTS idx_export_growth_country ON export_growth(country_code);
CREATE INDEX IF NOT EXISTS idx_export_growth_composite ON export_growth(hs_code, country_code);

CREATE INDEX IF NOT EXISTS idx_country_total_exports_country ON country_total_exports(country_code);
CREATE INDEX IF NOT EXISTS idx_country_total_exports_year ON country_total_exports(year_label);
CREATE INDEX IF NOT EXISTS idx_country_total_exports_composite ON country_total_exports(country_code, year_label);

-- =====================================================
-- INSERT REFERENCE DATA
-- =====================================================

-- Insert countries
INSERT INTO countries (country_code, country_name, region) VALUES
('AUS', 'Australia', 'Oceania'),
('UAE', 'United Arab Emirates', 'Middle East'),
('GBR', 'United Kingdom', 'Europe')
ON CONFLICT (country_code) DO NOTHING;

-- Insert financial years
INSERT INTO financial_years (year_label, start_year, end_year) VALUES
('2023-2024', 2023, 2024),
('2024-2025', 2024, 2025),
('2022-2023', 2022, 2023),
('2021-2022', 2021, 2022)
ON CONFLICT (year_label) DO NOTHING;

-- =====================================================
-- CREATE USEFUL VIEWS
-- =====================================================

-- View: Complete export data with commodity names
CREATE OR REPLACE VIEW v_export_data_complete AS
SELECT 
    es.id,
    es.hs_code,
    hc.description as commodity,
    hc.chapter_number,
    c.title as chapter_title,
    es.country_code,
    co.country_name,
    es.year_label,
    es.export_value_crore,
    es.serial_number
FROM export_statistics es
JOIN hs_codes hc ON es.hs_code = hc.hs_code
JOIN chapters c ON hc.chapter_number = c.chapter_number
JOIN countries co ON es.country_code = co.country_code
ORDER BY es.hs_code, es.country_code, es.year_label;

-- View: Year-over-year comparison
CREATE OR REPLACE VIEW v_export_yoy_comparison AS
SELECT 
    es1.hs_code,
    hc.description as commodity,
    es1.country_code,
    co.country_name,
    es1.year_label as year1,
    es1.export_value_crore as value1,
    es2.year_label as year2,
    es2.export_value_crore as value2,
    ROUND(((es2.export_value_crore - es1.export_value_crore) / 
           NULLIF(es1.export_value_crore, 0) * 100), 2) as growth_percentage
FROM export_statistics es1
JOIN export_statistics es2 
    ON es1.hs_code = es2.hs_code 
    AND es1.country_code = es2.country_code
JOIN hs_codes hc ON es1.hs_code = hc.hs_code
JOIN countries co ON es1.country_code = co.country_code
WHERE es1.year_label = '2023-2024' 
  AND es2.year_label = '2024-2025';

-- View: Top exporters by HS code
CREATE OR REPLACE VIEW v_top_export_by_hs AS
SELECT 
    es.hs_code,
    hc.description as commodity,
    es.year_label,
    es.country_code,
    co.country_name,
    es.export_value_crore,
    RANK() OVER (PARTITION BY es.hs_code, es.year_label 
                 ORDER BY es.export_value_crore DESC) as rank
FROM export_statistics es
JOIN hs_codes hc ON es.hs_code = hc.hs_code
JOIN countries co ON es.country_code = co.country_code;

-- View: Country-wise summary
CREATE OR REPLACE VIEW v_export_country_summary AS
SELECT 
    es.country_code,
    co.country_name,
    es.year_label,
    COUNT(DISTINCT es.hs_code) as num_products,
    SUM(es.export_value_crore) as total_exports,
    AVG(es.export_value_crore) as avg_export_per_product,
    MAX(es.export_value_crore) as max_export,
    MIN(es.export_value_crore) as min_export
FROM export_statistics es
JOIN countries co ON es.country_code = co.country_code
GROUP BY es.country_code, co.country_name, es.year_label
ORDER BY es.country_code, es.year_label;

-- =====================================================
-- CREATE FUNCTIONS
-- =====================================================

-- Function to calculate growth percentage
CREATE OR REPLACE FUNCTION calculate_growth(
    old_value DECIMAL,
    new_value DECIMAL
) RETURNS DECIMAL AS $$
BEGIN
    IF old_value IS NULL OR old_value = 0 THEN
        RETURN NULL;
    END IF;
    RETURN ROUND(((new_value - old_value) / old_value * 100), 2);
END;
$$ LANGUAGE plpgsql;

-- Function to get export trend for a specific HS code
CREATE OR REPLACE FUNCTION get_export_trend(
    p_hs_code VARCHAR,
    p_country_code VARCHAR DEFAULT NULL
) RETURNS TABLE (
    year_label VARCHAR,
    country_code VARCHAR,
    country_name VARCHAR,
    export_value DECIMAL,
    yoy_growth DECIMAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        es.year_label,
        es.country_code,
        co.country_name,
        es.export_value_crore,
        calculate_growth(
            LAG(es.export_value_crore) OVER (
                PARTITION BY es.country_code 
                ORDER BY es.year_label
            ),
            es.export_value_crore
        ) as yoy_growth
    FROM export_statistics es
    JOIN countries co ON es.country_code = co.country_code
    WHERE es.hs_code = p_hs_code
      AND (p_country_code IS NULL OR es.country_code = p_country_code)
    ORDER BY es.country_code, es.year_label;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- SAMPLE DATA (from your Excel files)
-- =====================================================

-- Insert sample export statistics for demonstration
-- In practice, you'll use the Python import script

-- Example: 070310 (Onions and Shallots) - Australia
INSERT INTO export_statistics (hs_code, country_code, year_label, export_value_crore, serial_number)
VALUES 
    ('070310', 'AUS', '2023-2024', 0.37, 50),
    ('070310', 'AUS', '2024-2025', 0.91, 50)
ON CONFLICT (hs_code, country_code, year_label) DO UPDATE
SET export_value_crore = EXCLUDED.export_value_crore,
    serial_number = EXCLUDED.serial_number,
    updated_at = CURRENT_TIMESTAMP;

-- Insert growth data
INSERT INTO export_growth (hs_code, country_code, from_year, to_year, growth_percentage, from_value, to_value)
VALUES 
    ('070310', 'AUS', '2023-2024', '2024-2025', 147.02, 0.37, 0.91)
ON CONFLICT (hs_code, country_code, from_year, to_year) DO UPDATE
SET growth_percentage = EXCLUDED.growth_percentage,
    from_value = EXCLUDED.from_value,
    to_value = EXCLUDED.to_value;

-- Example: 070700 (Cucumbers and Gherkins) - Australia
INSERT INTO export_statistics (hs_code, country_code, year_label, export_value_crore, serial_number)
VALUES 
    ('070700', 'AUS', '2023-2024', 0.00, 55),
    ('070700', 'AUS', '2024-2025', 0.02, 55)
ON CONFLICT (hs_code, country_code, year_label) DO UPDATE
SET export_value_crore = EXCLUDED.export_value_crore,
    serial_number = EXCLUDED.serial_number,
    updated_at = CURRENT_TIMESTAMP;

-- =====================================================
-- VERIFICATION QUERIES
-- =====================================================

-- Check tables
SELECT 'Countries' as table_name, COUNT(*) as count FROM countries
UNION ALL
SELECT 'Financial Years', COUNT(*) FROM financial_years
UNION ALL
SELECT 'Export Statistics', COUNT(*) FROM export_statistics
UNION ALL
SELECT 'Export Growth', COUNT(*) FROM export_growth;

-- Show sample export data
SELECT * FROM v_export_data_complete ORDER BY hs_code, country_code, year_label LIMIT 10;

-- Show year-over-year comparison
SELECT * FROM v_export_yoy_comparison LIMIT 10;

COMMIT;