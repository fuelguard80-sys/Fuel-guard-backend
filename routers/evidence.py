from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from core.config import settings
from core.dependencies import get_current_user, require_admin
from core.firebase import Collections, get_bucket, get_db
from models.evidence import EvidenceResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _blob_name_from_url(url: str, bucket_name: str) -> str | None:
    """
    Extract the GCS blob path from a public storage URL.
    Uses urllib.parse — not string-splitting — for reliability.
    """
    try:
        parsed   = urlparse(url)
        # Public URL format: https://storage.googleapis.com/<bucket>/<blob>
        prefix   = f"/{bucket_name}/"
        if prefix in parsed.path:
            return parsed.path.split(prefix, 1)[1]
    except Exception:
        pass
    return None


@router.post("", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def upload_evidence(
    transaction_id: str,
    nozzle_id: str,
    session_id: str | None = None,
    capture_trigger: str = "auto",
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    db     = get_db()
    bucket = get_bucket()

    tx_doc = db.collection(Collections.TRANSACTIONS).document(transaction_id).get()
    if not tx_doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    evidence_id = str(uuid.uuid4())
    ext         = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    blob_path   = f"evidence/{transaction_id}/{evidence_id}.{ext}"
    thumb_path  = f"evidence/{transaction_id}/{evidence_id}_thumb.{ext}"

    contents = await file.read()

    blob = bucket.blob(blob_path)
    blob.upload_from_string(contents, content_type=file.content_type or "image/jpeg")
    blob.make_public()
    image_url = blob.public_url

    # Generate thumbnail without crashing the upload if it fails
    thumbnail_url: str | None = None
    try:
        from io import BytesIO
        from PIL import Image

        img = Image.open(BytesIO(contents))
        img.thumbnail((320, 320))
        thumb_buf = BytesIO()
        fmt       = ext.upper() if ext.upper() in ("PNG", "JPEG") else "JPEG"
        img.save(thumb_buf, format=fmt)

        thumb_blob = bucket.blob(thumb_path)
        thumb_blob.upload_from_string(thumb_buf.getvalue(), content_type="image/jpeg")
        thumb_blob.make_public()
        thumbnail_url = thumb_blob.public_url
    except Exception:
        logger.exception("Thumbnail generation failed for evidence %s", evidence_id)

    delete_at     = datetime.now(timezone.utc) + timedelta(days=settings.EVIDENCE_RETENTION_DAYS)
    watermark_txt = (
        f"TXN:{transaction_id} | "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )

    doc_data = {
        "id": evidence_id,
        "transaction_id": transaction_id,
        "nozzle_id": nozzle_id,
        "session_id": session_id,
        "image_url": image_url,
        "thumbnail_url": thumbnail_url,
        "file_size_kb": round(len(contents) / 1024, 2),
        "capture_trigger": capture_trigger,
        "metadata": {
            "uploaded_by": current_user["uid"],
            "original_filename": file.filename,
        },
        "watermark_text": watermark_txt,
        "delete_at": delete_at,
        "created_at": datetime.now(timezone.utc),
    }
    db.collection(Collections.EVIDENCE).document(evidence_id).set(doc_data)
    db.collection(Collections.TRANSACTIONS).document(transaction_id).update(
        {"evidence_url": image_url}
    )

    return EvidenceResponse(**doc_data)


@router.get("/{transaction_id}")
async def get_evidence_for_transaction(
    transaction_id: str,
    _: dict = Depends(get_current_user),
):
    db   = get_db()
    docs = db.collection(Collections.EVIDENCE).where("transaction_id", "==", transaction_id).get()
    return [{"id": d.id, **d.to_dict()} for d in docs]


@router.get("/{evidence_id}/image")
async def get_evidence_image(evidence_id: str, _: dict = Depends(get_current_user)):
    db  = get_db()
    doc = db.collection(Collections.EVIDENCE).document(evidence_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
    data = doc.to_dict()
    return {"image_url": data.get("image_url"), "thumbnail_url": data.get("thumbnail_url")}


@router.delete("/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evidence(evidence_id: str, _: dict = Depends(require_admin)):
    db     = get_db()
    bucket = get_bucket()
    doc    = db.collection(Collections.EVIDENCE).document(evidence_id).get()
    if not doc.exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")

    data = doc.to_dict()
    for url_key in ("image_url", "thumbnail_url"):
        url = data.get(url_key)
        if url:
            blob_name = _blob_name_from_url(url, bucket.name)
            if blob_name:
                try:
                    bucket.blob(blob_name).delete()
                except Exception:
                    logger.exception("Failed to delete blob %s from storage", blob_name)

    db.collection(Collections.EVIDENCE).document(evidence_id).delete()


@router.post("/auto-delete", status_code=status.HTTP_200_OK)
async def auto_delete_expired_evidence():
    """
    Background job — enforces the evidence retention policy.
    Should be triggered by a scheduler, not end-users.
    """
    db     = get_db()
    bucket = get_bucket()
    now    = datetime.now(timezone.utc)
    docs   = db.collection(Collections.EVIDENCE).where("delete_at", "<=", now).get()

    deleted = 0
    for doc in docs:
        data = doc.to_dict()
        for url_key in ("image_url", "thumbnail_url"):
            url = data.get(url_key)
            if url:
                blob_name = _blob_name_from_url(url, bucket.name)
                if blob_name:
                    try:
                        bucket.blob(blob_name).delete()
                    except Exception:
                        logger.exception("Storage delete failed for blob %s", blob_name)
        db.collection(Collections.EVIDENCE).document(doc.id).delete()
        deleted += 1

    return {"deleted_count": deleted}


@router.get("")
async def list_all_evidence(
    nozzle_id: str | None = Query(None),
    capture_trigger: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: dict = Depends(require_admin),
):
    db    = get_db()
    query = db.collection(Collections.EVIDENCE)
    if nozzle_id:
        query = query.where("nozzle_id", "==", nozzle_id)
    if capture_trigger:
        query = query.where("capture_trigger", "==", capture_trigger)

    docs  = query.order_by("created_at", direction="DESCENDING").get()
    items = [{"id": d.id, **d.to_dict()} for d in docs]
    return {"total": len(items), "items": items[offset: offset + limit]}
