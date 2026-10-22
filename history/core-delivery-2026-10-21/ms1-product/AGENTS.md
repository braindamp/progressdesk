# Framework process diagram

- `framework_processflow.mmd` is maintained, versioned source for the intended owner-approved agent process.
- When an approved change affects roles, handoffs, acceptance, recovery or stop authority, update this source and regenerate `framework_processflow.png` in the same change.
- Use `npm --prefix tools install` followed by `npm --prefix tools run render:flow` to regenerate the PNG. The renderer supports the simple Mermaid flowchart syntax used in this file and rejects unsupported lines.
- Preserve the distinction between intended design and demonstrated implementation. Do not redraw an implementation defect as an approved design change.
- Keep both root-level diagram files tracked. Do not move them into ignored runtime or scratch directories.
