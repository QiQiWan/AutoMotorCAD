# V0.9 Simulation Data Factory

## 1. 目标

V0.9 的首要目标不是训练模型，而是建立一个能够长期、重复、审计地生产高质量电机仿真数据的流水线。数据工厂必须回答六个问题：

1. 这条数据来自哪个设计、工况、实验、Task 和 Case？
2. 使用了哪个模板、Motor-CAD/PyMotorCAD版本和参数映射？
3. 输入材料、Solver Settings、Automation Overrides 是否与其他Case完全一致？
4. 求解是否成功，结果是否经过质量门禁？
5. 某条数据为什么被纳入/排除数据集？
6. 同一个数据集版本未来能否精确复现？

## 2. 分层

```text
Solver artifacts
     |
     v
RAW INDEX
  artifact pointers, hashes, input fingerprint
     |
     v
CURATED
  canonical parameters + scenario + standardized results + provenance
     |
     v
FEATURES
  derived metrics + constraints + feasibility + quality metadata
     |
     v
QUALITY GATE / QUARANTINE
     |
     v
IMMUTABLE DATASET VERSION
  CSV / JSONL / optional Parquet
  schema hash / content hash
  stable partitions / case membership
```

### Raw Index

Raw 层不复制所有大文件，而是记录 Task/Case 到 Artifact 的索引。大型 MOT、FEA、CSV 和日志仍保存在结果仓库，通过 lineage 回查。

### Curated

Curated 层把 Motor-CAD 内部变量转换到平台 Canonical Schema。核心字段包括：

- Case/Task/Project/DesignRevision/ScenarioRevision/Experiment IDs；
- template/solver/analysis/version；
- `param.*`；
- `scenario.*`；
- `result.*`；
- simulation fingerprint；
- registry/template hashes。

### Features

当前派生指标包含：

- torque-derived mechanical power；
- recomputed efficiency；
- torque per peak amp；
- DC-bus voltage utilization；
- winding/magnet temperature rise；
- copper/iron/magnet loss fractions。

后续应继续加入质量/功率密度、磁体利用率、退磁裕度、热裕度等，但这些指标在材料质量和质量/体积输入正式标准化后再加入。

## 3. Dataset Version

Dataset 逻辑实体与 Version 分离：

```text
DST-XXXXXXXXXX
  v0001
  v0002
  v0003
```

每次 Build 都生成新版本，不覆盖旧版本。

Manifest 包含：

```text
dataset_id
version/version_id
studio_version
definition
source_task_ids
row_count
schema
schema_hash
content_hash
quality_report
files
lineage_policy
rejected_count
```

### Stable partition

Case 使用 `SHA256(seed + case_id)` 分配到：

- development；
- validation；
- holdout。

同一个 seed 和 case_id 在不同 Dataset Version 中保持稳定，避免数据重建后样本随机跨集合泄漏。

## 4. Quality Gate

数据进入 Dataset 前依次检查：

```text
Execution status
 -> Quality status
 -> Solver policy (Mock allowed?)
 -> Dataset-specific constraints
 -> Duplicate fingerprint
```

被排除的数据不会静默丢弃，而进入 `quarantine.jsonl`，记录 rejection reason，例如：

- EXECUTION_NOT_ACCEPTED
- QUALITY_GATE
- MOCK_EXCLUDED
- DATASET_CONSTRAINT
- DUPLICATE_INPUT

## 5. Fingerprint

V0.9 修正后，输入指纹覆盖：

```text
application version
template source hash
verified MOT hash
solver / analysis / Motor-CAD / PyMotorCAD version
all registry hashes
canonical parameters
scenario
materials
solver settings
automation overrides
requested outputs
```

缓存、checkpoint、dataset lineage 应以该指纹为统一基础。

## 6. 数据工厂与优化器关系

优化器只负责生成设计点：

```text
Optimizer.ask
 -> Cases
 -> Solver
 -> Quality
 -> Data Factory
 -> Optimizer.tell
```

Data Factory 不属于优化算法内部。这样 LHS、NSGA-II、未来 Bayesian Optimization、Maxwell 或实验数据均可落入相同数据层。

## 7. 真实数据生产规则建议

生产数据集默认建议：

```text
solver_mode = motorcad
execution_status in {SUCCEEDED,CACHED}
quality_status in {VALID,WARNING}
include_mock = false
deduplicate = true
```

对于正式 surrogate / 多保真研究，建议只使用 `VALID` 作为主训练集，将 `WARNING` 放入单独审查集合。

## 8. 下一步

数据工厂下一步不应首先接 AI，而应扩展：

- Map2DResult（效率图、损耗图、热图）；
- Series/Map 数据的 HDF5/Parquet sidecar；
- Dataset contract migration；
- material property snapshots；
- Motor-CAD session/environment snapshots；
- Maxwell fidelity tag；
- experiment/lab measured data ingestion；
- dataset diff / promotion / freeze / release。
