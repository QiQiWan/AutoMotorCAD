# Engineer Workflow

Current release: **MotorCAD Studio 0.89.6 / Schema 45**

## V0.89 workflow/context rule

V0.89-A separates the engineer-facing stage model from the persisted object hierarchy while binding both to one authority. The visible journey remains **Design -> Validate -> Decide**. The persistent breadcrumb shows the current **Project -> Solution -> Motor Revision -> Analysis -> Task -> Result** lineage.

`MCSEngineeringContextV3` is the browser identity authority. Descendant IDs restored from browser storage are resume hints only; they become current identity only after route/backend lineage validation. Changing an ancestor invalidates incompatible downstream state. The backend `GlobalWorkflowTruthV1` resumes from one deepest persisted object and derives its ancestors, preventing mixed branches.

V0.89-B also qualifies the HMI control surface. Fixed buttons and dynamically rendered action families receive semantic action IDs and handler-ownership evidence. The V0.89-B baseline covered 87 fixed controls; the current 0.89.6 full-shell sweep covers 90/90 registered buttons, with enabled controls actually clicked and workflow-gated controls recorded separately.

## V0.89-C edit/navigation behavior

Route changes are transaction-controlled. If Project settings have local edits, Studio offers **继续编辑 / 放弃修改 / 保存并继续** before leaving. Design Draft changes are flushed before navigation and the editor remains mounted until the target route commits. Analysis step/domain/mode/refresh transitions save the dirty current editor before re-rendering. Rapid navigation is last-intent-wins, duplicate write clicks share one in-flight operation, and browser close/reload warns while any active editor still owns local-only changes.


## V0.89-F Guided engineer rule

The default Guided shell keeps **当前位置 / 当前状态 / 需要处理 / 下一步** visible under the active project. These values are derived from `MCSEngineeringContextV3` and `GlobalWorkflowTruthV1`; they are not a parallel state model. Guided Chinese labels translate internal object vocabulary such as Design Revision, Case, ResultBundle and Native Binding into 电机版本、计算工况、计算结果 and Motor-CAD 参数映射. Expert/Developer evidence surfaces retain the original authority vocabulary and hashes.

V0.89-F also introduces `ReleaseCandidateGateV1`. Local RC means the distributable build, current automated regression and HMI/static gates are green. Formal RC additionally requires the licensed Windows Native gate, V0.89-D Golden Journeys, Native 100/500 Soak, V0.89-E UI resilience and a 12/12 evidence-backed engineer acceptance checklist.

## Design

Create a Golden Motor Starter (SPM, IPM or AFPM), edit guided engineering parameters, review geometry/material/winding state, and save an immutable Design Revision when the intended design is ready to preserve.

Editing is one server-authoritative Draft transaction shared by Geometry, Winding and Materials. Changing a parameter does not require opening a review form. The engineer can continue editing across steps, save the current design, discard changes, or return to the parameter overview. Source Motor-CAD templates remain read-only design baselines. The editor continuously shows 未修改 / 已修改未保存 / 草稿已保存 and the current Motor-CAD reconciliation state.

## Validate

Use the Standard Validation Package to materialize the recommended analysis set. Studio precheck and Motor-CAD native validation are separate stages and both remain authoritative.

V0.88-C turns native validation evidence into the following engineer-facing flow:

`native check -> typed root fault -> repair plan -> optional bounded safe repair -> fresh native check -> NativeModelSnapshot`

The first displayed issue is the highest-ranked root cause. The validation view should provide the affected parameter/component, native evidence and the next engineering action instead of exposing a generic exception.

### Safe repair rule

The **安全修复并重新检查** action is shown only when the current lineage-bound RepairPlan contains `AUTO_SAFE` actions. A safe repair may only reapply values already frozen in the exact current BindingPlan to the live Motor-CAD session. It cannot change the source template, Design Draft intent or an immutable Design Revision.

Typical safe actions are an explicit parameter resynchronization, an explicit material resynchronization, or a frozen custom-winding resynchronization. Geometry-kernel failures, missing native APIs, inherited-material ambiguity and post-solve design-state mutation remain confirmation/manual actions.

If a repair would change engineering intent, navigate back to the corresponding Geometry, Winding or Material editor, edit the Draft, save it normally, and run validation again.


### V0.88-D transaction and native-state rule

Before Motor-CAD native validation, pending browser edits are persisted. The native request carries the exact Draft version, transaction hash and design-intent hash; the server reloads parameters/materials from that Draft. When Motor-CAD returns, the server checks the same hashes again before attaching evidence. If the design changed during the native run, the old result cannot certify the newer Draft.

`CURRENT` means the native result belongs to the current transaction. `STALE` means the design changed after that result. `DRIFT` means Motor-CAD readback disagrees with the current design. These states are shown directly in the editor instead of collapsing into a generic “checked/unchecked” flag.


### V0.88-E visualization source rule

Saved Design views expose three explicit sources for geometry, longitudinal section, winding, slot and materials: **设计意图**, **Motor-CAD 原生**, and **差异对比**. Studio selects native values only through `NativePreviewReconciliationAuthorityV1`. The projection must belong to the exact immutable Design Revision.

A `QUALIFIED` native projection can be the default read-only source. `DRIFT` or `PARTIAL` evidence can be inspected and compared but does not silently replace Design Intent. After a Draft edit, the editor immediately returns to Design Intent and any older native projection becomes stale until a fresh transaction-bound native check completes. Fields that Motor-CAD did not return remain explicit Design fallback fields.

The Motor-CAD Native view is reconstructed using the same topology-specific renderer fed by native readback values and the native winding/material projection. GeometryTree digest/region evidence is shown as provenance when available; exact Motor-CAD viewport pixels remain outside this authority.

### V0.88-F spatial/result source rule

For the radial/native geometry view, Studio now also exposes the actual Motor-CAD GeometryTree Region boundaries captured as native Line/Arc entities. Result field views use the same post-solve spatial evidence and the same Case's `save_fea_data` export. A spatial overlay is trusted only when all native lineage hashes match and coordinate alignment is `CONFIRMED`.

If Motor-CAD exports element/node connectivity, Studio can show the native mesh and shade native elements using exported field values. If connectivity is missing, the UI keeps the data as native points; it will not generate an interpolated contour. The longitudinal assembly section remains an engineering reconstruction from native readback parameters because the current GeometryTree XY evidence does not by itself define that axial section.

## Decide

Completed ResultBundles are summarized into the Engineering Scorecard. Use baseline comparison, 1D/2D parameter study, Pareto/convergence/sensitivity views and Candidate Inspector. Candidate promotion reuses the validation/requirement gate and creates a new immutable Design Revision.

A ResultBundle used for formal qualification must retain the final post-solve NativeModelSnapshot lineage. Formal Native Closure requires a CLEAN V0.88-C RepairPlan and zero hidden repair attempts.

## Guided-mode rule

The default engineer workflow does not require Python, Automation API names, JSON, database schema knowledge or worker/runtime concepts. These remain available through advanced diagnostics/developer surfaces.
