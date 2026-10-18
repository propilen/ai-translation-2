import type { Segment } from '../api/client';
export type Change={id:string;before:string|null;after:string|null};
export class History { private undoStack:Change[]=[]; private redoStack:Change[]=[]; push(c:Change){this.undoStack.push(c);this.redoStack=[]} undo(){const c=this.undoStack.pop();if(c)this.redoStack.push(c);return c} redo(){const c=this.redoStack.pop();if(c)this.undoStack.push(c);return c} }
export function applyChange(rows:Segment[], change:Change, undo=false){return rows.map(x=>x.id===change.id?{...x,target_xml:undo?change.before:change.after,state:(undo?change.before:change.after)?.trim()?'translated':'untranslated'}:x)}
