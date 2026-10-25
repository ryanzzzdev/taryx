# Status-icon handling

Date: 2026-10-25

Cateniq and Voltix recorded corruption of non-BMP status icons by some agent edit tools. This is inherited tooling guidance, not a failure observed in Taryx.

Use UTF-8 scripted writes when changing status icons; update both the task status and its index icon. Verify that no U+FFFD replacement characters were introduced and that icons match the guide. For example, Python can read all Markdown with strict UTF-8 decoding and assert that `"\ufffd"` is absent. Do not assume a repository skill grants tool permissions or bypasses sandbox restrictions.
