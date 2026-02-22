-- =====================================================
-- ITC HS Code Database Schema
-- Updated to avoid conflicts with existing hs_codes table
-- =====================================================

-- 1. Chapter Master Table
CREATE TABLE IF NOT EXISTS itc_chapters (
    chapter_code VARCHAR(2) PRIMARY KEY,
    chapter_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Chapter Notes (Main Notes, Policy Conditions, Export Licensing Notes)
CREATE TABLE IF NOT EXISTS itc_chapter_notes (
    id SERIAL PRIMARY KEY,
    chapter_code VARCHAR(2) REFERENCES itc_chapters(chapter_code) ON DELETE CASCADE,
    note_type VARCHAR(50) NOT NULL, -- 'main_note', 'policy_condition', 'export_licensing'
    sl_no INTEGER,
    note_text TEXT NOT NULL,
    notification_no VARCHAR(50),
    notification_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. ITC HS Code Products (Main table for HS codes from ITC notifications)
CREATE TABLE IF NOT EXISTS itc_hs_products (
    id SERIAL PRIMARY KEY,
    chapter_code VARCHAR(2) REFERENCES itc_chapters(chapter_code),
    hs_code VARCHAR(10) UNIQUE NOT NULL,
    description TEXT,
    export_policy VARCHAR(50), -- 'Free', 'Prohibited', 'Restricted', etc.
    parent_hs_code VARCHAR(10), -- For hierarchical structure (e.g., 0701 is parent of 07011000)
    level INTEGER, -- 2-digit (chapter), 4-digit, 6-digit, 8-digit, 10-digit
    notification_no VARCHAR(50),
    notification_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Policy Conditions Referenced by HS Codes
CREATE TABLE IF NOT EXISTS itc_hs_policy_references (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) NOT NULL,
    policy_reference TEXT NOT NULL, -- 'Policy Condition 1 of the Chapter', etc.
    chapter_code VARCHAR(2) NOT NULL,
    notification_no VARCHAR(50),
    notification_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hs_code) REFERENCES itc_hs_products(hs_code) ON DELETE CASCADE,
    FOREIGN KEY (chapter_code) REFERENCES itc_chapters(chapter_code) ON DELETE CASCADE
);

-- 5. Chapter-wise Policy Definitions (stores actual policy text)
-- This links to your existing policies in the database
CREATE TABLE IF NOT EXISTS itc_chapter_policies (
    id SERIAL PRIMARY KEY,
    chapter_code VARCHAR(2) REFERENCES itc_chapters(chapter_code) ON DELETE CASCADE,
    policy_type VARCHAR(100) NOT NULL, -- 'Policy Condition 1', 'Export Licensing Note 1', etc.
    policy_text TEXT NOT NULL,
    notification_no VARCHAR(50),
    notification_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chapter_code, policy_type)
);

-- =====================================================
-- INDEXES for Query Performance
-- =====================================================

-- Index on hs_code for fast lookups
CREATE INDEX idx_itc_hs_products_code ON itc_hs_products(hs_code);

-- Index on chapter for filtering by chapter
CREATE INDEX idx_itc_hs_products_chapter ON itc_hs_products(chapter_code);

-- Index on export policy for filtering restricted items
CREATE INDEX idx_itc_hs_products_policy ON itc_hs_products(export_policy);

-- Index on parent_hs_code for hierarchy queries
CREATE INDEX idx_itc_hs_products_parent ON itc_hs_products(parent_hs_code);

-- Index on level for filtering by HS code depth
CREATE INDEX idx_itc_hs_products_level ON itc_hs_products(level);

-- Composite index for policy references
CREATE INDEX idx_itc_policy_refs_hs ON itc_hs_policy_references(hs_code);
CREATE INDEX idx_itc_policy_refs_chapter ON itc_hs_policy_references(chapter_code);

-- Composite index for chapter policies lookup
CREATE INDEX idx_itc_chapter_policies_lookup ON itc_chapter_policies(chapter_code, policy_type);

-- Index on chapter notes
CREATE INDEX idx_itc_chapter_notes_chapter ON itc_chapter_notes(chapter_code);
CREATE INDEX idx_itc_chapter_notes_type ON itc_chapter_notes(note_type);

-- =====================================================
-- SAMPLE DATA for Chapter 07
-- =====================================================

-- Insert Chapter 07
INSERT INTO itc_chapters (chapter_code, chapter_name) 
VALUES ('07', 'Edible Vegetables And Certain Roots And Tubers')
ON CONFLICT (chapter_code) DO NOTHING;

-- Insert Chapter Notes
INSERT INTO itc_chapter_notes (chapter_code, note_type, sl_no, note_text) VALUES
('07', 'main_note', 1, 'This Chapter does not cover forage products of heading 1214.'),
('07', 'main_note', 2, 'In headings 0709, 0710, 0711 and 0712, the word "vegetables" includes edible mushrooms, truffles, olives, capers, marrows, pumpkins, aubergines, sweet corn (Zea mays var. saccharata), fruits of the genus Capsicum or of the genus Pimenta, fennel, parsley, chervil, tarragon, cress and sweet marjoram (Majorana hortensis or Origanum majorana).'),
('07', 'main_note', 3, 'Heading 0712 covers all dried vegetables of the kinds falling in headings 0701 to 0711, other than: (a) dried leguminous vegetables, shelled (heading 0713); (b) sweet corn in the forms specified in headings 1102 to 1104; (c) flour, meal, powder, flakes, granules and pellets of potatoes (heading 1105); (d) flour, meal and powder of the dried leguminous vegetables of heading 0713 (heading 1106).'),
('07', 'main_note', 4, 'However, dried or crushed or ground fruits of the genus Capsicum or of the genus Pimenta are excluded from this Chapter (heading 0904).'),
('07', 'main_note', 5, 'Heading 0711 applies to vegetables which have been treated solely to ensure their provisional preservation during transport or storage prior to use (for example, by sulphur dioxide gas, in brine, in sulphur water or in other preservative solutions), provided they remain unsuitable for immediate consumption in that state.')
ON CONFLICT DO NOTHING;

-- Insert Policy Condition
INSERT INTO itc_chapter_notes (chapter_code, note_type, sl_no, note_text) VALUES
('07', 'policy_condition', 1, 'Export shall be through Custom EDI ports. However, export through the non-EDI Land Custom Stations (LCS) on Indo-Bangladesh and Indo-Nepal border shall also be allowed subject to registration of quantity with DGFT.')
ON CONFLICT DO NOTHING;

-- Insert Export Licensing Notes
INSERT INTO itc_chapter_notes (chapter_code, note_type, sl_no, note_text, notification_no, notification_date) VALUES
('07', 'export_licensing', 1, 'Reference to onions in this chapter includes onions fresh or chilled frozen, provisionally preserved or dried.', NULL, NULL),
('07', 'export_licensing', 2, 'Export of Organic pulses and lentils shall be subject to the following conditions: (a) It should be duly certified by APEDA as being organic pulses and lentils; (b) Export contracts should be registered with APEDA, New Delhi prior to shipment; (c) Exports shall be allowed only from Customs EDI Ports.', '78/2009-2024, 03/2015-20', '2017-04-19')
ON CONFLICT DO NOTHING;

-- Insert Chapter Policy Definition
INSERT INTO itc_chapter_policies (chapter_code, policy_type, policy_text) VALUES
('07', 'Policy Condition 1', 'Export shall be through Custom EDI ports. However, export through the non-EDI Land Custom Stations (LCS) on Indo-Bangladesh and Indo-Nepal border shall also be allowed subject to registration of quantity with DGFT.')
ON CONFLICT (chapter_code, policy_type) DO NOTHING;

-- Sample HS Code Products from Chapter 07
INSERT INTO itc_hs_products (chapter_code, hs_code, description, export_policy, parent_hs_code, level) VALUES
('07', '0701', 'Potatoes, fresh or chilled', NULL, NULL, 4),
('07', '07011000', 'Seed', 'Free', '0701', 8),
('07', '07019000', 'Other', 'Free', '0701', 8),
('07', '07020000', 'Tomatoes, fresh or chilled', 'Free', NULL, 8),
('07', '0703', 'Onions, shallots, garlic, leeks and other alliaceous vegetables, fresh or chilled', NULL, NULL, 4),
('07', '070310', 'Onions and shallots', NULL, '0703', 6),
('07', '07031011', 'Onions: Rose onion', 'Free', '070310', 8),
('07', '07031019', 'Onions: Other', 'Free', '070310', 8),
('07', '07031020', 'Shallots', 'Free', '070310', 8),
('07', '07032000', 'Garlic', 'Free', '0703', 8)
ON CONFLICT (hs_code) DO UPDATE SET
    description = EXCLUDED.description,
    export_policy = EXCLUDED.export_policy,
    updated_at = CURRENT_TIMESTAMP;

-- Sample HS Codes with Policy References (from dried leguminous vegetables section)
INSERT INTO itc_hs_products (chapter_code, hs_code, description, export_policy, parent_hs_code, level, notification_no, notification_date) VALUES
('07', '0713', 'Dried leguminous vegetables, shelled, whether or not skinned or split', NULL, NULL, 4, NULL, NULL),
('07', '071310', 'Peas (Pisum sativum)', NULL, '0713', 6, NULL, NULL),
('07', '07131010', 'Yellow peas', 'Free', '071310', 8, '38/2015-20', '2017-11-22'),
('07', '07131020', 'Green peas', 'Free', '071310', 8, '38/2015-20', '2017-11-22'),
('07', '071320', 'Chickpeas (garbanzos)', NULL, '0713', 6, '38/2015-20', '2017-11-22'),
('07', '07132010', 'Kabuli chana', 'Free', '071320', 8, '38/2015-20', '2017-11-22'),
('07', '07132020', 'Bengal gram (desi chana)', 'Free', '071320', 8, '38/2015-20', '2017-11-22')
ON CONFLICT (hs_code) DO UPDATE SET
    description = EXCLUDED.description,
    export_policy = EXCLUDED.export_policy,
    notification_no = EXCLUDED.notification_no,
    notification_date = EXCLUDED.notification_date,
    updated_at = CURRENT_TIMESTAMP;

-- Insert Policy References for the HS codes that have "Subject to Policy Condition 1 of the Chapter"
INSERT INTO itc_hs_policy_references (hs_code, policy_reference, chapter_code, notification_no, notification_date) VALUES
('07131010', 'Policy Condition 1', '07', '38/2015-20', '2017-11-22'),
('07131020', 'Policy Condition 1', '07', '38/2015-20', '2017-11-22'),
('07132010', 'Policy Condition 1', '07', '38/2015-20', '2017-11-22'),
('07132020', 'Policy Condition 1', '07', '38/2015-20', '2017-11-22')
ON CONFLICT DO NOTHING;

-- =====================================================
-- USEFUL QUERIES
-- =====================================================

-- Query 1: Get all information for a specific HS code
-- SELECT * FROM itc_hs_products WHERE hs_code = '07131010';

-- Query 2: Get HS code with its policy conditions
/*
SELECT 
    hp.hs_code,
    hp.description,
    hp.export_policy,
    pr.policy_reference,
    cp.policy_text
FROM itc_hs_products hp
LEFT JOIN itc_hs_policy_references pr ON hp.hs_code = pr.hs_code
LEFT JOIN itc_chapter_policies cp ON pr.chapter_code = cp.chapter_code 
    AND pr.policy_reference = cp.policy_type
WHERE hp.hs_code = '07131010';
*/

-- Query 3: Get all chapter notes for a chapter
-- SELECT * FROM itc_chapter_notes WHERE chapter_code = '07' ORDER BY note_type, sl_no;

-- Query 4: Find all HS codes with restrictions (not Free)
-- SELECT * FROM itc_hs_products WHERE export_policy != 'Free' AND export_policy IS NOT NULL;

-- Query 5: Get all HS codes that reference chapter policies
/*
SELECT DISTINCT
    hp.hs_code,
    hp.description,
    pr.policy_reference
FROM itc_hs_products hp
INNER JOIN itc_hs_policy_references pr ON hp.hs_code = pr.hs_code
WHERE hp.chapter_code = '07';
*/