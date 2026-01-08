"""
Sherpa 1099 FastAPI Backend.

Main application entry point.
Run with: uvicorn api.main:app --reload --port 8002
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import operating_years, filers, recipients, forms, dashboard, imports, web, pdf

app = FastAPI(
    title="Sherpa 1099 API",
    description="Backend API for 1099 e-filing with IRS IRIS",
    version="0.1.0",
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (if needed)
# app.mount("/static", StaticFiles(directory="static"), name="static")

# Include API routers
app.include_router(operating_years.router, prefix="/api/operating-years", tags=["Operating Years"])
app.include_router(filers.router, prefix="/api/filers", tags=["Filers"])
app.include_router(recipients.router, prefix="/api/recipients", tags=["Recipients"])
app.include_router(forms.router, prefix="/api/forms", tags=["1099 Forms"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(imports.router, prefix="/api/imports", tags=["Imports"])
app.include_router(pdf.router, prefix="/api/pdf", tags=["PDF Generation"])

# Include Web UI router (must be last to not override API routes)
app.include_router(web.router, tags=["Web UI"])


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "healthy"}
