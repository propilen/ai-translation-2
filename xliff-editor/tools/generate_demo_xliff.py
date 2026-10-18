"""Generate a deterministic 20k-row, roughly 100k-word XLIFF performance fixture."""
from pathlib import Path
import argparse
from xml.sax.saxutils import escape

def main():
    p=argparse.ArgumentParser();p.add_argument('-o','--output',type=Path,default=Path('demo-20000.xliff'));p.add_argument('-n','--segments',type=int,default=20_000);a=p.parse_args()
    rows=['<?xml version="1.0" encoding="UTF-8"?>','<xliff version="1.2" source-language="en" target-language="ru"><file original="performance-demo" datatype="plaintext"><body>']
    for i in range(1,a.segments+1):
        kind=i%4
        if i%997==0: source=f'Open <ph id="b{i}" equiv-text="&lt;b&gt;"/>important<ph id="e{i}" equiv-text="&lt;/b&gt;"/> record {i} with protected inline codes.'
        elif kind==0: source=f'Short segment {i} for a fast scrolling benchmark.'
        elif kind==1: source=f'Medium-length source segment {i} contains enough words to wrap in a narrower editor column and exercise dynamic row measurement during continuous scrolling.'
        elif kind==2: source=(f'Long source segment {i} is deliberately written with a larger number of ordinary words. ' * 3).strip()
        else: source=(f'Very long source segment {i} checks resize measurement, browser layout stability, virtual position correction, and rapid scrollbar dragging without mounting every row. ' * 6).strip()
        target='' if i%3 else f'<target state="translated">Перевод сегмента {i}</target>'
        rows.append(f'<trans-unit id="s{i}"><source>{source}</source>{target}</trans-unit>')
    rows.append('</body></file></xliff>');a.output.write_text('\n'.join(rows),encoding='utf-8');print(f'Wrote {a.segments} segments to {a.output}')
if __name__=='__main__': main()
