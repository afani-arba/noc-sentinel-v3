from fastapi import APIRouter, HTTPException
import subprocess
import json
import logging
from typing import Optional

logger = logging.getLogger("looking-glass")
router = APIRouter(tags=["BGP Looking Glass"])

@router.get("/bgp/looking-glass")
async def looking_glass_query(target: str):
    """Query GoBGP for a specific IP or Prefix"""
    if not target:
        raise HTTPException(status_code=400, detail="Target IP/Prefix is required")
        
    try:
        # Run gobgp query
        result = subprocess.run(
            ["gobgp", "global", "rib", "-j", target],
            capture_output=True, text=True, timeout=10
        )
        
        # If gobgp errors out, it usually returns non-zero
        if result.returncode != 0:
            err = result.stderr.strip()
            if "Network not in table" in err or "not found" in err.lower() or "No such network" in err:
                return {"status": "success", "target": target, "data": []}
            raise HTTPException(status_code=500, detail=f"GoBGP Error: {err}")
            
        output = result.stdout.strip()
        if not output:
             return {"status": "success", "target": target, "data": []}
             
        try:
            data = json.loads(output)
            # Gobgp returns a single prefix object or array of prefixes depending on query.
            # Convert to list if it's a single dict to keep frontend logic simple.
            if isinstance(data, dict):
                data = [data]
        except json.JSONDecodeError:
            # Maybe it output plaintext because of old gobgp version
            if "Network not in table" in output:
                return {"status": "success", "target": target, "data": []}
            raise HTTPException(status_code=500, detail="Failed to parse GoBGP output")
            
        return {"status": "success", "target": target, "data": data}
        
    except subprocess.TimeoutExpired:
         raise HTTPException(status_code=504, detail="GoBGP query timed out")
    except FileNotFoundError:
         raise HTTPException(status_code=500, detail="GoBGP CLI (gobgp) not found on server")
    except HTTPException:
         raise
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))
