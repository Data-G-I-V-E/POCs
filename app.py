"""
FastAPI Backend for Export Advisory System

Provides REST API endpoints for:
- Chat with multi-agent system
- Session management
- Trade data for visualizations
- Export policy queries
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import uvicorn
from datetime import datetime
import traceback
import psycopg2

from agents import ExportAdvisoryGraph
from export_data_integrator import ExportDataIntegrator
from config import Config

# Initialize FastAPI app
app = FastAPI(
    title="Export Advisory API",
    description="Multi-agent export advisory system with conversation memory",
    version="1.0.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize agent and integrator
try:
    agent = ExportAdvisoryGraph()
    integrator = ExportDataIntegrator()
    print("✓ Agent and integrator initialized successfully")
except Exception as e:
    print(f"❌ Error initializing: {e}")
    agent = None
    integrator = None


# ========== REQUEST/RESPONSE MODELS ==========

class ChatRequest(BaseModel):
    """Request model for chat endpoint"""
    query: str = Field(..., description="User query", min_length=1)
    session_id: str = Field(default="default", description="Session ID for conversation memory")

class ChatResponse(BaseModel):
    """Response model for chat endpoint"""
    answer: str
    sources: List[Dict[str, Any]]
    query_type: str
    hs_code: Optional[str] = None
    country: Optional[str] = None
    session_id: str
    timestamp: str

class SessionHistoryResponse(BaseModel):
    """Response model for session history"""
    session_id: str
    history: List[Dict[str, str]]
    message_count: int

class TradeDataRequest(BaseModel):
    """Request model for trade data"""
    hs_code: Optional[str] = None
    chapter: Optional[str] = None
    countries: List[str] = ["australia", "uae", "uk"]

class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    detail: Optional[str] = None
    timestamp: str


# ========== ENDPOINTS ==========

@app.get("/")
async def root():
    """Root endpoint - serves the frontend"""
    return FileResponse("static/index.html")

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy" if agent and integrator else "error",
        "agent_ready": agent is not None,
        "integrator_ready": integrator is not None,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a chat query through the multi-agent system
    
    Maintains conversation history per session
    """
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        result = agent.query(request.query, session_id=request.session_id)
        return ChatResponse(**result)
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/session/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str):
    """Get conversation history for a session"""
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        history = agent.get_session_history(session_id)
        message_count = agent.get_session_message_count(session_id)
        
        return SessionHistoryResponse(
            session_id=session_id,
            history=history,
            message_count=message_count
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    """Clear conversation history for a session"""
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        agent.clear_session(session_id)
        return {"message": f"Session {session_id} cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions"""
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        sessions = agent.list_sessions()
        return {
            "sessions": sessions,
            "count": len(sessions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trade-data")
async def get_trade_data(request: TradeDataRequest):
    """
    Get trade data for visualization
    
    Returns export statistics for specified HS code or chapter
    """
    if not integrator:
        raise HTTPException(status_code=503, detail="Integrator not initialized")
    
    try:
        conn = psycopg2.connect(**Config.DB_CONFIG)
        cursor = conn.cursor()
        
        # Build query based on request
        if request.hs_code:
            query = """
                SELECT c.country_name, SUM(es.export_value_crore) as total_value
                FROM export_statistics es
                JOIN countries c ON es.country_code = c.country_code
                WHERE es.hs_code = %s
                GROUP BY c.country_name, es.country_code
                ORDER BY total_value DESC
            """
            cursor.execute(query, (request.hs_code,))
        elif request.chapter:
            query = """
                SELECT c.country_name, SUM(es.export_value_crore) as total_value
                FROM export_statistics es
                JOIN countries c ON es.country_code = c.country_code
                WHERE es.hs_code LIKE %s
                GROUP BY c.country_name, es.country_code
                ORDER BY total_value DESC
            """
            cursor.execute(query, (f"{request.chapter}%",))
        else:
            # Get totals by country
            query = """
                SELECT c.country_name, SUM(es.export_value_crore) as total_value
                FROM export_statistics es
                JOIN countries c ON es.country_code = c.country_code
                GROUP BY c.country_name, es.country_code
                ORDER BY total_value DESC
            """
            cursor.execute(query)
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Format for chart
        data = []
        # Convert request.countries to lowercase for comparison
        countries_lower = [c.lower() for c in request.countries]
        
        for country_name, value in results:
            if country_name:
                # Check if country name matches any in the request list
                # Handle variations: "United Arab Emirates" → "uae", "United Kingdom" → "uk"
                country_lower = country_name.lower()
                if ('uae' in countries_lower and 'emirates' in country_lower) or \
                   ('uk' in countries_lower and 'kingdom' in country_lower) or \
                   ('australia' in countries_lower and 'australia' in country_lower):
                    data.append({
                        "country": country_name.upper() if len(country_name) <= 3 else country_name,
                        "value": float(value) if value else 0
                    })
        
        return {
            "data": data,
            "hs_code": request.hs_code,
            "chapter": request.chapter,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"Error in trade-data endpoint: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/monthly-trade-data")
async def get_monthly_trade_data(request: TradeDataRequest):
    """
    Get monthly trade data for visualization (line chart).
    
    Returns month-by-month export values per country for a given HS code or chapter.
    """
    if not integrator:
        raise HTTPException(status_code=503, detail="Integrator not initialized")
    
    try:
        conn = psycopg2.connect(**Config.DB_CONFIG)
        cursor = conn.cursor()
        
        if request.hs_code:
            query = """
                SELECT country_name, month, month_name, export_value_crore, 
                       monthly_growth_pct, ytd_value_crore
                FROM v_monthly_exports
                WHERE hs_code = %s
                ORDER BY country_name, month
            """
            cursor.execute(query, (request.hs_code,))
        elif request.chapter:
            query = """
                SELECT country_name, month, month_name, 
                       SUM(export_value_crore) as export_value_crore,
                       AVG(monthly_growth_pct) as monthly_growth_pct,
                       SUM(ytd_value_crore) as ytd_value_crore
                FROM v_monthly_exports
                WHERE chapter = %s
                GROUP BY country_name, month, month_name
                ORDER BY country_name, month
            """
            cursor.execute(query, (request.chapter,))
        else:
            cursor.close()
            conn.close()
            return {"monthly_data": {}, "months": [], "hs_code": None, "chapter": None,
                    "timestamp": datetime.now().isoformat()}
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Country name normalization for display
        def short_country(name):
            if not name:
                return "Unknown"
            nl = name.lower()
            if "emirates" in nl:
                return "UAE"
            if "kingdom" in nl:
                return "UK"
            return name
        
        # Group by country → list of monthly values
        countries_lower = [c.lower() for c in request.countries]
        monthly_data = {}  # { "Australia": [{month, value, growth}, ...], ... }
        months_set = set()
        
        for country_name, month, month_name, value, growth, ytd in results:
            if not country_name:
                continue
            cn_lower = country_name.lower()
            # Filter to requested countries
            if not (('uae' in countries_lower and 'emirates' in cn_lower) or
                    ('uk' in countries_lower and 'kingdom' in cn_lower) or
                    ('australia' in countries_lower and 'australia' in cn_lower)):
                continue
            
            label = short_country(country_name)
            if label not in monthly_data:
                monthly_data[label] = []
            
            monthly_data[label].append({
                "month": month,
                "month_name": month_name,
                "value": float(value) if value else 0,
                "growth_pct": float(growth) if growth else None,
                "ytd_value": float(ytd) if ytd else 0
            })
            months_set.add((month, month_name))
        
        # Sorted month labels
        months = [m[1] for m in sorted(months_set, key=lambda x: x[0])]
        
        return {
            "monthly_data": monthly_data,
            "months": months,
            "hs_code": request.hs_code,
            "chapter": request.chapter,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"Error in monthly-trade-data endpoint: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/hs-code/{hs_code}")
async def get_hs_code_info(hs_code: str):
    """Get information about a specific HS code"""
    if not integrator:
        raise HTTPException(status_code=503, detail="Integrator not initialized")
    
    try:
        info = integrator.get_hs_code_info(hs_code)
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/export-check")
async def check_export(
    hs_code: str = Query(..., description="HS Code to check"),
    country: str = Query(..., description="Country to export to (australia, uae, uk)")
):
    """Check if export is allowed for HS code to country"""
    if not integrator:
        raise HTTPException(status_code=503, detail="Integrator not initialized")
    
    try:
        result = integrator.can_export_to_country(hs_code, country)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/focus-codes")
async def get_focus_codes():
    """Get list of focus HS codes"""
    return {
        "focus_codes": Config.FOCUS_HS_CODES,
        "count": len(Config.FOCUS_HS_CODES)
    }

@app.get("/api/restriction-check")
async def check_restriction(
    hs_code: str = Query(..., description="HS Code to check for restrictions")
):
    """
    Check if an HS code is prohibited, restricted, or STE-controlled.
    Uses the improved prefix-matching to catch 6→8 digit lookups.
    """
    if not integrator:
        raise HTTPException(status_code=503, detail="Integrator not initialized")
    
    try:
        info = integrator.get_hs_code_info(hs_code)
        if not info:
            return {
                "hs_code": hs_code,
                "found": False,
                "message": f"HS code {hs_code} not found in database"
            }
        
        status = "FREE"
        if info.get('is_prohibited'):
            status = "PROHIBITED"
        elif info.get('is_restricted'):
            status = "RESTRICTED"
        elif info.get('is_ste'):
            status = "STE_ONLY"
        
        return {
            "hs_code": hs_code,
            "found": True,
            "status": status,
            "is_prohibited": info.get('is_prohibited', False),
            "is_restricted": info.get('is_restricted', False),
            "is_ste": info.get('is_ste', False),
            "description": info.get('description', 'N/A'),
            "prohibited_info": info.get('prohibited_info'),
            "restricted_info": info.get('restricted_info'),
            "ste_info": info.get('ste_info'),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Mount static files (frontend)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ========== STARTUP ==========

if __name__ == "__main__":
    print("="*70)
    print("EXPORT ADVISORY SYSTEM - FASTAPI SERVER")
    print("="*70)
    print("\nStarting server...")
    print("API Docs: http://localhost:8000/docs")
    print("Frontend: http://localhost:8000")
    print("\n" + "="*70)
    
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
