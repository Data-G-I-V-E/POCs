-- =====================================================
-- HS Codes Database - Complete Setup and Data Import
-- =====================================================

-- Drop existing tables if they exist
DROP TABLE IF EXISTS hs_codes CASCADE;
DROP TABLE IF EXISTS chapters CASCADE;

-- =====================================================
-- CREATE TABLES
-- =====================================================

-- Chapters table
CREATE TABLE chapters (
    chapter_number VARCHAR(10) PRIMARY KEY,
    title TEXT NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- HS Codes table
CREATE TABLE hs_codes (
    id SERIAL PRIMARY KEY,
    chapter_number VARCHAR(10) REFERENCES chapters(chapter_number),
    hs_code VARCHAR(10) UNIQUE NOT NULL,
    code_level INTEGER NOT NULL,
    description TEXT NOT NULL,
    parent_code VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX idx_hs_code ON hs_codes(hs_code);
CREATE INDEX idx_chapter ON hs_codes(chapter_number);
CREATE INDEX idx_parent_code ON hs_codes(parent_code);
CREATE INDEX idx_description ON hs_codes USING gin(to_tsvector('english', description));
CREATE INDEX idx_code_level ON hs_codes(code_level);

-- =====================================================
-- INSERT CHAPTER DATA
-- =====================================================

-- Chapter 7
INSERT INTO chapters (chapter_number, title, notes) VALUES 
('07', 'Edible vegetables and certain roots and tubers', 
'Notes. 
1.- This Chapter does not cover forage products of heading 12.14. 
2.- In headings 07.09, 07.10, 07.11 and 07.12 the word "vegetables" includes edible mushrooms, truffles, olives, capers, marrows, pumpkins, aubergines, sweet corn (Zea mays var. saccharata), fruits of the genus Capsicum or of the genus Pimenta, fennel, parsley, chervil, tarragon, cress and sweet marjoram (Majorana hortensis or Origanum majorana). 
3.- Heading 07.12 covers all dried vegetables of the kinds falling in headings 07.01 to 07.11, other than: (a) dried leguminous vegetables, shelled (heading 07.13); (b) sweet corn in the forms specified in headings 11.02 to 11.04; (c) flour, meal, powder, flakes, granules and pellets of potatoes (heading 11.05); (d) flour, meal and powder of the dried leguminous vegetables of heading 07.13 (heading 11.06). 
4.- However, dried or crushed or ground fruits of the genus Capsicum or of the genus Pimenta are excluded from this Chapter (heading 09.04). 
5.- Heading 07.11 applies to vegetables which have been treated solely to ensure their provisional preservation during transport or storage prior to use (for example, by sulphur dioxide gas, in brine, in sulphur water or in other preservative solutions), provided they remain unsuitable for immediate consumption in that state.');

-- Chapter 8
INSERT INTO chapters (chapter_number, title, notes) VALUES 
('08', 'Edible fruit and nuts; peel of citrus fruit or melons', 
'Notes. 
1.- This Chapter does not cover inedible nuts or fruits. 
2.- Chilled fruits and nuts are to be classified in the same headings as the corresponding fresh fruits and nuts. 
3.- Dried fruit or dried nuts of this Chapter may be partially rehydrated, or treated for the following purposes: (a) For additional preservation or stabilisation (for example, by moderate heat treatment, sulphuring, the addition of sorbic acid or potassium sorbate), (b) To improve or maintain their appearance (for example, by the addition of vegetable oil or small quantities of glucose syrup), provided that they retain the character of dried fruit or dried nuts. 
4.- Heading 08.12 applies to fruit and nuts which have been treated solely to ensure their provisional preservation during transport or storage prior to use (for example, by sulphur dioxide gas, in brine, in sulphur water or in other preservative solutions), provided they remain unsuitable for immediate consumption in that state.');

-- Chapter 61
INSERT INTO chapters (chapter_number, title, notes) VALUES 
('61', 'Articles of apparel and clothing accessories, knitted or crocheted', 
'Notes. 
1.- This Chapter applies only to made up knitted or crocheted articles. 
2.- This Chapter does not cover: (a) Goods of heading 62.12; (b) Worn clothing or other worn articles of heading 63.09; or (c) Orthopaedic appliances, surgical belts, trusses or the like (heading 90.21).');

-- Chapter 62
INSERT INTO chapters (chapter_number, title, notes) VALUES 
('62', 'Articles of apparel and clothing accessories, not knitted or crocheted', 
'Notes. 
1.- This Chapter applies only to made up articles of any textile fabric other than wadding, excluding knitted or crocheted articles (other than those of heading 62.12). 
2.- This Chapter does not cover: (a) Worn clothing or other worn articles of heading 63.09; or (b) Orthopaedic appliances, surgical belts, trusses or the like (heading 90.21).');

-- Chapter 85
INSERT INTO chapters (chapter_number, title, notes) VALUES 
('85', 'Electrical machinery and equipment and parts thereof; sound recorders and reproducers, television image and sound recorders and reproducers, and parts and accessories of such articles', 
'Notes. 
1.- This Chapter does not cover: (a) Electrically warmed blankets, bed pads, foot-muffs or the like; electrically warmed clothing, footwear or ear pads or other electrically warmed articles worn on or about the person; (b) Articles of glass of heading 70.11; (c) Machines and apparatus of heading 84.86; (d) Vacuum apparatus of a kind used in medical, surgical, dental or veterinary sciences (heading 90.18); or (e) Electrically heated furniture of Chapter 94.');

-- Chapter 90
INSERT INTO chapters (chapter_number, title, notes) VALUES 
('90', 'Optical, photographic, cinematographic, measuring, checking, precision, medical or surgical instruments and apparatus; parts and accessories thereof', 
'Notes. 
1.- This Chapter does not cover: (a) Articles of a kind used in machines, appliances or for other technical uses, of vulcanised rubber other than hard rubber (heading 40.16), of leather or of composition leather (heading 42.05) or of textile material (heading 59.11); (b) Supporting belts or other support articles of textile material.');

-- =====================================================
-- INSERT HS CODES DATA
-- =====================================================

-- Chapter 7 HS Codes
INSERT INTO hs_codes (chapter_number, hs_code, code_level, description, parent_code) VALUES
('07', '0703', 4, 'Onions, shallots, garlic, leeks and other alliaceous vegetables, fresh or chilled.', NULL),
('07', '070310', 6, 'Onions and shallots', '07.03'),
('07', '0707', 4, 'Cucumbers and gherkins, fresh or chilled', NULL),
('07', '070700', 6, 'Cucumbers and gherkins, fresh or chilled', '07.07'),
('07', '0709', 4, 'Other vegetables, fresh or chilled.', NULL),
('07', '070960', 6, 'Fruits of the genus Capsicum or of the genus Pimenta', '07.09');

-- Chapter 8 HS Codes
INSERT INTO hs_codes (chapter_number, hs_code, code_level, description, parent_code) VALUES
('08', '0803', 4, 'Bananas, including plantains, fresh or dried.', NULL),
('08', '080310', 6, 'Plantains', '08.03'),
('08', '0804', 4, 'Dates, figs, pineapples, avocados, guavas, mangoes and mangosteens, fresh or dried.', NULL),
('08', '080410', 6, 'Dates', '08.04'),
('08', '080450', 6, 'Guavas, mangoes and mangosteens', '08.04');

-- Chapter 61 HS Codes
INSERT INTO hs_codes (chapter_number, hs_code, code_level, description, parent_code) VALUES
('61', '6109', 4, 'T-shirts, singlets and other vests, knitted or crocheted.', NULL),
('61', '610910', 6, 'Of cotton', '61.09'),
('61', '6103', 4, 'Men''s or boys'' suits, ensembles, jackets, blazers, trousers, bib and brace overalls, breeches and shorts (other than swimwear), knitted or crocheted.', NULL),
('61', '610342', 6, 'Of cotton', '61.03'),
('61', '6104', 4, 'Women''s or girls'' suits, ensembles, jackets, blazers, dresses, skirts, divided skirts, trousers, bib and brace overalls, breeches and shorts (other than swimwear), knitted or crocheted.', NULL),
('61', '610442', 6, 'Of cotton', '61.04');

-- Chapter 62 HS Codes
INSERT INTO hs_codes (chapter_number, hs_code, code_level, description, parent_code) VALUES
('62', '6203', 4, 'Men''s or boys'' suits, ensembles, jackets, blazers, trousers, bib and brace overalls, breeches and shorts (other than swimwear)', NULL),
('62', '620342', 6, 'Of cotton', '62.03'),
('62', '6204', 4, 'Women''s or girls'' suits, ensembles, jackets, blazers, dresses, skirts, divided skirts, trousers, bib and brace overalls, breeches and shorts (other than swimwear)', NULL),
('62', '620462', 6, 'Of cotton', '62.04'),
('62', '6205', 4, 'Men''s or boys'' shirts', NULL),
('62', '620520', 6, 'Of cotton', '62.05');

-- Chapter 85 HS Codes
INSERT INTO hs_codes (chapter_number, hs_code, code_level, description, parent_code) VALUES
('85', '8504', 4, 'Electrical transformers, static converters (for example, rectifiers) and inductors.', NULL),
('85', '850440', 6, 'Static converters', '85.04'),
('85', '8513', 4, 'Portable electric lamps designed to function by their own source of energy (for example, dry batteries, accumulators, magnetos), other than lighting equipment of heading 85.12', NULL),
('85', '851310', 6, 'Lamps', '85.13'),
('85', '8517', 4, 'Telephone sets, including smartphones and other telephones for cellular networks or for other wireless networks; other apparatus for the transmission or reception of voice, images or other data, including apparatus for communication in a wired or wireless network (such as a local or wide area network), other than transmission or reception apparatus of heading 84.43, 85.25, 85.27 or 85.28.', NULL),
('85', '851762', 6, 'Machines for the reception, conversion and transmission or regeneration of voice, images or other data, including switching and routing apparatus', '85.17');

-- Chapter 90 HS Codes
INSERT INTO hs_codes (chapter_number, hs_code, code_level, description, parent_code) VALUES
('90', '9026', 4, 'Instruments and apparatus for measuring or checking the flow, level, pressure or other variables of liquids or gases (for example, flow meters, level gauges, manometers, heat meters), excluding instruments and apparatus of heading 90.14, 90.15, 90.28 or 90.32.', NULL),
('90', '902610', 6, 'For measuring or checking the flow or level of liquids', '90.26');

-- =====================================================
-- VERIFY DATA
-- =====================================================

-- Show chapter summary
SELECT 
    c.chapter_number,
    c.title,
    COUNT(h.id) as total_codes,
    SUM(CASE WHEN h.code_level = 4 THEN 1 ELSE 0 END) as headings_4digit,
    SUM(CASE WHEN h.code_level = 6 THEN 1 ELSE 0 END) as codes_6digit
FROM chapters c
LEFT JOIN hs_codes h ON c.chapter_number = h.chapter_number
GROUP BY c.chapter_number, c.title
ORDER BY c.chapter_number;

-- Show all HS codes organized by chapter
SELECT 
    h.chapter_number,
    h.hs_code,
    h.code_level,
    h.description,
    h.parent_code
FROM hs_codes h
ORDER BY h.chapter_number, h.hs_code;