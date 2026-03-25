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

-- =====================================================
-- SEED DATA: Prohibited Items from ITC(HS) 2017 Schedule 2
-- =====================================================

INSERT INTO prohibited_items (hs_code, description, export_policy, policy_condition) VALUES
('01063100', 'Birds: -- Birds of prey', 'Prohibited', ''),
('01063200', 'Birds: -- Psittaciformes(including parrots, parakeets,macaws and cockatoos)', 'Prohibited', 'Subject to Policy Condition 3 of the Chapter'),
('01063300', 'Birds: -- Ostriches; emus (Dromaius novaehollandiae)', 'Prohibited', 'Subject to Policy Condition 3 of the Chapter'),
('01063900', 'Birds: -- Other', 'Prohibited', 'Subject to Policy Condition 3 of the Chapter'),
('02011000', 'Carcasses and halfcarcasses', 'Prohibited', ''),
('02012000', 'Other cuts with bone in', 'Prohibited', ''),
('02013000', 'Boneless', 'Prohibited', 'However, export of Boneless meat of buffalo (both male and female) fresh and chilled is free subject to conditions.'),
('02021000', 'Carcasses and halfcarcasses', 'Prohibited', ''),
('02022000', 'Other cuts with bone in', 'Prohibited', ''),
('02023000', 'Boneless', 'Prohibited', 'However, export of Boneless meat of buffalo (both male and female) fresh and chilled is free subject to conditions.'),
('02061000', 'Of bovine animals, fresh or chilled', 'Prohibited', 'Beef in the form of offal of cows, oxen and calf is not permitted. Exports of offal of buffalo except gonads and reproductive organs is free subject to conditions.'),
('02062100', 'Of bovine animals, frozen : -- Tongues', 'Prohibited', 'Beef in the form of offal of cows, oxen and calf is not permitted. Exports of offal of buffalo except gonads and reproductive organs is free subject to conditions.'),
('02062200', 'Of bovine animals, frozen : -- Livers', 'Prohibited', 'Beef in the form of offal of cows, oxen and calf is not permitted. Exports of offal of buffalo except gonads and reproductive organs is free subject to conditions.'),
('02062900', 'Of bovine animals, frozen : -- Other', 'Prohibited', 'Beef in the form of offal of cows, oxen and calf is not permitted. Exports of offal of buffalo except gonads and reproductive organs is free subject to conditions.'),
('02102000', 'Meat of bovine animals', 'Prohibited', 'Beef in the form of offal of cows, oxen and calf is Prohibited. Exports of offal of buffalo except gonads and reproductive organs is free subject to conditions.'),
('03029200', 'Shark fins', 'Prohibited', ''),
('03039200', 'Shark fins', 'Prohibited', ''),
('03057100', 'Fish fins, heads, tails, maws and other edible fish offal:--Shark fins', 'Prohibited', ''),
('05010010', 'Human hair unworked,whether or not washed or scoured', 'Prohibited', 'However, export is Free if FOB value is US Dollar 65 or above per Kilogram.'),
('05010020', 'Waste of human hair', 'Prohibited', 'However, export is Free if FOB value is US Dollar 65 or above per Kilogram.'),
('05059010', 'Peacock tail and wing feather (trimmed or not)', 'Prohibited', ''),
('05061041', 'Bones, horn cones and parts thereof, not crushed: ---- Of wild animals', 'Prohibited', ''),
('05079040', 'Antlers', 'Prohibited', ''),
('05080050', 'Shells', 'Prohibited', 'Export of Sea shells, including polished sea shells and handicrafts made out of those species included in the Schedules of the Wild Life (Protection) Act, 1972 is not permitted.'),
('10011900', 'Durum wheat : -- Other', 'Prohibited', ''),
('10019100', 'Other : -- Seed', 'Prohibited', ''),
('10019910', 'Wheat', 'Prohibited', ''),
('10019920', 'Meslin', 'Prohibited', 'However, export of Meslin of seed quality is Free subject to conditions including seed dealer license and chemical treatment declaration.'),
('11010000', 'Wheat or meslin flour.', 'Prohibited', 'However, export of Wheat Flour (Atta) will be allowed against Advance Authorisation, and by EOUs and units in SEZs.'),
('12119051', 'Whole Plant, Aerial Part, Stem, Shoot and Wood :---- Sandalwood chips and dust', 'Prohibited', 'Export of Sandalwood in any form is prohibited. However, Export of Finished Handicraft products of Sandalwood and Machine finished sandalwood products is Free.'),
('14011000', 'Bamboos', 'Prohibited', 'Export of Bamboo products made from bamboo obtained from legal source is free subject to Certificate of Origin conditions.'),
('15011000', 'Lard', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15012000', 'Other pig fat', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15019000', 'Other', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15021010', 'Mutton tallow', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15021090', 'Other', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter. However, Export of Buffalo Tallow is free subject to conditions.'),
('15029010', 'Unrendered fats', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15029020', 'Rendered fats or solvent extraction fats', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15029090', 'Other', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15030000', 'Lard Stearin, Lard Oil, Oleostearin, Oleo-Oil and Tallow Oil, not emulsified or mixed or otherwise prepared', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15050010', 'Wool alcohol (including lanolin alcohol)', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15050020', 'Wool grease, crude', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15050090', 'Other', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter. Export of Lanolin is free subject to conditions.'),
('15060010', 'Neats Foot oil and fats from bone or waste', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('15060090', 'Other', 'Prohibited', 'Subject to Policy Condition 01 of the Chapter.'),
('16041800', 'Fish, whole or in pieces, but not minced : -- Shark fins', 'Prohibited', ''),
('41032000', 'Of reptiles', 'Prohibited', ''),
('41064000', 'Of reptiles', 'Prohibited', ''),
('41133000', 'Of reptiles', 'Prohibited', ''),
('43011000', 'Of mink, whole, with or without head, tail or paws', 'Prohibited', ''),
('43016000', 'Of fox, whole, with or without head, tail or paws', 'Prohibited', ''),
('43021940', 'Tiger-Cat skins', 'Prohibited', ''),
('43031010', 'Articles of apparel and clothing accessories: ---- Of wild animals covered under the Wild Life (Protection) Act,1972', 'Prohibited', ''),
('43031020', 'Articles of apparel and clothing accessories: ---- Of animals covered under CITES', 'Prohibited', ''),
('43039010', 'Of wild animals covered under the Wild Life (Protection) Act,1972', 'Prohibited', ''),
('43039020', 'Of animals covered under CITES', 'Prohibited', ''),
('44011110', 'In logs', 'Prohibited', 'Export of Wood and wood products in the form of logs, timber, stumps, roots, bark, chips, powder, flakes, dust, and charcoal is not permitted.'),
('44011190', 'Other', 'Prohibited', 'Export of Fuel wood in logs, billets, twigs, faggots; Wood in chips or particles; Sawdust and wood waste and scrap is not permitted.'),
('44011210', 'In logs', 'Prohibited', 'Export of Fuel wood in logs, billets, twigs, faggots; Wood in chips or particles; Sawdust and wood waste and scrap is not permitted.'),
('44011290', 'Other', 'Prohibited', 'Export of Fuel wood in logs, billets, twigs, faggots; Wood in chips or particles; Sawdust and wood waste and scrap is not permitted.'),
('44013100', 'Sawdust and wood waste and scrap, agglomerated : -- Wood pellets', 'Prohibited', 'Export of Wood and wood products in the form of logs, timber, stumps, roots, bark, chips, powder, flakes, dust, and charcoal is not permitted.'),
('44013900', 'Sawdust and wood waste and scrap, agglomerated : -- Other', 'Prohibited', 'Export of Wood and wood products in the form of logs, timber, stumps, roots, bark, chips, powder, flakes, dust, and charcoal is not permitted.'),
('44022090', 'Other', 'Prohibited', 'Export of Wood charcoal, whether or not agglomerated is Prohibited. This Prohibition will not apply to Bhutan.'),
('44039922', 'Sal, Sandalwood, Semul, Walnut wood, Anjam, Sisso and White cedar: ---- Sandal wood', 'Prohibited', 'Subject to Policy Condition 5 of this Chapter.'),
('44071100', 'Coniferous : -- Of pine (Pinus spp)', 'Prohibited', 'Certain Export items are permitted as per Policy condition 4 of this Chapter.'),
('44071910', 'Douglas fir (Pseudotsuga menziesii)', 'Prohibited', 'Certain Exports are permitted as per Policy condition 4 of this Chapter.'),
('44071990', 'Other', 'Prohibited', 'Certain Exports are permitted as per Policy condition 4 of this Chapter.'),
('44072900', 'Other', 'Prohibited', 'Certain Exports are permitted as per Policy condition 4 of this Chapter.'),
('44079600', 'Other : -- Of birch (Betula spp.)', 'Prohibited', 'Certain Exports are permitted as per Policy condition 4 of this Chapter.'),
('44079920', 'Willow', 'Prohibited', 'Certain Exports are permitted as per Policy condition 4 of this Chapter.'),
('47010000', 'Mechanical wood pulp.', 'Prohibited', ''),
('47020000', 'Chemical wood pulp, dissolving grades.', 'Prohibited', ''),
('47031100', 'Unbleached : -- Coniferous', 'Prohibited', ''),
('47031900', 'Unbleached : -- Non- coniferous', 'Prohibited', ''),
('47032100', 'Semi-bleached or bleached : -- Coniferous', 'Prohibited', ''),
('47032900', 'Semi-bleached or bleached : -- Non-coniferous', 'Prohibited', ''),
('47041100', 'Unbleached : -- Coniferous', 'Prohibited', ''),
('47041900', 'Unbleached : -- Non- coniferous', 'Prohibited', ''),
('47042100', 'Semi-bleached or bleached : -- Coniferous', 'Prohibited', ''),
('47042900', 'Semi-bleached or bleached : -- Non-coniferous', 'Prohibited', ''),
('47050000', 'Wood pulp obtained by a combination of mechanical and chemical pulping processes.', 'Prohibited', ''),
('47061000', 'Cotton linters pulp', 'Prohibited', ''),
('47062000', 'Pulps of fibres derived from recovered (waste and scrap) paper or', 'Prohibited', ''),
('47063000', 'other, of bamboo', 'Prohibited', ''),
('47069100', 'Other : -- Mechanical', 'Prohibited', ''),
('47069200', 'Other : -- Chemical', 'Prohibited', ''),
('47069300', 'Other : -- Obtained by a combination of mechanical and chemical processes', 'Prohibited', ''),
('47071000', 'Unbleached kraft paper or paperboard or corrugated paper or paperboard', 'Prohibited', ''),
('47072000', 'Other paper or paperboard made mainly of bleached chemical pulp, not coloured in the mass', 'Prohibited', ''),
('47073000', 'Paper or paperboard made mainly of mechanical pulp', 'Prohibited', ''),
('47079000', 'Other, including unsorted waste and scrap', 'Prohibited', ''),
('85434000', 'Electronic cigarettes and similar personal electric vaporising devices', 'Prohibited', 'Export of Electronic Cigarettes including all forms of Electronic Nicotine Delivery Systems, Heat not burn products, e-hookah and the like devices is not permitted.'),
('96011000', 'Worked ivory and articles of ivory', 'Prohibited', '')
ON CONFLICT (hs_code) DO UPDATE SET
    description = EXCLUDED.description,
    export_policy = EXCLUDED.export_policy,
    policy_condition = EXCLUDED.policy_condition,
    updated_at = CURRENT_TIMESTAMP;

-- =====================================================
-- SEED DATA: Restricted Items from ITC(HS) 2017 Schedule 2
-- =====================================================

INSERT INTO restricted_items (hs_code, description, export_policy, policy_condition) VALUES
('01012100', 'Horses : -- Pure-bred breeding animals', 'Restricted', 'Subject to Policy Condition 2 of the Chapter'),
('01012910', 'Horses for Polo', 'Restricted', 'Subject to Policy Condition 2 of the Chapter'),
('01012990', 'Other', 'Restricted', 'Subject to Policy Condition 2 of the Chapter'),
('01019090', 'Other', 'Restricted', ''),
('01022110', 'Bulls', 'Restricted', ''),
('01022120', 'Cows', 'Restricted', ''),
('01022910', 'Bulls', 'Restricted', ''),
('01022990', 'Other, including calves', 'Restricted', ''),
('01023100', 'Buffalo : -- Pure-bred breeding animals', 'Restricted', ''),
('01023900', 'Buffalo : -- Other', 'Restricted', ''),
('01029010', 'Pure-bred breeding animals', 'Restricted', ''),
('01029090', 'Other', 'Restricted', ''),
('01061300', 'Mammals: -- Camels and other camelids (Camelidae)', 'Restricted', ''),
('05111000', 'Bovine semen', 'Restricted', ''),
('05119190', 'Other', 'Restricted', ''),
('05119991', 'Other: ---- Frozen semen, other than bovine :bovine embryo:', 'Restricted', 'Export of Gonads and other reproductive organs of buffaloes & Germplasm of Cattle and buffaloes is restricted.'),
('06022010', 'Edible fruit or nut trees, grafted or not', 'Restricted', 'Exports of Cashew seeds and plants is restricted.'),
('10061010', 'Of seed quality', 'Restricted', 'Export permitted under Restricted Export Authorization subject to seed dealer license and chemical treatment declaration conditions.'),
('10061090', 'Other', 'Restricted', ''),
('12099130', 'Of Onion', 'Restricted', ''),
('12119012', 'Seeds, Kernel, Aril, Fruit, Pericarp :---- Nux vomica, dried ripe seeds', 'Restricted', ''),
('12119014', 'Seeds, Kernel, Aril, Fruit, Pericarp :---- Neem seed', 'Restricted', ''),
('12119054', 'Whole Plant, Aerial Part, Stem, Shoot and Wood :---- Agarwood', 'Restricted', 'The annual limits for export of Agarwood (Aquilaria Malaccensis) Chips and Powder from artificially propagated sources has been fixed for 2024-25 to 2026-27.'),
('12122910', 'Seaweeds', 'Restricted', ''),
('12122990', 'Other algae', 'Restricted', 'Exports of Sea weeds of all types, including G-edulis but excluding brown seaweeds and agarophytes of Tamil Nadu Coast origin in processed form is restricted.'),
('12130000', 'Cereal straw and husks, unprepared, whether or not chopped, ground, pressed or in the form of pellets.', 'Restricted', 'The export of Fodder, including wheat, rice straw is Restricted. Agri residue based Biomass and Briquettes/Pellets under ITC-HS Heading 1213 will be under Free category.'),
('12141000', 'Lucerne (alfalfa) meal and pellets', 'Restricted', ''),
('12149000', 'Other', 'Restricted', ''),
('15149120', 'Mustard oil', 'Restricted', 'Export of mustard oil under branded consumer packs of upto 5 Kgs will continue to be permitted with a Minimum Export Price (MEP) of USD 900 per MT.'),
('15149920', 'Refined mustard oil of edible grade', 'Restricted', 'Export of mustard oil under branded consumer packs of upto 5 Kgs will continue to be permitted with a Minimum Export Price (MEP) of USD 900 per MT.'),
('17011490', 'Other', 'Restricted', 'Export of Sugar (Raw Sugar, White Sugar, Refined Sugar and Organic Sugar) is Restricted till further orders.'),
('17019990', 'Other', 'Restricted', 'Export of Sugar (Raw Sugar, White Sugar, Refined Sugar and Organic Sugar) is Restricted till further orders.'),
('22072000', 'Ethyl alcohol and other spirits, denatured, of any strength', 'Restricted', 'Export is permitted under Restricted Export Authorization only for non-fuel purposes.'),
('23021010', 'Maize bran', 'Restricted', ''),
('23023000', 'Of wheat', 'Restricted', ''),
('23050010', 'Oil-cake and oil-cake meal of ground-nut, expeller variety', 'Restricted', 'Exports of De-oiled groundnut cakes containing more than 1% oil and groundnut expeller cakes is restricted.'),
('23050020', 'Oil-cake and oil-cake meal of ground-nut, solvent extracted variety (defatted)', 'Restricted', 'Exports of De-oiled groundnut cakes containing more than 1% oil and groundnut expeller cakes is restricted.'),
('23050090', 'Other', 'Restricted', 'Exports of De-oiled groundnut cakes containing more than 1% oil and groundnut expeller cakes is restricted.'),
('23080000', 'Vegetable materials and vegetable waste, vegetable residues and by-products, of a kind used in animal feeding', 'Restricted', ''),
('25051011', 'Silica Sands: ---- Processed (White)', 'Restricted', ''),
('25051012', 'Silica Sands: ---- Processed (Brown)', 'Restricted', ''),
('25051019', 'Silica Sands: ---- Other', 'Restricted', ''),
('25051020', 'Silica Sands: --- Quartz sands', 'Restricted', ''),
('25059000', 'Other', 'Restricted', ''),
('25309099', 'Other: ---- Other', 'Restricted', ''),
('26020010', 'Manganese ore (46 percent or more)', 'Restricted', ''),
('26100010', 'Chrome ore lumps, containing 47 percent Cr2O3 and above', 'Restricted', ''),
('26100020', 'Chrome ore lumps, containing 40 percent or more but less than 47 percent Cr2O3', 'Restricted', ''),
('26100030', 'Chrome ore lumps below 40 percent Cr2O3', 'Restricted', ''),
('26100040', 'Chrome ore friable and concentrates fixes containing 47 percent Cr2O3 and above', 'Restricted', ''),
('26100090', 'Other', 'Restricted', ''),
('27102010', 'Automotive diesel fuel, containing biodiesel, conforming to standard IS 1460', 'Restricted', 'Export is permitted under Restricted Export Authorization only for non-fuel purposes.'),
('27102020', 'Diesel fuel blend (B6 to B20) conforming to standard IS 16531', 'Restricted', 'Export is permitted under Restricted Export Authorization only for non-fuel purposes.'),
('27102090', 'Other', 'Restricted', 'Export is permitted under Restricted Export Authorization only for non-fuel purposes.'),
('33012937', 'Tuberose concentrate; Nutmeg oil; Palmarosa oil; Patchouli oil; Pepper oil; Sandalwood oil; Rose oil: ---- Sandalwood oil', 'Restricted', ''),
('33013010', 'Agar oil', 'Restricted', 'The annual limits for export of Agar Oil extracted from agarwood (Aquilaria Malaccensis) from artificially propagated sources apply.'),
('38051010', 'Wood turpentine oil and spirit of turpentine', 'Restricted', 'Exports permitted under Restricted Export Authorization.'),
('38089122', 'Methyl bromide', 'Restricted', ''),
('38260000', 'Biodiesel and mixtures thereof, not containing or containing less than 70 percent by weight of petroleum oils', 'Restricted', 'Export is permitted under Restricted Export Authorization only for non-fuel purposes.'),
('44039918', 'Red Sanders (Pterocar pus Sautatinus)', 'Restricted', 'Subject to Policy Condition 3 of this Chapter.'),
('44079990', 'Other', 'Restricted', 'Export of Red Sanders may be permitted subject to Policy condition 3 of this Chapter.'),
('44209090', 'Other', 'Restricted', 'Certain Export are permitted as per Policy Condition 6 of this Chapter.'),
('50010000', 'Silk-worm cocoons suitable for reeling.', 'Restricted', 'Export of Pure races of Silk worms, silkworm seeds, and silk worm cocoons are Restricted and may be exported only against a Restricted Export Authorisation.')
ON CONFLICT (hs_code) DO UPDATE SET
    description = EXCLUDED.description,
    export_policy = EXCLUDED.export_policy,
    policy_condition = EXCLUDED.policy_condition,
    updated_at = CURRENT_TIMESTAMP;

-- Success message
SELECT 'Schema created successfully!' as status;