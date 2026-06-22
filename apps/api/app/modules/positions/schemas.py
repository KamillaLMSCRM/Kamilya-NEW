from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class PositionCreate(BaseModel):
    name: str
    department: str = ""
    level: str = ""


class PositionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    department: str
    level: str
    employee_count: int
    created_at: datetime

    class Config:
        from_attributes = True
