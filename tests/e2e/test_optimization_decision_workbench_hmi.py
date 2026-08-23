from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _launch(pw):
    return pw.chromium.launch(
        headless=True,
        executable_path=str(Path("/usr/bin/chromium")) if Path("/usr/bin/chromium").is_file() else None,
        args=["--no-sandbox"],
    )


@pytest.mark.e2e
def test_v087e_linked_parameter_study_pareto_sensitivity_and_candidate_adoption_hmi():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_content('''<!doctype html><html><body>
          <article id="workbench"></article>
          <table><tbody><tr data-opt-candidate-row-v087e="C1"><td>C1 row</td></tr></tbody></table>
        </body></html>''')
        page.evaluate('''
          window.__promote=null;window.__validate=null;window.__open=null;
          window.api=async()=>({authority:'SensitivityStudyV1',content_hash:'SENS-HASH-123456789',study:{indices:[
            {method:'local',variable_id:'air_gap',available:true,value:-5,normalized_value:-0.72},
            {method:'local',variable_id:'magnet_thickness',available:true,value:2,normalized_value:0.31},
            {method:'morris',variable_id:'air_gap',available:true,mu:-5,mu_star:5.2,sigma:1.1,value:5.2},
            {method:'morris',variable_id:'magnet_thickness',available:true,mu:2,mu_star:2.4,sigma:.7,value:2.4},
            {method:'sobol',variable_id:'air_gap',available:true,first_order:.58,total_order:.66,value:.58},
            {method:'sobol',variable_id:'magnet_thickness',available:true,first_order:.25,total_order:.34,value:.25}
          ]}});
        ''')
        page.add_script_tag(content=(STATIC / "results" / "optimization-decision.js").read_text(encoding="utf-8"))
        page.evaluate('''
          const metrics=[
            {result_id:'shaft_torque_nm',label:'轴转矩',display_unit:'N·m',display_scale:1,favorable_direction:'max'},
            {result_id:'magnet_loss_w',label:'磁钢损耗',display_unit:'W',display_scale:1,favorable_direction:'min'}
          ];
          const params=[
            {parameter_id:'air_gap',label:'气隙',unit:'mm'},
            {parameter_id:'magnet_thickness',label:'永磁体厚度',unit:'mm'}
          ];
          const base={candidate_id:'BASE',case_id:'KB',is_baseline:true,feasible:true,pareto_rank:1,promotable:false,candidate_validation_status:'NOT_APPLICABLE',parameters:{air_gap:.8,magnet_thickness:5},objectives:{shaft_torque_nm:100,magnet_loss_w:20},comparison_to_baseline:{parameter_deltas:[],objective_deltas:[]}};
          const c1={candidate_id:'C1',case_id:'K1',feasible:true,pareto_rank:0,promotable:true,candidate_validation_status:'PASSED',candidate_validation:{report_id:'CV1'},candidate_validation_hash:'VH1',parameters:{air_gap:.7,magnet_thickness:4},objectives:{shaft_torque_nm:104,magnet_loss_w:18},comparison_to_baseline:{parameter_deltas:[
            {parameter_id:'air_gap',label:'气隙',unit:'mm',baseline:.8,value:.7,absolute:-.1,relative_percent:-12.5,changed:true},
            {parameter_id:'magnet_thickness',label:'永磁体厚度',unit:'mm',baseline:5,value:4,absolute:-1,relative_percent:-20,changed:true}
          ],objective_deltas:[
            {result_id:'shaft_torque_nm',label:'轴转矩',display_unit:'N·m',display_scale:1,baseline:100,value:104,absolute:4,relative_percent:4,verdict:'IMPROVED'},
            {result_id:'magnet_loss_w',label:'磁钢损耗',display_unit:'W',display_scale:1,baseline:20,value:18,absolute:-2,relative_percent:-10,verdict:'IMPROVED'}
          ]}};
          const c2={candidate_id:'C2',case_id:'K2',feasible:true,pareto_rank:0,promotable:false,candidate_validation_status:'REQUIRED',parameters:{air_gap:.9,magnet_thickness:6},objectives:{shaft_torque_nm:98,magnet_loss_w:16},comparison_to_baseline:{parameter_deltas:[],objective_deltas:[]}};
          const data={task:{id:'T1'},summary:{balanced_case_id:'K1',feasible_count:3},decision_workbench_contract_version:'0.87-E',decision_semantics:{parameters:params,metrics},candidates:[base,c1,c2],objectives:[{result_id:'shaft_torque_nm',direction:'max'},{result_id:'magnet_loss_w',direction:'min'}],parameter_study:{view_mode:'two_dimensional',experiment_mode:'full_factorial',variable_count:2,variables:params,outputs:metrics,x_axis:params[0],y_axis:params[1],x_values:[.7,.9],y_values:[4,6],baseline:{candidate_id:'BASE',parameters:base.parameters,objectives:base.objectives},surfaces:[
            {result_id:'shaft_torque_nm',metric:metrics[0],z_min:98,z_max:104,cells:[{candidate_id:'C1',case_id:'K1',x:.7,y:4,z:104,feasible:true,pareto_rank:0},{candidate_id:'C2',case_id:'K2',x:.9,y:6,z:98,feasible:true,pareto_rank:0}]},
            {result_id:'magnet_loss_w',metric:metrics[1],z_min:16,z_max:18,cells:[{candidate_id:'C1',case_id:'K1',x:.7,y:4,z:18,feasible:true,pareto_rank:0},{candidate_id:'C2',case_id:'K2',x:.9,y:6,z:16,feasible:true,pareto_rank:0}]}
          ]},convergence:[{generation:0,case_count:2,feasible_count:2,feasible_ratio:1,pareto_count:2,normalized_hypervolume_2d:.52,objective_series:{shaft_torque_nm:{cumulative_best:104,generation_median:101},magnet_loss_w:{cumulative_best:16,generation_median:17}}}],parallel_dimensions:[{key:'param.air_gap',label:'气隙'},{key:'result.shaft_torque_nm',label:'轴转矩'},{key:'result.magnet_loss_w',label:'磁钢损耗'}],parallel_rows:[{case_id:'K1',generation:0,feasible:true,pareto_rank:0,coordinates:{'param.air_gap':0,'result.shaft_torque_nm':1,'result.magnet_loss_w':.5}},{case_id:'K2',generation:0,feasible:true,pareto_rank:0,coordinates:{'param.air_gap':1,'result.shaft_torque_nm':0,'result.magnet_loss_w':0}}]};
          MCSOptimizationDecisionWorkbench.mount(document.querySelector('#workbench'),data,{openCandidate:r=>window.__open=r.case_id,validateCandidate:id=>window.__validate=id,promoteCandidate:id=>window.__promote=id});
        ''')
        page.wait_for_function("document.body.innerText.includes('二维响应面 / Heatmap')")
        text = page.locator("#workbench").inner_text()
        assert "参数研究与优化决策" in text
        assert "Pareto 权衡" in text
        assert "优化收敛" in text
        assert "敏感性分析" in text
        assert "平行坐标" in text
        assert "Candidate Validation" in text

        page.locator('[data-opt-linked-candidate-v087e="C1"]').first.click()
        page.wait_for_function("MCSOptimizationDecisionWorkbench.state.selectedCandidateId==='C1'")
        inspector = page.locator("[data-opt-candidate-inspector-v087e]").inner_text()
        assert "气隙" in inspector and "-12.5%" in inspector
        assert "轴转矩" in inspector and "改善" in inspector
        assert page.locator('[data-opt-candidate-row-v087e="C1"]').evaluate("el=>el.classList.contains('selected-v087e')") is True

        page.locator("[data-opt-sensitivity-load-v087e]").click()
        page.wait_for_function("document.body.innerText.includes('μ* 5.2')")
        sensitivity_text = page.locator("[data-opt-sensitivity-panel-v087e]").inner_text()
        assert "气隙" in sensitivity_text and "μ* 5.2" in sensitivity_text

        page.locator("[data-opt-inspector-promote-v087e]").click()
        page.wait_for_function("window.__promote==='K1'")
        browser.close()

@pytest.mark.e2e
def test_v087e_engineer_quick_start_presets_configure_safe_parameter_studies():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content('''<!doctype html><html><body>
          <main id="host">
            <section data-opt-config-v069>
              <select data-opt-strategy-v069>
                <option value="sweep">sweep</option>
                <option value="nsga2">nsga2</option>
              </select>
              <div data-opt-variables-v069></div>
              <div data-opt-objectives-v069></div>
              <div data-opt-wizard-summary-v081a></div>
            </section>
          </main>
        </body></html>''')
        page.evaluate('''
          window.esc=s=>String(s??'').replace(/[&<>"']/g,'');
          window.api=async()=>({});
          window.toast=(message,level)=>{window.__toast={message,level}};
          window.state={activeProjectId:'P1',activeSolutionId:'S1',activeMotorRevisionId:'R1'};
          window.nav=()=>{};
          window.q=(sel,root=document)=>root.querySelector(sel);
          window.qa=(sel,root=document)=>Array.from(root.querySelectorAll(sel));
          window.fmt=(v)=>String(v??'');
          window.safe=window.esc;
        ''')
        page.add_script_tag(content=(STATIC / "results" / "optimization.js").read_text(encoding="utf-8"))
        page.evaluate('''
          MCSOptimizationWorkbench.state.host=document.querySelector('#host');
          MCSOptimizationWorkbench.state.catalog={
            starter:{id:'golden_afpm_ssdr',label:'AFPM Golden Starter',short_label:'AFPM'},
            parameters:[
              {id:'air_gap',label:'气隙',unit:'mm',starter_recommended:true,recommended:true,suggested_low:.6,suggested_high:1.2,suggested_step:.1,description:'控制电磁耦合与机械公差。'},
              {id:'magnet_width',label:'磁钢周向宽度',unit:'mm',starter_recommended:true,recommended:true,suggested_low:18,suggested_high:28,suggested_step:1,description:'影响磁负荷与磁钢用量。'},
              {id:'turns_per_coil',label:'每线圈匝数',unit:'',recommended:true,suggested_low:8,suggested_high:16,suggested_step:1,description:'影响反电势和铜耗。'}
            ],
            outputs:[
              {id:'efficiency_percent',label:'效率',requested:true,optimization_eligible:true,suggested_direction:'max'},
              {id:'magnet_loss_w',label:'磁钢损耗',requested:true,optimization_eligible:true,suggested_direction:'min'}
            ]
          };
          MCSOptimizationWorkbench.applyStudyPreset('2d');
        ''')
        page.wait_for_function("document.querySelectorAll('[data-opt-variable-row-v069]').length===2")
        assert page.locator('[data-opt-strategy-v069]').input_value() == 'sweep'
        variables_text = page.locator('[data-opt-variables-v069]').inner_text()
        assert '气隙' in variables_text and '磁钢周向宽度' in variables_text
        assert '控制电磁耦合与机械公差' in variables_text

        page.evaluate("MCSOptimizationWorkbench.applyStudyPreset('multi')")
        page.wait_for_function("document.querySelectorAll('[data-opt-objective-row-v069]').length===2")
        assert page.locator('[data-opt-strategy-v069]').input_value() == 'nsga2'
        objectives_text = page.locator('[data-opt-objectives-v069]').inner_text()
        assert '效率' in objectives_text and '磁钢损耗' in objectives_text
        toast = page.evaluate('window.__toast')
        assert '多目标优化' in toast['message']
        browser.close()
