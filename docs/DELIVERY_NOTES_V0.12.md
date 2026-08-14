# V0.12 Delivery Notes

## Delivery focus

V0.12 is a hardening release rather than a feature-expansion release. The most important behavioural changes are:

- Project deletion is reversible and no longer destroys engineering lineage.
- System, Task and Log live channels share the same degradation/recovery model.
- Motor-CAD environment checks are separated from template/solver qualification.
- Studio material catalog validation is explicitly separated from actual Motor-CAD database verification.
- Raw native Motor-CAD controls are separated from normal engineering workflows by UI mode.
- Parameter experiment roles are defined at the parameter itself instead of being only an independent DOE form.

## Upgrade notes

Database schema version is 8. Existing project rows receive `ACTIVE` state by migration. No existing Task/Case/Result data should be deleted by the migration.

The application version is `0.12.0`.

## Real-workstation actions after unpacking

1. activate the project Python environment;
2. verify PyMotorCAD and Motor-CAD installation discovery;
3. perform one Automation registration check for the intended Motor-CAD version if required by the workstation installation;
4. use System -> Template Qualification for i5/e9/e14;
5. first run without solver smoke to validate template/parameter/material/geometry;
6. then enable real solver smoke;
7. export a diagnostic package for any failed qualification;
8. only after qualification, run the 20/100-case stability acceptance suite.

## Not packaged as validated

The delivery does not include a fabricated Production Ready flag for any Motor-CAD template. Qualification results depend on the user's actual Motor-CAD build, licence availability, material database and verified `.mot` master.
