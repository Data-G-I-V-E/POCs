#!/usr/bin/env python3
"""
HS Code Export Data Importer
Imports export statistics from Excel files into PostgreSQL database

Usage:
    python import_export_data.py --folder /path/to/excel/files --country AUS
    python import_export_data.py --folder /path/to/excel/files --auto-detect
    python import_export_data.py --file /path/to/070310_AUS.xlsx
"""

import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch
import os
import re
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ExportDataImporter:
    """Import export data from Excel files to PostgreSQL"""
    
    # Country code mappings
    COUNTRY_MAP = {
        'AUSTRALIA': 'AUS',
        'AUS': 'AUS',
        'UAE': 'UAE',
        'UNITED ARAB EMIRATES': 'UAE',
        'UK': 'GBR',
        'UNITED KINGDOM': 'GBR',
        'GBR': 'GBR',
        'BRITAIN': 'GBR'
    }
    
    def __init__(self, db_config: Dict):
        """
        Initialize importer
        
        Args:
            db_config: Dictionary with database connection parameters
                {
                    'host': 'localhost',
                    'database': 'hs_codes_db',
                    'user': 'hs_admin',
                    'password': 'your_password',
                    'port': 5432
                }
        """
        self.db_config = db_config
        self.conn = None
        self.cursor = None
        self.stats = {
            'files_processed': 0,
            'files_failed': 0,
            'records_inserted': 0,
            'records_updated': 0,
            'records_failed': 0
        }
    
    def connect(self):
        """Connect to PostgreSQL database"""
        try:
            self.conn = psycopg2.connect(**self.db_config)
            self.cursor = self.conn.cursor()
            logger.info("✓ Connected to PostgreSQL database")
        except Exception as e:
            logger.error(f"✗ Database connection failed: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Database connection closed")
    
    def verify_tables_exist(self):
        """Verify required tables exist in database"""
        required_tables = ['chapters', 'hs_codes', 'countries', 'export_statistics', 'country_total_exports']
        
        for table in required_tables:
            self.cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                );
            """, (table,))
            
            exists = self.cursor.fetchone()[0]
            if not exists:
                logger.error(f"✗ Required table '{table}' does not exist!")
                logger.error(f"Please run the SQL schema file first: export_data_schema.sql")
                raise Exception(f"Missing required table: {table}")
        
        logger.info("✓ All required tables exist")
    
    def extract_hs_code_from_file(self, filepath: str, df: pd.DataFrame = None) -> str:
        """
        Extract HS code from filename or DataFrame
        
        Args:
            filepath: Path to Excel file
            df: Optional DataFrame with data
            
        Returns:
            HS code (e.g., '070310')
        """
        # Try to get from DataFrame first
        if df is not None and not df.empty:
            try:
                hs_code_row = df[df['S.No.'] != 'Total'].iloc[0]
                hs_code = str(hs_code_row['HSCode']).strip()
                
                # Remove dot if present
                if '.' in hs_code:
                    return hs_code.replace('.', '')
                return hs_code
            except:
                pass
        
        # Try to extract from filename
        basename = os.path.basename(filepath)
        
        # Pattern 1: 070310.xlsx or 070310_AUS.xlsx
        match = re.match(r'(\d{6})', basename)
        if match:
            raw_code = match.group(1)
            return raw_code
        
        raise ValueError(f"Could not extract HS code from file: {filepath}")
    
    def extract_country_from_file(self, filepath: str) -> Optional[str]:
        """
        Extract country code from filename
        
        Supports formats:
        - 070310_AUS.xlsx
        - 070310_Australia.xlsx
        - australia/070310.xlsx (from folder name)
        
        Returns:
            Country code (e.g., 'AUS') or None
        """
        basename = os.path.basename(filepath)
        dirname = os.path.basename(os.path.dirname(filepath))
        
        # Try filename first: 070310_AUS.xlsx or 070310_Australia.xlsx
        match = re.search(r'_([A-Za-z]+)\.xlsx$', basename)
        if match:
            country = match.group(1).upper()
            return self.COUNTRY_MAP.get(country, country)
        
        # Try folder name: australia/070310.xlsx
        if dirname and dirname.upper() in self.COUNTRY_MAP:
            return self.COUNTRY_MAP[dirname.upper()]
        
        return None
    
    def read_excel_file(self, filepath: str) -> Tuple[str, pd.DataFrame, str, pd.Series]:
        """
        Read Excel file and extract data
        
        Returns:
            (hs_code, dataframe, commodity_description, total_row)
        """
        try:
            # Read Excel with header at row 2 (0-indexed)
            df = pd.read_excel(filepath, header=2)
            
            # Extract Total row before filtering
            total_row = df[df['S.No.'] == 'Total'].iloc[0] if 'Total' in df['S.No.'].values else None
            
            # Filter out 'Total' row
            df_clean = df[df['S.No.'] != 'Total'].copy()
            
            if df_clean.empty:
                raise ValueError("No data rows found (only Total row)")
            
            # Extract HS code
            hs_code = self.extract_hs_code_from_file(filepath, df_clean)
            
            # Extract commodity description
            commodity = str(df_clean['Commodity'].iloc[0]).strip() if not df_clean.empty else ''
            
            return hs_code, df_clean, commodity, total_row
            
        except Exception as e:
            logger.error(f"Error reading Excel file {filepath}: {e}")
            raise
    
    def verify_hs_code_exists(self, hs_code: str) -> bool:
        """Check if HS code exists in hs_codes table"""
        self.cursor.execute(
            "SELECT hs_code FROM hs_codes WHERE hs_code = %s",
            (hs_code,)
        )
        return self.cursor.fetchone() is not None
    
    def import_file(self, filepath: str, country_code: str = None):
        """
        Import a single Excel file
        
        Args:
            filepath: Path to Excel file
            country_code: Optional country code (if not in filename)
        """
        logger.info(f"\n{'='*70}")
        logger.info(f"Processing: {os.path.basename(filepath)}")
        logger.info(f"{'='*70}")
        
        try:
            # Read Excel file
            hs_code, df, commodity, total_row = self.read_excel_file(filepath)
            logger.info(f"  HS Code: {hs_code}")
            logger.info(f"  Commodity: {commodity}")
            
            # Determine country code
            if country_code is None:
                country_code = self.extract_country_from_file(filepath)
            
            if country_code is None:
                logger.warning(f"  ✗ Could not determine country code. Skipping file.")
                self.stats['files_failed'] += 1
                return
            
            logger.info(f"  Country: {country_code}")
            
            # Verify HS code exists in database
            if not self.verify_hs_code_exists(hs_code):
                logger.warning(f"  ✗ HS code {hs_code} not found in hs_codes table. Skipping.")
                self.stats['files_failed'] += 1
                return
            
            # Process each row
            records_inserted = 0
            records_updated = 0
            
            for _, row in df.iterrows():
                try:
                    serial_no = int(row['S.No.']) if pd.notna(row['S.No.']) else None
                    value_2023_24 = float(row['2023-2024']) if pd.notna(row['2023-2024']) else None
                    value_2024_25 = float(row['2024-2025']) if pd.notna(row['2024-2025']) else None
                    growth_pct = float(row['%Growth']) if pd.notna(row['%Growth']) else None
                    
                    # Insert 2023-2024 data
                    if value_2023_24 is not None:
                        self.cursor.execute("""
                            INSERT INTO export_statistics 
                            (hs_code, country_code, year_label, export_value_crore, serial_number)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (hs_code, country_code, year_label) 
                            DO UPDATE SET 
                                export_value_crore = EXCLUDED.export_value_crore,
                                serial_number = EXCLUDED.serial_number,
                                updated_at = CURRENT_TIMESTAMP
                            RETURNING (xmax = 0) AS inserted
                        """, (hs_code, country_code, '2023-2024', value_2023_24, serial_no))
                        
                        was_inserted = self.cursor.fetchone()[0]
                        if was_inserted:
                            records_inserted += 1
                        else:
                            records_updated += 1
                    
                    # Insert 2024-2025 data
                    if value_2024_25 is not None:
                        self.cursor.execute("""
                            INSERT INTO export_statistics 
                            (hs_code, country_code, year_label, export_value_crore, serial_number)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (hs_code, country_code, year_label) 
                            DO UPDATE SET 
                                export_value_crore = EXCLUDED.export_value_crore,
                                serial_number = EXCLUDED.serial_number,
                                updated_at = CURRENT_TIMESTAMP
                            RETURNING (xmax = 0) AS inserted
                        """, (hs_code, country_code, '2024-2025', value_2024_25, serial_no))
                        
                        was_inserted = self.cursor.fetchone()[0]
                        if was_inserted:
                            records_inserted += 1
                        else:
                            records_updated += 1
                    
                    # Insert growth data if available
                    if growth_pct is not None and value_2023_24 is not None and value_2024_25 is not None:
                        self.cursor.execute("""
                            INSERT INTO export_growth 
                            (hs_code, country_code, from_year, to_year, growth_percentage, from_value, to_value)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (hs_code, country_code, from_year, to_year) 
                            DO UPDATE SET 
                                growth_percentage = EXCLUDED.growth_percentage,
                                from_value = EXCLUDED.from_value,
                                to_value = EXCLUDED.to_value
                        """, (hs_code, country_code, '2023-2024', '2024-2025', 
                              growth_pct, value_2023_24, value_2024_25))
                
                except Exception as e:
                    logger.error(f"  ✗ Error processing row: {e}")
                    self.stats['records_failed'] += 1
                    continue
            
            # Store country total exports if total_row exists
            if total_row is not None:
                try:
                    total_2023_24 = float(total_row['2023-2024']) if pd.notna(total_row['2023-2024']) else None
                    total_2024_25 = float(total_row['2024-2025']) if pd.notna(total_row['2024-2025']) else None
                    total_growth = float(total_row['%Growth']) if pd.notna(total_row['%Growth']) else None
                    
                    # Insert total for 2023-2024
                    if total_2023_24 is not None:
                        self.cursor.execute("""
                            INSERT INTO country_total_exports 
                            (country_code, year_label, total_export_value_crore, growth_percentage)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (country_code, year_label) 
                            DO UPDATE SET 
                                total_export_value_crore = EXCLUDED.total_export_value_crore,
                                growth_percentage = EXCLUDED.growth_percentage,
                                updated_at = CURRENT_TIMESTAMP
                        """, (country_code, '2023-2024', total_2023_24, None))
                    
                    # Insert total for 2024-2025
                    if total_2024_25 is not None:
                        self.cursor.execute("""
                            INSERT INTO country_total_exports 
                            (country_code, year_label, total_export_value_crore, growth_percentage)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (country_code, year_label) 
                            DO UPDATE SET 
                                total_export_value_crore = EXCLUDED.total_export_value_crore,
                                growth_percentage = EXCLUDED.growth_percentage,
                                updated_at = CURRENT_TIMESTAMP
                        """, (country_code, '2024-2025', total_2024_25, total_growth))
                    
                    logger.info(f"  ✓ Country totals stored: {total_2023_24} → {total_2024_25} ({total_growth}% growth)")
                except Exception as e:
                    logger.warning(f"  ⚠ Could not store country totals: {e}")
            
            # Log import metadata
            self.cursor.execute("""
                INSERT INTO import_metadata 
                (hs_code, country_code, source_file, record_count, status)
                VALUES (%s, %s, %s, %s, %s)
            """, (hs_code, country_code, os.path.basename(filepath), 
                  records_inserted + records_updated, 'SUCCESS'))
            
            self.conn.commit()
            
            logger.info(f"  ✓ Inserted: {records_inserted} records")
            logger.info(f"  ✓ Updated: {records_updated} records")
            
            self.stats['files_processed'] += 1
            self.stats['records_inserted'] += records_inserted
            self.stats['records_updated'] += records_updated
            
        except Exception as e:
            self.conn.rollback()
            logger.error(f"  ✗ Error importing file: {e}")
            self.stats['files_failed'] += 1
            
            # Log failed import
            try:
                self.cursor.execute("""
                    INSERT INTO import_metadata 
                    (hs_code, country_code, source_file, record_count, status)
                    VALUES (%s, %s, %s, %s, %s)
                """, (None, country_code, os.path.basename(filepath), 0, f'FAILED: {str(e)}'))
                self.conn.commit()
            except:
                pass
    
    def import_folder(self, folder_path: str, country_code: str = None, recursive: bool = True):
        """
        Import all Excel files from a folder
        
        Args:
            folder_path: Path to folder containing Excel files
            country_code: Optional country code to use for all files
            recursive: Whether to search subfolders
        """
        folder = Path(folder_path)
        
        if not folder.exists():
            raise ValueError(f"Folder not found: {folder_path}")
        
        # Find all Excel files
        pattern = '**/*.xlsx' if recursive else '*.xlsx'
        excel_files = list(folder.glob(pattern))
        
        logger.info(f"\n{'='*70}")
        logger.info(f"Found {len(excel_files)} Excel files in: {folder_path}")
        logger.info(f"{'='*70}\n")
        
        if len(excel_files) == 0:
            logger.warning("No Excel files found!")
            return
        
        # Process each file
        for excel_file in excel_files:
            self.import_file(str(excel_file), country_code)
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print import summary statistics"""
        logger.info(f"\n{'='*70}")
        logger.info("IMPORT SUMMARY")
        logger.info(f"{'='*70}")
        logger.info(f"Files processed successfully: {self.stats['files_processed']}")
        logger.info(f"Files failed: {self.stats['files_failed']}")
        logger.info(f"Records inserted: {self.stats['records_inserted']}")
        logger.info(f"Records updated: {self.stats['records_updated']}")
        logger.info(f"Records failed: {self.stats['records_failed']}")
        logger.info(f"{'='*70}\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Import HS Code export data from Excel files to PostgreSQL',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import single file with country in filename
  python import_export_data.py --file 070310_AUS.xlsx
  
  # Import single file with manual country code
  python import_export_data.py --file 070310.xlsx --country AUS
  
  # Import all files from folder (auto-detect country from filename/folder)
  python import_export_data.py --folder /path/to/excel/files
  
  # Import all files from folder for specific country
  python import_export_data.py --folder ./australia --country AUS
  
  # Import with custom database settings
  python import_export_data.py --folder ./data --host localhost --database hs_codes_db --user hs_admin --password mypass
        """
    )
    
    # File/folder arguments
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--file', help='Path to single Excel file')
    group.add_argument('--folder', help='Path to folder containing Excel files')
    
    # Country code
    parser.add_argument('--country', help='Country code (AUS, UAE, GBR). Auto-detected if not provided.')
    
    # Database connection
    parser.add_argument('--host', default='localhost', help='Database host (default: localhost)')
    parser.add_argument('--port', type=int, default=5432, help='Database port (default: 5432)')
    parser.add_argument('--database', default='hs_codes_db', help='Database name (default: hs_codes_db)')
    parser.add_argument('--user', default='hs_admin', help='Database user (default: hs_admin)')
    parser.add_argument('--password', required=True, help='Database password')
    
    # Options
    parser.add_argument('--no-recursive', action='store_true', help='Do not search subfolders')
    
    args = parser.parse_args()
    
    # Database configuration
    db_config = {
        'host': args.host,
        'port': args.port,
        'database': args.database,
        'user': args.user,
        'password': args.password
    }
    
    # Create importer
    importer = ExportDataImporter(db_config)
    
    try:
        # Connect to database
        importer.connect()
        
        # Verify tables exist
        importer.verify_tables_exist()
        
        # Import data
        if args.file:
            # Single file
            importer.import_file(args.file, args.country)
            importer.print_summary()
        else:
            # Folder
            importer.import_folder(args.folder, args.country, not args.no_recursive)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1
    
    finally:
        importer.close()
    
    return 0


if __name__ == "__main__":
    exit(main())