# Deployment lineage

## Canonical source

The canonical repository is [GitHub](https://github.com/kuotunyu/tw-longcare-rag),
and **GitHub is the source of truth** for code, documentation, frozen evidence,
and release history. The audited canonical baseline is `main` at
`c9b84ee02d54c92802b580b7d2b4180c7d750de1`; the observed hash at the start of
this closeout was the same. Changes intended for deployment must first be
reviewed against a named GitHub commit.

## Space deployment

The public demo is the [Hugging Face
Space](https://huggingface.co/spaces/steven0226/tw-longcare-rag). Its observed
deployment baseline is `6272d60f5258a85af3e743f52ec81f91d2c8a98a`.
The Space is a **white-listed deployment subset** assembled from an explicit
bundle allowlist; it is not a second development branch and its commit history
does not supersede GitHub. Files outside that allowlist—including tests,
private configuration, runtime indexes, logs, evaluation documentation, and
model weights—must not enter the bundle.

## Frozen data and model boundary

The bundled legal corpus is the frozen snapshot
`2026-07-17-e941dcc3e345`. It is a versioned historical artifact, not a source
of current law and not legal, benefits, medical, or eligibility advice. This
closeout does not fetch laws, rebuild indexes, change retrieval thresholds,
replace models, or rerun paid model evaluations. Any future data or model
change is a separate review with its own provenance and regression evidence.

## Verification procedure

1. Record the reviewed GitHub commit and the candidate Space commit before any
   comparison.
2. Build the candidate bundle only from the repository's explicit allowlist.
3. Compare every bundled file to the same path at the reviewed GitHub commit,
   using Git blob or no-filter hashes so line-ending conversion is not mistaken
   for a source change.
4. Confirm the frozen snapshot identifier and deployment metadata, then run the
   repository tests and a read-only public smoke check.
5. Publish only after the named GitHub target and Space target receive separate
   approval.

## Rollback and update policy

**Rollback rule:** if verification exposes drift, stop publication and return
to the last separately verified GitHub/Space pair; rebuild the white-listed
bundle from that reviewed GitHub commit. Do not repair deployment drift by
resetting the evidence clone, force-pushing, moving tags, or treating a
Space-only commit as canonical. Law, corpus, model, or threshold updates remain
out of scope until separately audited and approved.
