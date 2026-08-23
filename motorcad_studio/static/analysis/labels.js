(() => {
  const labels={steady_electromagnetic:'稳态电磁有限元',steady_state:'稳态热网络',transient:'瞬态热',sequential_coupling:'顺序电磁—热耦合',native_iterative_coupling:'Motor-CAD 迭代耦合',mechanical_fea:'机械有限元',reduced_order_map:'Lab 降阶性能图',reduced_order_point:'Lab 单工作点',electromagnetic_map:'电磁参数扫描',torque_speed_sweep:'转矩—转速扫描',position_sweep:'转子位置扫描',harmonic_postprocess:'力谐波后处理',deterministic:'确定性计算',reduced_order_thermal_map:'Lab 热图谱',duty_cycle_transient:'循环工况瞬态',generator_map:'发电工况图谱',lab_test_sequence:'Lab 测试序列'};
  const solveModeLabel=value=>labels[value]||String(value||'计算');
  window.MCSAnalysisLabels=Object.freeze({solveModeLabel});
})();
