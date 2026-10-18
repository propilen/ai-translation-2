from datetime import datetime
from pathlib import Path
import re
from shutil import copyfileobj


def _create_timestamped_directory(root: Path) -> tuple[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y.%m.%d_%H.%M.%S")
    number = 1
    while True:
        job_id = base if number == 1 else f"{base}_{number:02d}"
        directory = root / job_id
        try:
            # The operation is atomic: concurrent uploads cannot claim the
            # same timestamped directory between an existence check and mkdir.
            directory.mkdir()
            break
        except FileExistsError:
            number += 1

    return job_id, directory


def _safe_folder_name(filename: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", Path(filename).stem).strip(". ")
    return name or "document"


def create_job_directory(root: Path) -> tuple[str, Path]:
    """Legacy single-document layout with a per-job glossary folder."""
    job_id, directory = _create_timestamped_directory(root)
    for name in ("in", "xliff", "out", "gloss"):
        (directory / name).mkdir()
    return job_id, directory


def create_batch_directory(root: Path) -> tuple[str, Path]:
    """Create a parent folder shared by every document in one upload."""
    batch_id, directory = _create_timestamped_directory(root)
    (directory / "jobs").mkdir()
    (directory / "gloss").mkdir()
    return batch_id, directory


def create_batch_job_directory(batch_directory: Path, index: int, filename: str) -> Path:
    """Create an isolated work folder for one document inside a batch."""
    directory = batch_directory / "jobs" / f"{index:03d}_{_safe_folder_name(filename)}"
    directory.mkdir()
    for name in ("in", "xliff", "out"):
        (directory / name).mkdir()
    return directory


def save_upload(upload, destination: Path) -> None:
    """Stream an uploaded file to disk without keeping it all in RAM."""
    with destination.open("wb") as output:
        copyfileobj(upload.file, output)
