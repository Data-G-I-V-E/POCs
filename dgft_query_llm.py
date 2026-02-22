"""
DGFT Query Agent - Smart Navigation with Cross-Reference Following
===================================================================
This agent can:
1. Perform semantic search on articles and tables
2. Navigate directly to specific articles
3. Follow cross-references automatically
4. Retrieve and format tables
5. Generate comprehensive answers using multimodal context
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict

from langchain_chroma import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

load_dotenv()


class DGFTQueryAgent:
    """Intelligent agent for querying DGFT documents with cross-reference navigation"""
    
    def __init__(
        self, 
        persist_directory: str = "./dgft_chroma_db",
        output_directory: str = "./dgft_output"
    ):
        self.persist_directory = persist_directory
        self.output_directory = Path(output_directory)
        
        # Load embeddings and vector store
        # Using local sentence transformers - no API limits!
        self.embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        self.vector_store = Chroma(
            persist_directory=persist_directory,
            embedding_function=self.embeddings,
            collection_name="dgft_policies"
        )
        
        # Load indices
        self.master_index = self._load_json("master_index.json")
        self.raw_tables = self._load_json("tables_raw.json")
        self.table_metadata = self._load_json("table_metadata.json")
        
        # Initialize LLM
        self.llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp")
        
        print("✅ DGFT Query Agent initialized")
        print(f"   📚 Loaded {len(self.master_index.get('chapters', {}))} chapters")
        print(f"   📊 Loaded {len(self.raw_tables)} tables")
    
    def _load_json(self, filename: str) -> Dict[str, Any]:
        """Load JSON file from output directory"""
        filepath = self.output_directory / filename
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def semantic_search(
        self, 
        query: str, 
        k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search on the vector store
        
        Args:
            query: Search query
            k: Number of results to return
            filter_dict: Metadata filters 
                Single condition: {"content_type": "article_text"}
                Multiple conditions: {"$and": [{"chapter": 1}, {"content_type": "article_text"}]}
        
        Returns:
            List of search results with content and metadata
        """
        print(f"\n🔍 Semantic search: '{query}'")
        
        search_kwargs = {"k": k}
        if filter_dict:
            search_kwargs["filter"] = filter_dict
        
        retriever = self.vector_store.as_retriever(search_kwargs=search_kwargs)
        docs = retriever.invoke(query)
        
        results = []
        for doc in docs:
            results.append({
                "content": doc.page_content,
                "metadata": doc.metadata
            })
        
        print(f"   ✅ Found {len(results)} results")
        return results
    
    def get_article(self, chapter: int, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific article by chapter and article ID
        
        Args:
            chapter: Chapter number
            article_id: Article ID (e.g., "1.1", "2.3")
        
        Returns:
            Article data including metadata
        """
        chapter_str = str(chapter)
        if chapter_str not in self.master_index.get("chapters", {}):
            print(f"❌ Chapter {chapter} not found")
            return None
        
        chapter_data = self.master_index["chapters"][chapter_str]
        if article_id not in chapter_data.get("articles", {}):
            print(f"❌ Article {article_id} not found in chapter {chapter}")
            return None
        
        article_data = chapter_data["articles"][article_id]
        
        # Fetch full content from vector store
        # ChromaDB requires $and operator for multiple conditions
        filter_dict = {
            "$and": [
                {"chapter": chapter},
                {"article": article_id},
                {"content_type": "article_text"}
            ]
        }
        
        docs = self.vector_store.similarity_search(
            article_data.get("title", ""),
            k=5,
            filter=filter_dict
        )
        
        # Combine chunks
        full_content = "\n\n".join([doc.page_content for doc in docs])
        
        return {
            "article_id": f"{chapter}.{article_id}",
            "content": full_content,
            "metadata": article_data,
            "cross_references": article_data.get("cross_references", []),
            "tables": article_data.get("tables", [])
        }
    
    def follow_cross_references(
        self, 
        article_data: Dict[str, Any],
        max_depth: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Follow cross-references from an article and retrieve referenced articles
        
        Args:
            article_data: Article data with cross_references
            max_depth: Maximum depth to follow references (default: 2)
        
        Returns:
            List of referenced articles
        """
        cross_refs = article_data.get("cross_references", [])
        if not cross_refs:
            return []
        
        print(f"\n🔗 Following {len(cross_refs)} cross-references...")
        
        referenced_articles = []
        visited = set()
        
        def _follow(refs, depth):
            if depth > max_depth:
                return
            
            for ref in refs:
                if ref in visited:
                    continue
                visited.add(ref)
                
                # Parse reference (e.g., "4.2" -> chapter 4, article 2)
                # For DGFT, articles are like "1.1", "2.3", etc.
                # Assume format: article_id within same chapter initially
                # If reference is "4.2", it could be chapter 4, article 2
                # We need to be smart about this
                
                parts = ref.split('.')
                if len(parts) >= 2:
                    # Try as chapter.article
                    try:
                        chapter = int(parts[0])
                        article_id = '.'.join(parts[1:])
                        
                        ref_article = self.get_article(chapter, article_id)
                        if ref_article:
                            referenced_articles.append(ref_article)
                            print(f"   ✓ Retrieved article {ref}")
                            
                            # Recursively follow references from this article
                            if depth < max_depth:
                                _follow(ref_article.get("cross_references", []), depth + 1)
                    except:
                        # Try searching for it
                        results = self.semantic_search(f"article {ref}", k=1)
                        if results:
                            referenced_articles.append(results[0])
        
        _follow(cross_refs, 1)
        
        print(f"   ✅ Retrieved {len(referenced_articles)} referenced articles")
        return referenced_articles
    
    def get_table(self, table_id: str, format: str = 'dict') -> Optional[Any]:
        """
        Retrieve a table by ID
        
        Args:
            table_id: Table identifier
            format: Output format ('dict', 'markdown', 'html')
        
        Returns:
            Table data in requested format
        """
        if table_id not in self.raw_tables:
            print(f"❌ Table {table_id} not found")
            return None
        
        table_data = self.raw_tables[table_id]
        
        if format == 'dict':
            return table_data
        elif format == 'markdown':
            if table_data.get("headers") and table_data.get("rows"):
                import pandas as pd
                df = pd.DataFrame(table_data["rows"], columns=table_data["headers"])
                return df.to_markdown(index=False)
            return table_data.get("text", "")
        elif format == 'html':
            return table_data.get("html", "")
        
        return table_data
    
    def get_articles_referencing(self, article_id: str) -> List[str]:
        """
        Get all articles that reference a specific article
        
        Args:
            article_id: Article ID to look up (e.g., "4.2")
        
        Returns:
            List of article IDs that reference this article
        """
        cross_ref_map = self.master_index.get("cross_reference_map", {})
        return cross_ref_map.get(article_id, [])
    
    def query_with_context(
        self, 
        query: str,
        include_cross_refs: bool = True,
        include_tables: bool = True,
        max_chunks: int = 5
    ) -> Dict[str, Any]:
        """
        Comprehensive query with automatic context gathering
        
        Args:
            query: User query
            include_cross_refs: Whether to follow cross-references
            include_tables: Whether to include related tables
            max_chunks: Maximum number of chunks to retrieve
        
        Returns:
            Comprehensive response with answer, sources, tables, and references
        """
        print(f"\n{'='*80}")
        print(f"❓ Query: {query}")
        print(f"{'='*80}")
        
        # Step 1: Semantic search
        search_results = self.semantic_search(query, k=max_chunks)
        
        # Step 2: Collect context
        context_articles = []
        all_tables = []
        all_cross_refs = set()
        
        for result in search_results:
            metadata = result["metadata"]
            
            # If it's an article, get full article
            if metadata.get("content_type") == "article_text":
                chapter = metadata.get("chapter")
                article_id = metadata.get("article")
                
                if chapter and article_id:
                    article = self.get_article(chapter, article_id)
                    if article:
                        context_articles.append(article)
                        
                        # Collect cross-references
                        all_cross_refs.update(article.get("cross_references", []))
                        
                        # Collect tables
                        if include_tables:
                            for table_id in article.get("tables", []):
                                table = self.get_table(table_id)
                                if table:
                                    all_tables.append(table)
            
            # If it's a table directly
            elif "table" in metadata.get("content_type", ""):
                table_id = metadata.get("table_id")
                if table_id and include_tables:
                    table = self.get_table(table_id)
                    if table:
                        all_tables.append(table)
        
        # Step 3: Follow cross-references
        referenced_articles = []
        if include_cross_refs and all_cross_refs:
            print(f"\n🔗 Following {len(all_cross_refs)} cross-references...")
            for ref in list(all_cross_refs)[:5]:  # Limit to 5 to avoid explosion
                parts = ref.split('.')
                if len(parts) >= 2:
                    try:
                        chapter = int(parts[0])
                        article_id = '.'.join(parts[1:])
                        ref_article = self.get_article(chapter, article_id)
                        if ref_article:
                            referenced_articles.append(ref_article)
                    except:
                        pass
        
        # Step 4: Generate answer using LLM
        answer = self._generate_answer(
            query, 
            context_articles, 
            referenced_articles,
            all_tables
        )
        
        return {
            "query": query,
            "answer": answer,
            "source_articles": [
                f"{a['article_id']}: {a['metadata'].get('title', '')[:100]}"
                for a in context_articles
            ],
            "referenced_articles": [
                f"{a['article_id']}: {a['metadata'].get('title', '')[:100]}"
                for a in referenced_articles
            ],
            "tables": all_tables,
            "cross_references": list(all_cross_refs)
        }
    
    def _generate_answer(
        self,
        query: str,
        context_articles: List[Dict[str, Any]],
        referenced_articles: List[Dict[str, Any]],
        tables: List[Dict[str, Any]]
    ) -> str:
        """Generate answer using LLM with collected context"""
        
        # Build prompt
        prompt = f"""You are an expert on DGFT (Directorate General of Foreign Trade) policies. 
Answer the following question based on the provided policy documents, tables, and cross-references.

QUESTION: {query}

CONTEXT FROM POLICY DOCUMENTS:
"""
        
        # Add context articles
        for i, article in enumerate(context_articles[:3], 1):
            prompt += f"\n--- Article {article['article_id']} ---\n"
            prompt += article['content'][:1500]  # Limit length
            prompt += "\n"
        
        # Add referenced articles
        if referenced_articles:
            prompt += "\n\nRELATED POLICY ARTICLES (Cross-referenced):\n"
            for article in referenced_articles[:2]:
                prompt += f"\n--- Article {article['article_id']} ---\n"
                prompt += article['content'][:1000]
                prompt += "\n"
        
        # Add tables
        if tables:
            prompt += "\n\nRELEVANT POLICY TABLES:\n"
            for i, table in enumerate(tables[:3], 1):
                prompt += f"\n--- Table {i}: {table.get('caption', 'Policy Table')} ---\n"
                if table.get("headers") and table.get("rows"):
                    import pandas as pd
                    df = pd.DataFrame(table["rows"], columns=table["headers"])
                    prompt += df.head(10).to_markdown(index=False)
                else:
                    prompt += table.get("text", "")[:1000]
                prompt += "\n"
        
        prompt += """

Please provide a comprehensive answer that:
1. Directly answers the question
2. References specific article numbers when relevant
3. Includes information from tables if applicable
4. Mentions any important cross-references or related policies

If the information is insufficient, clearly state what is missing.

ANSWER:"""
        
        try:
            message = HumanMessage(content=prompt)
            response = self.llm.invoke([message])
            return response.content
        except Exception as e:
            return f"Error generating answer: {e}"
    
    def display_response(self, response: Dict[str, Any]):
        """Pretty print the query response"""
        print(f"\n{'='*80}")
        print("📋 ANSWER")
        print(f"{'='*80}")
        print(response["answer"])
        
        if response["source_articles"]:
            print(f"\n{'='*80}")
            print(f"📚 SOURCE ARTICLES ({len(response['source_articles'])})")
            print(f"{'='*80}")
            for article in response["source_articles"]:
                print(f"  • {article}")
        
        if response["referenced_articles"]:
            print(f"\n{'='*80}")
            print(f"🔗 CROSS-REFERENCED ARTICLES ({len(response['referenced_articles'])})")
            print(f"{'='*80}")
            for article in response["referenced_articles"]:
                print(f"  • {article}")
        
        if response["tables"]:
            print(f"\n{'='*80}")
            print(f"📊 RELEVANT TABLES ({len(response['tables'])})")
            print(f"{'='*80}")
            for table in response["tables"]:
                print(f"  • {table.get('caption', 'Table')}")
                print(f"    Parent: Article {table.get('parent_article', 'Unknown')}")
        
        if response["cross_references"]:
            print(f"\n{'='*80}")
            print(f"🔖 RELATED ARTICLES")
            print(f"{'='*80}")
            print(f"  {', '.join(sorted(response['cross_references']))}")
        
        print(f"\n{'='*80}")


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

def example_usage():
    """Demonstrate various query patterns"""
    
    # Initialize agent
    agent = DGFTQueryAgent(
        persist_directory="./dgft_chroma_db",
        output_directory="./dgft_output"
    )
    
    print("\n" + "="*80)
    print("EXAMPLE 1: Semantic Search with Context")
    print("="*80)
    
    # Example 1: Comprehensive query with context
    response = agent.query_with_context(
        "What are the import restrictions on prohibited items?",
        include_cross_refs=True,
        include_tables=True
    )
    agent.display_response(response)
    
    print("\n" + "="*80)
    print("EXAMPLE 2: Direct Article Lookup")
    print("="*80)
    
    # Example 2: Get specific article
    article = agent.get_article(chapter=1, article_id="1.1")
    if article:
        print(f"\n📄 Article {article['article_id']}")
        print(f"Content: {article['content'][:500]}...")
        print(f"\nCross-references: {article['cross_references']}")
        print(f"Tables: {article['tables']}")
    
    print("\n" + "="*80)
    print("EXAMPLE 3: Table Search")
    print("="*80)
    
    # Example 3: Search for tables
    table_results = agent.semantic_search(
        "list of prohibited items",
        k=3,
        filter_dict={"content_type": "table_summary"}
    )
    
    for result in table_results:
        table_id = result["metadata"].get("table_id")
        if table_id:
            table = agent.get_table(table_id, format='markdown')
            print(f"\n📊 Table: {table_id}")
            print(f"Parent: Article {result['metadata'].get('parent_article')}")
            if table:
                print(f"\n{table[:500]}...")
    
    print("\n" + "="*80)
    print("EXAMPLE 4: Cross-Reference Navigation")
    print("="*80)
    
    # Example 4: Find what references a specific article
    referencing = agent.get_articles_referencing("4.2")
    if referencing:
        print(f"\nArticles that reference article 4.2:")
        for ref in referencing:
            print(f"  • {ref}")


def interactive_mode():
    """Interactive query mode"""
    
    agent = DGFTQueryAgent(
        persist_directory="./dgft_chroma_db",
        output_directory="./dgft_output"
    )
    
    print("\n" + "="*80)
    print("🤖 DGFT Query Agent - Interactive Mode")
    print("="*80)
    print("\nCommands:")
    print("  - Type your question to search")
    print("  - 'article <chapter>.<id>' to get specific article (e.g., 'article 1.1')")
    print("  - 'table <id>' to get specific table")
    print("  - 'refs <article_id>' to see cross-references")
    print("  - 'quit' to exit")
    print("="*80)
    
    while True:
        try:
            user_input = input("\n💬 Your query: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() == 'quit':
                print("👋 Goodbye!")
                break
            
            # Parse commands
            if user_input.lower().startswith('article '):
                # Direct article lookup
                article_ref = user_input.split(' ', 1)[1]
                parts = article_ref.split('.')
                if len(parts) >= 2:
                    try:
                        chapter = int(parts[0])
                        article_id = '.'.join(parts[1:])
                        article = agent.get_article(chapter, article_id)
                        if article:
                            print(f"\n📄 Article {article['article_id']}")
                            print(f"\n{article['content']}")
                            print(f"\n🔗 Cross-references: {', '.join(article['cross_references']) if article['cross_references'] else 'None'}")
                            print(f"📊 Tables: {', '.join(article['tables']) if article['tables'] else 'None'}")
                    except Exception as e:
                        print(f"❌ Error: {e}")
            
            elif user_input.lower().startswith('table '):
                # Direct table lookup
                table_id = user_input.split(' ', 1)[1]
                table = agent.get_table(table_id, format='markdown')
                if table:
                    print(f"\n📊 Table: {table_id}")
                    print(f"\n{table}")
            
            elif user_input.lower().startswith('refs '):
                # Cross-reference lookup
                article_id = user_input.split(' ', 1)[1]
                refs = agent.get_articles_referencing(article_id)
                if refs:
                    print(f"\n🔗 Articles referencing {article_id}:")
                    for ref in refs:
                        print(f"  • {ref}")
                else:
                    print(f"No articles reference {article_id}")
            
            else:
                # Regular query
                response = agent.query_with_context(
                    user_input,
                    include_cross_refs=True,
                    include_tables=True
                )
                agent.display_response(response)
        
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    # Run interactive mode
    # interactive_mode()
    
    # Or run examples
    example_usage()