"""
Announcement endpoints for the High School Management System API
"""

from datetime import date
from typing import Any, Dict, List, Optional
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from bson import ObjectId

from ..database import announcements_collection, teachers_collection

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementInput(BaseModel):
    message: str = Field(..., min_length=5, max_length=600)
    expiration_date: date
    start_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "AnnouncementInput":
        if self.start_date and self.start_date > self.expiration_date:
            raise ValueError("start_date must be earlier than or equal to expiration_date")
        return self


class AnnouncementUpdate(BaseModel):
    message: Optional[str] = Field(default=None, min_length=5, max_length=600)
    expiration_date: Optional[date] = None
    start_date: Optional[date] = None


class AnnouncementOutput(BaseModel):
    id: str
    message: str
    expiration_date: str
    start_date: Optional[str] = None
    created_by: str



def _validate_teacher(teacher_username: Optional[str]) -> Dict[str, Any]:
    if not teacher_username:
        raise HTTPException(status_code=401, detail="Authentication required")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher



def _to_output(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "message": doc["message"],
        "expiration_date": doc["expiration_date"],
        "start_date": doc.get("start_date"),
        "created_by": doc.get("created_by", "unknown")
    }


@router.get("", response_model=List[AnnouncementOutput])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get active announcements for all users.

    Returns announcements that are not expired and, when start_date exists,
    are already started.
    """
    today = date.today().isoformat()

    query = {
        "expiration_date": {"$gte": today},
        "$or": [
            {"start_date": None},
            {"start_date": {"$exists": False}},
            {"start_date": {"$lte": today}}
        ]
    }

    docs = announcements_collection.find(query).sort("expiration_date", 1)
    return [_to_output(doc) for doc in docs]


@router.get("/all", response_model=List[AnnouncementOutput])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Get all announcements for management. Requires authenticated teacher."""
    _validate_teacher(teacher_username)

    docs = announcements_collection.find({}).sort("expiration_date", 1)
    return [_to_output(doc) for doc in docs]


@router.post("", response_model=AnnouncementOutput)
def create_announcement(
    payload: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create an announcement. Requires authenticated teacher."""
    _validate_teacher(teacher_username)

    new_doc = {
        "message": payload.message.strip(),
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "expiration_date": payload.expiration_date.isoformat(),
        "created_by": teacher_username
    }

    try:
        result = announcements_collection.insert_one(new_doc)
        created = announcements_collection.find_one({"_id": result.inserted_id})
        return _to_output(created)
    except Exception:
        logger.exception("Failed to create announcement")
        raise HTTPException(status_code=500, detail="Unable to create announcement")


@router.put("/{announcement_id}", response_model=AnnouncementOutput)
def update_announcement(
    announcement_id: str,
    payload: AnnouncementUpdate,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an announcement. Requires authenticated teacher."""
    _validate_teacher(teacher_username)

    update_data: Dict[str, Any] = {}

    provided_fields = payload.model_fields_set

    if "message" in provided_fields and payload.message is not None:
        update_data["message"] = payload.message.strip()

    if "start_date" in provided_fields:
        update_data["start_date"] = payload.start_date.isoformat() if payload.start_date else None

    if "expiration_date" in provided_fields and payload.expiration_date is not None:
        update_data["expiration_date"] = payload.expiration_date.isoformat()

    if not update_data:
        raise HTTPException(status_code=400, detail="No changes provided")

    try:
        object_id = ObjectId(announcement_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid announcement id")

    existing = announcements_collection.find_one({"_id": object_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Announcement not found")

    effective_start_date = update_data.get("start_date", existing.get("start_date"))
    effective_expiration_date = update_data.get("expiration_date", existing.get("expiration_date"))

    if effective_start_date and effective_start_date > effective_expiration_date:
        raise HTTPException(status_code=400, detail="start_date must be <= expiration_date")

    try:
        result = announcements_collection.update_one(
            {"_id": object_id},
            {"$set": update_data}
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Announcement not found")

        updated = announcements_collection.find_one({"_id": object_id})
        return _to_output(updated)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update announcement")
        raise HTTPException(status_code=500, detail="Unable to update announcement")


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement. Requires authenticated teacher."""
    _validate_teacher(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid announcement id")

    try:
        result = announcements_collection.delete_one({"_id": object_id})

        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Announcement not found")

        return {"message": "Announcement deleted"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete announcement")
        raise HTTPException(status_code=500, detail="Unable to delete announcement")
