/* Generated frontend module catalog for MotorCAD Studio 0.91.8. */
(() => {
  const release = () => window.MCS_RELEASE || {};
  const descriptors = Object.freeze([
  {
    "id": "frontend.release",
    "contractKey": "frontend.release",
    "global": "MCS_RELEASE",
    "required": true,
    "dependencies": []
  },
  {
    "id": "frontend.i18n",
    "contractKey": "frontend.i18n",
    "global": "MCS_I18N",
    "required": true,
    "dependencies": [
      "frontend.release"
    ]
  },
  {
    "id": "frontend.core",
    "contractKey": "frontend.core",
    "global": "MotorCADStudio",
    "required": true,
    "dependencies": [
      "frontend.release"
    ]
  },
  {
    "id": "frontend.runtime-capsule",
    "contractKey": "frontend.runtime-capsule",
    "global": "MCSFrontendModuleRegistry",
    "required": true,
    "dependencies": [
      "frontend.release",
      "frontend.core"
    ]
  },
  {
    "id": "frontend.binary-field-viewer",
    "contractKey": "frontend.binary-field-viewer",
    "global": "MotorCADStudio",
    "required": true,
    "dependencies": [
      "frontend.core",
      "frontend.results"
    ]
  },
  {
    "id": "frontend.control-plane",
    "contractKey": "frontend.control-plane",
    "global": "MotorCADStudio",
    "required": true,
    "dependencies": [
      "frontend.core",
      "control-plane.application",
      "optimization.application",
      "data-factory.application",
      "qualification.application",
      "native.closure",
      "requirements.application"
    ]
  },
  {
    "id": "frontend.context",
    "contractKey": "frontend.context",
    "global": "MCSEngineeringContext",
    "required": true,
    "dependencies": [
      "frontend.core"
    ]
  },
  {
    "id": "frontend.design",
    "contractKey": "frontend.design",
    "global": "MCSDesignRenderer",
    "required": true,
    "dependencies": [
      "frontend.core",
      "frontend.context"
    ]
  },
  {
    "id": "frontend.analysis",
    "contractKey": "frontend.analysis",
    "global": "MCSUnifiedAnalysis",
    "required": true,
    "dependencies": [
      "frontend.core",
      "frontend.context"
    ]
  },
  {
    "id": "frontend.standard-validation",
    "contractKey": "frontend.standard-validation",
    "global": "MCSStandardValidation",
    "required": true,
    "dependencies": [
      "frontend.analysis"
    ]
  },
  {
    "id": "frontend.results",
    "contractKey": "frontend.results",
    "global": "MCSResultsWorkbench",
    "required": true,
    "dependencies": [
      "frontend.core",
      "frontend.context"
    ]
  },
  {
    "id": "frontend.fea-viewer",
    "contractKey": "frontend.fea-viewer",
    "global": "MCSFieldViewer",
    "required": true,
    "dependencies": [
      "frontend.results"
    ]
  },
  {
    "id": "frontend.action-readiness",
    "contractKey": "frontend.action-readiness",
    "global": "MCSActionReadiness",
    "required": true,
    "dependencies": [
      "frontend.analysis",
      "frontend.design"
    ]
  },
  {
    "id": "frontend.shell",
    "contractKey": "frontend.shell",
    "global": "MCSGlobalShellConvergence",
    "required": true,
    "dependencies": [
      "frontend.design",
      "frontend.analysis",
      "frontend.results"
    ]
  },
  {
    "id": "frontend.router",
    "contractKey": "frontend.router",
    "global": "MCSRouter",
    "required": true,
    "dependencies": [
      "frontend.context",
      "frontend.shell"
    ]
  }
]);

  function snapshot() {
    const manifest = release();
    const productVersion = String(manifest.productVersion || '');
    const assetVersion = String(manifest.assetVersion || '');
    const documentVersion = String(document.documentElement.dataset.studioVersion || '');
    const contracts = manifest.moduleContracts || {};
    const moduleIds = new Set(descriptors.map(row => row.id));
    const contractIds = new Set(Object.keys(contracts));
    const loadedById = new Map();
    const issues = [];

    const modules = descriptors.map(row => {
      const loaded = Boolean(window[row.global]);
      const contractVersion = String(contracts[row.contractKey] || '');
      loadedById.set(row.id, loaded);
      if (row.required && !loaded) {
        issues.push({code:'FRONTEND_MODULE_NOT_LOADED', module_id:row.id, detail:row.global});
      }
      if (!contractVersion) {
        issues.push({code:'FRONTEND_CONTRACT_NOT_DECLARED', module_id:row.id, detail:row.contractKey});
      }
      for (const dependency of row.dependencies) {
        if (!moduleIds.has(dependency) && !contractIds.has(dependency)) {
          issues.push({code:'FRONTEND_DEPENDENCY_UNDECLARED', module_id:row.id, detail:dependency});
        }
      }
      return {
        module_id: row.id,
        implementation_version: productVersion,
        contract_version: contractVersion,
        global: row.global,
        loaded,
        dependencies: [...row.dependencies],
      };
    });

    for (const row of descriptors) {
      if (!loadedById.get(row.id)) continue;
      for (const dependency of row.dependencies) {
        if (moduleIds.has(dependency) && !loadedById.get(dependency)) {
          issues.push({code:'FRONTEND_DEPENDENCY_NOT_LOADED', module_id:row.id, detail:dependency});
        }
      }
    }
    if (!productVersion || documentVersion !== productVersion || assetVersion !== productVersion) {
      issues.push({
        code:'FRONTEND_RELEASE_VERSION_MISMATCH',
        module_id:'frontend.release',
        detail:`document=${documentVersion || '-'} manifest=${productVersion || '-'} assets=${assetVersion || '-'}`,
      });
    }
    return {
      authority:'FrontendModuleRegistryV1',
      catalog_version:String(manifest.moduleCatalogVersion || ''),
      product_version:productVersion,
      asset_version:assetVersion,
      document_version:documentVersion,
      compatible:issues.length === 0,
      module_count:modules.length,
      issues,
      modules,
    };
  }

  function publish() {
    const report = snapshot();
    document.documentElement.dataset.moduleCompatibility = report.compatible ? 'compatible' : 'incompatible';
    window.dispatchEvent(new CustomEvent('mcs:frontend-modules-validated', {detail:report}));
    return report;
  }

  window.MCSFrontendModuleRegistry = Object.freeze({descriptors, snapshot, publish});
  document.addEventListener('DOMContentLoaded', publish, {once:true});
  window.addEventListener('mcs:bootstrap-ready', publish);
})();
