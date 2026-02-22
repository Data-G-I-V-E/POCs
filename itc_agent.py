"""
ITC HS Code Agent
Query system to retrieve rules and policies for HS codes
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ITCHSCodeAgent:
    """Agent to query ITC HS code rules and policies"""
    
    def __init__(self, db_config: Dict):
        """
        Initialize database connection
        
        Args:
            db_config: Dict with keys: host, database, user, password, port
        """
        self.conn = psycopg2.connect(**db_config)
        self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
    
    def get_hs_code_info(self, hs_code: str) -> Optional[Dict]:
        """
        Get basic information for an HS code
        
        Args:
            hs_code: HS code like "07131010"
            
        Returns:
            Dict with hs_code details or None
        """
        query = """
            SELECT 
                id,
                chapter_code,
                hs_code,
                description,
                export_policy,
                parent_hs_code,
                level,
                notification_no,
                notification_date
            FROM itc_hs_products
            WHERE hs_code = %s
        """
        
        self.cursor.execute(query, (hs_code,))
        result = self.cursor.fetchone()
        
        return dict(result) if result else None
    
    def get_policy_conditions(self, hs_code: str) -> List[Dict]:
        """
        Get all policy conditions applicable to an HS code
        
        Args:
            hs_code: HS code like "07131010"
            
        Returns:
            List of policy condition dicts
        """
        query = """
            SELECT 
                pr.policy_reference,
                pr.notification_no,
                pr.notification_date,
                cp.policy_text
            FROM itc_hs_policy_references pr
            LEFT JOIN itc_chapter_policies cp 
                ON pr.chapter_code = cp.chapter_code 
                AND pr.policy_reference = cp.policy_type
            WHERE pr.hs_code = %s
        """
        
        self.cursor.execute(query, (hs_code,))
        results = self.cursor.fetchall()
        
        return [dict(r) for r in results]
    
    def get_chapter_notes(self, chapter_code: str, note_type: Optional[str] = None) -> List[Dict]:
        """
        Get chapter notes for a given chapter
        
        Args:
            chapter_code: Chapter code like "07"
            note_type: Optional filter by note type (main_note, policy_condition, export_licensing)
            
        Returns:
            List of chapter notes
        """
        if note_type:
            query = """
                SELECT 
                    note_type,
                    sl_no,
                    note_text,
                    notification_no,
                    notification_date
                FROM itc_chapter_notes
                WHERE chapter_code = %s AND note_type = %s
                ORDER BY sl_no
            """
            self.cursor.execute(query, (chapter_code, note_type))
        else:
            query = """
                SELECT 
                    note_type,
                    sl_no,
                    note_text,
                    notification_no,
                    notification_date
                FROM itc_chapter_notes
                WHERE chapter_code = %s
                ORDER BY note_type, sl_no
            """
            self.cursor.execute(query, (chapter_code,))
        
        results = self.cursor.fetchall()
        return [dict(r) for r in results]
    
    def get_complete_hs_rules(self, hs_code: str) -> Dict:
        """
        Get complete rules and regulations for an HS code including:
        - Basic info
        - Policy conditions
        - Chapter notes
        
        Args:
            hs_code: HS code like "07131010"
            
        Returns:
            Complete dict with all applicable rules
        """
        # Get basic info
        hs_info = self.get_hs_code_info(hs_code)
        
        if not hs_info:
            return {
                'status': 'NOT_FOUND',
                'hs_code': hs_code,
                'message': f'HS code {hs_code} not found in database'
            }
        
        # Get policy conditions
        policies = self.get_policy_conditions(hs_code)
        
        # Get chapter notes
        chapter_notes = self.get_chapter_notes(hs_info['chapter_code'])
        
        return {
            'status': 'FOUND',
            'hs_code': hs_code,
            'basic_info': hs_info,
            'policy_conditions': policies,
            'chapter_notes': chapter_notes
        }
    
    def check_export_restrictions(self, hs_code: str) -> Dict:
        """
        Check if HS code has export restrictions
        
        Args:
            hs_code: HS code like "07131010"
            
        Returns:
            Dict with restriction status and details
        """
        rules = self.get_complete_hs_rules(hs_code)
        
        if rules['status'] == 'NOT_FOUND':
            return rules
        
        basic_info = rules['basic_info']
        
        # Determine if restricted
        is_restricted = False
        restriction_details = []
        
        # Check export policy
        if basic_info['export_policy'] and basic_info['export_policy'] != 'Free':
            is_restricted = True
            restriction_details.append({
                'type': 'EXPORT_POLICY',
                'policy': basic_info['export_policy'],
                'message': f"Export policy is '{basic_info['export_policy']}' (not Free)"
            })
        
        # Check policy conditions
        if rules['policy_conditions']:
            for policy in rules['policy_conditions']:
                if policy['policy_text']:
                    is_restricted = True
                    restriction_details.append({
                        'type': 'POLICY_CONDITION',
                        'reference': policy['policy_reference'],
                        'details': policy['policy_text'],
                        'notification': policy.get('notification_no')
                    })
        
        return {
            'status': 'CHECKED',
            'hs_code': hs_code,
            'description': basic_info['description'],
            'export_policy': basic_info['export_policy'],
            'is_restricted': is_restricted,
            'restrictions': restriction_details,
            'chapter_code': basic_info['chapter_code']
        }
    
    def get_all_restricted_codes(self, chapter_code: Optional[str] = None) -> List[Dict]:
        """
        Get all HS codes that have restrictions (not Free)
        
        Args:
            chapter_code: Optional chapter filter
            
        Returns:
            List of restricted HS codes
        """
        if chapter_code:
            query = """
                SELECT DISTINCT
                    hp.hs_code,
                    hp.description,
                    hp.export_policy,
                    hp.chapter_code
                FROM itc_hs_products hp
                LEFT JOIN itc_hs_policy_references pr ON hp.hs_code = pr.hs_code
                WHERE hp.chapter_code = %s
                AND (hp.export_policy != 'Free' OR pr.hs_code IS NOT NULL)
                ORDER BY hp.hs_code
            """
            self.cursor.execute(query, (chapter_code,))
        else:
            query = """
                SELECT DISTINCT
                    hp.hs_code,
                    hp.description,
                    hp.export_policy,
                    hp.chapter_code
                FROM itc_hs_products hp
                LEFT JOIN itc_hs_policy_references pr ON hp.hs_code = pr.hs_code
                WHERE (hp.export_policy != 'Free' OR pr.hs_code IS NOT NULL)
                ORDER BY hp.hs_code
            """
            self.cursor.execute(query)
        
        results = self.cursor.fetchall()
        return [dict(r) for r in results]
    
    def search_hs_codes(self, search_term: str, chapter_code: Optional[str] = None) -> List[Dict]:
        """
        Search for HS codes by description
        
        Args:
            search_term: Search term to find in description
            chapter_code: Optional chapter filter
            
        Returns:
            List of matching HS codes
        """
        search_pattern = f"%{search_term}%"
        
        if chapter_code:
            query = """
                SELECT 
                    hs_code,
                    description,
                    export_policy,
                    chapter_code
                FROM itc_hs_products
                WHERE chapter_code = %s
                AND description ILIKE %s
                ORDER BY hs_code
                LIMIT 50
            """
            self.cursor.execute(query, (chapter_code, search_pattern))
        else:
            query = """
                SELECT 
                    hs_code,
                    description,
                    export_policy,
                    chapter_code
                FROM itc_hs_products
                WHERE description ILIKE %s
                ORDER BY hs_code
                LIMIT 50
            """
            self.cursor.execute(query, (search_pattern,))
        
        results = self.cursor.fetchall()
        return [dict(r) for r in results]
    
    def get_hierarchy(self, hs_code: str) -> List[Dict]:
        """
        Get the full hierarchy of an HS code (parent codes)
        
        Args:
            hs_code: HS code like "07131010"
            
        Returns:
            List of parent codes in hierarchical order
        """
        query = """
            WITH RECURSIVE hierarchy AS (
                -- Base case: start with the given HS code
                SELECT 
                    hs_code,
                    description,
                    export_policy,
                    parent_hs_code,
                    level,
                    1 as depth
                FROM itc_hs_products
                WHERE hs_code = %s
                
                UNION ALL
                
                -- Recursive case: get parent codes
                SELECT 
                    p.hs_code,
                    p.description,
                    p.export_policy,
                    p.parent_hs_code,
                    p.level,
                    h.depth + 1
                FROM itc_hs_products p
                INNER JOIN hierarchy h ON p.hs_code = h.parent_hs_code
            )
            SELECT * FROM hierarchy
            ORDER BY depth DESC
        """
        
        self.cursor.execute(query, (hs_code,))
        results = self.cursor.fetchall()
        return [dict(r) for r in results]
    
    def close(self):
        """Close database connection"""
        self.cursor.close()
        self.conn.close()
        logger.info("Database connection closed")


# Example usage
if __name__ == "__main__":
    # Database configuration
    db_config = {
        'host': 'localhost',
        'database': 'PPL-AI',
        'user': 'postgres',
        'password': 'shreyaan999!',
        'port': 5432
    }
    
    # Initialize agent
    agent = ITCHSCodeAgent(db_config)
    
    try:
        # Example 1: Get complete rules for an HS code
        print("\n=== Complete Rules for HS Code 07131010 ===")
        rules = agent.get_complete_hs_rules('07131010')
        print(json.dumps(rules, indent=2, default=str))
        
        # Example 2: Check export restrictions
        print("\n=== Export Restrictions for HS Code 07131010 ===")
        restrictions = agent.check_export_restrictions('07131010')
        print(json.dumps(restrictions, indent=2, default=str))
        
        # Example 3: Search for HS codes
        print("\n=== Search for 'peas' ===")
        search_results = agent.search_hs_codes('peas', chapter_code='07')
        print(json.dumps(search_results, indent=2, default=str))
        
        # Example 4: Get all restricted codes in chapter
        print("\n=== All Restricted Codes in Chapter 07 ===")
        restricted = agent.get_all_restricted_codes(chapter_code='07')
        print(json.dumps(restricted, indent=2, default=str))
        
        # Example 5: Get hierarchy
        print("\n=== Hierarchy for HS Code 07131010 ===")
        hierarchy = agent.get_hierarchy('07131010')
        print(json.dumps(hierarchy, indent=2, default=str))
        
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        agent.close()