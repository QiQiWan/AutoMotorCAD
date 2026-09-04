(() => {
  const tr = (zh, en) => window.MCS_I18N?.t?.(zh, en) ?? zh;
  const solveModes = {
    steady_electromagnetic:['稳态电磁有限元','Steady electromagnetic FEA'],
    steady_state:['稳态热网络','Steady-state thermal network'],
    transient:['瞬态热','Transient thermal'],
    sequential_coupling:['顺序电磁—热耦合','Sequential electromagnetic–thermal coupling'],
    native_iterative_coupling:['Motor-CAD 迭代耦合','Motor-CAD iterative coupling'],
    mechanical_fea:['机械有限元','Mechanical FEA'],
    reduced_order_map:['降阶性能图','Reduced-order performance map'],
    reduced_order_point:['单工作点性能计算','Single operating-point calculation'],
    electromagnetic_map:['电磁参数扫描','Electromagnetic parameter sweep'],
    torque_speed_sweep:['转矩—转速扫描','Torque–speed sweep'],
    position_sweep:['转子位置扫描','Rotor-position sweep'],
    harmonic_postprocess:['力谐波后处理','Force-harmonic post-processing'],
    deterministic:['确定性计算','Deterministic calculation'],
    reduced_order_thermal_map:['热性能图谱','Thermal performance map'],
    duty_cycle_transient:['循环工况瞬态','Duty-cycle transient'],
    generator_map:['发电工况图谱','Generator map'],
    lab_test_sequence:['测试序列','Test sequence'],
  };
  const recipes = {
    emag:['额定点电磁','Rated-point electromagnetic'],
    thermal_steady:['稳态热','Steady-state thermal'],
    thermal_transient:['瞬态热','Transient thermal'],
    emag_thermal:['电磁 + 稳态热（顺序）','Electromagnetic + steady thermal (sequential)'],
    emag_thermal_coupled:['原生电磁-热耦合','Native electromagnetic–thermal coupling'],
    lab_magnetic:['电磁性能图谱','Electromagnetic performance map'],
    lab_operating_point:['单工作点性能','Single operating point'],
    mechanical:['机械与振动','Mechanical and vibration'],
  };
  const modules = {
    EMag:['电磁','Electromagnetic'], Therm:['热','Thermal'],
    Coupled:['电磁-热耦合','Electromagnetic–thermal'], Lab:['性能图谱','Performance map'],
    Mechanical:['机械','Mechanical'],
  };
  const pair = (table, value, fallback) => {
    const row = table[value];
    return row ? tr(row[0], row[1]) : String(value || fallback);
  };
  const solveModeLabel = value => pair(solveModes, value, tr('计算','Calculation'));
  const recipeLabel = value => pair(recipes, value, tr('分析配方','Analysis recipe'));
  const moduleLabel = value => pair(modules, value, tr('分析','Analysis'));
  const revisionLabel = (value, kind = 'analysis') => kind === 'motor'
    ? tr(`电机版本 ${value ?? '—'}`, `Motor revision ${value ?? '—'}`)
    : tr(`分析版本 ${value ?? '—'}`, `Analysis revision ${value ?? '—'}`);
  const booleanLabel = value => value ? tr('启用','Enabled') : tr('未启用','Disabled');
  window.MCSAnalysisLabels = Object.freeze({solveModeLabel, recipeLabel, moduleLabel, revisionLabel, booleanLabel});
})();
