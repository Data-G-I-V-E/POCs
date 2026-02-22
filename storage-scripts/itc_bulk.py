"""
Improved Bulk PDF Processor using pdfplumber
Better for extracting tabular data from ITC HS Code PDFs
"""

import os
import re
import pdfplumber
from pathlib import Path
from typing import Dict, List, Optional
import logging
from datetime import datetime
from itc_data_loader import ITCHSDataLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ImprovedPDFExtractor:
    """Extract ITC HS Code data using pdfplumber for better table handling"""
    
    def __init__(self):
        self.chapter_code = None
        
    def extract_chapter_number(self, filename: str) -> Optional[str]:
        """Extract chapter number from filename like 'Ch-7.pdf' or 'ch-61.pdf'"""
        pattern = r'[Cc]h-?(\d+)\.pdf'
        match = re.search(pattern, filename)
        
        if match:
            chapter_num = match.group(1)
            return chapter_num.zfill(2)  # Pad with 0
        return None
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        # Replace multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def extract_chapter_info(self, pdf_path: str) -> Dict:
        """
        Extract chapter name and basic info from first page
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Dict with chapter_code and chapter_name
        """
        filename = os.path.basename(pdf_path)
        chapter_code = self.extract_chapter_number(filename)
        
        if not chapter_code:
            logger.error(f"Could not extract chapter number from filename: {filename}")
            return None
        
        chapter_name = f"Chapter {chapter_code}"
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if pdf.pages:
                    first_page_text = pdf.pages[0].extract_text()
                    
                    # Try to find chapter name
                    patterns = [
                        rf'Chapter\s+{int(chapter_code)}\s+(.+?)(?:\n|Main Notes)',
                        rf'Ch\s+{int(chapter_code)}\s+(.+?)(?:\n|Main Notes)',
                        rf'CHAPTER\s+{int(chapter_code)}\s+(.+?)(?:\n|MAIN NOTES)',
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, first_page_text, re.IGNORECASE | re.DOTALL)
                        if match:
                            name = match.group(1).strip()
                            name = self.clean_text(name)
                            # Remove any trailing periods or extra text
                            name = re.sub(r'\.+$', '', name)
                            if len(name) > 5 and len(name) < 200:
                                chapter_name = name
                                break
        except Exception as e:
            logger.warning(f"Could not extract chapter name: {e}")
        
        return {
            'chapter_code': chapter_code,
            'chapter_name': chapter_name
        }
    
    def extract_notes_section(self, text: str, section_name: str) -> List[Dict]:
        """
        Extract numbered notes from a section
        
        Args:
            text: Full text content
            section_name: Section name like 'Main Notes', 'Policy Condition'
            
        Returns:
            List of note dictionaries
        """
        notes = []
        
        # More flexible patterns for section matching
        if section_name == "Main Notes":
            section_patterns = [
                r'Main Notes.*?(?=\nPolicy Condition|Export Licensing|Product Description|Itc\(hs\)|$)',
                r'MAIN NOTES.*?(?=\nPOLICY CONDITION|EXPORT LICENSING|PRODUCT DESCRIPTION|ITC\(HS\)|$)',
                r'Chapter Notes.*?(?=\nPolicy Condition|Export Licensing|Product Description|Itc\(hs\)|$)',
            ]
        elif section_name == "Policy Condition":
            section_patterns = [
                r'Policy Condition.*?(?=\nExport Licensing|Product Description|Itc\(hs\)|$)',
                r'POLICY CONDITION.*?(?=\nEXPORT LICENSING|PRODUCT DESCRIPTION|ITC\(HS\)|$)',
                r'Policy Conditions.*?(?=\nExport Licensing|Product Description|Itc\(hs\)|$)',
            ]
        elif section_name == "Export Licensing Notes":
            section_patterns = [
                r'Export Licensing Notes.*?(?=\nProduct Description|Itc\(hs\)|$)',
                r'EXPORT LICENSING NOTES.*?(?=\nPRODUCT DESCRIPTION|ITC\(HS\)|$)',
                r'Export Licensing.*?(?=\nProduct Description|Itc\(hs\)|$)',
            ]
        else:
            return notes
        
        # Try each pattern
        section_text = None
        for pattern in section_patterns:
            section_match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if section_match:
                section_text = section_match.group(0)
                logger.debug(f"Found section '{section_name}' with pattern: {pattern[:30]}...")
                break
        
        if not section_text:
            logger.debug(f"Section '{section_name}' not found in document")
            return notes
        
        # Extract numbered items
        # Pattern: number followed by text until next number or section end
        lines = section_text.split('\n')
        current_note = None
        current_num = None
        
        for line in lines:
            line = line.strip()
            
            # Check if line starts with a number
            num_match = re.match(r'^(\d+)\s+(.+)', line)
            
            if num_match:
                # Save previous note if exists
                if current_note and len(current_note) > 10:
                    notes.append({
                        'sl_no': current_num,
                        'note_text': self.clean_text(current_note)
                    })
                
                # Start new note
                current_num = int(num_match.group(1))
                current_note = num_match.group(2)
            elif current_note is not None and line and not line.startswith(('Notification', 'Sl.No')):
                # Continue previous note
                current_note += " " + line
        
        # Save last note
        if current_note and len(current_note) > 10:
            notes.append({
                'sl_no': current_num,
                'note_text': self.clean_text(current_note)
            })
        
        return notes
    
    def extract_hs_codes_from_table(self, pdf_path: str) -> List[str]:
        """
        Extract HS code lines from PDF tables
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of HS code line strings
        """
        hs_lines = []
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    # Extract tables
                    tables = page.extract_tables()
                    
                    if tables:
                        for table in tables:
                            for row in table:
                                if not row or len(row) < 2:
                                    continue
                                
                                # First column should be HS code
                                hs_code = str(row[0]).strip() if row[0] else ""
                                
                                # Check if it looks like an HS code
                                if re.match(r'^\d{4,10}$', hs_code):
                                    # Combine all columns into a line
                                    line_parts = [str(cell).strip() if cell else "" for cell in row]
                                    line = " ".join(line_parts)
                                    line = self.clean_text(line)
                                    
                                    if line:
                                        hs_lines.append(line)
                    
                    # Also extract text and look for HS code patterns
                    text = page.extract_text()
                    if text:
                        for line in text.split('\n'):
                            line = line.strip()
                            # Look for lines starting with HS code
                            if re.match(r'^\d{4,10}\s+\w', line):
                                hs_lines.append(line)
        
        except Exception as e:
            logger.error(f"Error extracting HS codes from {pdf_path}: {e}")
        
        # Deduplicate while preserving order
        seen = set()
        unique_lines = []
        for line in hs_lines:
            # Use first 8-10 characters as key (HS code part)
            key = line[:10]
            if key not in seen:
                seen.add(key)
                unique_lines.append(line)
        
        return unique_lines
    
    def extract_all_from_pdf(self, pdf_path: str) -> Dict:
        """
        Extract all data from a PDF file
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Dictionary with all extracted data
        """
        logger.info(f"Processing {os.path.basename(pdf_path)}...")
        
        # Get chapter info
        chapter_info = self.extract_chapter_info(pdf_path)
        if not chapter_info:
            logger.error(f"Could not extract chapter info from {pdf_path}")
            return None
        
        # Extract full text for notes sections
        full_text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    full_text += page.extract_text() or ""
        except Exception as e:
            logger.error(f"Error reading PDF: {e}")
            return None
        
        # Extract sections
        main_notes = self.extract_notes_section(full_text, "Main Notes")
        policy_conditions = self.extract_notes_section(full_text, "Policy Condition")
        export_licensing = self.extract_notes_section(full_text, "Export Licensing Notes")
        
        # Extract HS codes
        hs_code_lines = self.extract_hs_codes_from_table(pdf_path)
        
        result_summary = (f"Chapter {chapter_info['chapter_code']}: "
                         f"{len(main_notes)} main notes, "
                         f"{len(policy_conditions)} policy conditions, "
                         f"{len(export_licensing)} licensing notes, "
                         f"{len(hs_code_lines)} HS codes")
        logger.info(result_summary)
        
        # Warn if nothing was extracted
        if not main_notes and not policy_conditions and not export_licensing and not hs_code_lines:
            logger.warning(f"No data extracted from {os.path.basename(pdf_path)}! Check PDF format.")
        
        return {
            'chapter_code': chapter_info['chapter_code'],
            'chapter_name': chapter_info['chapter_name'],
            'main_notes': main_notes,
            'policy_conditions': policy_conditions,
            'export_licensing_notes': export_licensing,
            'hs_code_lines': hs_code_lines
        }


class SimpleBulkProcessor:
    """Simple processor for multiple chapter PDFs"""
    
    def __init__(self, db_config: Dict):
        self.extractor = ImprovedPDFExtractor()
        self.loader = ITCHSDataLoader(db_config)
        
    def process_folder(self, folder_path: str):
        """
        Process all Chapter PDFs in a folder
        
        Args:
            folder_path: Path to folder containing Ch-*.pdf files
        """
        folder = Path(folder_path)
        
        if not folder.exists():
            logger.error(f"Folder not found: {folder_path}")
            return
        
        # Find all Chapter PDFs (Ch-*.pdf or ch-*.pdf)
        pdf_files = list(folder.glob("[Cc]h-*.pdf"))
        pdf_files = sorted(pdf_files, key=lambda x: self.extractor.extract_chapter_number(x.name) or "")
        
        if not pdf_files:
            logger.warning(f"No Chapter PDFs found in {folder_path}")
            logger.info("Looking for files matching pattern: Ch-*.pdf or ch-*.pdf")
            return
        
        logger.info(f"Found {len(pdf_files)} Chapter PDFs to process:")
        for pdf_file in pdf_files:
            chapter_num = self.extractor.extract_chapter_number(pdf_file.name)
            logger.info(f"  - {pdf_file.name} (Chapter {chapter_num})")
        
        success_count = 0
        error_count = 0
        
        for pdf_file in pdf_files:
            try:
                # Extract data
                logger.info(f"\n{'='*60}")
                logger.info(f"Processing file: {pdf_file.name}")
                logger.info(f"{'='*60}")
                
                data = self.extractor.extract_all_from_pdf(str(pdf_file))
                
                if not data:
                    logger.error(f"Failed to extract data from {pdf_file.name}")
                    error_count += 1
                    continue
                
                logger.info(f"Extracted chapter {data['chapter_code']}: {data['chapter_name']}")
                
                # Load into database
                try:
                    self.load_chapter_data(data)
                    
                    # Commit after each chapter successfully loads
                    self.loader.commit()
                    success_count += 1
                    logger.info(f"✓ Successfully processed and saved {pdf_file.name} to database")
                    
                except Exception as db_error:
                    logger.error(f"✗ Database error for {pdf_file.name}: {db_error}", exc_info=True)
                    self.loader.rollback()
                    error_count += 1
                
            except Exception as e:
                logger.error(f"✗ Error processing {pdf_file.name}: {e}", exc_info=True)
                error_count += 1
        
        # Summary (commits happen per chapter now)
        logger.info(f"\n{'='*60}")
        logger.info(f"PROCESSING SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Successfully processed: {success_count} chapters")
        if error_count > 0:
            logger.warning(f"Failed to process: {error_count} chapters")
        logger.info(f"{'='*60}")
    
    def load_chapter_data(self, data: Dict):
        """Load extracted chapter data into database"""
        chapter_code = data['chapter_code']
        
        logger.info(f"Loading chapter {chapter_code} into database...")
        
        try:
            # Insert chapter
            self.loader.insert_chapter(chapter_code, data['chapter_name'])
            logger.info(f"  ✓ Inserted chapter {chapter_code}: {data['chapter_name']}")
        except Exception as e:
            logger.error(f"  ✗ Failed to insert chapter: {e}")
            raise
        
        # Insert main notes
        try:
            for note in data['main_notes']:
                self.loader.insert_chapter_note(
                    chapter_code=chapter_code,
                    note_type='main_note',
                    sl_no=note['sl_no'],
                    note_text=note['note_text']
                )
            if data['main_notes']:
                logger.info(f"  ✓ Inserted {len(data['main_notes'])} main notes")
            else:
                logger.info(f"  - No main notes found")
        except Exception as e:
            logger.error(f"  ✗ Failed to insert main notes: {e}")
            raise
        
        # Insert policy conditions
        try:
            for condition in data['policy_conditions']:
                # Insert as chapter note
                self.loader.insert_chapter_note(
                    chapter_code=chapter_code,
                    note_type='policy_condition',
                    sl_no=condition['sl_no'],
                    note_text=condition['note_text']
                )
                
                # Also create policy definition
                self.loader.insert_chapter_policy(
                    chapter_code=chapter_code,
                    policy_type=f"Policy Condition {condition['sl_no']}",
                    policy_text=condition['note_text']
                )
            if data['policy_conditions']:
                logger.info(f"  ✓ Inserted {len(data['policy_conditions'])} policy conditions")
            else:
                logger.info(f"  - No policy conditions found")
        except Exception as e:
            logger.error(f"  ✗ Failed to insert policy conditions: {e}")
            raise
        
        # Insert export licensing notes
        try:
            for note in data['export_licensing_notes']:
                self.loader.insert_chapter_note(
                    chapter_code=chapter_code,
                    note_type='export_licensing',
                    sl_no=note['sl_no'],
                    note_text=note['note_text']
                )
            if data['export_licensing_notes']:
                logger.info(f"  ✓ Inserted {len(data['export_licensing_notes'])} export licensing notes")
            else:
                logger.info(f"  - No export licensing notes found")
        except Exception as e:
            logger.error(f"  ✗ Failed to insert export licensing notes: {e}")
            raise
        
        # Load HS codes
        try:
            if data['hs_code_lines']:
                self.loader.load_hs_codes_from_list(chapter_code, data['hs_code_lines'])
                logger.info(f"  ✓ Inserted {len(data['hs_code_lines'])} HS codes")
            else:
                logger.info(f"  - No HS codes found")
        except Exception as e:
            logger.error(f"  ✗ Failed to insert HS codes: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        self.loader.close()


if __name__ == "__main__":
    import sys
    
    # Database configuration - UPDATE THESE VALUES
    db_config = {
        'host': 'localhost',
        'database': 'PPL-AI',
        'user': 'postgres',
        'password': 'shreyaan999!',
        'port': 5432
    }
    
    # Hardcoded folder path for ITC HS notifications
    folder_path = r"C:\Users\Shreyaan\Desktop\coding\python\aiml\internship_assignment\ppl+ai\POCs\data\policies\ITC_HS_notifications"
    
    logger.info(f"Processing PDFs from: {folder_path}")
    
    # Process all PDFs
    processor = SimpleBulkProcessor(db_config)
    
    try:
        processor.process_folder(folder_path)
    except KeyboardInterrupt:
        logger.warning("\nProcess interrupted by user")
        processor.loader.rollback()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        processor.loader.rollback()
    finally:
        processor.close()