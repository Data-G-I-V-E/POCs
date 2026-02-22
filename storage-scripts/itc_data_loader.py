"""
ITC HS Code Data Loader
Parses ITC HS notification PDFs and loads data into PostgreSQL
"""

import re
import psycopg2
from psycopg2.extras import execute_batch
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ITCHSDataLoader:
    """Loads ITC HS Code data into PostgreSQL database"""
    
    def __init__(self, db_config: Dict):
        """
        Initialize database connection
        
        Args:
            db_config: Dict with keys: host, database, user, password, port
        """
        self.conn = psycopg2.connect(**db_config)
        self.cursor = self.conn.cursor()
        
    def parse_hs_code_line(self, line: str) -> Optional[Dict]:
        """
        Parse a single HS code line from the table
        
        Args:
            line: String like "07011000 Seed Free"
            
        Returns:
            Dict with hs_code, description, export_policy, additional_info
        """
        line = line.strip()
        if not line:
            return None
            
        # Pattern: HS_CODE DESCRIPTION EXPORT_POLICY [ADDITIONAL_INFO]
        # HS code can be 4, 6, 8, or 10 digits
        pattern = r'^(\d{4,10})\s+(.+?)\s+(Free|Prohibited|Restricted)(.*)$'
        match = re.match(pattern, line)
        
        if match:
            return {
                'hs_code': match.group(1),
                'description': match.group(2).strip(),
                'export_policy': match.group(3),
                'additional_info': match.group(4).strip()
            }
        
        # Try pattern without export policy (for parent codes)
        pattern_no_policy = r'^(\d{4,10})\s+(.+)$'
        match = re.match(pattern_no_policy, line)
        if match:
            return {
                'hs_code': match.group(1),
                'description': match.group(2).strip(),
                'export_policy': None,
                'additional_info': ''
            }
            
        return None
    
    def extract_policy_reference(self, additional_info: str) -> Optional[str]:
        """
        Extract policy condition reference from additional info
        
        Args:
            additional_info: String like "Subject to Policy Condition 1 of the Chapter"
            
        Returns:
            String like "Policy Condition 1" or None
        """
        if not additional_info:
            return None
            
        pattern = r'Subject\s+to\s+Policy\s+Condition\s+(\d+)\s+of\s+the\s+Chapter'
        match = re.search(pattern, additional_info, re.IGNORECASE)
        
        if match:
            return f"Policy Condition {match.group(1)}"
        return None
    
    def extract_notification_info(self, additional_info: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract notification number and date from additional info
        
        Args:
            additional_info: String containing notification details
            
        Returns:
            Tuple of (notification_no, notification_date)
        """
        notification_no = None
        notification_date = None
        
        # Pattern for notification number: "38/2015-20"
        notif_pattern = r'(\d+/\d{4}-\d{2})'
        notif_match = re.search(notif_pattern, additional_info)
        if notif_match:
            notification_no = notif_match.group(1)
        
        # Pattern for date: "22.11.2017" or "13.09.2024"
        date_pattern = r'(\d{2}\.\d{2}\.\d{4})'
        date_match = re.search(date_pattern, additional_info)
        if date_match:
            date_str = date_match.group(1)
            try:
                notification_date = datetime.strptime(date_str, '%d.%m.%Y').date()
            except ValueError:
                logger.warning(f"Could not parse date: {date_str}")
        
        return notification_no, notification_date
    
    def determine_parent_code(self, hs_code: str) -> Optional[str]:
        """
        Determine parent HS code based on hierarchy
        
        Args:
            hs_code: HS code like "07011000"
            
        Returns:
            Parent code like "0701" or None if it's a top-level code
        """
        code_len = len(hs_code)
        
        if code_len <= 4:
            return None  # Top-level, no parent
        elif code_len == 6:
            return hs_code[:4]  # Parent is 4-digit
        elif code_len == 8:
            return hs_code[:6]  # Parent is 6-digit
        elif code_len == 10:
            return hs_code[:8]  # Parent is 8-digit
        
        return None
    
    def insert_chapter(self, chapter_code: str, chapter_name: str):
        """Insert or update chapter"""
        query = """
            INSERT INTO itc_chapters (chapter_code, chapter_name)
            VALUES (%s, %s)
            ON CONFLICT (chapter_code) DO UPDATE 
            SET chapter_name = EXCLUDED.chapter_name,
                updated_at = CURRENT_TIMESTAMP
        """
        self.cursor.execute(query, (chapter_code, chapter_name))
        # Removed verbose logging - will be logged by caller
    
    def insert_chapter_note(self, chapter_code: str, note_type: str, 
                           sl_no: int, note_text: str,
                           notification_no: Optional[str] = None,
                           notification_date: Optional[str] = None):
        """Insert chapter note"""
        query = """
            INSERT INTO itc_chapter_notes 
            (chapter_code, note_type, sl_no, note_text, notification_no, notification_date)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """
        self.cursor.execute(query, (
            chapter_code, note_type, sl_no, note_text,
            notification_no, notification_date
        ))
    
    def insert_hs_product(self, chapter_code: str, hs_code: str, 
                         description: str, export_policy: Optional[str],
                         notification_no: Optional[str] = None,
                         notification_date: Optional[str] = None) -> int:
        """
        Insert or update HS product
        
        Returns:
            ID of inserted/updated record
        """
        parent_code = self.determine_parent_code(hs_code)
        level = len(hs_code)
        
        query = """
            INSERT INTO itc_hs_products 
            (chapter_code, hs_code, description, export_policy, parent_hs_code, 
             level, notification_no, notification_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (hs_code) DO UPDATE 
            SET description = EXCLUDED.description,
                export_policy = EXCLUDED.export_policy,
                notification_no = EXCLUDED.notification_no,
                notification_date = EXCLUDED.notification_date,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
        """
        
        self.cursor.execute(query, (
            chapter_code, hs_code, description, export_policy,
            parent_code, level, notification_no, notification_date
        ))
        
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def insert_policy_reference(self, hs_code: str, policy_reference: str,
                               chapter_code: str,
                               notification_no: Optional[str] = None,
                               notification_date: Optional[str] = None):
        """Insert policy reference for HS code"""
        query = """
            INSERT INTO itc_hs_policy_references 
            (hs_code, policy_reference, chapter_code, notification_no, notification_date)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """
        
        self.cursor.execute(query, (
            hs_code, policy_reference, chapter_code,
            notification_no, notification_date
        ))
    
    def insert_chapter_policy(self, chapter_code: str, policy_type: str,
                             policy_text: str,
                             notification_no: Optional[str] = None,
                             notification_date: Optional[str] = None):
        """Insert or update chapter policy definition"""
        query = """
            INSERT INTO itc_chapter_policies 
            (chapter_code, policy_type, policy_text, notification_no, notification_date)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chapter_code, policy_type) DO UPDATE
            SET policy_text = EXCLUDED.policy_text,
                notification_no = EXCLUDED.notification_no,
                notification_date = EXCLUDED.notification_date,
                updated_at = CURRENT_TIMESTAMP
        """
        
        self.cursor.execute(query, (
            chapter_code, policy_type, policy_text,
            notification_no, notification_date
        ))
    
    def load_hs_codes_from_list(self, chapter_code: str, hs_code_lines: List[str]):
        """
        Load multiple HS codes from a list of lines
        
        Args:
            chapter_code: Chapter code like "07"
            hs_code_lines: List of strings, each containing HS code data
        """
        loaded_count = 0
        for line in hs_code_lines:
            parsed = self.parse_hs_code_line(line)
            if not parsed:
                continue
            
            # Extract notification info
            notif_no, notif_date = self.extract_notification_info(
                parsed['additional_info']
            )
            
            # Insert HS product
            self.insert_hs_product(
                chapter_code=chapter_code,
                hs_code=parsed['hs_code'],
                description=parsed['description'],
                export_policy=parsed['export_policy'],
                notification_no=notif_no,
                notification_date=notif_date
            )
            
            # Check for policy reference
            policy_ref = self.extract_policy_reference(parsed['additional_info'])
            if policy_ref:
                self.insert_policy_reference(
                    hs_code=parsed['hs_code'],
                    policy_reference=policy_ref,
                    chapter_code=chapter_code,
                    notification_no=notif_no,
                    notification_date=notif_date
                )
            
            loaded_count += 1
        
        # Log summary instead of each code
        if loaded_count > 0:
            logger.debug(f"Loaded {loaded_count} HS codes for chapter {chapter_code}")
    
    def commit(self):
        """Commit transaction"""
        self.conn.commit()
        logger.info("✓ All changes committed to database")
    
    def rollback(self):
        """Rollback transaction"""
        self.conn.rollback()
        logger.warning("⚠ Transaction rolled back")
    
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
    
    # Initialize loader
    loader = ITCHSDataLoader(db_config)
    
    try:
        # Insert chapter
        loader.insert_chapter('07', 'Edible Vegetables And Certain Roots And Tubers')
        
        # Insert chapter notes
        loader.insert_chapter_note(
            chapter_code='07',
            note_type='main_note',
            sl_no=1,
            note_text='This Chapter does not cover forage products of heading 1214.'
        )
        
        # Insert chapter policy
        loader.insert_chapter_policy(
            chapter_code='07',
            policy_type='Policy Condition 1',
            policy_text='Export shall be through Custom EDI ports. However, export through the non-EDI Land Custom Stations (LCS) on Indo-Bangladesh and Indo-Nepal border shall also be allowed subject to registration of quantity with DGFT.'
        )
        
        # Load HS codes
        hs_codes = [
            "07011000 Seed Free",
            "07019000 Other Free",
            "07131010 Yellow peas Free Subject to Policy Condition 1 of the Chapter 38/2015-20 22.11.2017",
            "07132010 Kabuli chana Free Subject to Policy Condition 1 of the Chapter 38/2015-20 22.11.2017"
        ]
        
        loader.load_hs_codes_from_list('07', hs_codes)
        
        # Commit changes
        loader.commit()
        
    except Exception as e:
        logger.error(f"Error: {e}")
        loader.rollback()
    finally:
        loader.close()