/**
 * Canonical client for the transactional M5-B/M5-C control-plane APIs.
 *
 * All commands pass through ApiClient, which supplies Correlation-ID,
 * Idempotency-Key, cancellation and structured error handling.  The client keeps
 * browser state aligned with immutable backend aggregate versions without exposing
 * writable window globals.
 */
const encode = value => encodeURIComponent(String(value));
const object = value => (value && typeof value === 'object' ? value : {});

export class ControlPlaneClient {
  constructor({api, stores = {}, bus = null} = {}) {
    if (!api || typeof api.get !== 'function' || typeof api.post !== 'function') {
      throw new TypeError('ControlPlaneClient requires an ApiClient-compatible instance');
    }
    this.api = api;
    this.stores = stores;
    this.bus = bus;
    this.lastRuntime = null;
  }

  async _read(path, options = {}) {
    const payload = await this.api.get(path, options);
    this.bus?.emit('control-plane:read', {path, payload});
    return payload;
  }

  async _command(path, payload = {}, options = {}) {
    const result = await this.api.post(path, object(payload), options);
    this.bus?.emit('control-plane:command', {
      path,
      replayed: Boolean(result?._command?.replayed),
      commandId: result?._command?.command_id || null,
      result,
    });
    return result;
  }

  async runtime(options = {}) {
    const payload = await this._read('/api/control-plane/runtime', {useEtag: true, ...options});
    if (!payload?.notModified) {
      this.lastRuntime = payload;
      this.bus?.emit('control-plane:runtime', payload);
    }
    return payload;
  }

  command(commandId, options = {}) {
    return this._read(`/api/control-plane/commands/${encode(commandId)}`, options);
  }

  outbox({status = 'PENDING', limit = 100, ...options} = {}) {
    const query = new URLSearchParams({status: String(status), limit: String(limit)});
    return this._read(`/api/control-plane/outbox?${query}`, options);
  }

  acknowledgeOutbox(eventIds, options = {}) {
    return this._command('/api/control-plane/outbox/acknowledge', {event_ids: [...new Set(eventIds || [])]}, options);
  }

  optimization = Object.freeze({
    listCampaigns: (projectId = null, options = {}) => {
      const query = projectId ? `?project_id=${encode(projectId)}` : '';
      return this._read(`/api/optimization/v2/campaigns${query}`, options);
    },
    getCampaign: (campaignId, options = {}) => this._read(`/api/optimization/v2/campaigns/${encode(campaignId)}`, options),
    createCampaign: async (payload, options = {}) => {
      const result = await this._command('/api/optimization/v2/campaigns', payload, options);
      const row = result?.campaign || result;
      if (row?.campaign_id || row?.id) this.stores.optimization?.set?.({campaignId: row.campaign_id || row.id, version: Number(row.version || 0)}, {source: 'control-plane'});
      return result;
    },
    listCandidates: (campaignId, options = {}) => this._read(`/api/optimization/v2/campaigns/${encode(campaignId)}/candidates`, options),
    getCandidate: (candidateId, options = {}) => this._read(`/api/optimization/v2/candidates/${encode(candidateId)}`, options),
    createCandidate: async (campaignId, payload, options = {}) => {
      const result = await this._command(`/api/optimization/v2/campaigns/${encode(campaignId)}/candidates`, payload, options);
      const row = result?.candidate || result;
      if (row?.candidate_id || row?.id) this.stores.optimization?.set?.({campaignId, candidateId: row.candidate_id || row.id, version: Number(row.version || 0)}, {source: 'control-plane'});
      return result;
    },
    evaluateCandidate: async (candidateId, payload, options = {}) => {
      const result = await this._command(`/api/optimization/v2/candidates/${encode(candidateId)}/evaluate`, payload, options);
      const row = result?.candidate || result;
      if (row?.candidate_id || row?.id) this.stores.optimization?.set?.({candidateId: row.candidate_id || row.id, version: Number(row.version || 0)}, {source: 'control-plane'});
      return result;
    },
    promoteCandidate: async (candidateId, payload, options = {}) => {
      const result = await this._command(`/api/optimization/v2/candidates/${encode(candidateId)}/promote`, payload, options);
      const row = result?.candidate || result?.promotion || result;
      this.stores.optimization?.set?.({candidateId, version: Number(row?.version || 0), promoted: true}, {source: 'control-plane'});
      return result;
    },
    createReplayPlan: (payload, options = {}) => this._command('/api/optimization/v2/replay-plans', payload, options),
  });

  dataFactory = Object.freeze({
    getDataset: (datasetId, options = {}) => this._read(`/api/data-factory/v2/datasets/${encode(datasetId)}`, options),
    createDataset: (payload, options = {}) => this._command('/api/data-factory/v2/datasets', payload, options),
    createVersion: (datasetId, payload, options = {}) => this._command(`/api/data-factory/v2/datasets/${encode(datasetId)}/versions`, payload, options),
    createBuildJob: (versionId, payload = {}, options = {}) => this._command(`/api/data-factory/v2/versions/${encode(versionId)}/build-jobs`, payload, options),
    transitionBuild: (jobId, payload, options = {}) => this._command(`/api/data-factory/v2/build-jobs/${encode(jobId)}/transition`, payload, options),
    recordQuality: (versionId, payload, options = {}) => this._command(`/api/data-factory/v2/versions/${encode(versionId)}/quality-reports`, payload, options),
    publishVersion: (versionId, payload, options = {}) => this._command(`/api/data-factory/v2/versions/${encode(versionId)}/publish`, payload, options),
  });

  qualification = Object.freeze({
    getCampaign: (campaignId, options = {}) => this._read(`/api/qualification/v2/campaigns/${encode(campaignId)}`, options),
    createCampaign: async (payload, options = {}) => {
      const result = await this._command('/api/qualification/v2/campaigns', payload, options);
      const row = result?.campaign || result;
      if (row?.campaign_id || row?.id) this.stores.qualification?.set?.({campaignId: row.campaign_id || row.id}, {source: 'control-plane'});
      return result;
    },
    appendEvidence: async (campaignId, payload, options = {}) => {
      const result = await this._command(`/api/qualification/v2/campaigns/${encode(campaignId)}/evidence`, payload, options);
      this.stores.qualification?.set?.(state => ({campaignId, evidenceCount: Number(state.evidenceCount || 0) + 1}), {source: 'control-plane'});
      return result;
    },
    integrity: (campaignId, options = {}) => this._read(`/api/qualification/v2/campaigns/${encode(campaignId)}/integrity`, options),
    decide: async (campaignId, payload, options = {}) => {
      const result = await this._command(`/api/qualification/v2/campaigns/${encode(campaignId)}/decision`, payload, options);
      this.stores.qualification?.set?.({campaignId, decision: result?.decision || result}, {source: 'control-plane'});
      return result;
    },
  });

  nativeRuntime = Object.freeze({
    acquire: async (resourceKey, payload, options = {}) => {
      const result = await this._command(`/api/native-runtime/v2/leases/${encode(resourceKey)}`, payload, options);
      const row = result?.lease || result;
      this.stores.nativeRuntime?.set?.({leaseId: row?.lease_id || null, fencingToken: row?.fencing_token ?? null, state: 'leased', resourceKey}, {source: 'control-plane'});
      return result;
    },
    heartbeat: (resourceKey, payload, options = {}) => this._command(`/api/native-runtime/v2/leases/${encode(resourceKey)}/heartbeat`, payload, options),
    release: async (resourceKey, payload, options = {}) => {
      const result = await this._command(`/api/native-runtime/v2/leases/${encode(resourceKey)}/release`, payload, options);
      this.stores.nativeRuntime?.set?.({leaseId: null, fencingToken: null, state: 'idle', resourceKey: null}, {source: 'control-plane'});
      return result;
    },
    lockArtifact: (payload, options = {}) => this._command('/api/native-runtime/v2/artifact-locks', payload, options),
    observeProcess: (payload, options = {}) => this._command('/api/native-runtime/v2/process-observations', payload, options),
    reconcile: (options = {}) => this.api.post('/api/native-runtime/v2/reconcile', {}, options),
    createSnapshot: (payload, options = {}) => this._command('/api/native-runtime/v2/snapshots', payload, options),
  });

  requirements = Object.freeze({
    createSet: async (payload, options = {}) => {
      const result = await this._command('/api/requirements/v2/sets', payload, options);
      const row = result?.requirement_set || result;
      if (row?.set_id || row?.id) this.stores.requirements?.set?.({setId: row.set_id || row.id, version: Number(row.version || 0)}, {source: 'control-plane'});
      return result;
    },
    createRevision: async (setId, payload, options = {}) => {
      const result = await this._command(`/api/requirements/v2/sets/${encode(setId)}/revisions`, payload, options);
      const row = result?.revision || result;
      this.stores.requirements?.set?.({setId, revisionId: row?.revision_id || row?.id || null, version: Number(row?.revision_number || row?.version || 0)}, {source: 'control-plane'});
      return result;
    },
    createToleranceRevision: (subjectType, subjectId, payload, options = {}) => this._command(`/api/requirements/v2/tolerances/${encode(subjectType)}/${encode(subjectId)}/revisions`, payload, options),
    probabilisticQualification: (revisionId, payload, options = {}) => this._command(`/api/requirements/v2/revisions/${encode(revisionId)}/probabilistic-qualifications`, payload, options),
  });

  snapshot() {
    return Object.freeze({
      authority: 'MotorCADStudioFrontendControlPlaneV1',
      connected: Boolean(this.lastRuntime),
      runtime: this.lastRuntime,
      stores: {
        optimization: this.stores.optimization?.value || null,
        qualification: this.stores.qualification?.value || null,
        nativeRuntime: this.stores.nativeRuntime?.value || null,
        requirements: this.stores.requirements?.value || null,
      },
    });
  }
}
