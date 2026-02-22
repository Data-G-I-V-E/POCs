"""
STE Items Database Importer
This script imports State Trading Enterprise (STE) items into PostgreSQL
Database: PPL-AI
Password: shreyaan999!
"""

import psycopg2
from psycopg2 import sql

# Database connection parameters
DB_CONFIG = {
    'dbname': 'PPL-AI',
    'user': 'postgres',
    'password': 'shreyaan999!',
    'host': 'localhost',
    'port': '5432'
}

# All STE items from the PDF
STE_ITEMS_DATA = """
25085031|Sillimanite ---- Lumps|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
25085032|Sillimanite ---- Fines (including sand)|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
25085039|Sillimanite ---- Other|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
25132030|Natural garnet|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
26011111|60percent Fe or more but below 62percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011112|62percent Fe or more but below 65percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011119|65percent Fe and above|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011121|Iron ore lumps (below 60percent Fe, including black iron ore containing up to 10percent Mn) ---- Iron ore lumps below 55percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011122|Iron ore lumps (below 60percent Fe, including black iron ore containing up to 10percent Mn) ---- Iron ore lumps 55percent Fe or more but below 58 percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011129|Iron ore lumps (below 60percent Fe, including black iron ore containing up to 10percent Mn) ---- 58 percent Fe or more but below 60 percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011131|Iron ore fines (62percent Fe or more) --- - 62percent Fe or more but below 65percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011139|Iron ore fines (62percent Fe or more) --- - 65percent Fe and above|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011141|Iron ore Fines (below 62percent Fe) ---- below 55percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011142|Iron ore Fines (below 62percent Fe) ---- 55percent Fe or more but below 58percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011143|Iron ore Fines (below 62percent Fe) ---- 58percent Fe or more but below 60percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011149|Iron ore Fines (below 62percent Fe) ---- 60percent Fe or more but below 62percent Fe|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26011150|Iron ore concentrates|STE (State Trading Enterprise)|Export of Iron ore concentrate prepared by benefication and/or concentration of lowgrade ore containing 40 percent or less of iron produced by Kudremukh Iron Ore Company Limited can be exported by STE- Kudremukh Iron Ore Company Limited, Bangalore.
26011190|Others|STE (State Trading Enterprise)|Subject to Policy Condition 1 of the Chapter.
26020020|Manganese ore (44percent or more but below 46percent)|STE (State Trading Enterprise)|Export is allowed through Manganese Ore India Limited (MOIL) only.
26020030|Manganese ore (40percent or more but below 44percent)|STE (State Trading Enterprise)|Export is allowed through Manganese Ore India Limited (MOIL) only.
26020040|Manganese ore (35percent or more but below 40percent)|STE (State Trading Enterprise)|Export is allowed through Manganese Ore India Limited (MOIL) only.
26020050|Manganese ore (30percent or more but below 35percent)|STE (State Trading Enterprise)|Export is allowed through Manganese Ore India Limited (MOIL) only.
26020060|Ferruginous (10percent or more but below 30percent)|STE (State Trading Enterprise)|Export is allowed through Manganese Ore India Limited (MOIL) only.
26020070|Manganese ore sinters, agglomerated|STE (State Trading Enterprise)|Export is allowed through Manganese Ore India Limited (MOIL) only.
26020090|Other|STE (State Trading Enterprise)|Export is allowed through Manganese Ore India Limited (MOIL) only.
26121000|Uranium ores and concentrates|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
26122000|Thorium ores and concentrates|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
26140010|Ilmenite, unprocessed|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
26140020|Ilmenite, upgraded (beneficiated ilmenite including ilmenite ground)|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
26140031|Rutile: ---- Rare earth oxides including rutile sand|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
26140039|Rutile: ----Other|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
26140090|Other|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
26151000|Zirconium ores and concentrates|STE (State Trading Enterprise)|Export is allowed through Indian Rare Earths Limited (IREL) only.
27090010|PETROLEUM CRUDE|STE (State Trading Enterprise)|Export is allowed through Indian Oil Corporation Limited (IOCL) only.
27090090|OTHER|STE (State Trading Enterprise)|Export is allowed through Indian Oil Corporation Limited (IOCL) only.
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
                
                # Extract authorized entity from policy_condition
                authorized_entity = extract_authorized_entity(policy_condition)
                
                items.append((hs_code, description, export_policy, policy_condition, authorized_entity))
    return items


def extract_authorized_entity(policy_condition):
    """Extract the authorized STE entity from policy condition"""
    if 'Indian Rare Earths Limited' in policy_condition or 'IREL' in policy_condition:
        return 'IREL'
    elif 'Manganese Ore India Limited' in policy_condition or 'MOIL' in policy_condition:
        return 'MOIL'
    elif 'Indian Oil Corporation Limited' in policy_condition or 'IOCL' in policy_condition:
        return 'IOCL'
    elif 'Kudremukh Iron Ore Company Limited' in policy_condition:
        return 'Kudremukh Iron Ore Company Limited'
    else:
        return None


def create_table(conn):
    """Create the STE items table"""
    with conn.cursor() as cur:
        print("Dropping existing table if it exists...")
        cur.execute("DROP TABLE IF EXISTS ste_items CASCADE;")
        
        print("Creating ste_items table...")
        cur.execute("""
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
        """)
        
        print("Creating indexes...")
        cur.execute("CREATE INDEX idx_ste_hs_code ON ste_items(hs_code);")
        cur.execute("CREATE INDEX idx_ste_authorized_entity ON ste_items(authorized_entity);")
        cur.execute("CREATE INDEX idx_ste_description ON ste_items USING gin(to_tsvector('english', description));")
        
        conn.commit()
        print("✓ Table and indexes created successfully\n")


def insert_data(conn, ste_items):
    """Insert data into the table"""
    with conn.cursor() as cur:
        print(f"Inserting {len(ste_items)} STE items...")
        for item in ste_items:
            try:
                cur.execute("""
                    INSERT INTO ste_items (hs_code, description, export_policy, policy_condition, authorized_entity)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (hs_code) DO UPDATE 
                    SET description = EXCLUDED.description,
                        export_policy = EXCLUDED.export_policy,
                        policy_condition = EXCLUDED.policy_condition,
                        authorized_entity = EXCLUDED.authorized_entity,
                        updated_at = CURRENT_TIMESTAMP
                """, item)
            except Exception as e:
                print(f"  Error inserting STE item {item[0]}: {e}")
        
        conn.commit()
        print("✓ Data inserted successfully\n")


def verify_data(conn):
    """Verify the inserted data"""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ste_items;")
        ste_count = cur.fetchone()[0]
        
        print(f"{'='*60}")
        print(f"DATABASE VERIFICATION")
        print(f"{'='*60}")
        print(f"STE items in database: {ste_count}")
        
        # Count by authorized entity
        cur.execute("""
            SELECT authorized_entity, COUNT(*) 
            FROM ste_items 
            WHERE authorized_entity IS NOT NULL
            GROUP BY authorized_entity 
            ORDER BY COUNT(*) DESC;
        """)
        print("\nItems by Authorized Entity:")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]} items")
        
        print(f"{'='*60}\n")
        
        print("Sample STE items (first 5):")
        cur.execute("SELECT hs_code, description, authorized_entity FROM ste_items ORDER BY hs_code LIMIT 5;")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1][:50]}... [{row[2]}]")
        
        print(f"\n{'='*60}")


def create_search_functions(conn):
    """Create search functions for STE items"""
    with conn.cursor() as cur:
        # Function to search STE items
        cur.execute("""
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
        """)
        
        # Function to get items by authorized entity
        cur.execute("""
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
        """)
        
        # Function to check if HS code is STE controlled
        cur.execute("""
            CREATE OR REPLACE FUNCTION is_ste_item(code VARCHAR)
            RETURNS BOOLEAN AS $$
            DECLARE
                item_exists BOOLEAN;
            BEGIN
                SELECT EXISTS(SELECT 1 FROM ste_items WHERE hs_code = code) INTO item_exists;
                RETURN item_exists;
            END;
            $$ LANGUAGE plpgsql;
        """)
        
        conn.commit()
        print("✓ Search functions created successfully\n")


def create_unified_view(conn):
    """Create a unified view combining all export policy items"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE OR REPLACE VIEW all_export_policy_items AS
            SELECT 
                'Prohibited' as item_type,
                hs_code,
                description,
                export_policy,
                policy_condition,
                NULL as authorized_entity,
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
                NULL as authorized_entity,
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
        """)
        
        # Create comprehensive search function
        cur.execute("""
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
                ORDER BY a.item_type, a.hs_code;
            END;
            $$ LANGUAGE plpgsql;
        """)
        
        conn.commit()
        print("✓ Unified view and search function created successfully\n")


def main():
    """Main function to run the import"""
    print("\n" + "="*60)
    print("STE ITEMS DATABASE IMPORTER")
    print("="*60 + "\n")
    print(f"Target Database: {DB_CONFIG['dbname']}")
    print(f"Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"User: {DB_CONFIG['user']}\n")
    
    # Parse the data
    print("Parsing data from PDF...")
    ste_items = parse_data(STE_ITEMS_DATA)
    print(f"✓ Parsed {len(ste_items)} STE items\n")
    
    try:
        # Connect to PostgreSQL
        print("Connecting to PostgreSQL...")
        conn = psycopg2.connect(**DB_CONFIG)
        print("✓ Connected successfully\n")
        
        # Create table
        create_table(conn)
        
        # Insert data
        insert_data(conn, ste_items)
        
        # Create search functions
        create_search_functions(conn)
        
        # Create unified view (if other tables exist)
        try:
            create_unified_view(conn)
        except Exception as e:
            print(f"Note: Could not create unified view (other tables may not exist yet): {e}\n")
        
        # Verify data
        verify_data(conn)
        
        print("\n✅ IMPORT COMPLETED SUCCESSFULLY!")
        print("\nYou can now query the database using:")
        print("  - SELECT * FROM ste_items;")
        print("  - SELECT * FROM search_ste_items('iron');")
        print("  - SELECT * FROM get_items_by_entity('IREL');")
        print("  - SELECT * FROM all_export_policy_items WHERE item_type = 'STE';")
        
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