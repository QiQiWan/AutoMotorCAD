# 变更记录

## 0.92.0

- 将顶部工程流程明确收敛为“设计 → 计算 → 结果 → 决策”四个独立阶段。结果页负责展示计算事实、曲线、场数据和可信度；决策页只负责把结果证据与项目工程要求对照后形成工程结论。
- 修复“结果/决策”共享 `resultViewer` Tab 导致的路由串线：新增独立 `/results`、`/results/viewer` 与 `/decision` 语义路由；点击“结果”不再落到决策页，点击“决策”也不会复用结果查看器的隐式模式。
- 修复路由切换偶发弹出 `页面加载失败：route change`：PageRuntime 过去用字符串作为 AbortController 取消原因，浏览器 Fetch 可直接以该字符串拒绝 Promise，旧 `isAbortError` 无法识别。现在统一使用带 `AbortError` 类型和 `mcsRouteAbort` 标记的取消对象，正常页面切换不会被误报为加载失败。
- 修复“结果”和“决策”两个顶部按钮因共享 `data-tab=resultViewer` 而同时高亮的问题；Router 在 Prime 和 Apply 阶段根据 `resultsMode` 同步唯一活动阶段。
- 重构工程要求编辑器：中文界面不再混排 Requirement Authority、Revision、Hash、Promotion、Requirement Gate 等产品内部术语；主界面改成“选择指标 → 定义判定方式 → 保存版本”三步，并将复杂晋级策略收进高级设置。
- 工程要求指标目录补充中文工程描述、工程分组和有利方向；指标行同时显示中文名称、技术字段 ID、用途说明、单位与判定方式，降低工程师理解成本。
- 重构决策逻辑：区分“暂不能判定”“建议调整设计”“通过但有预警”“建议通过”四种结论。缺少工程要求、结果可信度不足、必须指标证据缺失或单位不一致属于未具备判定条件；硬约束真实失败属于已经完成的负向工程判定，不再被错误归类为“无法判断”。
- 决策页改成明确的三问流程：“结果可靠吗？→ 项目要求是什么？→ 设计达标吗？”，结果证据、工程要求和判定完整性分别显示状态；工程要求缺失时直接提供“定义工程要求”，硬约束失败时直接定位到未满足指标。
- 结果概览移除重复的决策/要求模块，增加明确“进入工程决策”交接；结果工作台内部导航统一为“结果概览、单工况结果、工况比较、版本比较、参数研究与优化”。

## 0.91.9

- 收敛设计完成后的资格与交接流程：设计阶段统一称为“设计资格”，只检查几何、绕组、材料和 Motor-CAD 模型可接受性；分析阶段统一称为“计算就绪检查”，复用设计资格并补查工况、求解设置、输出合同和运行环境，避免两个“检查”语义重叠。
- 修复从设计验证返回编辑器后的生命周期失活：重新进入编辑视图时若旧 Shell AbortController 已失效会重新绑定；设计资格通过后提供明确“进入分析配置”动作。零修改草稿不再因“保存新设计版本”静默 return，而会明确提示无需创建重复 Revision，并允许直接进入分析配置；存在修改时执行“保存新设计版本并进入分析配置”。
- HMI 资格注册补充设计检查、原生检查、安全修复、下一步和进入分析配置等动态委托按钮族，减少运行日志中的假性 `FRONTEND_BUTTON_BINDING_GAP`，并继续由真实 click owner 负责执行。
- 结果查看器改为 evidence-first 布局：强化 ResultBundle/Case/提取覆盖/FEA 状态/Bundle Hash 身份，只有实际有数据的模块进入主导航；Result Contract 的真实缺项折叠到“结果合同缺项”，与“本分析类型不适用”分开。
- “本次计算实际使用的输入”改为工程语义表，统一显示“中文名称 / 字段标识 / 说明 / 数值 / 单位”，保留原始字段 ID 便于追踪，同时提高参数快速审阅能力。
- FEA 查看器切换到单一 Binary FieldData 热路径：现代二进制 WebGL 查看器在 FEA 模块渲染前取得所有权，禁止旧 JSON/CPU 几何管线同时启动；二进制缓存命中时不再预先解析 frame/chunk JSON，也不再每次完整读取 `.mcfd` 重新计算 SHA-256。帧拖动增加 70 ms 合并，动画按“上一帧完成后再调度下一帧”执行，并用 AbortController 取消被新帧覆盖的请求。
- WebGL FEA 查看器增加三维旋转、平移、缩放、透视/正交、顶/前/右视、网格边线、节点拾取、X/Y/Z 剖切和全屏。对具有真实 Z 坐标的体/面网格使用物理三维坐标；仅有 X/Y 的 Motor-CAD 平面 FEA 明确显示为 2.5D 工程平面，并允许“标量高度”作为视觉辅助，禁止把视觉拉伸冒充物理三维结果。
- 修复 FEA “碎片/孔洞”观感的一项渲染根因：原生面片节点顺序可能不一致，查看器不再对这些工程表面强制背面剔除；网格边线单独构建 Line Index Buffer，以填色面 + 边线共同表达有限元离散。
- 热结果改为“真实数据优先”：绕组最高温度等已提取标量用现代 KPI 卡显示；没有 `thermal_node_table` 时不再绘制推断节点、虚线热路或空白大图，而明确说明结构化热网络未提取。原生 SteadyState CSV 新增语义解析器，只有同时存在温度列与节点/部件身份列才提升为 `thermal_node_table`，不会把普通 summary CSV 错标为热网络。
- 工况比较首页改成“选择任务 → 选择 2–8 个工况 → 工程对照”三步式，明确只比较同一 Task / Execution Plan；加载态、Case 选择卡、Lineage、Trust/Gate 和比较表统一现代化样式。
- 针对本轮现场日志的性能证据：48 个 HTTP 请求全部 2xx；Motor-CAD Native check 21.67 s、Analysis Definition 创建 4.77 s、安装发现 3.21 s，ResultBundle 路由记录到 20.20 s。0.91.9 重点消除 Result Viewer 的双渲染管线和二进制缓存命中仍重解析的两项确定性浪费；真实 Windows + Licensed Motor-CAD 工作站仍需复测 cold/warm 路由和首帧/连续帧时延。

## 0.91.8

- 根据 2026-09-04 第二组实机日志重构分析页加载生命周期：路由挂载与手工刷新使用独立 single-flight；新路由上下文等待旧挂载退出后必须重新执行自己的 mount，禁止旧 Promise 吞掉新页面初始化。
- 分析页顶部“新建分析配置/刷新/模式切换/返回电机配置”改为稳定委托事件所有权，避免 PageRuntime 卸载旧路由时移除持久按钮处理器；HMI 资格检查不再以模块存在冒充按钮已绑定。
- 分析工作区使用 `/api/projects/{id}/analysis-workspace` 聚合启动接口，只加载最新电机/分析版本窗口并保留被引用版本，减少 N+1 与不可变历史读取；分析编辑器继续使用聚合 editor bundle。
- 修复 Solver JSON 被全局 i18n 误改的第二类故障：`TorqueCalculation`、`BackEMFCalculation`、`CoggingTorqueCalculation` 不再被翻译成 `Torque计算`、`BackEMF计算`、`CoggingTorque计算`。高级 Solver JSON 明确 `data-i18n-skip`，i18n 同时保护 CamelCase/API 技术标识；已持久化坏值通过受限白名单映射自动迁移。
- Motor-CAD 安装发现退出普通页面热路径：正常读取只返回已选择安装，主机注册表/文件系统扫描仅在显式“重新扫描”或首次自动选择时执行；扫描缓存延长并在选择变化时失效。浅层 Preflight 不再启动 PowerShell 文件版本探针，深度检查继续保留二进制版本证据。
- `/api/health` 收敛为轻量启动/存活合同，移除 Worker、Session、Data Factory、日志聚合等昂贵摘要；SQLite WAL 读取取消进程级写锁，SELECT 不再 commit，写事务保留串行化并采用 `synchronous=NORMAL`，降低慢磁盘下无关请求互相等待。
- Studio 产品版本与外部 PyMotorCAD API 版本彻底解耦：全局状态栏不再显示 `· 0.8.6`，发布合同不再固定 PyMotorCAD 0.8.8；Windows 资格改为 capability-qualified，并仍记录实际 PyMotorCAD 版本作为环境证据。
- 当前上传日志 100 个 HTTP 请求全部成功返回（无 4xx/5xx），主要现场问题属于 8 s 级安装发现/I/O 阻塞、分析路由生命周期竞态和技术标识被 i18n 污染；真实 Windows + Licensed Motor-CAD 求解仍需在目标工作站复测。

## 0.91.7

- 根据 2026-09-04 实机日志收敛配置与运行环境加载性能：Motor-CAD 安装发现由安装根目录无限递归扫描改为有限目录模式匹配，并增加 120 s 扫描缓存/并发合并；浅层 Preflight 增加 30 s 缓存和 single-flight，安装选择变化会立即失效缓存，手工“扫描/检查”继续支持强制刷新。
- 前端启动将安装发现与浅层 Preflight 移到持久路由可交互后的 idle 阶段；工程工作区复用 Router 已水合的 Project，分析模板目录一次请求只解析一次设计上下文、Motor 上下文和 Analysis Catalog，移除按模板重复查询。
- 修复 AFPM 提交任务 `TASK-072743F7C2` 在专家参数写入阶段因本地化 Automation 标识 `当前Definition` 失败：统一将历史坏值规范化为 Motor-CAD 原生 `CurrentDefinition`，在请求准备、验证和最终 RPC 三层防护；未知本地化/非法 Automation 标识在进入 Worker 前阻断。
- 原始 Motor-CAD Automation 标识在前端增加 i18n-skip，避免技术标识被语言系统再次翻译；Automation Registry 导入同步校验合法标识。
- AFPM 原生绕组消息按“本次验证新增消息”判定，隔离模板/绕组探针历史消息；若本次验证真实产生 `Coil index too high`，升级为阻断故障 `MOTORCAD_WINDING_COIL_INDEX_OUT_OF_RANGE`。
- 求解过程可视化改为拓扑感知：AFPM 显示与 Case 极槽数、盘径、内径、轴径、极弧、气隙和轴向堆叠尺寸一致的环形端面，以及双转子/单定子轴向堆叠；过程磁力线继续明确标记为状态示意，不作为 FEA 场结果证据。
- 顶部 Engineer Journey 的 `待解锁` 状态同步写入 `disabled`、`aria-disabled` 和 workflow gate，点击处理器再次校验阻断态，并在渲染后重新应用全局 Workflow Truth，消除“显示待解锁但仍可导航”的双状态源竞态。
- 当前目标工作站日志使用 PyMotorCAD 0.8.6，而发布资格基线仍为 0.8.8；该版本差异未导致本次 `CurrentDefinition` 故障，但正式 Native 资格需切换到冻结版本或针对 0.8.6 重新形成工作站证据。

## 0.91.6

- 恢复 Motor-CAD 材料数据库发现链：扫描范围覆盖 `MOTORCAD_DEFAULTS_FILE`、Motor-CAD 安装目录及其 `Motor-CAD Data`、AppData/ProgramData/Documents 下的 Ansys/Motor-CAD 目录；解析 Defaults.INI 中的 `.mdb` 引用，并记录扫描根、发现数据库和导入数量。
- 材料选择器首次发现 Studio 材料索引为空时自动执行一次本机材料库扫描；空列表同时提供“扫描本机材料库”和“材料数据库管理”，部件材料页增加常驻材料数据库管理入口。
- 材料选择结果将源 `Solids.mdb` 路径写入设计草稿 `material_database_path`，后续 Motor-CAD 原生绑定通过 `select_material_database` 使用同一数据库，避免 UI 选择库与计算库脱节。
- 方案管理卡片增加“删除方案”，调用既有受引用保护的方案删除事务；存在分析、任务或证据引用时后端继续拒绝删除。
- 根据 0.91.5 实机日志修正 AFM 原生检查权威：未修改 `e14` 注册模板在 Motor-CAD 2026R1 / PyMotorCAD 0.8.6 上通过模板加载、27/27 参数解析、绕组和材料回读，但通用 `check_if_geometry_is_valid(0)` 对 AFM 报告 Stator/StatorAir、Stator/Magnet 等交叠，且自动修复产生更多交叠。0.91.6 将该 API 对 AFM 降级为诊断证据，禁止 AFM 通用自动修复；计算前门禁改由 AFM 线性截面语义、Studio 几何/绕组关系和原生参数/材料/绕组回读共同判定。
- AFM NativeGeometryReadback 不再调用当前运行时未实现的 `get_geometry_tree`，并明确记录 `MotorCADAFMLinearCrossSectionValidationV1`、局限性和真实求解 Smoke Test 生产资格要求。
- 修复 AFM readback 分支中空间几何变量未初始化的潜在异常，并新增真实执行回归测试。

## 0.91.5

- 重绘 AFPM 双转子单定子轴向堆叠剖面：采用物理 r-z 环形截面表达，定子、两侧气隙、永磁体和转子盘保留中心孔，转轴只占据孔径范围，修正旧版整高矩形导致的实体穿孔和堆叠误读。
- 深链接刷新增加 URL-first route prime 与启动水合遮罩；项目/方案/Design Revision/分析页面在上下文恢复期间不再显示默认初始页，后台 Runtime Preflight 移到持久路由进入可交互状态之后。
- 修复设计材料编辑进入工作台时的 `Illegal invocation`：设计编辑器和草稿服务不再依赖 Window receiver-sensitive `structuredClone`，Compatibility Runtime 同时保留真实 Window 绑定作为防御；加载失败会写入 `DESIGN_EDITOR_LOAD_FAILED`、清理半初始化状态并提供可重试入口。
- 修复 AFPM 默认设计完整计算前检查在调用 Motor-CAD 之前因错误相对导入 `motorcad_studio.api.operations.validation` 失败的问题；参数规范化统一从包根 `motorcad_studio.validation` 导入。
- 修正 Native 检查错误分类：Studio 内部模块加载错误不会再被误报为“无法导入 PyMotorCAD”。
- 对 `e14_eMobility_AFM` 默认模板增加回归：Studio 几何/绕组静态检查均通过，默认未修改参数不写回 Motor-CAD，原生检查继续从注册模板 `e14` 建模；正式 Windows Native 结果仍以目标工作站检查证据为准。
- 浅层运行环境检查会提示 PyMotorCAD 实际版本与冻结资格基线的差异。当前日志中的 0.8.6 可用于继续基础连接诊断，但 0.91.5 正式资格合同仍要求 0.8.8 或重新形成对应版本工作站证据。
- `MODEL_RUNTIME_CHECK_PLAN` 新增模板来源、registered template、显式参数写入与忽略冗余默认值等诊断字段；按钮绑定缺口日志同时记录具体控件身份。

## 0.91.4

- 修复“新建方案”无响应：Compatibility Runtime 中旧代码通过 `window.showTab` 访问词法函数时会得到空值，现已将核心跨模块帮助函数显式导出到密封代理，并将方案创建入口改为直接调用 History API Router。
- 深链接刷新改为由 URL 驱动：`/app/projects/<project>/...` 会先从后端恢复项目上下文，再挂载方案、电机、分析、任务和结果页面，不再用空的内存项目列表判断链接失效。
- 启动时先恢复当前 URL，再在后台执行运行环境检查；运行环境诊断不再阻断项目页面交互。
- 顶部导航与辅助导航增加现代 `navigation-bridge`，固定导航按钮统一进入 History API Router，降低旧 `showTab` 旁路造成的 URL 与界面状态漂移。
- 增加 `interaction-monitor`：可见按钮点击后若没有路由、网络请求、DOM 状态变化或忙碌状态，会记录 `FRONTEND_BUTTON_NO_EFFECT` 到根目录 `logs/frontend.jsonl`。
- 路由完成后自动执行 HMI 按钮绑定资格检查；出现绑定缺口会记录 `FRONTEND_BUTTON_BINDING_GAP`。
- 方案页恢复项目 Shell 同步，修复 URL 已进入项目但顶部仍显示“未进入项目”的状态漂移。
- 工程流程 Readiness 改为路由完成后的后台刷新，避免已渲染页面额外等待数秒。
- 发布门禁新增 `frontend_navigation_actions`，检查 13 个主页面路由、91 个固定按钮、深链接恢复、方案创建入口和静默按钮诊断。

## 0.91.3

- 修复 Motor-CAD 深度运行环境检查结束时的 Windows 进程竞态：子进程在 `psutil` 枚举期间自行退出时按 `already_exited` 处理，不再抛出 `NoSuchProcess` 导致 HTTP 500。
- 深度运行环境检查增加前端 single-flight 和后端请求合并；双击、浏览器重试或多个页面并发请求只启动一个 Motor-CAD 检查进程。
- 修正全局网络进度统计：后台 GET、系统轮询和启动数据读取不再被汇总为“多项请求进行中”；一次深度检查只显示一个明确的运行环境检查进度。
- `pollSystemSnapshot` 标记为静默后台刷新，避免和工程师主动操作竞争进度卡片。
- 运行环境检查异常被收敛为结构化失败结果，完整 traceback 进入根目录错误日志，主服务保持可用。
- 日志默认迁移到程序根目录 `logs`，新增 `http.jsonl`、`preflight.jsonl`、`errors.log/jsonl`、`frontend.jsonl`、`tasks/`、`cases/` 和 `snapshots/preflight/`。
- 增加日志目录 `README.txt` 与 `current_session.json`，方便现场复制整个 `logs` 目录排查。
- 新增进程竞态、并发 preflight 合并、前端后台请求过滤和日志 fan-out 自动化测试。

## 0.91.2

- 修复 legacy compatibility capsule 经代理调用 `window.requestIdleCallback` 产生的 `TypeError: Illegal invocation`。
- `requestIdleCallback/cancelIdleCallback` 绑定真实 Window，并纳入 Runtime Scope 生命周期管理。
- 前端模块注册允许声明的跨 surface 后端合同，不再错误要求浏览器全局对象。
- Compatibility Capsule 启动错误保留具体 legacy source owner，便于定位。

## 0.91.1

- 修复首次运行生成 runtime diagnostics 后再次启动被包完整性门禁误判为 `UNEXPECTED_FILE`。
- `data`、`runtime`、`results`、`logs`、`baselines`、`factory` 明确作为可变运行目录排除在不可变文件哈希之外。
- 正式安装模式清理指向程序目录的旧运行数据目录覆盖。

## 0.91.0

- 建立统一事务控制平面：幂等命令、Transactional Outbox、Optimization、Data Factory、Qualification、Native Runtime Safety 和 Requirements。
- 后端公开处理器按有界上下文拆分，兼容操作收敛为 0，OpenAPI 操作写入 `x-module-owner`。
- 前端形成单 ES Module 入口、统一 ApiClient、Runtime Capsule 和生命周期资源管理。
- FieldData 增加二进制 TypedArray、Indexed Geometry、ETag/Range、Topology Hash 复用和 WebGL2 查看器。
- 正式包目录固定为 `AutoMotorCAD_Studio`，根目录保留 `start.bat` 一键启动。
