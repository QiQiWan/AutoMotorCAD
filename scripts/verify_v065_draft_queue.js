/* Runtime contract for V0.65 serialized optimistic Draft writes. */
const assert = require('assert');
const path = require('path');

global.window = global;
global.toast = () => {};

let value = 1;
let serverVersion = 1;
let callIndex = 0;
let releaseFirst;
const firstGate = new Promise(resolve => { releaseFirst = resolve; });
const expectedVersions = [];
const savedValues = [];
let deletedWith = null;

global.api = async (url, options = {}) => {
  if ((options.method || 'GET') === 'DELETE') {
    const parsed = new URL(`http://local${url}`);
    deletedWith = Number(parsed.searchParams.get('expected_version'));
    if (deletedWith !== serverVersion) {
      const error = new Error('stale delete');
      error.status = 409;
      error.detail = {code: 'DESIGN_DRAFT_STALE', current_version: serverVersion};
      throw error;
    }
    return {status: 'deleted'};
  }
  const body = JSON.parse(options.body || '{}');
  expectedVersions.push(body.expected_version);
  savedValues.push(body.parameters?.x);
  const currentCall = callIndex++;
  if (currentCall === 0) await firstGate;
  if (body.expected_version !== serverVersion) {
    const error = new Error(`stale write ${body.expected_version} != ${serverVersion}`);
    error.status = 409;
    error.detail = {code: 'DESIGN_DRAFT_STALE', current_version: serverVersion};
    throw error;
  }
  serverVersion += 1;
  return {draft: {version: serverVersion, updated_at: `t${serverVersion}`}};
};

require(path.join(__dirname, '..', 'motorcad_studio', 'static', 'design', 'draft-service.js'));

(async () => {
  const service = global.MCSDesignDraftService.create({
    getDesignId: () => 'DSN-TEST',
    hasChanges: () => true,
    buildPayload: () => ({base_revision_id: 'REV-1', parameters: {x: value}, materials: {}, explicit_parameter_ids: ['x'], active_view: 'radial'}),
  });
  service.begin({draft: {version: 1, updated_at: 't1'}});
  const first = service.persist({reason: 'first'});
  await new Promise(resolve => setImmediate(resolve));
  value = 2;
  const second = service.persist({reason: 'second'});
  releaseFirst();
  await Promise.all([first, second]);
  assert.deepStrictEqual(expectedVersions, [1, 2], 'queued PUT must bind optimistic version at send time');
  assert.deepStrictEqual(savedValues, [1, 2], 'queued PUT must preserve immutable payload snapshots');
  assert.strictEqual(service.state.draft.version, 3);
  await service.delete({force: true, reason: 'discard'});
  assert.strictEqual(deletedWith, 3, 'DELETE must carry the latest optimistic draft version');
  console.log('V0.65 draft queue concurrency contract: PASS');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
