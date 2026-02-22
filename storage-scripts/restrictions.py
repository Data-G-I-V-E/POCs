"""
Export Items Database Importer
This script imports prohibited and restricted export items into PostgreSQL
Database: PPL-AI
Password: shreyaan999!
"""

import psycopg2
from psycopg2 import sql
import re

# Database connection parameters
DB_CONFIG = {
    'dbname': 'PPL-AI',
    'user': 'postgres',
    'password': 'shreyaan999!',
    'host': 'localhost',
    'port': '5432'
}

# All prohibited items from the PDF
PROHIBITED_ITEMS_DATA = """
01063100|Birds: -- Birds of prey|Prohibited|
01063200|Birds: -- Psittaciformes(including parrots, parakeets,macaws and cockatoos)|Prohibited|Subject to Policy Condition 3 of the Chapter
01063300|Birds: -- Ostriches; emus (Dromaius novaehollandiae)|Prohibited|Subject to Policy Condition 3 of the Chapter
01063900|Birds: -- Other|Prohibited|Subject to Policy Condition 3 of the Chapter
02011000|Carcasses and halfcarcasses|Prohibited|
02012000|Other cuts with bone in|Prohibited|
02013000|Boneless|Prohibited|However, export of Boneless meat of buffalo (both male and female) fresh and chilled Boneless meat of buffalo (both male and female) frozen is free subject to the following condition. 1. Export allowed on production of a certificate from the designated veterinary authority of the State, from which the meat or offals emanate, to the effect that the meat or offals are from buffaloes not used for breeding and purposes.condition stipulated 2. Quality control and inspection under Policy Conition 1 and 2 respectively as well as Policy Condition 4 and 6 above are required to be fulfilled. Exports shall also be subject to Policy Condition 8 of this Chapter.
02021000|Carcasses and halfcarcasses|Prohibited|
02022000|Other cuts with bone in|Prohibited|
02023000|Boneless|Prohibited|However, export of Boneless meat of buffalo (both male and female) fresh and chilled Boneless meat of buffalo (both male and female) frozen is free subject to the following condition. 1. Export allowed on production of a certificate from the designated veterinary authority of the State, from which the meat or offals emanate, to the effect that the meat or offals are from buffaloes not used for breeding and purposes. 2. Quality control and inspection under Policy Conition 1 and 2 respectively as well as Policy Condition 4 and 6 above are required to be fulfilled. Exports shall also be subject to Policy Condition 8 of this Chapter.
02061000|Of bovine animals, fresh or chilled|Prohibited|Beef in the form of offal of cows, oxen and calf is not permitted to be exported. However, exports of offal of buffalo except gonads and reproductive organs is free subject to following condition: - 1.Export allowed on Production of a certificate from the designated veterinary authority of the State, from which the meat or offals emanate, to the effect that the meat or offals are from buffaloes not used for breeding and milch purposes. 2. Quality control and inspection under Policy Conition 1 and 2 respectively as well as Policy Condition 4 and 6 above are required to be fulfilled. Exports shall also be subject to Policy Condition 8 of this Chapter.
02062100|Of bovine animals, frozen : -- Tongues|Prohibited|Beef in the form of offal of cows, oxen and calf is not permitted to be exported. However, exports of offal of buffalo except gonads and reproductive organs is free subject to following condition: - 1.Export allowed on Production of a certificate from the designated veterinary authority of the State, from which the meat or offals emanate, to the effect that the meat or offals are from buffaloes not used for breeding and milch purposes. 2. Quality control and inspection under Policy Conition 1 and 2 respectively as well as Policy Condition 4 and 6 above are required to be fulfilled. Exports shall also be subject to Policy Condition 8 of this Chapter.
02062200|Of bovine animals, frozen : -- Livers|Prohibited|Beef in the form of offal of cows, oxen and calf is not permitted to be exported. However, exports of offal of buffalo except gonads and reproductive organs is free subject to following condition: - 1.Export allowed on Production of a certificate from the designated veterinary authority of the State, from which the meat or offals emanate, to the effect that the meat or offals are from buffaloes not used for breeding and milch purposes. 2. Quality control and inspection under Policy Conition 1 and 2 respectively as well as Policy Condition 4 and 6 above are required to be fulfilled. Exports shall also be subject to Policy Condition 8 of this Chapter.
02062900|Of bovine animals, frozen : -- Other|Prohibited|Beef in the form of offal of cows, oxen and calf is not permitted to be exported. However, exports of offal of buffalo except gonads and reproductive organs is free subject to following condition: - 1.Export allowed on Production of a certificate from the designated veterinary authority of the State, from which the meat or offals emanate, to the effect that the meat or offals are from buffaloes not used for breeding and milch purposes. 2. Quality control and inspection under Policy Conition 1 and 2 respectively as well as Policy Condition 4 and 6 above are required to be fulfilled. Exports shall also be subject to Policy Condition 8 of this Chapter.
02102000|Meat of bovine animals|Prohibited|Beef in the form of offal of cows, oxen and calf is Prohibited and not permitted to be exported. However, exports of offal of buffalo except gonads and reproductive organs is free subject to following condition: - 1.Export allowed on Production of a certificate from the designated veterinary authority of the State, from which the meat or offals emanate, to the effect that the meat or offals are from buffaloes not used for breeding and milch purposes. 2. Quality control and inspection under Policy Conition 1 and 2 respectively as well as Policy Condition 4 and 6 above are required to be fulfilled.
03029200|Shark fins|Prohibited|
03039200|Shark fins|Prohibited|
03057100|Fish fins, heads, tails, maws and other edible fish offal:--Shark fins|Prohibited|
05010010|Human hair unworked,whether or not washed or scoured|Prohibited|However, export is 'Free' if FOB value is US Dollar 65 or above per Kilogram.
05010020|Waste of human hair|Prohibited|However, export is 'Free' if FOB value is US Dollar 65 or above per Kilogram.
05059010|Peacock tail and wing feather (trimmed or not)|Prohibited|
05061041|Bones, horn cones and parts thereof, not crushed: ---- Of wild animals|Prohibited|
05079040|Antlers|Prohibited|
05080050|Shells|Prohibited|Export of Sea shells, including polished sea shells and handicrafts made out of those species included in the Schedules of the Wild Life (Protection) Act, 1972 is not permitted to be exported
10011900|Durum wheat : -- Other|Prohibited|
10019100|Other : -- Seed|Prohibited|
10019910|Wheat|Prohibited|
10019920|Meslin|Prohibited|However, export of Meslin of seed quality is Free subject to the following conditions: 1. Export will be allowed subject to submission of following documents to Customs at the time of export: (i) A license to carry on the business of a dealer in seeds issued under Section 3 of the Seed Control Order (1983) from the State Government; and (ii) Declaration that the export consignment of seeds has been chemically treated and is not fit for human consumption; and 2. Export packets will be labeled that seeds are treated with chemical insecticides and cannot be used for food or feed purposes.
11010000|Wheat or meslin flour.|Prohibited|However, export of Wheat Flour (Atta) will be allowed against Advance Authorisation, and by Export Oriented Units (EOUs) and units in SEZs. Procedural conditions to be followed by Advance Authorisation holders will be provided in the Handbook of Procedures. Export of Wheat Flour (Atta) by 100% Export Oriented Units (EOUs) and units in the SEZ will be subject to pre-import of wheat condition. The Wheat Flour (Atta) will have to be exported within 180 days from the date of import of the wheat consignment.
12119051|Whole Plant, Aerial Part, Stem, Shoot and Wood :---- Sandalwood chips and dust|Prohibited|1. Export of Sandalwood in any form is prohibited and not permitted to be exported. 2. However, Export of Finished Handicraft products of Sandalwood and Other species and Machine finished sandalwood products is Free.
14011000|Bamboos|Prohibited|Export of Bamboo products made from bamboo obtained from legal source; except bamboo charcoal, bamboo pulp and unprocessed bamboo shoots is free subject to following conditions: (i) All the bamboo products made from bamboo obtained from legal sources are permitted for export subject to proper documentation/Certificate of Origin (CoO) proving that the bamboo used for making products has been obtained from legal sources.
15011000|Lard|Prohibited|Subject to Policy Condition 01 of the Chapter.
15012000|Other pig fat|Prohibited|Subject to Policy Condition 01 of the Chapter.
15019000|Other|Prohibited|Subject to Policy Condition 01 of the Chapter.
15021010|Mutton tallow|Prohibited|Subject to Policy Condition 01 of the Chapter.
15021090|Other|Prohibited|1. Subject to Policy Condition 01 of the Chapter. 2. However, Export of Buffalo Tallow is free subject to following condition:- (i) Export permitted only from APEDA registered integrated meat plants having rendering facilities subject to compulsory pre-shipment bio-chemical test by laboratories approved by APEDA.
15029010|Unrendered fats|Prohibited|Subject to Policy Condition 01 of the Chapter.
15029020|Rendered fats or solvent extraction fats|Prohibited|Subject to Policy Condition 01 of the Chapter.
15029090|Other|Prohibited|Subject to Policy Condition 01 of the Chapter.
15030000|Lard Stearin, Lard Oil, Oleostearin, Oleo-Oil and Tallow Oil, not emulsified or mixed or otherwise prepared|Prohibited|Subject to Policy Condition 01 of the Chapter.
15050010|Wool alcohol (including lanolin alcohol)|Prohibited|Subject to Policy Condition 01 of the Chapter.
15050020|Wool grease, crude|Prohibited|Subject to Policy Condition 01 of the Chapter.
15050090|Other|Prohibited|1. Subject to Policy Condition 01 of the Chapter 2. Export of Lanolin is free subject to following condition
15060010|Neats Foot oil and fats from bone or waste|Prohibited|Subject to Policy Condition 01 of the Chapter.
15060090|Other|Prohibited|Subject to Policy Condition 01 of the Chapter.
16041800|Fish, whole or in pieces, but not minced : -- Shark fins|Prohibited|
41032000|Of reptiles|Prohibited|
41064000|Of reptiles|Prohibited|
41133000|Of reptiles|Prohibited|
43011000|Of mink, whole, with or without head, tail or paws|Prohibited|
43016000|Of fox, whole, with or without head, tail or paws|Prohibited|
43021940|Tiger-Cat skins|Prohibited|
43031010|Articles of apparel and clothing accessories: ---- Of wild animals covered under the Wild Life (Protection) Act,1972|Prohibited|
43031020|Articles of apparel and clothing accessories: ---- Of animals covered under Convention on International Trade of Endangered Species (CITES), Other than those of Tariff item 43031010|Prohibited|
43039010|Of wild animals covered under the Wild Life (Protection) Act,1972|Prohibited|
43039020|Of animals covered under Convention on International Trade of Endangered Species (CITES), other than those of item 4303 90 10|Prohibited|
44011110|In logs|Prohibited|Export of - a. Wood and wood products in the form of logs, timber, stumps, roots, bark, chips, powder, flakes, dust, and charcoal (other than sawn timber made exclusively out of imported logs/timber) and; b. Fuel wood, in logs, in billets, in twigs, in faggots or in similar forms; Wood in chips or particles; Sawdust and wood waste and scrap, whether or not agglomerated in logs, briquettes, pellets or similar forms is not permitted.
44011190|Other|Prohibited|Export of Fuel wood, in logs, in billets, in twigs, in faggots or in similar forms; wood in chips or particles; Sawdust and wood waste and scrap, whether or not agglomerated in logs, briquettes, pellets or similar forms is not permitted.
44011210|In logs|Prohibited|Export of Fuel wood, in logs, in billets, in twigs, in faggots or in similar forms; Wood in chips or particles; Sawdust and wood waste and scrap, whether or not agglomerated in logs, briquettes, pellets or similar forms is not permitted.
44011290|Other|Prohibited|Export of Fuel wood, in logs, in billets, in twigs, in faggots or in similar forms; Wood in chips or particles; Sawdust and wood waste and scrap, whether or not agglomerated in logs, briquettes, pellets or similar forms is not permitted.
44013100|Sawdust and wood waste and scrap, agglomerated in logs, briquettes, pellets or similar forms : -- Wood pellets|Prohibited|1. Export of Wood and wood products in the form of logs, timber, stumps, roots, bark, chips, powder, flakes, dust, and charcoal (other than sawn timber made exclusively out of imported logs/timber) is not permitted.
44013900|Sawdust and wood waste and scrap, agglomerated in logs, briquettes, pellets or similar forms : -- Other|Prohibited|1. Export of Wood and wood products in the form of logs, timber, stumps, roots, bark, chips, powder, flakes, dust, and charcoal other than sawn timber made exclusively out of imported logs/timber is not permitted.
44022090|Other|Prohibited|Export of Wood charcoal, whether or not agglomerated is Prohibited. However, this Prohibition on Export of charcoal will not apply to Bhutan.
44039922|Sal (Chorea robusta, Sandalwood (Santalum album), Semul (Bombax ceiba), Walnut wood (Juglans binata), Anjam (Hardwickia binata), Sisso (Dalbergia sisso) and White cedar (Dysozylum spp.) and the like: ---- Sandal wood (Santalum albur)|Prohibited|Subject to Policy Conditon 5 of this Chapter
44071100|Coniferous : -- Of pine (Pinus spp)|Prohibited|Certain Export items are permitted as per Policy condition 4 of this Chapter.
44071910|Douglas fir (Pseudotsuga menziesii)|Prohibited|Certain Exports are permitted as per Policy condition 4 of this Chapter.
44071990|Other|Prohibited|Certain Exports are permitted as per Policy condition 4 of this Chapter.
44072900|Other|Prohibited|Certain Exports are permitted as per Policy condition 4 of this Chapter.
44079600|Other : -- Of birch (Betula spp.)|Prohibited|Certain Exports are permitted as per Policy condition 4 of this Chapter.
44079920|Willow|Prohibited|Certain Exports are permitted as per Policy condition 4 of this Chapter.
47010000|Mechanical wood pulp.|Prohibited|
47020000|Chemical wood pulp, dissolving grades.|Prohibited|
47031100|Unbleached : -- Coniferous|Prohibited|
47031900|Unbleached : -- Non- coniferous|Prohibited|
47032100|Semi-bleached or bleached : -- Coniferous|Prohibited|
47032900|Semi-bleached or bleached : -- Non-coniferous|Prohibited|
47041100|Unbleached : -- Coniferous|Prohibited|
47041900|Unbleached : -- Non- coniferous|Prohibited|
47042100|Semi-bleached or bleached : -- Coniferous|Prohibited|
47042900|Semi-bleached or bleached : -- Non-coniferous|Prohibited|
47050000|Wood pulp obtained by a combination of mechanical and chemical pulping processes.|Prohibited|
47061000|Cotton linters pulp|Prohibited|
47062000|Pulps of fibres derived from recovered (waste and scrap) paper or|Prohibited|
47063000|other, of bamboo|Prohibited|
47069100|Other : -- Mechanical|Prohibited|
47069200|Other : -- Chemical|Prohibited|
47069300|Other : -- Obtained by a combination of mechanical and chemical processes|Prohibited|
47071000|Unbleached kraft paper or paperboard or corrugated paper or paperboard|Prohibited|
47072000|Other paper or paperboard made mainly of bleached chemical pulp, not coloured in the mass|Prohibited|
47073000|Paper or paperboard made mainly of mechanical pulp (for example, newspapers, journals and similar printed matter)|Prohibited|
47079000|Other, including unsorted waste and scrap|Prohibited|
85434000|Electronic cigarettes and similar personal electric vaporising devices|Prohibited|Export of Electronic Cigarretes (including all forms of Electronic Nicotine Delivery Systems, Heat not burn products, e-hookah and the like devices, by whatever name called and whatever shape, size or form it may have, but not including any product licensed under the Drugs and Cosmetics Act, 1940 or any parts or components thereof such as refill pods, atomisers, cartridges etc) and Parts or Components is not permitted to be exported.
96011000|Worked ivory and articles of ivory|Prohibited|
"""

# All restricted items from the PDF
RESTRICTED_ITEMS_DATA = """
01012100|Horses : -- Pure-bred breeding animals|Restricted|Subject to Policy Condition 2 of the Chapter
01012910|Horses for Polo|Restricted|Subject to Policy Condition 2 of the Chapter
01012990|Other|Restricted|Subject to Policy Condition 2 of the Chapter
01019090|Other|Restricted|
01022110|Bulls|Restricted|
01022120|Cows|Restricted|
01022910|Bulls|Restricted|
01022990|Other, including calves|Restricted|
01023100|Buffalo : -- Pure-bred breeding animals|Restricted|
01023900|Buffalo : -- Other|Restricted|
01029010|Pure-bred breeding animals|Restricted|
01029090|Other|Restricted|
01061300|Mammals: -- Camels and other camelids (Camelidae)|Restricted|
05111000|Bovine semen|Restricted|
05119190|Other|Restricted|
05119991|Other: ---- Frozen semen, other than bovine :bovine embryo:|Restricted|Export of Gonads and other reproductive organs of buffaloes & Germplasm of Cattle and buffaloes is restricted.
06022010|Edible fruit or nut trees, grafted or not|Restricted|Exports of Cashew seeds and plants is restricted.
10061010|Of seed quality|Restricted|Export permitted under Restricted Export Authorization subject to the following conditions: (i) submission of following documents to Customs at the time of export: (a) a license to carry on the business of a dealer in seeds issued under Section 3 of the Seed Control Order (1983) from the State Government; and (b) Declaration that the export consignment of seeds has been chemically treated and is not fit for human consumption; and (ii) Export packets will be labeled that seeds are treated with chemical insecticides and cannot be used for food or feed purposes.
10061090|Other|Restricted|
12099130|Of Onion|Restricted|
12119012|Seeds, Kernel, Aril, Fruit, Pericarp, Fruit rind, Endosperm, Mesocarp, Endocarp :---- Nux vomica, dried ripe seeds|Restricted|
12119014|Seeds, Kernel, Aril, Fruit, Pericarp, Fruit rind, Endosperm, Mesocarp, Endocarp :---- Neem seed|Restricted|
12119054|Whole Plant, Aerial Part, Stem, Shoot and Wood :---- Agarwood|Restricted|The annual limits for export of Agarwood (Aquilaria Malaccensis) Chips and Powder obtained from artificially propagated sources (cultivated origin outside forest areas) has been fixed for three financial years, viz, 2024-25 to 2026-27
12122910|Seaweeds|Restricted|
12122990|Other algae|Restricted|1. Exports of Sea weeds of all types, including G-edulis but excluding brown seaweeds and agarophytes of Tamil Nadu Coast origin in processed form is restricted for export.
12130000|Cereal straw and husks, unprepared, whether or not chopped, ground, pressed or in the form of pellets.|Restricted|The export of Fodder, including wheat, rice straw is Restricted. However, Agri residue based Biomass and Briquettes/Pellets under ITC-HS Heading 1213 will be under Free category.
12141000|Lucerne (alfalfa) meal and pellets|Restricted|
12149000|Other|Restricted|
15149120|Mustard oil|Restricted|However, Export of mustard oil under branded consumer packs of upto 5 Kgs will continue to be permitted with a Minimum Export Price (MEP) of USD 900 per MT.
15149920|Refined mustard oil of edible grade|Restricted|However, Export of mustard oil under branded consumer packs of upto 5 Kgs will continue to be permitted with a Minimum Export Price (MEP) of USD 900 per MT.
17011490|Other|Restricted|1. Export of Sugar (Raw Sugar, White Sugar, Refined Sugar and Organic Sugar) is Restricted till further orders
17019990|Other|Restricted|1. Export of Sugar (Raw Sugar, White Sugar, Refined Sugar and Organic Sugar) is Restricted till further orders
22072000|Ethyl alcohol and other spirits, denatured, of any strength|Restricted|Export is permitted under Restricted Export Authorization only for non-fuel purposes.
23021010|Maize bran|Restricted|
23023000|Of wheat|Restricted|
23050010|Oil-cake and oil-cake meal of ground-nut, expeller variety|Restricted|Exports of De-oiled groundnut cakes containing more than 1% oil and groundnut expeller cakes is restricted.
23050020|Oil-cake and oil-cake meal of ground-nut, solvent extracted variety (defatted)|Restricted|Exports of De-oiled groundnut cakes containing more than 1% oil and groundnut expeller cakes is restricted.
23050090|Other|Restricted|Exports of De-oiled groundnut cakes containing more than 1% oil and groundnut expeller cakes is restricted.
23080000|Vegetable materials and vegetable waste, vegetable residues and by-products, whether or not in the form of pellets, of a kind used in animal feeding, not elsewhere specified or included|Restricted|
25051011|Silica Sands: ---- Processed (White)|Restricted|
25051012|Silica Sands: ---- Processed (Brown)|Restricted|
25051019|Silica Sands: ---- Other|Restricted|
25051020|Silica Sands: --- Quartz sands|Restricted|
25059000|Other|Restricted|
25309099|Other: ---- Other|Restricted|
26020010|Manganese ore (46 percent or more)|Restricted|
26100010|Chrome ore lumps, containing 47 percent Cr2O3 and above|Restricted|
26100020|Chrome ore lumps, containing 40 percent or more but less than 47 percent Cr2O3|Restricted|
26100030|Chrome ore lumps below 40 percent Cr2O3|Restricted|
26100040|Chrome ore friable and concentrates fixes containing 47 percent Cr2O3 and above|Restricted|
26100090|Other|Restricted|
27102010|Automotive diesel fuel, containing biodiesel, conforming to standard IS 1460|Restricted|Export is permitted under Restricted Export Authorization only for non-fuel purposes.
27102020|Diesel fuel blend (B6 to B20) conforming to standard IS 16531|Restricted|Export is permitted under Restricted Export Authorization only for non-fuel purposes.
27102090|Other|Restricted|Export is permitted under Restricted Export Authorization only for non-fuel purposes.
33012937|Tuberose concentrate; Nutmeg oil; Palmarosa oil; Patchouli oil; Pepper oil; Petitgrain oil; Sandalwood oil; Rose oil: ---- Sandalwood oil|Restricted|
33013010|Agar oil|Restricted|The annual limits for export of Agar Oil extracted from agarwood (Aquilaria Malaccensis) obtained from artificially propagated sources
38051010|Wood turpentine oil and spirit of turpentine|Restricted|Exports permitted under Restricted Export Authorization
38089122|Methyl bromide|Restricted|
38260000|Biodiesel and mixtures thereof, not containing or containing less than 70 percent by weight of petroleum oils or oils obtained from bituminous minerals.|Restricted|Export is permitted under Restricted Export Authorization only for non-fuel purposes.
44039918|Red Sanders (Pterocar pus Sautatinus)|Restricted|Subject to Policy Conditon 3 of this Chapter
44079990|Other|Restricted|1.Export of Red Sanders may be permitted subject to Policy condition 3 of this Chapter.
44209090|Other|Restricted|Certain Export are permitted as per Policy Condition 6 of this Chapter.
50010000|Silk-worm cocoons suitable for reeling.|Restricted|Export of Pure races of Silk worms, silkworm seeds, and silk worm cocoons are Restricted and may be exported only against a Restricted Export Authorisation
"""


def parse_data(data_string):
    """Parse pipe-delimited data into list of tuples"""
    items = []
    for line in data_string.strip().split('\n'):
        if line.strip():
            parts = line.split('|')
            if len(parts) >= 3:
                hs_code = parts[0].strip()
                description = parts[1].strip()
                export_policy = parts[2].strip()
                policy_condition = parts[3].strip() if len(parts) > 3 else ''
                items.append((hs_code, description, export_policy, policy_condition))
    return items


def create_tables(conn):
    """Create the database tables"""
    with conn.cursor() as cur:
        print("Dropping existing tables if they exist...")
        cur.execute("DROP TABLE IF EXISTS prohibited_items CASCADE;")
        cur.execute("DROP TABLE IF EXISTS restricted_items CASCADE;")
        
        print("Creating prohibited_items table...")
        cur.execute("""
            CREATE TABLE prohibited_items (
                id SERIAL PRIMARY KEY,
                hs_code VARCHAR(20) NOT NULL UNIQUE,
                description TEXT NOT NULL,
                export_policy VARCHAR(50) NOT NULL,
                policy_condition TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        print("Creating restricted_items table...")
        cur.execute("""
            CREATE TABLE restricted_items (
                id SERIAL PRIMARY KEY,
                hs_code VARCHAR(20) NOT NULL UNIQUE,
                description TEXT NOT NULL,
                export_policy VARCHAR(50) NOT NULL,
                policy_condition TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        print("Creating indexes...")
        cur.execute("CREATE INDEX idx_prohibited_hs_code ON prohibited_items(hs_code);")
        cur.execute("CREATE INDEX idx_prohibited_description ON prohibited_items USING gin(to_tsvector('english', description));")
        cur.execute("CREATE INDEX idx_restricted_hs_code ON restricted_items(hs_code);")
        cur.execute("CREATE INDEX idx_restricted_description ON restricted_items USING gin(to_tsvector('english', description));")
        
        conn.commit()
        print("✓ Tables and indexes created successfully\n")


def insert_data(conn, prohibited_items, restricted_items):
    """Insert data into the tables"""
    with conn.cursor() as cur:
        print(f"Inserting {len(prohibited_items)} prohibited items...")
        for item in prohibited_items:
            try:
                cur.execute("""
                    INSERT INTO prohibited_items (hs_code, description, export_policy, policy_condition)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (hs_code) DO UPDATE 
                    SET description = EXCLUDED.description,
                        export_policy = EXCLUDED.export_policy,
                        policy_condition = EXCLUDED.policy_condition,
                        updated_at = CURRENT_TIMESTAMP
                """, item)
            except Exception as e:
                print(f"  Error inserting prohibited item {item[0]}: {e}")
        
        print(f"Inserting {len(restricted_items)} restricted items...")
        for item in restricted_items:
            try:
                cur.execute("""
                    INSERT INTO restricted_items (hs_code, description, export_policy, policy_condition)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (hs_code) DO UPDATE 
                    SET description = EXCLUDED.description,
                        export_policy = EXCLUDED.export_policy,
                        policy_condition = EXCLUDED.policy_condition,
                        updated_at = CURRENT_TIMESTAMP
                """, item)
            except Exception as e:
                print(f"  Error inserting restricted item {item[0]}: {e}")
        
        conn.commit()
        print("✓ Data inserted successfully\n")


def verify_data(conn):
    """Verify the inserted data"""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM prohibited_items;")
        prohibited_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM restricted_items;")
        restricted_count = cur.fetchone()[0]
        
        print(f"{'='*60}")
        print(f"DATABASE VERIFICATION")
        print(f"{'='*60}")
        print(f"Prohibited items in database: {prohibited_count}")
        print(f"Restricted items in database: {restricted_count}")
        print(f"Total items: {prohibited_count + restricted_count}")
        print(f"{'='*60}\n")
        
        print("Sample prohibited items (first 5):")
        cur.execute("SELECT hs_code, description FROM prohibited_items ORDER BY hs_code LIMIT 5;")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1][:60]}{'...' if len(row[1]) > 60 else ''}")
        
        print("\nSample restricted items (first 5):")
        cur.execute("SELECT hs_code, description FROM restricted_items ORDER BY hs_code LIMIT 5;")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1][:60]}{'...' if len(row[1]) > 60 else ''}")
        
        print(f"\n{'='*60}")


def create_search_function(conn):
    """Create a function to search items by HS code or description"""
    with conn.cursor() as cur:
        cur.execute("""
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
                   OR r.description ILIKE '%' || search_term || '%';
            END;
            $$ LANGUAGE plpgsql;
        """)
        conn.commit()
        print("✓ Search function created successfully\n")


def main():
    """Main function to run the import"""
    print("\n" + "="*60)
    print("EXPORT ITEMS DATABASE IMPORTER")
    print("="*60 + "\n")
    print(f"Target Database: {DB_CONFIG['dbname']}")
    print(f"Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"User: {DB_CONFIG['user']}\n")
    
    # Parse the data
    print("Parsing data from PDFs...")
    prohibited_items = parse_data(PROHIBITED_ITEMS_DATA)
    restricted_items = parse_data(RESTRICTED_ITEMS_DATA)
    print(f"✓ Parsed {len(prohibited_items)} prohibited items")
    print(f"✓ Parsed {len(restricted_items)} restricted items\n")
    
    try:
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL...")
        conn = psycopg2.connect(**DB_CONFIG)
        print("✓ Connected successfully\n")
        
        # Create tables
        create_tables(conn)
        
        # Insert data
        insert_data(conn, prohibited_items, restricted_items)
        
        # Create search function
        create_search_function(conn)
        
        # Verify data
        verify_data(conn)
        
        print("\n✅ IMPORT COMPLETED SUCCESSFULLY!")
        print("\nYou can now query the database using:")
        print("  - SELECT * FROM prohibited_items;")
        print("  - SELECT * FROM restricted_items;")
        print("  - SELECT * FROM search_export_items('shark');")
        
    except psycopg2.OperationalError as e:
        print(f"\n❌ CONNECTION ERROR:")
        print(f"Could not connect to database '{DB_CONFIG['dbname']}'")
        print(f"Error: {e}")
        print("\nPlease ensure:")
        print("  1. PostgreSQL is running")
        print("  2. Database 'PPL-AI' exists")
        print("  3. Password is correct")
        print("  4. User has appropriate permissions")
        return False
        
    except psycopg2.Error as e:
        print(f"\n❌ DATABASE ERROR: {e}")
        return False
        
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if 'conn' in locals() and conn:
            conn.close()
            print("\n✓ Database connection closed")
    
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)