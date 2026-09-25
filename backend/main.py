"""
FastAPI application for Document Intake Assistant.

Exposes REST API endpoints for session initialization, multi-turn conversational intake,
structured state inspection, document retrieval, and session resets.
"""

from typing import Any, Dict
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.conversation import ConversationOrchestrator
from backend.document_generator import DocumentGenerator
from backend.llm.factory import get_llm_service
from backend.schemas import (
    ChatRequest,
    ChatResponse,
    DocumentResponse,
    SessionInitResponse,
    StateResponse,
)
from backend.state_manager import SessionManager, SessionNotFoundError


def create_app(
    session_manager: SessionManager = None,
    orchestrator: ConversationOrchestrator = None,
) -> FastAPI:
    """
    Application factory allowing easy dependency injection for tests.
    """
    app = FastAPI(
        title="Document Intake Assistant API",
        description="Conversational intake system for Personal Wishes Documents",
        version="1.0.0",
    )

    # CORS Middleware Configuration (Permits explicit local development origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5500",
            "http://127.0.0.1:5500",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # State singletons & provider selection
    sm = session_manager or SessionManager()
    llm = get_llm_service()
    orch = orchestrator or ConversationOrchestrator(session_manager=sm, llm_service=llm)

    # Attach instances to app state
    app.state.session_manager = sm
    app.state.orchestrator = orch

    INITIAL_GREETING = (
        "Hello! I am your Document Intake Assistant. I am here to help you draft your "
        "Personal Wishes Document step-by-step. To get started, may I please have your full legal name?"
    )

    # --------------------------------------------------------------------------
    # API ENDPOINTS
    # --------------------------------------------------------------------------

    @app.post(
        "/api/session",
        response_model=SessionInitResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create a new intake session",
    )
    def create_session() -> SessionInitResponse:
        """
        Initializes an isolated intake session with an empty structured state
        and a baseline draft document.
        """
        session = app.state.session_manager.create_session()
        draft_doc = DocumentGenerator.generate(session.state)
        return SessionInitResponse(
            session_id=session.session_id,
            state=session.state,
            initial_message=INITIAL_GREETING,
            draft_document=draft_doc,
        )

    @app.post(
        "/api/chat",
        response_model=ChatResponse,
        status_code=status.HTTP_200_OK,
        summary="Process a conversational turn",
    )
    def chat(request: ChatRequest) -> ChatResponse:
        """
        Handles a user message, runs deterministic validation and extraction,
        updates the session state, and returns the assistant reply along with the updated draft document.
        """
        # Validate session existence
        if not app.state.session_manager.exists(request.session_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session '{request.session_id}' not found.",
            )

        # Delegate execution to orchestrator
        result = app.state.orchestrator.handle_user_message(
            session_id=request.session_id,
            user_message=request.message,
        )

        if result.status == "error":
            # Return HTTP 500 while preserving safe structured state
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "session_id": result.session_id,
                    "assistant_message": result.assistant_message,
                    "state": result.state.model_dump(),
                    "draft_document": result.draft_document,
                    "missing_fields": result.missing_fields,
                    "status": "error",
                    "pending_clarification": (
                        result.pending_clarification.model_dump()
                        if result.pending_clarification
                        else None
                    ),
                },
            )

        return ChatResponse(
            session_id=result.session_id,
            assistant_message=result.assistant_message,
            state=result.state,
            draft_document=result.draft_document,
            missing_fields=result.missing_fields,
            status=result.status,
            pending_clarification=result.pending_clarification,
        )

    @app.get(
        "/api/session/{session_id}/state",
        response_model=StateResponse,
        status_code=status.HTTP_200_OK,
        summary="Get structured intake state",
    )
    def get_state(session_id: str) -> StateResponse:
        """
        Retrieves the current confirmed IntakeState for a session.
        """
        try:
            session = app.state.session_manager.get_session(session_id)
            return StateResponse(
                session_id=session.session_id,
                state=session.state,
                missing_fields=session.state.get_missing_fields(),
                is_complete=session.state.is_complete,
            )
        except SessionNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session '{session_id}' not found.",
            )

    @app.get(
        "/api/session/{session_id}/document",
        response_model=DocumentResponse,
        status_code=status.HTTP_200_OK,
        summary="Get formatted draft document",
    )
    def get_document(session_id: str) -> DocumentResponse:
        """
        Generates and returns the latest draft Personal Wishes Document.
        """
        try:
            session = app.state.session_manager.get_session(session_id)
            doc = DocumentGenerator.generate(session.state)
            return DocumentResponse(
                session_id=session.session_id,
                document=doc,
                is_complete=session.state.is_complete,
            )
        except SessionNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session '{session_id}' not found.",
            )

    @app.post(
        "/api/session/{session_id}/reset",
        response_model=SessionInitResponse,
        status_code=status.HTTP_200_OK,
        summary="Reset a session",
    )
    def reset_session(session_id: str) -> SessionInitResponse:
        """
        Resets an existing session back to a blank IntakeState and empty history.
        """
        try:
            reset_session_obj = app.state.session_manager.reset_session(session_id)
            draft_doc = DocumentGenerator.generate(reset_session_obj.state)
            return SessionInitResponse(
                session_id=reset_session_obj.session_id,
                state=reset_session_obj.state,
                initial_message=INITIAL_GREETING,
                draft_document=draft_doc,
            )
        except SessionNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session '{session_id}' not found.",
            )

    # Mount static frontend files for direct browser access at http://localhost:8000
    import os
    from fastapi.staticfiles import StaticFiles
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    if os.path.isdir(frontend_dir):
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


# Default app instance for uvicorn runtime: `py -m uvicorn backend.main:app --reload`
app = create_app()
