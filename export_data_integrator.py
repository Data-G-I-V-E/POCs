"""
Unified Data Integrator for Export Agent System

Combines multiple data sources into a single queryinterface:
- PostgreSQL (HS codes, restrictions, trade stats)
- ChromaDB (agreements, DGFT policies)
- Vector stores for semantic search

This is the core integration layer that all agents should use.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional, Any
import logging
import re
from pathlib import Path

from config import Config

# Import existing agents
import sys
sys.path.append(str(Config.ROOT_DIR / "storage-scripts"))

try:
    from agreements_retriever import AgreementsRetriever
except ImportError:
    AgreementsRetriever = None
    print("⚠️ AgreementsRetriever not available")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ExportDataIntegrator:
    """
    Unified interface to query all export-related data sources
    """
    
    def __init__(self, use_vector_stores: bool = True):
        """
        Initialize integrator with all data sources
        
        Args:
            use_vector_stores: Whether to load vector stores (agreements, DGFT)
        """
        logger.info("Initializing Export Data Integrator...")
        
        # Database connection
        try:
            self.conn = psycopg2.connect(**Config.DB_CONFIG)
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            logger.info("✓ Database connected")
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            self.conn = None
            self.cursor = None
        
        # Vector stores
        self.agreements_retriever = None
        if use_vector_stores and AgreementsRetriever:
            try:
                agreements_path = Config.ROOT_DIR / "agreements_rag_store"
                if agreements_path.exists():
                    self.agreements_retriever = AgreementsRetriever(agreements_path)
                    logger.info("✓ Agreements retriever loaded")
            except Exception as e:
                logger.warning(f"⚠️ Agreements retriever not available: {e}")
        
        logger.info("✓ Export Data Integrator ready!\n")

    @staticmethod
    def _sanitize_hs_code(hs_code: str) -> str:
        """Return digit-only HS code text."""
        if hs_code is None:
            return ""
        return re.sub(r"\D", "", str(hs_code))

    @classmethod
    def _normalize_hs_code(cls, hs_code: str) -> str:
        """
        Normalize HS code to stable 2/4/6/8-digit representation where possible.
        Handles dropped leading-zero cases (e.g., 1023900 -> 01023900).
        """
        digits = cls._sanitize_hs_code(hs_code)
        if not digits:
            return ""

        if len(digits) in (1, 3, 5, 7):
            digits = digits.zfill(len(digits) + 1)

        if len(digits) > 8:
            digits = digits[:8]

        return digits

    @classmethod
    def _exact_hs_candidates(cls, hs_code: str) -> List[str]:
        """Generate exact-match candidate HS codes (normalized first, then raw)."""
        raw = cls._sanitize_hs_code(hs_code)
        normalized = cls._normalize_hs_code(hs_code)

        candidates: List[str] = []
        for code in (normalized, raw):
            if code and code not in candidates:
                candidates.append(code)

        if raw and len(raw) > 8:
            raw8 = raw[:8]
            if raw8 not in candidates:
                candidates.append(raw8)

        return candidates
    
    # ========== HS CODE QUERIES ==========
    
    def get_hs_code_info(self, hs_code: str) -> Optional[Dict]:
        """
        Get comprehensive HS code information from all sources
        
        Args:
            hs_code: 6-digit or longer HS code
            
        Returns:
            Dict with HS code info, export policy, restrictions, etc.
        """
        if not self.cursor:
            return None

        hs_code = self._normalize_hs_code(hs_code)
        if not hs_code:
            return None
        
        result = {
            'hs_code': hs_code,
            'hierarchy': Config.get_hs_hierarchy(hs_code),
            'is_focus_code': Config.is_focus_hs_code(hs_code),
        }
        
        # 1. Get basic HS code info
        basic_info = self._get_hs_code_basic(hs_code)
        if basic_info:
            result.update(basic_info)
        
        # 2. Get ITC export policy
        itc_policy = self._get_itc_policy(hs_code)
        if itc_policy:
            result['itc_policy'] = itc_policy
        
        # 3. Check if prohibited
        prohibited = self._check_prohibited(hs_code)
        result['is_prohibited'] = prohibited is not None
        if prohibited:
            result['prohibited_info'] = prohibited
        
        # 4. Check if restricted
        restricted = self._check_restricted(hs_code)
        result['is_restricted'] = restricted is not None
        if restricted:
            result['restricted_info'] = restricted
        
        # 5. Check STE requirements
        ste = self._check_ste(hs_code)
        result['is_ste'] = ste is not None
        if ste:
            result['ste_info'] = ste
        
        # 6. Get chapter notes (main notes, export licensing)
        chapter_notes = self._get_chapter_notes(hs_code)
        if chapter_notes:
            result['chapter_notes'] = chapter_notes
        
        return result
    
    def _get_hs_code_basic(self, hs_code: str) -> Optional[Dict]:
        """Get basic HS code info from hs_codes table, fallback to itc_hs_products"""
        candidates = self._exact_hs_candidates(hs_code)
        if not candidates:
            return None

        # Try exact match in hs_codes first
        query = """
            SELECT hs_code, description, code_level, chapter_number, parent_code
            FROM hs_codes
            WHERE hs_code = ANY(%s)
            ORDER BY CASE WHEN hs_code = %s THEN 0 ELSE 1 END, length(hs_code) DESC
            LIMIT 1
        """
        try:
            self.cursor.execute(query, (candidates, candidates[0]))
            result = self.cursor.fetchone()
            if result:
                return dict(result)
        except Exception as e:
            logger.error(f"Error fetching HS code basic info: {e}")
        
        # Fallback: search itc_hs_products (has 8-digit codes)
        query2 = """
            SELECT hs_code, description, level AS code_level, 
                   chapter_code AS chapter_number, parent_hs_code AS parent_code
            FROM itc_hs_products
            WHERE hs_code = ANY(%s)
            ORDER BY CASE WHEN hs_code = %s THEN 0 ELSE 1 END, length(hs_code) DESC
            LIMIT 1
        """
        try:
            self.cursor.execute(query2, (candidates, candidates[0]))
            result = self.cursor.fetchone()
            if result:
                return dict(result)
        except Exception as e:
            logger.debug(f"No ITC product found for {hs_code}: {e}")
        
        # Fallback: try prefix match (user gave 6-digit, DB has 8-digit)
        prefix_code = next((code for code in candidates if len(code) <= 6), None)
        if prefix_code:
            query3 = """
                SELECT hs_code, description, level AS code_level,
                       chapter_code AS chapter_number, parent_hs_code AS parent_code
                FROM itc_hs_products
                WHERE hs_code LIKE %s
                ORDER BY length(hs_code) ASC
                LIMIT 1
            """
            try:
                self.cursor.execute(query3, (prefix_code + '%',))
                result = self.cursor.fetchone()
                if result:
                    return dict(result)
            except Exception as e:
                logger.debug(f"No ITC product found for prefix {prefix_code}: {e}")
        
        return None
    
    def _get_itc_policy(self, hs_code: str) -> Optional[Dict]:
        """Get ITC export policy with policy references from unified view"""
        candidates = self._exact_hs_candidates(hs_code)
        if not candidates:
            return None

        query = """
            SELECT hs_code, hs_description, itc_policy, 
                   itc_notification, itc_date,
                   policy_reference, policy_reference_text,
                   overall_status
            FROM v_export_policy_unified
            WHERE hs_code = ANY(%s)
            ORDER BY CASE WHEN hs_code = %s THEN 0 ELSE 1 END, length(hs_code) DESC
            LIMIT 1
        """
        try:
            self.cursor.execute(query, (candidates, candidates[0]))
            result = self.cursor.fetchone()
            if result:
                policy_dict = dict(result)
                # Add human-readable status
                if policy_dict.get('policy_reference'):
                    policy_dict['has_conditions'] = True
                    policy_dict['condition_details'] = {
                        'reference': policy_dict['policy_reference'],
                        'full_text': policy_dict['policy_reference_text']
                    }
                return policy_dict
            return None
        except Exception as e:
            logger.debug(f"No ITC policy found for {hs_code}: {e}")
            return None
    
    def _check_prohibited(self, hs_code: str) -> Optional[Dict]:
        """Check if HS code is prohibited (exact match + prefix match)"""
        candidates = self._exact_hs_candidates(hs_code)
        if not candidates:
            return None

        # Try exact match first
        query = """
            SELECT hs_code, description, export_policy, policy_condition
            FROM prohibited_items
            WHERE hs_code = ANY(%s)
            ORDER BY CASE WHEN hs_code = %s THEN 0 ELSE 1 END, length(hs_code) DESC
            LIMIT 1
        """
        try:
            self.cursor.execute(query, (candidates, candidates[0]))
            result = self.cursor.fetchone()
            if result:
                return dict(result)
        except Exception as e:
            logger.debug(f"Error checking prohibited for {hs_code}: {e}")
        
        # Prefix match: 6-digit query matches 8-digit prohibited entry
        prefix_code = next((code for code in candidates if len(code) <= 6), None)
        if prefix_code:
            query2 = """
                SELECT hs_code, description, export_policy, policy_condition
                FROM prohibited_items
                WHERE hs_code LIKE %s
                LIMIT 1
            """
            try:
                self.cursor.execute(query2, (prefix_code + '%',))
                result = self.cursor.fetchone()
                if result:
                    return dict(result)
            except Exception as e:
                logger.debug(f"Error prefix-checking prohibited for {prefix_code}: {e}")
        
        return None
    
    def _check_restricted(self, hs_code: str) -> Optional[Dict]:
        """Check if HS code is restricted (exact match + prefix match)"""
        candidates = self._exact_hs_candidates(hs_code)
        if not candidates:
            return None

        # Try exact match first
        query = """
            SELECT hs_code, description, export_policy, policy_condition
            FROM restricted_items
            WHERE hs_code = ANY(%s)
            ORDER BY CASE WHEN hs_code = %s THEN 0 ELSE 1 END, length(hs_code) DESC
            LIMIT 1
        """
        try:
            self.cursor.execute(query, (candidates, candidates[0]))
            result = self.cursor.fetchone()
            if result:
                return dict(result)
        except Exception as e:
            logger.debug(f"Error checking restricted for {hs_code}: {e}")
        
        # Prefix match: 6-digit query matches 8-digit restricted entry
        prefix_code = next((code for code in candidates if len(code) <= 6), None)
        if prefix_code:
            query2 = """
                SELECT hs_code, description, export_policy, policy_condition
                FROM restricted_items
                WHERE hs_code LIKE %s
                LIMIT 1
            """
            try:
                self.cursor.execute(query2, (prefix_code + '%',))
                result = self.cursor.fetchone()
                if result:
                    return dict(result)
            except Exception as e:
                logger.debug(f"Error prefix-checking restricted for {prefix_code}: {e}")
        
        return None
    
    def _check_ste(self, hs_code: str) -> Optional[Dict]:
        """Check if HS code requires STE (exact match + prefix match)"""
        candidates = self._exact_hs_candidates(hs_code)
        if not candidates:
            return None

        # Try exact match first
        query = """
            SELECT hs_code, description, export_policy, 
                   policy_condition, authorized_entity
            FROM ste_items
            WHERE hs_code = ANY(%s)
            ORDER BY CASE WHEN hs_code = %s THEN 0 ELSE 1 END, length(hs_code) DESC
            LIMIT 1
        """
        try:
            self.cursor.execute(query, (candidates, candidates[0]))
            result = self.cursor.fetchone()
            if result:
                return dict(result)
        except Exception as e:
            logger.debug(f"Error checking STE for {hs_code}: {e}")
        
        # Prefix match: 6-digit query matches 8-digit STE entry
        prefix_code = next((code for code in candidates if len(code) <= 6), None)
        if prefix_code:
            query2 = """
                SELECT hs_code, description, export_policy, 
                       policy_condition, authorized_entity
                FROM ste_items
                WHERE hs_code LIKE %s
                LIMIT 1
            """
            try:
                self.cursor.execute(query2, (prefix_code + '%',))
                result = self.cursor.fetchone()
                if result:
                    return dict(result)
            except Exception as e:
                logger.debug(f"Error prefix-checking STE for {prefix_code}: {e}")
        
        return None
    
    def _get_chapter_notes(self, hs_code: str) -> Optional[Dict]:
        """Get chapter notes (main notes, policy conditions, export licensing) for the HS code's chapter"""
        chapter_code = hs_code[:2]
        query = """
            SELECT note_type, sl_no, note_text
            FROM itc_chapter_notes
            WHERE chapter_code = %s
            ORDER BY note_type, sl_no
        """
        try:
            self.cursor.execute(query, (chapter_code,))
            rows = self.cursor.fetchall()
            if not rows:
                return None
            
            notes = {'chapter_code': chapter_code, 'main_notes': [], 'policy_conditions': [], 'export_licensing': []}
            
            # Also get chapter name
            try:
                self.cursor.execute(
                    "SELECT chapter_name FROM itc_chapters WHERE chapter_code = %s",
                    (chapter_code,)
                )
                ch_row = self.cursor.fetchone()
                if ch_row:
                    notes['chapter_name'] = ch_row[0] if isinstance(ch_row, tuple) else ch_row.get('chapter_name', '')
            except Exception:
                pass
            
            for row in rows:
                if isinstance(row, dict):
                    note_type = row.get('note_type', '')
                    note_text = row.get('note_text', '')
                else:
                    note_type, _, note_text = row[0], row[1], row[2]
                
                if note_type == 'main_note':
                    notes['main_notes'].append(note_text)
                elif note_type == 'policy_condition':
                    notes['policy_conditions'].append(note_text)
                elif note_type == 'export_licensing':
                    notes['export_licensing'].append(note_text)
            
            notes['total_notes'] = len(rows)
            return notes
        except Exception as e:
            logger.debug(f"Error getting chapter notes for {chapter_code}: {e}")
            return None
    
    # ========== COUNTRY-SPECIFIC QUERIES ==========
    
    def get_export_statistics(
        self, 
        hs_code: str, 
        country: str,
        years: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Get export statistics for HS code to specific country
        
        Args:
            hs_code: HS code
            country: Country code (australia, uae, uk)
            years: Optional list of year labels (e.g., ['2023-2024'])
            
        Returns:
            List of export statistics records
        """
        if not self.cursor:
            return []
        
        country_code = Config.COUNTRY_CODES.get(country.lower(), country.upper())
        
        query = """
            SELECT es.*, c.country_name
            FROM export_statistics es
            JOIN countries c ON es.country_code = c.country_code
            WHERE es.hs_code = %s AND es.country_code = %s
        """
        
        params = [hs_code, country_code]
        
        if years:
            query += " AND es.year_label = ANY(%s)"
            params.append(years)
        
        query += " ORDER BY es.year_label DESC"
        
        try:
            self.cursor.execute(query, params)
            results = self.cursor.fetchall()
            return [dict(r) for r in results]
        except Exception as e:
            logger.error(f"Error fetching export statistics: {e}")
            return []
    
    def search_trade_agreements(
        self,
        query: str,
        country: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict]:
        """
        Search trade agreements using semantic search
        
        Args:
            query: Natural language query
            country: Optional country filter
            top_k: Number of results
            
        Returns:
            List of relevant document chunks
        """
        if not self.agreements_retriever:
            logger.warning("Agreements retriever not available")
            return []
        
        try:
            results = self.agreements_retriever.search(
                query=query,
                top_k=top_k,
                country=country
            )
            return results
        except Exception as e:
            logger.error(f"Error searching agreements: {e}")
            return []
    
    # ========== COMPREHENSIVE QUERIES ==========
    
    def can_export_to_country(
        self,
        hs_code: str,
        country: str,
        check_agreements: bool = True
    ) -> Dict[str, Any]:
        """
        Comprehensive check if HS code can be exported to country
        
        Args:
            hs_code: HS code to check
            country: Destination country
            check_agreements: Whether to search agreement details
            
        Returns:
            Dict with export feasibility assessment
        """
        normalized_hs_code = self._normalize_hs_code(hs_code)
        effective_hs_code = normalized_hs_code or hs_code

        result = {
            'hs_code': effective_hs_code,
            'country': country,
            'can_export': True,  # Assume yes until proven otherwise
            'issues': [],
            'warnings': [],
            'requirements': [],
        }
        
        # 1. Get HS code info (never early-return — always check restrictions)
        hs_info = self.get_hs_code_info(effective_hs_code)
        if not hs_info:
            # Still try to build partial info with what we have
            hs_info = {
                'hs_code': effective_hs_code,
                'is_prohibited': False,
                'is_restricted': False,
                'is_ste': False,
            }
            result['warnings'].append(f"HS code {effective_hs_code} has limited data in database")
        
        result['hs_info'] = hs_info
        
        # 2. Check prohibitions
        if hs_info.get('is_prohibited'):
            prohibited_info = hs_info['prohibited_info']
            result['can_export'] = False
            result['issues'].append(
                f"PROHIBITED: {prohibited_info.get('policy_condition', 'Export not allowed')}"
            )
        
        # 3. Check restrictions
        if hs_info.get('is_restricted'):
            restricted_info = hs_info['restricted_info']
            result['warnings'].append(
                f"RESTRICTED: {restricted_info.get('policy_condition', 'Special conditions apply')}"
            )
            result['requirements'].append("Check restricted items policy conditions")
        
        # 4. Check STE
        if hs_info.get('is_ste'):
            ste_info = hs_info['ste_info']
            entity = ste_info.get('authorized_entity')
            condition = ste_info.get('policy_condition', '')
            if entity:
                result['requirements'].append(
                    f"STE (State Trading): Export only through {entity}"
                )
            elif condition:
                result['requirements'].append(
                    f"STE (State Trading): {condition}"
                )
            else:
                result['requirements'].append(
                    "STE (State Trading): Canalized through designated State Trading Enterprise"
                )
        
        # 5. Get export statistics
        stats_hs_code = effective_hs_code[:6] if len(effective_hs_code) >= 6 else effective_hs_code
        stats = self.get_export_statistics(stats_hs_code, country)
        if stats:
            result['trade_statistics'] = stats
            result['has_trade_history'] = True
        else:
            result['has_trade_history'] = False
            result['warnings'].append("No historical trade data found for this route")
        
        # 6. Search trade agreements
        if check_agreements and self.agreements_retriever:
            search_query = f"export {effective_hs_code} tariff duty requirements"
            agreement_docs = self.search_trade_agreements(search_query, country, top_k=3)
            if agreement_docs:
                result['agreement_references'] = [
                    {
                        'document': doc['metadata'].get('filename'),
                        'relevance': doc['similarity_score'],
                        'preview': doc['text'][:200]
                    }
                    for doc in agreement_docs
                ]
        
        return result
    
    def get_focus_codes_summary(self) -> Dict[str, Any]:
        """Get summary of all focus HS codes with export status"""
        summary = {
            'total_codes': len(Config.FOCUS_HS_CODES),
            'codes_by_chapter': {},
            'exportable_codes': [],
            'restricted_codes': [],
            'prohibited_codes': [],
        }
        
        for hs_code in Config.FOCUS_HS_CODES:
            chapter = Config.get_chapter_from_hs(hs_code)
            
            if chapter not in summary['codes_by_chapter']:
                summary['codes_by_chapter'][chapter] = []
            
            info = self.get_hs_code_info(hs_code)
            if info:
                code_summary = {
                    'hs_code': hs_code,
                    'description': info.get('description', 'N/A')[:50],
                    'status': 'Free'
                }
                
                if info.get('is_prohibited'):
                    code_summary['status'] = 'Prohibited'
                    summary['prohibited_codes'].append(hs_code)
                elif info.get('is_restricted'):
                    code_summary['status'] = 'Restricted'
                    summary['restricted_codes'].append(hs_code)
                else:
                    summary['exportable_codes'].append(hs_code)
                
                summary['codes_by_chapter'][chapter].append(code_summary)
        
        return summary
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.cursor.close()
            self.conn.close()
            logger.info("Database connection closed")


def demo_integrator():
    """Demonstrate the unified data integrator"""
    print("="*70)
    print("EXPORT DATA INTEGRATOR - DEMO")
    print("="*70)
    
    integrator = ExportDataIntegrator()
    
    # Test HS code lookup
    test_code = "070310"
    print(f"\n1. HS Code Information: {test_code}")
    print("-"*70)
    info = integrator.get_hs_code_info(test_code)
    if info:
        print(f"   Description: {info.get('description', 'N/A')}")
        print(f"   Chapter: {info['hierarchy']['chapter']}")
        print(f"   Prohibited: {info.get('is_prohibited', False)}")
        print(f"   Restricted: {info.get('is_restricted', False)}")
        print(f"   STE: {info.get('is_ste', False)}")
    
    # Test export check
    print(f"\n2. Can Export Check: {test_code} → Australia")
    print("-"*70)
    export_check = integrator.can_export_to_country(test_code, "australia")
    print(f"   Can Export: {export_check['can_export']}")
    print(f"   Issues: {len(export_check['issues'])}")
    print(f"   Warnings: {len(export_check['warnings'])}")
    print(f"   Requirements: {len(export_check['requirements'])}")
    
    # Test focus codes summary
    print(f"\n3. Focus Codes Summary")
    print("-"*70)
    summary = integrator.get_focus_codes_summary()
    print(f"   Total Focus Codes: {summary['total_codes']}")
    print(f"   Exportable: {len(summary['exportable_codes'])}")
    print(f"   Restricted: {len(summary['restricted_codes'])}")
    print(f"   Prohibited: {len(summary['prohibited_codes'])}")
    
    integrator.close()


if __name__ == "__main__":
    demo_integrator()
