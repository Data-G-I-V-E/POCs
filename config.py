"""
Centralized Configuration Management
Loads settings from .env file and provides easy access
"""

import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Centralized configuration for the export agent system"""
    
    # Base Paths
    ROOT_DIR = Path(__file__).parent
    DATA_DIR = ROOT_DIR / "data"
    
    # Database Configuration
    DB_CONFIG = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': int(os.getenv('DB_PORT', '5432')),
        'database': os.getenv('DB_NAME', os.getenv('POSTGRES_DB', 'PPL-AI')),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', os.getenv('POSTGRES_PASSWORD', '')),
    }
    
    # Vector Store Paths
    AGREEMENTS_CHROMA_PATH = Path(os.getenv(
        'AGREEMENTS_CHROMA_PATH',
        str(ROOT_DIR / 'agreements_rag_store' / 'agreements_chroma')
    ))
    
    DGFT_CHROMA_PATH = Path(os.getenv(
        'DGFT_CHROMA_PATH',
        str(ROOT_DIR / 'dgft_chroma_db')
    ))
    
    # Data Directories
    AGREEMENTS_DIR = DATA_DIR / 'agreements'
    HS_CODES_DIR = DATA_DIR / 'hs_codes'
    POLICIES_DIR = DATA_DIR / 'policies'
    DGFT_FTP_DIR = POLICIES_DIR / 'DGFT_FTP'
    ITC_NOTIFICATIONS_DIR = POLICIES_DIR / 'ITC_HS_notifications'
    
    # API Keys
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
    
    # Qdrant Configuration
    QDRANT_URL     = os.getenv('QDRANT_URL', 'http://localhost:6333')
    QDRANT_API_KEY = os.getenv('QDRANT_API_KEY', '')   # leave blank for local
    QDRANT_AGREEMENTS_COLLECTION = os.getenv('QDRANT_AGREEMENTS_COLLECTION', 'trade_agreements')
    QDRANT_DGFT_COLLECTION       = os.getenv('QDRANT_DGFT_COLLECTION', 'dgft_ftp')
    QDRANT_EMBEDDING_DIM         = int(os.getenv('QDRANT_EMBEDDING_DIM', '384'))  # all-MiniLM-L6-v2
    # Separate from EMBEDDING_MODEL so voyage scripts don't interfere with Qdrant
    QDRANT_EMBEDDING_MODEL       = os.getenv('QDRANT_EMBEDDING_MODEL', 'all-MiniLM-L6-v2')

    # Embedding Model
    EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
    
    # LLM Configuration
    LLM_MODEL = os.getenv('LLM_MODEL', 'claude-sonnet-4-20250514')
    LLM_TEMPERATURE = float(os.getenv('LLM_TEMPERATURE', '0.1'))
    
    # Agreements RAG Store Path
    AGREEMENTS_RAG_STORE_PATH = ROOT_DIR / 'agreements_rag_store'
    
    # Focus HS Codes (6-digit codes you're targeting)
    FOCUS_HS_CODES = [
        # Agriculture
        '070310', '070700', '070960',  # Chapter 7
        '080310', '080410', '080450',  # Chapter 8
        # Textiles
        '610910', '610342', '610442',  # Chapter 61
        '620342', '620462', '620520',  # Chapter 62
        # Electronics
        '850440', '851310', '851762',  # Chapter 85
        # Instruments
        '902610',                       # Chapter 90
    ]
    
    # HS Chapters of interest
    FOCUS_CHAPTERS = ['07', '08', '61', '62', '85', '90']
    
    # Target Countries
    TARGET_COUNTRIES = ['australia', 'uae', 'uk']
    
    COUNTRY_CODES = {
        'australia': 'AUS',
        'uae': 'UAE',
        'uk': 'GBR',
    }
    
    # Chapter descriptions
    CHAPTER_DESCRIPTIONS = {
        '07': 'Edible vegetables and certain roots and tubers',
        '08': 'Edible fruit and nuts; peel of citrus fruit or melons',
        '61': 'Articles of apparel and clothing accessories, knitted or crocheted',
        '62': 'Articles of apparel and clothing accessories, not knitted or crocheted',
        '85': 'Electrical machinery and equipment',
        '90': 'Optical, photographic, cinematographic, measuring instruments',
    }
    
    @classmethod
    def get_chapter_from_hs(cls, hs_code: str) -> str:
        """Extract chapter number from HS code"""
        return hs_code[:2] if len(hs_code) >= 2 else ''
    
    @classmethod
    def get_hs_hierarchy(cls, hs_code: str) -> dict:
        """Get HS code hierarchy levels"""
        if len(hs_code) < 2:
            return {}
        
        return {
            'chapter': hs_code[:2],      # HS-2
            'heading': hs_code[:4] if len(hs_code) >= 4 else None,  # HS-4
            'subheading': hs_code[:6] if len(hs_code) >= 6 else None,  # HS-6
            'full_code': hs_code
        }
    
    @classmethod
    def is_focus_hs_code(cls, hs_code: str) -> bool:
        """Check if HS code is in focus list"""
        hs_6 = hs_code[:6] if len(hs_code) >= 6 else hs_code
        return hs_6 in cls.FOCUS_HS_CODES
    
    @classmethod
    def is_focus_chapter(cls, chapter: str) -> bool:
        """Check if chapter is in focus list"""
        return chapter in cls.FOCUS_CHAPTERS
    
    @classmethod
    def validate_config(cls) -> List[str]:
        """Validate configuration and return list of issues"""
        issues = []
        
        # Check database password
        if not cls.DB_CONFIG['password']:
            issues.append("Database password not set in .env file")
        
        # Check critical paths
        if not cls.DATA_DIR.exists():
            issues.append(f"Data directory not found: {cls.DATA_DIR}")
        
        if not cls.AGREEMENTS_DIR.exists():
            issues.append(f"Agreements directory not found: {cls.AGREEMENTS_DIR}")
        
        return issues


def print_config_info():
    """Print configuration summary"""
    print("="*70)
    print("EXPORT AGENT SYSTEM - CONFIGURATION")
    print("="*70)
    print(f"\nDatabase:")
    print(f"  Host: {Config.DB_CONFIG['host']}:{Config.DB_CONFIG['port']}")
    print(f"  Database: {Config.DB_CONFIG['database']}")
    print(f"  User: {Config.DB_CONFIG['user']}")
    
    print(f"\nData Directories:")
    print(f"  Root: {Config.ROOT_DIR}")
    print(f"  Data: {Config.DATA_DIR}")
    print(f"  Agreements: {Config.AGREEMENTS_DIR}")
    print(f"  Policies: {Config.POLICIES_DIR}")
    
    print(f"\nVector Stores:")
    print(f"  Agreements: {Config.AGREEMENTS_CHROMA_PATH}")
    print(f"  DGFT: {Config.DGFT_CHROMA_PATH}")
    
    print(f"\nFocus Areas:")
    print(f"  Chapters: {', '.join(Config.FOCUS_CHAPTERS)}")
    print(f"  HS Codes: {len(Config.FOCUS_HS_CODES)} codes")
    print(f"  Countries: {', '.join(Config.TARGET_COUNTRIES)}")
    
    # Validate
    issues = Config.validate_config()
    if issues:
        print(f"\n⚠️  Configuration Issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print(f"\n✓ Configuration validated successfully")
    
    print("="*70)


if __name__ == "__main__":
    # Test configuration
    print_config_info()
    
    # Test HS code functions
    print("\nTesting HS Code Functions:")
    test_code = "070310"
    print(f"  HS Code: {test_code}")
    print(f"  Chapter: {Config.get_chapter_from_hs(test_code)}")
    print(f"  Hierarchy: {Config.get_hs_hierarchy(test_code)}")
    print(f"  Is Focus Code: {Config.is_focus_hs_code(test_code)}")
