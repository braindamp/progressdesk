# Core delivery evidence

What is here, for a reader with only GitHub access.

- `ms1-acceptance.json` - the receipt for the first accepted milestone: the
  attempt, the product digest, the evaluator, the delivered features, and the
  first attempt that failed on a defect in the instrument rather than in the
  product.
- `ms2-progress.json` - what the second milestone has delivered so far and what
  is outstanding.
- `coverage.md` - every FUSP requirement and acceptance condition, mapped to
  what the product does, with the module that does it.
- `events.jsonl` - the event log of the delivery run: the history the framework
  actually produced. It carries local paths and run ids; no credentials.
- `plant-commits.txt` - the factory commits of the delivery, newest first.
- `ms1-product/` - the product as it was accepted: the frozen assembly of the
  first milestone, with its manifest. This is the product, not a description
  of it.

The state this delivery is still running in is not here: the artifacts, the
projects and the pending rounds live in the workshop's working directory. The
handover at the repository root says where, and how to resume.
