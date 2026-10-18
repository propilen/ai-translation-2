from pydantic import BaseModel, Field

class SegmentOut(BaseModel):
    id: str; xliff_id: str | None; file_id: str; unit_id: str; segment_index: int
    source_text: str; source_xml: str; target_xml: str | None; state: str

class DocumentOut(BaseModel):
    id: str; name: str; source_language: str | None; target_language: str | None
    segment_count: int

class DocumentDetail(DocumentOut):
    segments: list[SegmentOut]

class SegmentPatch(BaseModel):
    target_xml: str = Field(max_length=1_000_000)
    state: str | None = Field(default=None, pattern="^(translated|untranslated|reviewed|initial)$")

class SaveRequest(BaseModel):
    changes: list[SegmentPatch] | None = None
