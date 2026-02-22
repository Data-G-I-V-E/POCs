"""
DGFT Policy Documents - Hybrid RAG System with Table Storage
==============================================================
This script processes DGFT trade policy PDFs with:
1. Hybrid Storage: Vector embeddings + Structured metadata
2. Advanced Table Storage: Raw data + Multiple text representations
3. Cross-reference detection and indexing
4. Article-level chunking with hierarchical metadata
"""

import json
import re
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
import pandas as pd
from datetime import datetime

# Unstructured for document parsing
from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.title import chunk_by_title

# LangChain components
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from dotenv import load_dotenv

load_dotenv()


class TableProcessor:
    """Handles table extraction, storage, and retrieval"""
    
    def __init__(self):
        self.raw_tables = {}  # Layer 1: Raw structured data
        self.table_metadata = {}  # Layer 3: Quick lookup index
        
    def extract_and_process_table(
        self, 
        table_element: Any, 
        chapter_num: int,
        article_id: str,
        table_index: int,
        page_num: int
    ) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
        """
        Extract table and create multiple representations
        
        Returns:
            table_id: Unique identifier for the table
            raw_data: Structured table data (Layer 1)
            embedding_chunks: List of text representations for vector store (Layer 2)
        """
        table_id = f"table_{chapter_num}.{article_id}_{table_index}"
        
        # Extract raw table data
        raw_data = {
            "table_id": table_id,
            "parent_article": article_id,
            "chapter": chapter_num,
            "page_num": page_num,
            "html": getattr(table_element.metadata, "text_as_html", ""),
            "text": table_element.text,
            "caption": self._extract_caption(table_element),
            "extracted_at": datetime.now().isoformat()
        }
        
        # Try to parse table structure
        try:
            parsed_table = self._parse_html_table(raw_data["html"])
            raw_data["headers"] = parsed_table["headers"]
            raw_data["rows"] = parsed_table["rows"]
            raw_data["row_count"] = len(parsed_table["rows"])
            raw_data["col_count"] = len(parsed_table["headers"])
        except Exception as e:
            print(f"⚠️ Could not parse table structure for {table_id}: {e}")
            raw_data["headers"] = []
            raw_data["rows"] = []
            raw_data["row_count"] = 0
            raw_data["col_count"] = 0
        
        # Store raw data (Layer 1)
        self.raw_tables[table_id] = raw_data
        
        # Create multiple text representations (Layer 2)
        embedding_chunks = self._create_table_embeddings(table_id, raw_data, article_id)
        
        # Update metadata index (Layer 3)
        self.table_metadata[table_id] = {
            "caption": raw_data["caption"],
            "parent_article": article_id,
            "chapter": chapter_num,
            "page": page_num,
            "row_count": raw_data["row_count"],
            "has_structure": len(raw_data["headers"]) > 0
        }
        
        return table_id, raw_data, embedding_chunks
    
    def _extract_caption(self, table_element) -> str:
        """Extract or generate table caption"""
        # Try to get from metadata or surrounding context
        text = table_element.text[:100]  # First 100 chars as fallback
        return text.split('\n')[0] if '\n' in text else text
    
    def _parse_html_table(self, html: str) -> Dict[str, Any]:
        """Parse HTML table into structured format"""
        if not html:
            return {"headers": [], "rows": []}
        
        try:
            # Use pandas to parse HTML table
            dfs = pd.read_html(html)
            if dfs:
                df = dfs[0]
                return {
                    "headers": df.columns.tolist(),
                    "rows": df.values.tolist()
                }
        except:
            pass
        
        return {"headers": [], "rows": []}
    
    def _create_table_embeddings(
        self, 
        table_id: str, 
        raw_data: Dict[str, Any],
        article_id: str
    ) -> List[Dict[str, Any]]:
        """Create multiple text representations for vector store"""
        chunks = []
        
        # Representation 1: Table Summary (always created)
        summary = self._generate_table_summary(raw_data)
        chunks.append({
            "content": summary,
            "metadata": {
                "doc_id": f"{table_id}_summary",
                "content_type": "table_summary",
                "table_id": table_id,
                "parent_article": article_id,
                "chapter": raw_data["chapter"],
                "has_structure": len(raw_data["headers"]) > 0
            }
        })
        
        # Representation 2: Row-by-row text (only for structured tables)
        if raw_data["headers"] and len(raw_data["rows"]) > 0:
            # For large tables, create row chunks
            if len(raw_data["rows"]) > 10:
                for idx, row in enumerate(raw_data["rows"][:20]):  # Limit to first 20 rows
                    row_text = self._row_to_text(raw_data["headers"], row)
                    chunks.append({
                        "content": row_text,
                        "metadata": {
                            "doc_id": f"{table_id}_row_{idx}",
                            "content_type": "table_row",
                            "table_id": table_id,
                            "parent_article": article_id,
                            "chapter": raw_data["chapter"],
                            "row_index": idx
                        }
                    })
        
        # Representation 3: Markdown format (for context)
        markdown = self._table_to_markdown(raw_data)
        if markdown:
            chunks.append({
                "content": markdown,
                "metadata": {
                    "doc_id": f"{table_id}_markdown",
                    "content_type": "table_markdown",
                    "table_id": table_id,
                    "parent_article": article_id,
                    "chapter": raw_data["chapter"]
                }
            })
        
        return chunks
    
    def _generate_table_summary(self, raw_data: Dict[str, Any]) -> str:
        """Generate natural language summary of table"""
        caption = raw_data.get("caption", "Table")
        row_count = raw_data.get("row_count", 0)
        
        summary_parts = [f"Table: {caption}"]
        
        if raw_data["headers"]:
            headers = ", ".join(str(h) for h in raw_data["headers"][:5])  # First 5 headers
            summary_parts.append(f"Columns: {headers}")
            
            if row_count > 0:
                summary_parts.append(f"Contains {row_count} rows of data")
                
                # Extract sample values from first few rows
                sample_rows = []
                for row in raw_data["rows"][:3]:
                    row_text = " | ".join(str(cell)[:50] for cell in row[:3])  # First 3 cells
                    sample_rows.append(row_text)
                
                if sample_rows:
                    summary_parts.append("Sample entries:")
                    summary_parts.extend(sample_rows)
        else:
            # Fallback to raw text
            text_snippet = raw_data.get("text", "")[:300]
            summary_parts.append(f"Content: {text_snippet}")
        
        return "\n".join(summary_parts)
    
    def _row_to_text(self, headers: List[str], row: List[Any]) -> str:
        """Convert table row to searchable text"""
        pairs = [f"{h}: {v}" for h, v in zip(headers, row)]
        return " | ".join(pairs)
    
    def _table_to_markdown(self, raw_data: Dict[str, Any]) -> str:
        """Convert table to markdown format"""
        if not raw_data["headers"] or not raw_data["rows"]:
            return ""
        
        try:
            df = pd.DataFrame(raw_data["rows"], columns=raw_data["headers"])
            return df.to_markdown(index=False)
        except:
            return ""
    
    def save_raw_tables(self, output_path: str):
        """Save Layer 1: Raw table data to JSON"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.raw_tables, f, indent=2, ensure_ascii=False)
        print(f"✅ Saved {len(self.raw_tables)} raw tables to {output_path}")
    
    def get_table(self, table_id: str, format: str = 'json') -> Any:
        """Retrieve table in various formats"""
        if table_id not in self.raw_tables:
            return None
        
        raw_data = self.raw_tables[table_id]
        
        if format == 'json':
            return raw_data
        elif format == 'dataframe':
            if raw_data["headers"] and raw_data["rows"]:
                return pd.DataFrame(raw_data["rows"], columns=raw_data["headers"])
            return None
        elif format == 'markdown':
            return self._table_to_markdown(raw_data)
        elif format == 'html':
            return raw_data.get("html", "")
        
        return raw_data


class CrossReferenceExtractor:
    """Extract and index cross-references between articles"""
    
    @staticmethod
    def extract_references(text: str) -> List[str]:
        """
        Extract article references from text
        Patterns: "article 4.2", "refer to 7.3", "section 1.1", "para 2.3"
        """
        patterns = [
            r'(?:article|section|para|paragraph|clause)\s+(\d+\.\d+)',
            r'(?:refer to|see|as per)\s+(?:article|section|para)?\s*(\d+\.\d+)',
            r'\b(\d+\.\d+)\b(?=\s+(?:above|below|herein))'
        ]
        
        references = set()
        text_lower = text.lower()
        
        for pattern in patterns:
            matches = re.findall(pattern, text_lower)
            references.update(matches)
        
        return sorted(list(references))


class ArticleExtractor:
    """Extract and structure articles from document elements"""
    
    @staticmethod
    def detect_article_id(text: str) -> Optional[str]:
        """
        Detect article ID from text
        Patterns: "1.1", "2.3.1", "Article 4.2"
        """
        # Match patterns like "1.1", "1.2", "10.5" at start of text
        pattern = r'^(?:Article\s+)?(\d+\.\d+(?:\.\d+)?)'
        match = re.match(pattern, text.strip(), re.IGNORECASE)
        
        if match:
            return match.group(1)
        
        return None
    
    @staticmethod
    def extract_chapter_number(filename: str) -> int:
        """Extract chapter number from filename like 'ch-7.pdf' or 'chapter_7.pdf'"""
        match = re.search(r'ch(?:apter)?[-_]?(\d+)', filename.lower())
        if match:
            return int(match.group(1))
        return 0


class DGFTHybridRAGSystem:
    """Main system for processing DGFT documents with hybrid storage"""
    
    def __init__(self, persist_directory: str = "./dgft_chroma_db", output_dir: str = "./dgft_output"):
        self.persist_directory = persist_directory
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Initialize components
        self.table_processor = TableProcessor()
        self.cross_ref_extractor = CrossReferenceExtractor()
        self.article_extractor = ArticleExtractor()
        
        # Initialize embeddings and vector store
        # Using local sentence transformers - no API limits!
        self.embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        self.vector_store = None
        
        # Master index (Layer 3)
        self.master_index = {
            "chapters": {},
            "cross_reference_map": defaultdict(list),  # article_id -> [articles that reference it]
            "article_to_tables": defaultdict(list),
            "processing_metadata": {
                "processed_at": datetime.now().isoformat(),
                "total_chapters": 0,
                "total_articles": 0,
                "total_tables": 0
            }
        }
    
    def process_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """Process a single PDF file"""
        pdf_path = Path(pdf_path)
        print(f"\n{'='*80}")
        print(f"📄 Processing: {pdf_path.name}")
        print(f"{'='*80}")
        
        # Extract chapter number
        chapter_num = self.article_extractor.extract_chapter_number(pdf_path.name)
        print(f"📖 Chapter: {chapter_num}")
        
        # Partition PDF
        elements = partition_pdf(
            filename=str(pdf_path),
            strategy="hi_res",
            infer_table_structure=True,
            extract_image_block_types=["Table"],  # Only extract tables, not images
            extract_image_block_to_payload=True,
            languages=["eng"]
        )
        
        print(f"✅ Extracted {len(elements)} elements")
        
        # Separate tables and text elements
        tables = [el for el in elements if el.category == "Table"]
        text_elements = [el for el in elements if el.category != "Table"]
        
        print(f"   📊 Tables: {len(tables)}")
        print(f"   📝 Text elements: {len(text_elements)}")
        
        # Process elements by article
        chapter_data = self._process_chapter_elements(
            text_elements, 
            tables, 
            chapter_num, 
            pdf_path.name
        )
        
        return chapter_data
    
    def _process_chapter_elements(
        self, 
        text_elements: List[Any], 
        table_elements: List[Any],
        chapter_num: int,
        filename: str
    ) -> Dict[str, Any]:
        """Process elements and organize by article"""
        
        current_article_id = None
        current_article_content = []
        articles = {}
        table_index = 0
        
        # First pass: identify articles and group content
        for elem in text_elements:
            text = elem.text.strip()
            
            # Try to detect article start
            detected_article = self.article_extractor.detect_article_id(text)
            
            if detected_article:
                # Save previous article
                if current_article_id and current_article_content:
                    articles[current_article_id] = {
                        "content": current_article_content,
                        "article_id": current_article_id
                    }
                
                # Start new article
                current_article_id = detected_article
                current_article_content = [elem]
            elif current_article_id:
                # Add to current article
                current_article_content.append(elem)
            else:
                # Content before first article (intro, chapter title, etc.)
                if "intro" not in articles:
                    articles["intro"] = {"content": [], "article_id": "intro"}
                articles["intro"]["content"].append(elem)
        
        # Save last article
        if current_article_id and current_article_content:
            articles[current_article_id] = {
                "content": current_article_content,
                "article_id": current_article_id
            }
        
        print(f"   📑 Found {len(articles)} article sections")
        
        # Second pass: process each article and create chunks
        chapter_chunks = []
        chapter_index = {
            "chapter_num": chapter_num,
            "filename": filename,
            "articles": {}
        }
        
        for article_id, article_data in articles.items():
            article_chunks, article_meta = self._process_article(
                article_data["content"],
                article_id,
                chapter_num,
                table_elements,
                table_index
            )
            
            chapter_chunks.extend(article_chunks)
            chapter_index["articles"][article_id] = article_meta
            
            # Update table index
            table_index += len(article_meta.get("tables", []))
        
        # Update master index
        self.master_index["chapters"][str(chapter_num)] = chapter_index
        
        return {
            "chapter_num": chapter_num,
            "chunks": chapter_chunks,
            "metadata": chapter_index
        }
    
    def _process_article(
        self,
        article_elements: List[Any],
        article_id: str,
        chapter_num: int,
        all_tables: List[Any],
        table_start_index: int
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Process a single article and create embedding chunks"""
        
        # Combine text content
        article_text = "\n".join([elem.text for elem in article_elements])
        
        # Extract cross-references
        cross_refs = self.cross_ref_extractor.extract_references(article_text)
        
        # Update cross-reference map
        for ref in cross_refs:
            self.master_index["cross_reference_map"][ref].append(f"{chapter_num}.{article_id}")
        
        # Get page number
        page_nums = [getattr(elem.metadata, "page_number", 1) for elem in article_elements if hasattr(elem, 'metadata')]
        page_num = page_nums[0] if page_nums else 1
        
        # Process tables in this article
        article_tables = []
        table_chunks = []
        
        # Find tables that belong to this article (heuristic: same page or nearby)
        for idx, table_elem in enumerate(all_tables):
            table_page = getattr(table_elem.metadata, "page_number", 1)
            if abs(table_page - page_num) <= 1:  # Tables within 1 page
                table_id, raw_data, embed_chunks = self.table_processor.extract_and_process_table(
                    table_elem,
                    chapter_num,
                    article_id,
                    table_start_index + idx,
                    table_page
                )
                article_tables.append(table_id)
                table_chunks.extend(embed_chunks)
                
                # Update article-to-tables mapping
                self.master_index["article_to_tables"][f"{chapter_num}.{article_id}"].append(table_id)
        
        # Create main article chunk
        chunks = []
        
        # Split article if too long (>2000 chars)
        if len(article_text) > 2000:
            # Split into smaller chunks
            chunk_size = 1500
            for i in range(0, len(article_text), chunk_size):
                chunk_text = article_text[i:i+chunk_size]
                chunks.append({
                    "content": chunk_text,
                    "metadata": {
                        "doc_id": f"ch{chapter_num}_art{article_id}_part{i//chunk_size}",
                        "content_type": "article_text",
                        "chapter": chapter_num,
                        "article": article_id,
                        "article_full": f"{chapter_num}.{article_id}",
                        "cross_references": json.dumps(cross_refs),  # Convert list to JSON string
                        "has_tables": len(article_tables) > 0,
                        "tables": json.dumps(article_tables),  # Convert list to JSON string
                        "page_num": page_num
                    }
                })
        else:
            chunks.append({
                "content": article_text,
                "metadata": {
                    "doc_id": f"ch{chapter_num}_art{article_id}",
                    "content_type": "article_text",
                    "chapter": chapter_num,
                    "article": article_id,
                    "article_full": f"{chapter_num}.{article_id}",
                    "cross_references": json.dumps(cross_refs),  # Convert list to JSON string
                    "has_tables": len(article_tables) > 0,
                    "tables": json.dumps(article_tables),  # Convert list to JSON string
                    "page_num": page_num
                }
            })
        
        # Add table chunks
        chunks.extend(table_chunks)
        
        # Article metadata for index
        article_meta = {
            "article_id": article_id,
            "title": article_text[:100],  # First 100 chars as title
            "cross_references": cross_refs,
            "tables": article_tables,
            "page": page_num,
            "chunk_count": len(chunks)
        }
        
        return chunks, article_meta
    
    def process_all_pdfs(self, pdf_directory: str):
        """Process all PDFs in a directory"""
        pdf_dir = Path(pdf_directory)
        pdf_files = sorted(list(pdf_dir.glob("*.pdf")))
        
        print(f"\n🚀 Found {len(pdf_files)} PDF files to process")
        
        all_chunks = []
        
        for pdf_path in pdf_files:
            try:
                chapter_data = self.process_pdf(pdf_path)
                all_chunks.extend(chapter_data["chunks"])
            except Exception as e:
                print(f"❌ Error processing {pdf_path.name}: {e}")
                continue
        
        # Update processing metadata
        self.master_index["processing_metadata"]["total_chapters"] = len(self.master_index["chapters"])
        self.master_index["processing_metadata"]["total_articles"] = sum(
            len(ch["articles"]) for ch in self.master_index["chapters"].values()
        )
        self.master_index["processing_metadata"]["total_tables"] = len(self.table_processor.raw_tables)
        
        print(f"\n{'='*80}")
        print(f"📊 PROCESSING SUMMARY")
        print(f"{'='*80}")
        print(f"Total chapters: {self.master_index['processing_metadata']['total_chapters']}")
        print(f"Total articles: {self.master_index['processing_metadata']['total_articles']}")
        print(f"Total tables: {self.master_index['processing_metadata']['total_tables']}")
        print(f"Total chunks for embedding: {len(all_chunks)}")
        
        # Create vector store
        print(f"\n📥 Creating vector store...")
        self._create_vector_store(all_chunks)
        
        # Save all indices
        self._save_indices()
        
        print(f"\n✅ Processing complete!")
    
    def _create_vector_store(self, chunks: List[Dict[str, Any]]):
        """Create Chroma vector store from chunks"""
        # Convert chunks to LangChain Documents
        documents = []
        for chunk in chunks:
            doc = Document(
                page_content=chunk["content"],
                metadata=chunk["metadata"]
            )
            documents.append(doc)
        
        print(f"   Creating embeddings for {len(documents)} chunks...")
        
        # Create Chroma vector store
        self.vector_store = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            persist_directory=self.persist_directory,
            collection_name="dgft_policies"
        )
        
        print(f"   ✅ Vector store created at {self.persist_directory}")
    
    def _save_indices(self):
        """Save all indices to files"""
        # Save master index
        master_index_path = self.output_dir / "master_index.json"
        with open(master_index_path, 'w', encoding='utf-8') as f:
            # Convert defaultdict to dict for JSON serialization
            index_copy = dict(self.master_index)
            index_copy["cross_reference_map"] = dict(index_copy["cross_reference_map"])
            index_copy["article_to_tables"] = dict(index_copy["article_to_tables"])
            json.dump(index_copy, f, indent=2, ensure_ascii=False)
        print(f"   ✅ Master index saved to {master_index_path}")
        
        # Save raw tables
        tables_path = self.output_dir / "tables_raw.json"
        self.table_processor.save_raw_tables(str(tables_path))
        
        # Save table metadata
        table_meta_path = self.output_dir / "table_metadata.json"
        with open(table_meta_path, 'w', encoding='utf-8') as f:
            json.dump(self.table_processor.table_metadata, f, indent=2, ensure_ascii=False)
        print(f"   ✅ Table metadata saved to {table_meta_path}")
    
    def load_existing_system(self):
        """Load existing vector store and indices"""
        print("📂 Loading existing system...")
        
        # Load vector store
        self.vector_store = Chroma(
            persist_directory=self.persist_directory,
            embedding_function=self.embeddings,
            collection_name="dgft_policies"
        )
        
        # Load master index
        master_index_path = self.output_dir / "master_index.json"
        if master_index_path.exists():
            with open(master_index_path, 'r', encoding='utf-8') as f:
                loaded_index = json.load(f)
                self.master_index = loaded_index
                # Convert back to defaultdict
                self.master_index["cross_reference_map"] = defaultdict(
                    list, 
                    loaded_index.get("cross_reference_map", {})
                )
                self.master_index["article_to_tables"] = defaultdict(
                    list,
                    loaded_index.get("article_to_tables", {})
                )
        
        # Load raw tables
        tables_path = self.output_dir / "tables_raw.json"
        if tables_path.exists():
            with open(tables_path, 'r', encoding='utf-8') as f:
                self.table_processor.raw_tables = json.load(f)
        
        # Load table metadata
        table_meta_path = self.output_dir / "table_metadata.json"
        if table_meta_path.exists():
            with open(table_meta_path, 'r', encoding='utf-8') as f:
                self.table_processor.table_metadata = json.load(f)
        
        print("✅ System loaded successfully")


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

def main():
    """Main execution function"""
    
    # Configuration
    PDF_DIRECTORY = "./data/policies/DGFT_FTP"  # Change to your PDF directory
    PERSIST_DIRECTORY = "./dgft_chroma_db"
    OUTPUT_DIRECTORY = "./dgft_output"
    
    # Initialize system
    rag_system = DGFTHybridRAGSystem(
        persist_directory=PERSIST_DIRECTORY,
        output_dir=OUTPUT_DIRECTORY
    )
    
    # Process all PDFs
    rag_system.process_all_pdfs(PDF_DIRECTORY)
    
    print("\n" + "="*80)
    print("🎉 DGFT Hybrid RAG System Setup Complete!")
    print("="*80)
    print(f"\nVector Store: {PERSIST_DIRECTORY}")
    print(f"Indices & Tables: {OUTPUT_DIRECTORY}")
    print(f"\nYou can now query the system using:")
    print(f"  - Semantic search: vector_store.similarity_search(query)")
    print(f"  - Direct article lookup: master_index['chapters'][chapter_num]['articles'][article_id]")
    print(f"  - Cross-references: master_index['cross_reference_map'][article_id]")
    print(f"  - Table retrieval: table_processor.get_table(table_id)")


if __name__ == "__main__":
    main()