"""
Comprehensive Export Advisor Agent

Main agent that helps users with export-related queries by:
1. Checking HS code restrictions and policies
2. Finding relevant trade agreements
3. Providing tariff information
4. Suggesting export procedures

This is the user-facing agent that orchestrates all backend systems.
"""

from typing import Dict, List, Optional, Any
import re
import os
from datetime import datetime

from config import Config
from export_data_integrator import ExportDataIntegrator

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    from dotenv import load_dotenv
    load_dotenv()
    HAS_LLM = True
except ImportError:
    HAS_LLM = False


class ExportAdvisorAgent:
    """
    Comprehensive export advisor for India-to-target-countries trade
    
    Handles queries like:
    - "Can I export onions to Australia?"
    - "What are tariffs for HS 070310 in UAE?"
    - "Export policy for textiles to UK?"
    """
    
    def __init__(self):
        """Initialize the advisor agent"""
        print("Initializing Export Advisor Agent...")
        self.integrator = ExportDataIntegrator(use_vector_stores=True)
        
        # Initialize LLM for general queries
        self.llm = None
        if HAS_LLM:
            try:
                api_key = os.getenv("GOOGLE_API_KEY")
                if api_key:
                    self.llm = ChatGoogleGenerativeAI(
                        model="gemini-2.5-flash",
                        google_api_key=api_key,
                        temperature=0.3
                    )
                    print("✓ LLM initialized for general queries")
            except Exception as e:
                print(f"⚠️ LLM not available for general queries: {e}")
        
        print("✓ Export Advisor Agent ready!\n")
    
    def advise_export(
        self,
        hs_code: str,
        country: str,
        quantity: Optional[float] = None,
        detailed: bool = True
    ) -> Dict[str, Any]:
        """
        Get comprehensive export advice
        
        Args:
            hs_code: 6-digit HS code
            country: Destination country (australia, uae, uk)
            quantity: Optional quantity for quota checks
            detailed: Include detailed agreement references
            
        Returns:
            Comprehensive export guidance
        """
        advice = {
            'hs_code': hs_code,
            'country': country.title(),
            'query_time': datetime.now().isoformat(),
            'is_focus_code': Config.is_focus_hs_code(hs_code),
            'recommendation': None,
            'export_allowed': None,
            'restrictions': [],
            'requirements': [],
            'next_steps': [],
        }
        
        # 1. Validate inputs
        if not hs_code or not hs_code.strip():
            advice['recommendation'] = "⚠️ No HS code provided. Please specify a valid HS code."
            advice['export_allowed'] = None
            return advice
        
        if country.lower() not in Config.TARGET_COUNTRIES:
            advice['recommendation'] = f"⚠️ Country '{country}' not in focus. System supports: {', '.join(Config.TARGET_COUNTRIES)}"
            return advice
        
        chapter = Config.get_chapter_from_hs(hs_code)
        if not Config.is_focus_chapter(chapter):
            advice['recommendation'] = f"⚠️ HS Chapter {chapter} not in focus. System covers chapters: {', '.join(Config.FOCUS_CHAPTERS)}"
        
        # 2. Get comprehensive export check
        export_check = self.integrator.can_export_to_country(
            hs_code, 
            country.lower(),
            check_agreements=detailed
        )
        
        advice['export_allowed'] = export_check['can_export']
        advice['restrictions'] = export_check.get('issues', [])
        advice['requirements'] = export_check.get('requirements', [])
        
        # 3. Generate recommendation
        if not export_check['can_export']:
            advice['recommendation'] = f"❌ EXPORT NOT ALLOWED: {hs_code} to {country}"
            advice['next_steps'].extend([
                "Review prohibition reasons listed below",
                "Check if product classification is correct",
                "Consider alternative product categories"
            ])
        else:
            if export_check.get('warnings'):
                advice['recommendation'] = f"⚠️ EXPORT ALLOWED WITH CONDITIONS: {hs_code} to {country}"
                advice['restrictions'].extend(export_check['warnings'])
                advice['next_steps'].extend([
                    "Review all restriction conditions carefully",
                    "Obtain required licenses/certificates",
                    "Ensure compliance with policy conditions"
                ])
            else:
                advice['recommendation'] = f"✅ EXPORT ALLOWED: {hs_code} to {country}"
                advice['next_steps'].extend([
                    "Verify product meets quality standards",
                    "Check trade agreement for preferential tariffs",
                    "Prepare necessary export documentation"
                ])
        
        # 4. Add HS code details
        hs_info = export_check.get('hs_info', {})
        if hs_info:
            advice['product_info'] = {
                'description': hs_info.get('description', 'N/A'),
                'chapter': chapter,
                'chapter_name': Config.CHAPTER_DESCRIPTIONS.get(chapter, 'N/A')
            }
        
        # 5. Add trade statistics if available
        if export_check.get('has_trade_history'):
            advice['trade_history'] = "Historical trade data available"
            stats = export_check.get('trade_statistics', [])
            if stats:
                advice['recent_exports'] = [
                    {
                        'year': s['year_label'],
                        'value_crore': float(s['export_value_crore']) if s['export_value_crore'] else 0
                    }
                    for s in stats[:3]
                ]
        else:
            advice['trade_history'] = "No historical trade data found"
            advice['next_steps'].append("Consider market research for this export route")
        
        # 6. Add agreement references
        if export_check.get('agreement_references'):
            advice['trade_agreement_docs'] = export_check['agreement_references']
            advice['next_steps'].append("Review trade agreement documents for tariff details")
        
        return advice
    
    def answer_query(self, query: str) -> str:
        """
        Answer natural language export query
        
        Args:
            query: Natural language question
            
        Returns:
            Formatted text response
        """
        # Extract HS code and country from query
        extracted = self._extract_query_params(query)
        
        if not extracted['hs_code']:
            return self._general_query_response(query)
        
        # Get advice
        advice = self.advise_export(
            hs_code=extracted['hs_code'],
            country=extracted['country'] or 'australia',  # Default
            detailed=True
        )
        
        # Format response
        return self._format_advice(advice)
    
    def _extract_query_params(self, query: str) -> Dict[str, Optional[str]]:
        """Extract HS code and country from natural language query"""
        result = {'hs_code': None, 'country': None}
        
        # Look for 6-digit HS code
        hs_match = re.search(r'\b(\d{6})\b', query)
        if hs_match:
            result['hs_code'] = hs_match.group(1)
        
        # Look for country
        query_lower = query.lower()
        for country in Config.TARGET_COUNTRIES:
            if country in query_lower or Config.COUNTRY_CODES[country].lower() in query_lower:
                result['country'] = country
                break
        
        return result
    
    def _general_query_response(self, query: str) -> str:
        """Handle general queries without specific HS code using LLM"""
        # Try to answer with LLM if available
        if self.llm:
            try:
                system_context = """You are an expert Indian export trade advisor. Answer the user's 
question about Indian exports, trade agreements, trade policies, and related topics.

Key knowledge:
- India has trade agreements with Australia (AI-ECTA), UAE (CEPA), and UK (FTA under negotiation)
- Exports are governed by DGFT (Directorate General of Foreign Trade)
- Export policies: Free, Restricted, Prohibited, STE (State Trading Enterprise)
- ITC-HS codes classify products for trade
- The Foreign Trade Policy 2023 governs current export rules

India-Australia ECTA (Economic Cooperation and Trade Agreement):
- Signed: April 2, 2022, In force: December 29, 2022
- Covers: Goods, Services, Rules of Origin, Customs Procedures, SPS, TBT
- India gains: Zero-duty access on ~96.4% of Australian tariff lines
- Key sectors: Textiles, agriculture, gems & jewelry, leather, IT services
- Australia gains: Preferential access for minerals, wines, wool, education services

India-UAE CEPA (Comprehensive Economic Partnership Agreement):
- Signed: February 18, 2022, In force: May 1, 2022
- India gains: Zero duty on ~97% of UAE tariff lines covering ~99% of Indian exports
- Key sectors: Gems & jewelry, textiles, agriculture, engineering goods
- UAE gains: Preferential access for petrochemicals, metals, minerals

Be concise, accurate, and helpful. Use markdown formatting.
If you don't know something specific, say so clearly."""

                response = self.llm.invoke([
                    HumanMessage(content=f"{system_context}\n\nUser Question: {query}")
                ])
                return response.content
            except Exception as e:
                print(f"LLM error: {e}")
        
        # Fallback: static response
        response = "I can help you with export queries! \n\n"
        response += "Please provide:\n"
        response += "1. HS Code (6-digit code) - e.g., 070310 for onions\n"
        response += "2. Destination Country - Australia, UAE, or UK\n\n"
        response += "Example queries:\n"
        response += "- 'Can I export HS 070310 to Australia?'\n"
        response += "- 'Export policy for 610910 to UAE'\n"
        response += "- 'Tariff for 850440 in UK'\n\n"
        response += f"My focus areas:\n"
        response += f"- Chapters: {', '.join(Config.FOCUS_CHAPTERS)}\n"
        response += f"- Countries: {', '.join([c.title() for c in Config.TARGET_COUNTRIES])}\n"
        response += f"\n💡 For trade agreement questions, try the web UI at http://localhost:8000\n"
        
        return response
    
    def _format_advice(self, advice: Dict) -> str:
        """Format advice as readable text"""
        lines = []
        lines.append("="*70)
        lines.append("EXPORT ADVICE")
        lines.append("="*70)
        lines.append(f"\nProduct: HS Code {advice['hs_code']}")
        
        if 'product_info' in advice:
            lines.append(f"Description: {advice['product_info']['description']}")
            lines.append(f"Chapter: {advice['product_info']['chapter']} - {advice['product_info']['chapter_name']}")
        
        lines.append(f"Destination: {advice['country']}")
        lines.append(f"\n{advice['recommendation']}")
        
        if advice['restrictions']:
            lines.append(f"\n{'─'*70}")
            lines.append("RESTRICTIONS & WARNINGS:")
            for i, restriction in enumerate(advice['restrictions'], 1):
                lines.append(f"  {i}. {restriction}")
        
        if advice['requirements']:
            lines.append(f"\n{'─'*70}")
            lines.append("REQUIREMENTS:")
            for i, req in enumerate(advice['requirements'], 1):
                lines.append(f"  {i}. {req}")
        
        if advice.get('recent_exports'):
            lines.append(f"\n{'─'*70}")
            lines.append("RECENT EXPORT STATISTICS:")
            for stat in advice['recent_exports']:
                lines.append(f"  {stat['year']}: ₹{stat['value_crore']:.2f} Crore")
        
        if advice.get('trade_agreement_docs'):
            lines.append(f"\n{'─'*70}")
            lines.append("RELEVANT TRADE AGREEMENT DOCUMENTS:")
            for i, doc in enumerate(advice['trade_agreement_docs'][:3], 1):
                lines.append(f"  {i}. {doc['document']}")
                lines.append(f"     Relevance: {doc['relevance']:.1%}")
        
        if advice['next_steps']:
            lines.append(f"\n{'─'*70}")
            lines.append("NEXT STEPS:")
            for i, step in enumerate(advice['next_steps'], 1):
                lines.append(f"  {i}. {step}")
        
        lines.append(f"\n{'='*70}")
        lines.append(f"Query Time: {advice['query_time']}")
        lines.append("="*70)
        
        return "\n".join(lines)
    
    def get_focus_codes_status(self) -> str:
        """Get status of all focus HS codes"""
        summary = self.integrator.get_focus_codes_summary()
        
        lines = []
        lines.append("="*70)
        lines.append("FOCUS HS CODES EXPORT STATUS")
        lines.append("="*70)
        lines.append(f"\nTotal Focus Codes: {summary['total_codes']}")
        lines.append(f"✅ Exportable: {len(summary['exportable_codes'])}")
        lines.append(f"⚠️  Restricted: {len(summary['restricted_codes'])}")
        lines.append(f"❌ Prohibited: {len(summary['prohibited_codes'])}")
        
        for chapter, codes in summary['codes_by_chapter'].items():
            lines.append(f"\n{'─'*70}")
            lines.append(f"Chapter {chapter} - {Config.CHAPTER_DESCRIPTIONS.get(chapter, 'N/A')}")
            lines.append(f"{'─'*70}")
            for code_info in codes:
                status_icon = {
                    'Free': '✅',
                    'Restricted': '⚠️',
                    'Prohibited': '❌'
                }.get(code_info['status'], '?')
                lines.append(f"  {status_icon} {code_info['hs_code']}: {code_info['description']}")
        
        lines.append("\n" + "="*70)
        
        return "\n".join(lines)
    
    def close(self):
        """Cleanup resources"""
        self.integrator.close()


def interactive_demo():
    """Interactive demo of the export advisor"""
    print("\n" + "="*70)
    print("EXPORT ADVISOR AGENT - INTERACTIVE DEMO")
    print("="*70)
    print("\nInitializing...")
    
    agent = ExportAdvisorAgent()
    
    # Demo queries
    demo_queries = [
        # ("Can I export HS 070310 to Australia?", "070310", "australia"),
        # ("What about HS 610910 to UAE?", "610910", "uae"),
        # ("Export policy for 850440 to UK", "850440", "uk"),
        # ("Tell me if there are restrictions on export of Electronic cigarettes and similar personal electric vaporising devices" , "85434000" , "UAE"),
        # ("Tell about iron ore concentrates" , "26011150" , "australia" ),
        # ("what is the rules" , " 85131010" , "uae"),
        ("Tell me in short the trade agreements b/w india and australia", "", "australia")
    ]
    
    for query, hs_code, country in demo_queries:
        print(f"\n{'═'*70}")
        print(f"Query: {query}")
        print(f"{'═'*70}")
        
        # Use answer_query for NLP-based routing (handles general queries)
        response = agent.answer_query(query)
        print(response)
        
        input("\nPress Enter for next query...")
    
    # Show focus codes summary
    print("\n" + "="*70)
    print(agent.get_focus_codes_status())
    
    agent.close()


if __name__ == "__main__":
    interactive_demo()
