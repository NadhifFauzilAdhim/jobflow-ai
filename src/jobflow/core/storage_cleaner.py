"""Storage and Output Files Cleanup Engine for JobFlow AI.

Manages deletion, orphan purging, and storage tracking of generated resumes,
preview artifacts, and automation screenshots in the output directory.
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Set, Dict, Any, Optional

from jobflow.config import OUTPUT_DIR

logger = logging.getLogger("jobflow.storage_cleaner")


def get_output_dir() -> Path:
    """Ensure output directory exists and return Path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def delete_job_files(job_id: int, resume_pdf_path: Optional[str] = None) -> List[str]:
    """
    Delete all output files associated with a specific job ID:
    - Primary and highlighted resume PDFs (e.g. resume_{job_id}_*.pdf)
    - Application screenshots (e.g. screenshots/app_{job_id}.png)
    - Directly referenced resume_pdf_path if provided
    """
    output_dir = get_output_dir()
    deleted_files: List[str] = []

    # 1. Delete referenced resume_pdf_path
    if resume_pdf_path:
        p = Path(resume_pdf_path)
        if p.exists() and p.is_file():
            try:
                p.unlink()
                deleted_files.append(p.name)
            except Exception as e:
                logger.warning(f"Could not delete file {p}: {e}")

    # 2. Find and delete all PDFs starting with resume_{job_id}_
    prefix = f"resume_{job_id}_"
    try:
        for f in output_dir.glob(f"{prefix}*.pdf"):
            if f.is_file():
                try:
                    f.unlink()
                    deleted_files.append(f.name)
                except Exception as e:
                    logger.warning(f"Could not delete {f}: {e}")
    except Exception as e:
        logger.warning(f"Error scanning for job {job_id} PDFs: {e}")

    # 3. Find and delete screenshots for this job
    screenshot_dir = output_dir / "screenshots"
    if screenshot_dir.exists():
        for s in screenshot_dir.glob(f"app_{job_id}*.png"):
            if s.is_file():
                try:
                    s.unlink()
                    deleted_files.append(f"screenshots/{s.name}")
                except Exception as e:
                    logger.warning(f"Could not delete screenshot {s}: {e}")

    logger.info(f"Deleted {len(deleted_files)} files for Job #{job_id}: {deleted_files}")
    return deleted_files


def cleanup_orphaned_output_files(active_job_ids: Set[int]) -> Dict[str, Any]:
    """
    Scan the output directory and delete any resume PDFs and screenshots
    that do not correspond to any active job in active_job_ids.
    Also removes temporary/test PDFs (e.g. test_tailored.pdf).
    """
    output_dir = get_output_dir()
    deleted: List[str] = []
    bytes_freed = 0

    # Pattern to match resume_{id}_...
    resume_pattern = re.compile(r"^resume_(\d+)_", re.IGNORECASE)

    # 1. Check all files in output root
    for f in output_dir.iterdir():
        if not f.is_file() or f.name == ".gitkeep":
            continue

        match = resume_pattern.match(f.name)
        should_delete = False

        if match:
            job_id = int(match.group(1))
            if job_id not in active_job_ids:
                should_delete = True
        elif f.name.startswith("test_") and f.suffix == ".pdf":
            # Leftover test artifact
            should_delete = True

        if should_delete:
            try:
                size = f.stat().st_size
                f.unlink()
                bytes_freed += size
                deleted.append(f.name)
            except Exception as e:
                logger.warning(f"Could not delete orphaned file {f.name}: {e}")

    # 2. Check screenshots directory
    screenshot_dir = output_dir / "screenshots"
    if screenshot_dir.exists():
        screenshot_pattern = re.compile(r"^app_(\d+)", re.IGNORECASE)
        for s in screenshot_dir.iterdir():
            if not s.is_file() or s.name == ".gitkeep":
                continue

            match = screenshot_pattern.match(s.name)
            if match:
                job_id = int(match.group(1))
                if job_id not in active_job_ids:
                    try:
                        size = s.stat().st_size
                        s.unlink()
                        bytes_freed += size
                        deleted.append(f"screenshots/{s.name}")
                    except Exception as e:
                        logger.warning(f"Could not delete orphaned screenshot {s.name}: {e}")

    return {
        "deleted_count": len(deleted),
        "deleted_files": deleted,
        "bytes_freed": bytes_freed,
        "bytes_freed_mb": round(bytes_freed / (1024 * 1024), 2)
    }


def purge_all_output_files(keep_gitkeep: bool = True) -> Dict[str, Any]:
    """
    Completely purge all generated PDFs and screenshots in output directory.
    """
    output_dir = get_output_dir()
    deleted: List[str] = []
    bytes_freed = 0

    for item in output_dir.rglob("*"):
        if item.is_file():
            if keep_gitkeep and item.name == ".gitkeep":
                continue
            try:
                size = item.stat().st_size
                item.unlink()
                bytes_freed += size
                rel = item.relative_to(output_dir).as_posix()
                deleted.append(rel)
            except Exception as e:
                logger.warning(f"Failed to delete {item}: {e}")

    return {
        "deleted_count": len(deleted),
        "deleted_files": deleted,
        "bytes_freed": bytes_freed,
        "bytes_freed_mb": round(bytes_freed / (1024 * 1024), 2)
    }


def get_output_storage_stats(active_job_ids: Optional[Set[int]] = None) -> Dict[str, Any]:
    """
    Calculate output directory storage statistics:
    - Total files and total size (bytes and MB)
    - Resume PDFs count
    - Screenshots count
    - Count of orphaned files
    """
    output_dir = get_output_dir()
    total_files = 0
    total_bytes = 0
    pdf_count = 0
    screenshot_count = 0
    orphaned_count = 0

    resume_pattern = re.compile(r"^resume_(\d+)_", re.IGNORECASE)
    screenshot_pattern = re.compile(r"^app_(\d+)", re.IGNORECASE)

    for item in output_dir.rglob("*"):
        if item.is_file() and item.name != ".gitkeep":
            total_files += 1
            size = item.stat().st_size
            total_bytes += size

            if item.suffix.lower() == ".pdf":
                pdf_count += 1
            elif item.suffix.lower() == ".png":
                screenshot_count += 1

            if active_job_ids is not None:
                if item.name.startswith("test_"):
                    orphaned_count += 1
                else:
                    m1 = resume_pattern.match(item.name)
                    m2 = screenshot_pattern.match(item.name)
                    jid = None
                    if m1:
                        jid = int(m1.group(1))
                    elif m2:
                        jid = int(m2.group(1))

                    if jid is not None and jid not in active_job_ids:
                        orphaned_count += 1

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "pdf_count": pdf_count,
        "screenshot_count": screenshot_count,
        "orphaned_count": orphaned_count
    }
