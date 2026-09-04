"""Agent management endpoints.

POST   /api/v1/agents         — create an agent
GET    /api/v1/agents          — list agents for the authenticated user
GET    /api/v1/agents/{id}     — get a specific agent
PUT    /api/v1/agents/{id}     — update an agent

Does NOT execute payments, call LLMs, or modify engine logic.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.identity import get_current_user
from app.core.ownership import validate_agent_belongs_to_user
from app.models.user import User
from app.repositories.agents import AgentRepository
from app.schemas.agent import AgentCreate, AgentListResponse, AgentRead, AgentUpdate

logger = structlog.get_logger()
router = APIRouter()


@router.post("/agents", response_model=AgentRead, status_code=201)
async def create_agent(
    request: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    """Create a new agent for the authenticated user."""
    try:
        repo = AgentRepository(db)
        agent = await repo.create(
            user_id=current_user.id,
            name=request.name,
            description=request.description,
            external_reference=request.external_reference,
        )
        logger.info(
            "agent_created",
            agent_id=str(agent.id),
            user_id=str(current_user.id),
            name=agent.name,
        )
        return AgentRead.model_validate(agent)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("agent_create_error", error=str(e))
        raise HTTPException(
            status_code=500, detail="Failed to create agent"
        ) from e


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AgentListResponse:
    """List agents belonging to the authenticated user."""
    try:
        repo = AgentRepository(db)
        agents, total = await repo.list_by_user(
            current_user.id, offset=offset, limit=limit,
        )
        return AgentListResponse(
            agents=[AgentRead.model_validate(a) for a in agents],
            total=total,
        )
    except Exception as e:
        logger.error("agent_list_error", error=str(e))
        raise HTTPException(
            status_code=500, detail="Failed to list agents"
        ) from e


@router.get("/agents/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    """Get a specific agent by ID. Ownership is enforced."""
    try:
        await validate_agent_belongs_to_user(db, current_user.id, agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    repo = AgentRepository(db)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    return AgentRead.model_validate(agent)


@router.put("/agents/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: uuid.UUID,
    request: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    """Update an agent. Ownership is enforced."""
    try:
        await validate_agent_belongs_to_user(db, current_user.id, agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    repo = AgentRepository(db)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Apply updates — only non-None fields
    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return AgentRead.model_validate(agent)

    agent = await repo.update(agent, **update_data)

    logger.info(
        "agent_updated",
        agent_id=str(agent.id),
        user_id=str(current_user.id),
        fields=list(update_data.keys()),
    )
    return AgentRead.model_validate(agent)
