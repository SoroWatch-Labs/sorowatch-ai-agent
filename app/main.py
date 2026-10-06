from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.graph.pipeline import run_pipeline
from app.horizon_client import HorizonRateLimitError

app = FastAPI(
    title="SoroWatch AI Agent",
    description="Standalone risk-scoring service using a LangGraph pipeline.",
    version="0.1.0",
)


class ScoreRequest(BaseModel):
    address: str
    threshold: int = 50


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/score")
async def score_address(req: ScoreRequest):
    try:
        result = await run_pipeline(req.address, req.threshold)
    except HorizonRateLimitError:
        raise HTTPException(
            status_code=503,
            detail="Upstream Horizon API is rate limiting requests; try again shortly.",
            headers={"Retry-After": "30"},
        )
    return {
        "address": result["address"],
        "score": result["score"],
        "flagged": result["flagged"],
        "operations_considered": len(result["operations"]),
    }
