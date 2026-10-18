"""Repeatable import budget check; run after generating the fixture."""
from pathlib import Path
from time import perf_counter
from app.xliff import parse
p=Path(__file__).parents[2]/'demo-20000.xliff'
start=perf_counter();_,_,_,segments=parse(p.read_bytes());elapsed=perf_counter()-start
assert len(segments)==20_000, len(segments)
print(f'Parsed {len(segments):,} segments in {elapsed:.2f}s (target: < 5s on a developer machine)')
