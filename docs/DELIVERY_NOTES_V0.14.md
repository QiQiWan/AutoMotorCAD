# V0.14 Delivery Notes

This delivery should replace the complete prior application directory. Do not copy only `static/` or only Python files over V0.13: the supplied diagnostic bundle demonstrated exactly the type of frontend/backend version skew that partial replacement can create.

Recommended workstation upgrade: stop the old Uvicorn/Studio service, replace the code with the V0.14 package, start from the V0.14 directory, verify `/api/health` and the browser both report 0.14.0, then run shallow preflight. If automatic Motor-CAD discovery still fails, use System Diagnostics -> Motor-CAD installation and launch path -> Browse local or paste the full EXE path.

The runtime/data/log/factory directories in the release are clean. Existing user runtime data should be backed up before replacing a production installation.
