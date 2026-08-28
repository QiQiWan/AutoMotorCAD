from __future__ import annotations

from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "motorcad_studio" / "static"


def _browser(pw):
    executable = Path("/usr/bin/chromium")
    return pw.chromium.launch(
        headless=True,
        executable_path=str(executable) if executable.is_file() else None,
        args=["--no-sandbox"],
    )


@pytest.mark.e2e
def test_v089c_navigation_is_last_intent_wins_and_action_lock_is_single_flight():
    nav_source = (STATIC / "routing" / "navigation-transaction.js").read_text(encoding="utf-8")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<html><body><button id='x'>x</button></body></html>")
        page.add_script_tag(content=nav_source)

        result = page.evaluate("""
        async () => {
          let actionCalls=0;
          const one=MCSNavigationTransaction.withActionLock('save',async()=>{actionCalls+=1;await new Promise(r=>setTimeout(r,30));return 7});
          const two=MCSNavigationTransaction.withActionLock('save',async()=>{actionCalls+=1;return 8});
          const actionResults=await Promise.all([one,two]);

          const commits=[];
          let unsafe=true;
          MCSNavigationTransaction.registerGuard({
            id:'e2e-editor',priority:10,isActive:()=>true,unsafe:()=>unsafe,
            prepare:target=>new Promise(resolve=>setTimeout(()=>resolve(true),target==='A'?80:10))
          });
          const first=MCSNavigationTransaction.run({target:'A',key:'A',source:'e2e:first',commit:async()=>{commits.push('A');return true}});
          await new Promise(r=>setTimeout(r,5));
          const second=MCSNavigationTransaction.run({target:'B',key:'B',source:'e2e:second',commit:async()=>{commits.push('B');return true}});
          const navResults=await Promise.all([first,second]);
          const rollbacks=[];
          const failedResult=await MCSNavigationTransaction.run({
            target:'C',key:'C',source:'e2e:failed-route',
            commit:async()=>false,
            rollback:async info=>rollbacks.push(info.reason||'rollback')
          });
          const unload=new Event('beforeunload',{cancelable:true});window.dispatchEvent(unload);
          unsafe=false;
          return {actionCalls,actionResults,commits,navResults,failedResult,rollbacks,unloadPrevented:unload.defaultPrevented,inspect:MCSNavigationTransaction.inspect()};
        }
        """)
        assert result["actionCalls"] == 1
        assert result["actionResults"] == [7, 7]
        assert result["commits"] == ["B"]
        assert result["navResults"] == [False, True]
        assert result["failedResult"] is False
        assert result["rollbacks"] == ["commit-returned-false"]
        assert result["unloadPrevented"] is True
        assert any(row["status"] == "SUPERSEDED" for row in result["inspect"]["history"])
        assert any(row["status"] == "FAILED" and row["target"] == "C" for row in result["inspect"]["history"])
        assert errors == []
        browser.close()


@pytest.mark.e2e
def test_v089c_keyed_dialog_is_deduplicated_single_fire_and_closeall_removes_orphans():
    dialog_source = (STATIC / "dialogs.js").read_text(encoding="utf-8")
    with playwright.sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content("<html><body><button id='opener'>open</button></body></html>")
        page.add_script_tag(content="window.esc=v=>String(v);")
        page.add_script_tag(content=dialog_source)
        result = page.evaluate("""
        async () => {
          document.querySelector('#opener').focus();
          const p1=StudioDialog.confirm({key:'same',title:'Confirm',message:'x'});
          const p2=StudioDialog.confirm({key:'same',title:'Confirm',message:'x'});
          const countBefore=StudioDialog.activeCount();
          document.querySelector('[data-dialog-action="1"]').click();
          const values=await Promise.all([p1,p2]);
          await new Promise(r=>setTimeout(r,360));
          const afterConfirm=StudioDialog.activeCount();
          StudioDialog.open({key:'orphan',title:'Orphan',message:'x'});
          const beforeCloseAll=StudioDialog.activeCount();
          StudioDialog.closeAll({reason:'e2e'});
          await new Promise(r=>setTimeout(r,360));
          return {countBefore,values,afterConfirm,beforeCloseAll,afterCloseAll:StudioDialog.activeCount(),focusId:document.activeElement?.id||null};
        }
        """)
        assert result["countBefore"] == 1
        assert result["values"] == [True, True]
        assert result["afterConfirm"] == 0
        assert result["beforeCloseAll"] == 1
        assert result["afterCloseAll"] == 0
        assert result["focusId"] == "opener"
        assert errors == []
        browser.close()
