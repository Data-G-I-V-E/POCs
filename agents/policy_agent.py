"""
Policy Agent

Checks export policies and restrictions for specific HS codes.
Uses ExportDataIntegrator for policy lookups.
"""

from datetime import datetime

from export_data_integrator import ExportDataIntegrator
from .state import AgentState


class PolicyAgent:
    """Agent for checking export policies and restrictions"""
    
    def __init__(self):
        self.integrator = ExportDataIntegrator(use_vector_stores=False)
    
    def execute(self, state: AgentState) -> AgentState:
        """Check export policy"""
        hs_code = state.get("hs_code")
        country = state.get("country")
        
        if not hs_code:
            state["policy_results"] = {
                "error": "No HS code provided",
                "success": False
            }
            state["next_agent"] = "synthesizer"
            return state
        
        try:
            # Get comprehensive export check
            if country:
                result = self.integrator.can_export_to_country(
                    hs_code=hs_code,
                    country=country,
                    check_agreements=False
                )
            else:
                result = self.integrator.get_hs_code_info(hs_code)
            
            state["policy_results"] = {
                "result": result,
                "success": True
            }
            
            state["sources"].append({
                "type": "policy_check",
                "hs_code": hs_code,
                "country": country,
                "tables": ["v_export_policy_unified", "prohibited_items", "restricted_items", "ste_items", "itc_chapter_notes"],
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            state["policy_results"] = {
                "error": str(e),
                "success": False
            }
        
        state["next_agent"] = "synthesizer"
        return state
