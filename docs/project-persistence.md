# Saved projects and imports

Saved projects have a positive integer `revision`. Existing SQLite rows receive revision 1 through an idempotent startup migration; their canvas JSON is preserved. Creating a project returns revision 1. Listing or reading a project returns its canvas and revision.

Every `PUT /api/projects/{id}` requires `expected_revision`. A missing revision returns HTTP 428; a stale revision returns 409 and the current revision. The update uses an atomic SQL revision predicate and increments the revision once. A concurrent deletion returns 404. Clients must preserve their unsaved draft and ask the user to review a conflict; automatically refreshing the revision and retrying could overwrite newer work.

Renaming or moving a project sends only metadata and the revision. It does not replace its canvas with the open editor's unrelated design. An explicit canvas save uses the revision loaded with that design. AI updates use the same guard and require the target project to be loaded first. Project identity/revision bookkeeping is not persisted in canvas JSON.

Folder references must exist. Folder moves reject self/descendant references and corrupt ancestor cycles. One CatLabel process serializes project/folder mutations through validation and commit. This process lock does not coordinate external database writers or additional server workers; use one CatLabel process for a data directory. Revision predicates still protect project updates against concurrent external changes.

Imports keep export format `1.0`. The complete tree is validated before the first insert, with at most 10,000 nodes, 64 levels and a 16 MiB upload. All inserts commit together; a failed later child or database write rolls back the whole import. Existing destination data remain intact. Export and deletion detect cycles and enforce traversal limits; root export rejects disconnected or orphaned records instead of silently omitting them.

Local drafts, undo history and user confirmation before replacing a design are separate editor concerns tracked in the maintenance plan. These transaction guarantees do not yet imply complete draft recovery.
