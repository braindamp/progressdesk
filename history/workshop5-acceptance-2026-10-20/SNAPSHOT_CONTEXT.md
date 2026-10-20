# Preserved acceptance dogfood workshop

Read the current target VISP and implementation plan section 0A first. This is a reference snapshot of D:/Coding/progressDesk5-acceptance, taken during the dogfood recovery review on 20 October 2026. It is not an automatically deployed engine.

The original repository HEAD was 676fc5b874e963c692018f3bdeffb8ed2045676d. Its tracked HIER GEBLEVEN 2026_10_01.txt deletion was already present. Readable source, specifications, briefs, runtime records, inboxes and lessons are preserved. Git metadata, environments, caches, bytecode and the journal lock are excluded. The copied SQLite database was checked and its WAL consolidated in this snapshot; the original workshop was not changed.

start_workshop.bat loads this workshop's Python source while passing D:/Coding/ProgressDesk as the operational root. That distinction explains why code, configuration and runtime records can come from different directories.

The snapshot includes prototype acceptance modules deliberately excluded from the target in October. They are implementation references and workshop capabilities, not proof that a target acceptance milestone has been delivered. Historical documents and old restrictions do not override the current VISP or the owner's later instructions.
