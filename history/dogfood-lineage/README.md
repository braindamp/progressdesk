# Factory lineage and recoverable changes

The owner's sequence is build 4 foundations -> build 5 acceptance dogfood -> finalized ProgressDesk. The current VISP is primary; these older instructions and patches explain the history.

foundation-gate-receipts.json extracts the six recorded milestone-gate ticks from build 4's typed journal, including MS6.GATE at 493cac3. The original journal has 35 distinct item ticks. The static CHECKLIST.md was not updated to show that state.

acceptance-standard-negative-control.txt records one actual invocation of build 5's existing standard against four syntactically invalid candidate modules and no event log. It returned exit 0 with 3 tests passed. This is direct evidence that the existing standard does not establish runnable candidate behavior.

The two archived patches added a board dispatch door (542f57e) and source staging (de5c717) to build 5. They were explicitly reverted by ed9f0e8 and e09d47b on 4 October. Their revert messages state no rationale. Preserve them as implementation clues; do not silently reapply them.

Target commits 0b7e2f4 and ecdd0d8 describe manual synchronization of workshop repairs on 3 October. Commit 777d8e5 explicitly excludes acceptance modules because those were the intended dogfood deliverable. The review's recovery branch preserves today's newer target work before any possible rollback.

Do not assume that October 4 was still the tested September foundation: October 1 commits e35ee83, 2b381a8 and 2dc1745 removed checkpoint/recovery and authorization machinery before the factory and target diverged. MilestoneService itself predates these acceptance additions and belongs to the original foundation.
